from flask_socketio import emit
from modelos import Lobby, sala_room
from datetime import datetime
import re
import secrets
import store
import threading
import time

SALA_PADRAO = "padrao"

# Tempo (segundos) que um resumo pode ficar sem sinal de vida (heartbeat/evento)
# antes de sumir da busca. O cliente renova a cada 60s; o dobro dá folga para
# uma batida perdida/rede. Sem isso, salas cuja instância serverless morreu sem
# disconnect apareciam como ativas por dias (TTL).
LIMITE_RESUMO_PARADO_SEGUNDOS = 150

# Fase 9: código de sala gerado no servidor, com charset sem caracteres
# ambíguos (sem 0/o, 1/l/i) e checagem de colisão contra o store.
CARACTERES_SALA = "abcdefghjkmnpqrstuvwxyz23456789"
TAMANHO_CODIGO_SALA = 6

# Fase 9: janela de reconexão (segundos) para quem cai no meio da partida
# voltar via chave_secreta antes de ser removido da sala.
GRACE_RECONEXAO_SEGUNDOS = 30

# Fase 15: limite de espectadores simultâneos por sala (entram assistindo uma
# partida em andamento); evita que conexões de leitura inchem o estado da sala.
MAX_ESPECTADORES = 20

# Limite de caracteres do apelido — fonte única do número. Vale para o que o
# jogador digita (`validar_input`) e para o que a IA sorteia: `ia.gerar_nome`
# escolhe de um pool podado nesse limite já no import, então nenhum bot nasce
# com nome estourado e os dois caminhos nunca divergem.
LIMITE_APELIDO = 12

# Marcador do bot: faz parte do apelido guardado (é o que o narrador usa para
# saber quem é máquina) e come orçamento. Dos 12 caracteres, 2 são do marcador
# ('🤖' + espaço) e sobram 10 para o nome em si. Vive aqui (e não em `ia.py`)
# porque o payload de `update_user_list` também precisa dele — o master edita o
# nome do bot na lista e o cliente tem de tirar o marcador do input sem duplicar
# a constante.
MARCADOR_IA = '\U0001f916 '
LIMITE_NOME_IA = LIMITE_APELIDO - len(MARCADOR_IA)

# Fase 77: rate limit leve do chat de emojis — reações em tempo real mas sem spam.
# 0.3s permite ~3 reações/s por sid (o cliente não trava o botão; o rate limit é
# todo do servidor). O preview (`chat_reagindo`) tem balde próprio
# (`cooldown_chave`) para não consumir a janela do emoji real.
COOLDOWN_CHAT = 0.3

# Fase 77: lista canônica de emojis por categoria (source of truth do servidor).
# O cliente espelha estes conjuntos para renderizar o picker; a validação do emoji
# contra o conjunto global garante que nada além disso chegue ao broadcast
# (a categoria é recalculada no servidor, nunca confiada ao cliente).
EMOJIS_PROVOCATIVOS = ['😎', '😏', '😈', '👑', '🔥', '💪', '😤', '😠', '😡', '👎']
EMOJIS_AMIGAVEIS = ['😊', '😄', '😁', '👍', '👋', '✌️', '❤️', '🎉', '🥳', '🙌']
EMOJIS_GERAIS = ['🤔', '🤷‍♂️', '🤦‍♂️', '🙄', '😂', '😭', '😵‍💫', '😴', '💤', '⚡', '⭐', '❓']
# Mapa de categoria → emojis permitidos (validação estrita).
EMOJIS_POR_CATEGORIA = {
    'provocativo': EMOJIS_PROVOCATIVOS,
    'amigavel': EMOJIS_AMIGAVEIS,
    'geral': EMOJIS_GERAIS,
}
# Conjunto plano de todos os emojis permitidos (proibição de qualquer outro).
EMOJIS_PERMITIDOS = set(EMOJIS_PROVOCATIVOS + EMOJIS_AMIGAVEIS + EMOJIS_GERAIS)

# Rate limit para reações de bots (Fase 77): um bot não reage mais de uma vez por
# este intervalo, evitando spam durante laços de IAs assistidas.
COOLDOWN_EMOJI_BOT = 1.0

# Índice em processo client_id -> sala_id (Fase 7, A4). Permite achar a sala sem
# varrer o store e adquirir o lock da sala antes do read-modify-write dos handlers.
# É só um cache local: não substitui o estado distribuído.
_clientes_por_sala = {}
_sala_por_cliente = {}
_clientes_guard = threading.Lock()


def registrar_cliente(client_id, sala_id):
    """Registra o client_id no índice em processo da sala (Fase 8: e no store)."""
    with _clientes_guard:
        _clientes_por_sala.setdefault(sala_id, set()).add(client_id)
        _sala_por_cliente[client_id] = sala_id
    store.registrar_sid(client_id, sala_id)


def desregistrar_cliente(client_id, sala_id):
    """Remove o client_id do índice em processo da sala (Fase 8: e do store)."""
    with _clientes_guard:
        clientes = _clientes_por_sala.get(sala_id)
        if clientes is not None:
            clientes.discard(client_id)
            if not clientes:
                _clientes_por_sala.pop(sala_id, None)
        _sala_por_cliente.pop(client_id, None)
    store.desregistrar_sid(client_id)


def sala_do_cliente(client_id):
    """Sala em que o client_id está conectado neste processo, ou None."""
    with _clientes_guard:
        return _sala_por_cliente.get(client_id)


# Rate limit leve por sid (Fase 7, V2), protegendo o free tier da Upstash.
_cooldowns = {}
_cooldowns_guard = threading.Lock()


def tem_cooldown(client_id, segundos):
    """
    Retorna True se o client_id já disparou um evento dentro da janela informada
    (e não registra o novo momento); False caso contrário (e registra o acesso).
    """
    agora = time.time()
    with _cooldowns_guard:
        # Evita crescimento sem limite do dicionário numa instância quente:
        # ao passar do teto, expurga entradas que já expiraram faz tempo.
        if len(_cooldowns) > 4096:
            limite = agora - 60
            for cid in [c for c, instante in _cooldowns.items() if instante < limite]:
                _cooldowns.pop(cid, None)
        ultima = _cooldowns.get(client_id, 0.0)
        if agora - ultima < segundos:
            return True
        _cooldowns[client_id] = agora
        return False


def normalizar_sala(sala_id):
    """
    Normaliza e valida o id de sala vindo da URL/front-end. Inválidos caem no
    sentinela SALA_PADRAO; o connect trata esse sentinela deixando o cliente na
    home (sem criar sala automaticamente), que escolhe criar ou buscar.
    """
    if not isinstance(sala_id, str):
        return SALA_PADRAO
    sala = sala_id.strip().lower()
    if re.fullmatch(r"[a-z0-9\-_]{1,24}", sala):
        return sala
    return SALA_PADRAO


def obter_sala(sala_id):
    """
    Retorna o Lobby da sala, carregando-o do store distribuído ou criando caso ainda não exista.
    """
    sala_id = normalizar_sala(sala_id)
    lobby = store.carregar_sala(sala_id)
    if lobby is None:
        # Fase 8 (B8): número novo via contador distribuído (INCR no Upstash),
        # sem deserializar todas as salas só para numerar.
        lobby = Lobby(sala_id=sala_id, lobby_numero=store.proximo_numero())
        store.salvar_sala(lobby)
    return lobby


def gerar_codigo_sala():
    """
    Gera um código de sala curto e sem caracteres ambíguos, verificando que não
    colide com uma sala já existente no store (Fase 9). Devolve None se não
    achar um código livre após algumas tentativas.
    """
    for _ in range(10):
        codigo = "".join(secrets.choice(CARACTERES_SALA) for _ in range(TAMANHO_CODIGO_SALA))
        if store.carregar_sala(codigo) is None:
            return codigo
    return None


def salvar_sala(lobby):
    """
    Persiste o estado atual da sala no store distribuído.
    """
    if lobby is not None:
        store.salvar_sala(lobby)


def buscar_lobby_pelo_client_id(client_id):
    """
    Procura o Lobby que contém o jogador com o client_id informado.
    Fase 8 (S1): usa o índice distribuído client_id -> sala_id para achar a sala
    direto (uma leitura pontual), em vez de deserializar todas as salas; a
    varredura completa fica só como último recurso (índice desatualizado).
    """
    sala_id = store.sala_do_sid(client_id)
    if sala_id is not None:
        lobby = store.carregar_sala(sala_id)
        if lobby is not None and lobby.buscar_jogador_pelo_client_id(client_id) is not None:
            return lobby
    for lobby in store.listar_lobbys():
        if lobby.buscar_jogador_pelo_client_id(client_id) is not None:
            return lobby
    return None


def remover_sala(sala_id):
    """
    Remove uma sala vazia do store (GC de salas sem ninguém), junto do resumo
    dela na busca, do índice em processo e do índice distribuído de sids —
    nenhum cliente pode continuar apontando para uma sala morta.
    """
    with _clientes_guard:
        clientes = list(_clientes_por_sala.pop(sala_id, ()))
        for client_id in clientes:
            if _sala_por_cliente.get(client_id) == sala_id:
                _sala_por_cliente.pop(client_id, None)
    for client_id in clientes:
        store.desregistrar_sid(client_id)
    store.remover_sala(sala_id)
    store.remover_resumo(sala_id)


def mudar_pagina(num, sala):
    """
    Envia a mudança de página escopada à room da sala.
    """
    emit("mudar_pagina", {'pag_numero': num}, to=sala_room(sala))


def _rodada_atual(lobby):
    """Última rodada da última partida do lobby, se existir."""
    partida = lobby.partidas[-1] if lobby.partidas else None
    if partida is None or not partida.rodadas:
        return None
    return partida.rodadas[-1]


def status_rolagem(lobby):
    """Quem já rolou os dados na rolagem (página 1), por apelido."""
    rodada = _rodada_atual(lobby)
    return rodada.status_rolagem_dict() if rodada else {'confirmados': [], 'pendentes': [], 'total': 0}


def status_conferencia(lobby):
    """Quem já confirmou o "Ok" na tela de conferência (página 3), por apelido."""
    rodada = _rodada_atual(lobby)
    return rodada.status_conferencia_dict() if rodada else {'confirmados': [], 'pendentes': [], 'total': 0}


def status_vitoria(lobby):
    """Quem já confirmou o "Ok" na tela de vitória (página 4), por apelido."""
    return lobby.status_vitoria_dict()


def emitir_status_rolagem(lobby):
    """Re-emite o estado atual da rolagem (quem já rolou) para a room."""
    emit('rolagem_status', status_rolagem(lobby), to=lobby.sala_room())


def emitir_status_conferencia(lobby):
    """Re-emite o estado atual das confirmações da conferência para a room."""
    emit('conferencia_status', status_conferencia(lobby), to=lobby.sala_room())


def emitir_status_vitoria(lobby):
    """Re-emite o estado atual das confirmações da vitória para a room."""
    emit('vitoria_status', status_vitoria(lobby), to=lobby.sala_room())


def emitir_dispatcher_turno(lobby, jogador):
    """
    Reemite só o indicador de vez da página de turnos (2) — `meu_turno` (menu
    de jogada) ou `espera_turno` — para um jogador cuja tela já está montada
    mas cujo dispatcher ficou desatualizado (snapshot foi para outra instância
    ou o `meu_turno`/`espera_turno` de uma troca de vez se perdeu entre
    instâncias no serverless). Servidor nunca emite para espectador.
    """
    partida = lobby.partidas[-1] if lobby.partidas else None
    if partida is None or not partida.rodadas:
        return
    rodada = partida.rodadas[-1]
    vez = rodada.vez_atual
    if vez is None or jogador not in partida.jogadores:
        return
    # Fase 21: o contador do turno (tempo restante) vai também para quem
    # espera, para todos verem o mesmo relógio.
    tempo_restante = rodada.tempo_restante_turno()
    if vez == jogador:
        payload = {'username': jogador.username,
                   'tempo_max': tempo_restante}
        payload.update(rodada.contexto_aposta())
        emit('meu_turno', payload, to=jogador.client_id, ignore_queue=True)
    else:
        emit('espera_turno', {'username': vez.username, 'tempo_max': tempo_restante},
             to=jogador.client_id, ignore_queue=True)


def reconstruir_tela_sala(lobby, exceto=None):
    """
    Fase 76: reemite o snapshot da sala para **todos** os clientes humanos.

    Existe para o caso em que o apelido guardado muda no meio da partida — hoje
    só a troca do desconectado por IA, que marca o nome com o `🤖` (e o desmarca
    quando o humano volta). Como o apelido é a chave dos `id`s dos cards no
    cliente (`card_hea_<apelido>`), cada tela precisa ser reconstruída para os
    `card`s casarem com os nomes que vêm nos eventos seguintes (`atualizar_turno`,
    `reset_rodada`, `formatador_coletivo`); sem isso o card do substituto ficaria
    com o nome antigo e o turno dele não acharia a linha de dados.

    É o mesmo caminho (e a mesma garantia) do snapshot de reconexão, só que para a
    sala inteira em vez de um cliente. `exceto` (client_id) pula quem acabou de
    receber o snapshot individual. Não filtra `desconectado_em`: emit para um sid
    morto é de graça, e o jogador dentro da janela de graça volta a receber tudo
    no `retomar_identidade` dele. Bots são pulados (não têm socket).
    """
    for alvo in list(lobby.jogadores) + list(lobby.espectadores):
        if alvo.is_ia or alvo.client_id is None:
            continue
        if exceto is not None and alvo.client_id == exceto:
            continue
        enviar_snapshot_sala(lobby, alvo)


def _categoria_canonica_emoji(emoji):
    """
    Categoria canônica de um emoji (Fase 77). O servidor é a autoridade: a
    `categoria` enviada pelo cliente é ignorada e recalculada a partir do emoji,
    que já foi validado contra a whitelist global — assim um "provocativo" não
    chega com um emoji "amigável" e o broadcast sai sempre consistente.
    """
    for cat, emojis in EMOJIS_POR_CATEGORIA.items():
        if emoji in emojis:
            return cat
    return 'geral'


def bot_enviar_emoji(lobby, jogador, emoji):
    """
    Fase 77: emite `chat_emoji` em nome de um bot (reação inteligente ao jogo).
    O servidor é a única fonte de verdade do emoji/categoria; o rate limit por
    `client_id` do bot (balde `bot_chat:<id>`) evita spam durante laços de IAs
    assistidas. Não persiste estado — é broadcast efêmero como Instagram Live.
    """
    if lobby is None or lobby.status not in ('espera', 'jogando'):
        return
    if not isinstance(emoji, str) or emoji not in EMOJIS_PERMITIDOS:
        return
    if tem_cooldown(f"bot_chat:{jogador.client_id}", COOLDOWN_EMOJI_BOT):
        return
    emit('chat_emoji', {
        'jogador': jogador.username or '',
        'emoji': emoji,
        'categoria': _categoria_canonica_emoji(emoji),
    }, to=lobby.sala_room())


def reemitir_narracao_rodada(rodada, jogador):
    """
    Rejoga para um cliente que acabou de reconectar a sequência de narrações
    gravadas da rodada corrente (Fase P2). Preserva a ordem cronológica, mas:
    - `atraso` vem zerado (sem simular o tempo de pensamento no replay);
    - `is_ia`/`nivel` são descartados (não dispara "pensando" nem o poll do
      espectador);
    - leva `reconstrucao: True` para o cliente saber que é replay (a primeira
      narração aqui também arma o sinal de mute de sons do snapshot/P3).
    O narrador é só estética — reemitir antes do `mudar_pagina` final não afeta
    a consistência do estado.
    """
    historico = getattr(rodada, 'historico_narracao', []) or []
    for item in historico:
        replay = {
            'texto': item.get('texto', ''),
            'segmentos': item.get('segmentos', []),
            'tipo': item.get('tipo'),
            'jogador': item.get('jogador'),
            'atraso': 0,
            'reconstrucao': True,
        }
        emit('narracao', replay, to=jogador.client_id, ignore_queue=True)


def enviar_snapshot_sala(lobby, jogador):
    """
    Reconstrói o front-end de um jogador que acabou de conectar (tab novo, refresh
    ou reconexão), refletindo o estado persistido da sala (Fase 4).

    O estado autoritativo já é emitido por eventos; aqui apenas os repetimos para
    este cliente, na ordem certa, baseado em `lobby.pagina`. A ordem dos eventos
    espelha o fluxo vivo do jogo — em especial o `mudar_pagina` é o ÚLTIMO da
    página —, senão o cliente troca de tela antes do conteúdo existir (invertia
    a página 3 antes de montar os cards) e o narrador/votos/sons disparavam em
    rajada no refresh.
    """
    pagina = lobby.pagina
    # Fase 40 (C5): o snapshot é sempre para o jogador que acabou de conectar/
    # reconectar (o próprio request) — sid local à instância, então
    # `ignore_queue` evita um PUBLISH à toa na fila.
    if pagina == 0:
        emit("mudar_pagina", {'pag_numero': 0}, to=jogador.client_id, ignore_queue=True)
        return

    # Um tab novo que chega no meio da partida não tem partida_atual: usa a última.
    partida = jogador.partida_atual
    if partida is None and lobby.partidas:
        partida = lobby.partidas[-1]
    if partida is None:
        # Sem partida ativa (ex.: ninguém a iniciou ainda) — ainda assim garante a
        # página certa do lobby, já que o `mudar_pagina` precisa chegar por último.
        emit("mudar_pagina", {'pag_numero': pagina}, to=jogador.client_id, ignore_queue=True)
        return

    rodada = partida.rodadas[-1] if partida.rodadas else None
    espectador = jogador not in partida.jogadores

    # Fase 9: espectador (entrou no meio da partida pela busca) recebe o selo
    # ESPECTADOR já no snapshot, para não aparecer com os painéis de jogo.
    # A página 4 também conta: o selo não esconde o "Ok" da vitória (botão
    # `bot_vencedor_fim`), e sem ele um espectador que dá refresh direto na
    # vitória não teria o botão de "Sair da sala" (Fase 30).
    if espectador and pagina in (1, 2, 3, 4):
        emit('espectador', {'nome': jogador.username}, to=jogador.client_id, ignore_queue=True)

    # Fase P1/P3: marcação de snapshot. `reconstrucao: True` no primeiro evento de
    # conteúdo da página arma o mute de sons no cliente; o narrador replay também
    # usa para saber que é reconstrução. O `mudar_pagina` final é o ÚLTIMO evento —
    # espelha o fluxo vivo e deixa o conteúdo montado antes da troca de tela.
    if pagina == 1:
        if rodada is not None:
            emit('construtor_dados', {'quantidade': jogador.dados_qtd, 'espectador': espectador,
                                      'tempo_max': int(lobby.config.get('tempo_max_jogada', 0) or 0),
                                      'reconstrucao': True},
                 to=jogador.client_id, ignore_queue=True)
            if not espectador and jogador.joguei_dados and jogador.dados:
                # Já rolou: repete o resultado pra reapresentar os dados na tela.
                emit('jogar_dados_resultado', {'jogador': jogador.client_id, 'dados_jogador': jogador.dados},
                     to=jogador.client_id, ignore_queue=True)
            reemitir_narracao_rodada(rodada, jogador)
            emitir_status_rolagem(lobby)

    elif pagina == 2:
        if rodada is None:
            # Sem rodada não há conteúdo de turno; ainda assim avisa a página.
            pass
        else:
            turnos_lista = {
                j.username: [[t.dado_face, t.dado_qtd] for t in j.turnos[-3:][::-1]]
                for j in partida.jogadores
            }
            emit('construtor_html',
                 {'rodada_n': rodada.rodada_num, 'turnos_lista': turnos_lista,
                  'dados_tt': partida.dados_qtd, 'reconstrucao': True}, to=jogador.client_id, ignore_queue=True)
            # Fase 6 (B7): em rodada 2+, cada jogador pode ter perdido dados; o
            # construtor_html usa a base (partida.dados_qtd), então corrige os cards
            # com reset_rodada (mesmo mecanismo do fluxo normal do jogo).
            if rodada.rodada_num > 1:
                emit('reset_rodada',
                     {'jogadores_nomes': [j.username for j in partida.jogadores],
                      'jogadores_dados_qtd': [j.dados_qtd for j in partida.jogadores]},
                     to=jogador.client_id, ignore_queue=True)
            emit('dados_mesa', {'total': sum(j.dados_qtd for j in partida.jogadores)}, to=jogador.client_id, ignore_queue=True)
            if rodada.com_coringa is False:
                emit('atualizar_coringa', {'coringa_cancelado': True}, to=jogador.client_id, ignore_queue=True)
            else:
                emit('atualizar_coringa', {
                    'coringa_atual': rodada.coringa_atual_qtd,
                    'ultimo_coringa': rodada.coringa_atual_jogador.username if rodada.coringa_atual_jogador else '',
                }, to=jogador.client_id, ignore_queue=True)
            if not espectador:
                emit('meus_dados', {'dados': jogador.dados}, to=jogador.client_id, ignore_queue=True)
            nomes = [j.username for j in partida.jogadores]
            vez_atual = rodada.vez_atual
            emit('formatador_coletivo', {'jogadores_nomes': nomes,
                                         'jogador_inicial_nome': vez_atual.username if vez_atual else ''},
                 to=jogador.client_id, ignore_queue=True)
            ultimo_turno = rodada.turnos[-1] if rodada.turnos else None
            for j in partida.jogadores:
                if j.turnos:
                    emit('atualizar_turno',
                         {'jogador': j.username,
                          'lista_turnos': [[t.dado_face, t.dado_qtd] for t in j.turnos[-3:][::-1]],
                          'ultimo': ultimo_turno is not None and j == ultimo_turno.do_jogador},
                         to=jogador.client_id, ignore_queue=True)
            reemitir_narracao_rodada(rodada, jogador)
            if not espectador:
                emitir_dispatcher_turno(lobby, jogador)

    elif pagina == 3:
        if rodada is not None and rodada.conferencia:
            snapshot_conferencia = dict(rodada.conferencia)
            snapshot_conferencia['reconstrucao'] = True
            emit('cards_conferencia', snapshot_conferencia, to=jogador.client_id, ignore_queue=True)
            reemitir_narracao_rodada(rodada, jogador)
        emitir_status_conferencia(lobby)

    elif pagina == 4:
        if partida.vencedor_final is not None:
            emit('vencedor_da_partida',
                 {'nome': partida.vencedor_final.username,
                  'tempo_max': int(lobby.config.get('tempo_max_jogada', 0) or 0),
                  'reconstrucao': True},
                 to=jogador.client_id, ignore_queue=True)
            nomes = [j.username for j in lobby.jogadores if j.username is not None]
            pontos = [j.pontos for j in lobby.jogadores if j.username is not None]
            emit('atualizar_pontos', {'nomes': nomes, 'pontos': pontos}, to=jogador.client_id, ignore_queue=True)
            if partida.seed_info:
                emit('auditoria_partida', partida.montar_auditoria(), to=jogador.client_id, ignore_queue=True)
            if not espectador and partida.vencedor_final == jogador:
                emit('botao_vencedor_ativ', to=jogador.client_id, ignore_queue=True)
            reemitir_narracao_rodada(partida.rodadas[-1], jogador)
        emitir_status_vitoria(lobby)

    # Fase P1: o flip de página é o ÚLTIMO evento da página — o conteúdo (cards,
    # dados, turno, etc.) já foi montado, como no fluxo vivo, e os sons do
    # reconstruction são mantidos em mute até aqui.
    emit("mudar_pagina", {'pag_numero': pagina}, to=jogador.client_id, ignore_queue=True)


def montar_payload_lista_usuarios(lobby):
    """
    Monta o payload de `update_user_list` (estado público da sala de espera),
    com os efeitos colaterais leves: reafirma o master e retoma o fluxo de seed
    (provably fair) se necessário. Reutilizado pelo broadcast normal
    (`atualizar_lista_usuarios`) e pelo re-sync entre instâncias do heartbeat
    (Fase 18/19): como as rooms do Socket.IO vivem por instância, o servidor
    devolve este snapshot ao cliente que bateu, lido do store compartilhado.
    """
    lista = lobby.jogadores
    usernames = [jogador.username for jogador in lista if jogador.username is not None]
    pontos = [jogador.pontos for jogador in lista if jogador.username is not None]
    masters = [jogador.master for jogador in lista if jogador.username is not None]
    prontos = [jogador.pronto for jogador in lista if jogador.username is not None]
    # `bots` acompanha `usernames` (mesmos índices): o master só pode renomear
    # bots, então o cliente precisa saber quais linhas são máquina. O `🤖` já
    # está no apelido — isto é estrutura, não informação nova.
    bots = [jogador.is_ia for jogador in lista if jogador.username is not None]
    # `ids` acompanha `usernames` (mesmos índices): permite o master expulsar um
    # jogador pelo client_id (Fase 19), sem expor as chaves secretas.
    ids = [jogador.client_id for jogador in lista if jogador.username is not None]
    o_master = lobby.retornar_master()
    if o_master:
        emit("master_def", {"is_master": True}, to=o_master.client_id)
    # Verificação ativa: o servidor compromete a entropia (nonce secreto) antes
    # de os clientes enviarem os nonces deles e, quando todos já comprometeram,
    # pede a revelação (cobre reconexões que perderam o pedido original).
    if lobby.config.get('verificacao_ativa') and lobby.status == 'espera':
        lobby.preparar_seed()
        if lobby.compromissos_completos() and lobby.revelacoes_pendentes():
            emit("seed_revelar", {'sala': lobby.sala_id}, to=lobby.sala_room())
    pode_iniciar, motivo = lobby.pode_iniciar()
    # `nome` vive no Lobby, não em `config`, mas o cliente o edita junto das
    # demais configurações (`aplicar_config` lê `config.nome`). Vai mesclado no
    # payload de config para o input do master não ser limpo a cada atualização.
    config_publica = dict(lobby.config)
    config_publica['nome'] = lobby.nome
    return {
        "users": usernames,
        "pontos": pontos,
        "masters": masters,
        "prontos": prontos,
        "bots": bots,
        "ids": ids,
        # O editor de nome do bot (só master, só na espera) monta o input com
        # estes dois: o `maxlength` e o prefixo a tirar do apelido guardado.
        "marcador_ia": MARCADOR_IA,
        "limite_nome_ia": LIMITE_NOME_IA,
        "nome": lobby.nome,
        "status": lobby.status,
        "config": config_publica,
        # Fonte única dos defaults: o cliente usa isto (em vez de uma cópia local
        # desatualizável) para decidir se a sala recém-criada ainda está no padrão.
        "config_padrao": Lobby.config_padrao(),
        "seed": lobby.info_publica_seed(),
        "pode_iniciar": pode_iniciar,
        "motivo": motivo,
    }


def atualizar_lista_usuarios(lobby):
    """
    Atualiza a lista de usuários na tela de entrada de jogadores da sala.
    Também envia o estado da sala de espera: nome, status, configurações e prontidão.

    Fase P4: o broadcast de `update_user_list` só é útil na espera — durante a
    partida a tela de lobby está oculta e emitir para a room só gera ruído (e
    dispara `aplicar_config_salva` → `enviar_config` no master). Os efeitos
    colaterais leves (`master_def`, seed/verificação e a persistência) continuam
    sempre: o lobby só de IAs assistida e o re-sync do heartbeat têm outros caminhos
    para repor a lista quando precisam.
    """
    payload = montar_payload_lista_usuarios(lobby)
    if lobby.status == 'espera':
        emit("update_user_list", payload, to=lobby.sala_room())
    # Fase 8: índice leve de resumos p/ a busca (evita reidratar os lobbies).
    # Stamp do sinal de vida antes de persistir: resumos velhos são escondidos da
    # busca (serverless), e o próprio blob do Lobby guarda o instante renovado.
    lobby.marcar_visto()
    # Fase 60: Lobby + resumo da busca num SÓ save no store (pipeline) em vez de
    # `salvar_sala` + `salvar_resumo` em sequência — o caminho mais chamado do
    # jogo (qualquer evento que muda lista/estado cai aqui).
    store.salvar_sala_com_resumo(lobby, lobby.resumo_partida())


def _resumo_vivo(resumo):
    """
    True se o resumo teve sinal de vida dentro de LIMITE_RESUMO_PARADO_SEGUNDOS.
    Resumo sem `visto_em` (formato antigo ou gravação órfã) conta como morto: é
    exatamente o caso dos fantasmas do serverless que não dispararam disconnect.
    """
    visto = resumo.get('visto_em')
    if not visto:
        return False
    try:
        return (datetime.now() - datetime.fromisoformat(visto)).total_seconds() \
            <= LIMITE_RESUMO_PARADO_SEGUNDOS
    except (ValueError, TypeError):
        return False


def listar_resumos_partidas(filtros, sala_atual=None):
    """
    Monta a listagem de partidas públicas para a busca, aplicando os filtros enviados
    pelo front-end. Nada do estado é modificado aqui — apenas leitura do store.

    Fase 8: lê o índice leve de resumos (store.listar_resumos) em vez de reidratar
    cada Lobby inteiro (que inclui a árvore Partida/Rodada/Turno).
    """
    filtros = filtros if isinstance(filtros, dict) else {}
    busca = str(filtros.get('busca', '') or '').strip().lower()
    status = filtros.get('status', 'todas')
    com_vaga = bool(filtros.get('com_vaga', False))
    coringa = filtros.get('com_coringa', 'todas')
    ordenar = filtros.get('ordenar', 'recentes')

    resumos = []
    for resumo in store.listar_resumos():
        sala = resumo.get('sala', '')
        if sala == sala_atual:
            continue
        # Sala órfã (sem humano conectado) não aparece na busca: cobre sala só
        # com bots e humanos todos na janela de reconexão. Resumos antigos, sem
        # o campo, caem no total de jogadores.
        humanos = resumo.get('humanos')
        if humanos is None:
            humanos = resumo.get('jogadores') or 0
        if int(humanos or 0) < 1:
            continue
        # Sem sinal de vida recente é fantasma do serverless: some da busca até
        # um cliente voltar (heartbeat/evento reescreve o resumo).
        if not _resumo_vivo(resumo):
            continue
        if not resumo.get('publica'):
            continue
        if busca and busca not in (resumo.get('nome') or '').lower() and busca not in sala.lower():
            continue
        if status in ('espera', 'jogando') and resumo.get('status') != status:
            continue
        if com_vaga and not resumo.get('pode_entrar'):
            continue
        if coringa == 'sim' and not resumo.get('com_coringa'):
            continue
        if coringa == 'nao' and resumo.get('com_coringa'):
            continue
        resumos.append(resumo)

    if ordenar == 'jogadores':
        resumos.sort(key=lambda r: (-int(r.get('jogadores') or 0), (r.get('nome') or '').lower()))
    elif ordenar == 'nome':
        resumos.sort(key=lambda r: (r.get('nome') or '').lower())
    else:
        resumos.sort(key=lambda r: r.get('criada_em') or '', reverse=True)
    return resumos


def validar_input(texto, tamanho_minimo=1, tamanho_maximo=LIMITE_APELIDO, permitir_espacos=True,
                  caracteres_permitidos=r"^[a-zA-Z0-9\s\-_.@#!$%*()+=,;:?{}\[\]\\/áéíóúâêîôûãõçÁÉÍÓÚÂÊÎÔÛÃÕÇ]*$"):
    """
    Valida o texto recebido do front-end para verificar se é válido ou inválido.
    Args:
        texto (str): O texto a ser validado.
        tamanho_minimo (int): Tamanho mínimo permitido do texto.
        tamanho_maximo (int): Tamanho máximo permitido do texto.
        permitir_espacos (bool): Se espaços são permitidos no texto.
        caracteres_permitidos (str): Regex de caracteres permitidos (None para permitir todos os caracteres comuns).
    Returns:
        bool: True se o texto for válido, False caso contrário.
    """
    if not isinstance(texto, str):
        return False

    # Remover espaços extras no início e no fim
    texto = texto.strip()

    # Verificar tamanho
    if not (tamanho_minimo <= len(texto) <= tamanho_maximo):
        return False

    # Verificar se espaços são permitidos
    if not permitir_espacos and " " in texto:
        return False

    # Verificar caracteres permitidos
    if caracteres_permitidos and not re.fullmatch(caracteres_permitidos, texto):
        return False

    return True
