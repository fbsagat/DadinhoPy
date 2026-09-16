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
    if vez == jogador:
        payload = {'username': jogador.username,
                   'tempo_max': int(lobby.config.get('tempo_max_jogada', 0) or 0)}
        payload.update(rodada.contexto_aposta())
        emit('meu_turno', payload, to=jogador.client_id, ignore_queue=True)
    else:
        emit('espera_turno', {'username': vez.username}, to=jogador.client_id, ignore_queue=True)


def enviar_snapshot_sala(lobby, jogador):
    """
    Reconstrói o front-end de um jogador que acabou de conectar (tab novo, refresh
    ou reconexão), refletindo o estado persistido da sala (Fase 4).

    O estado autoritativo já é emitido por eventos; aqui apenas os repetimos para
    este cliente, na ordem certa, baseado em `lobby.pagina`.
    """
    pagina = lobby.pagina
    # Fase 40 (C5): o snapshot é sempre para o jogador que acaba de conectar/
    # reconectar (o próprio request) — sid local à instância, então
    # `ignore_queue` evita um PUBLISH à toa na fila.
    emit("mudar_pagina", {'pag_numero': pagina}, to=jogador.client_id, ignore_queue=True)
    if pagina == 0:
        return

    # Um tab novo que chega no meio da partida não tem partida_atual: usa a última.
    partida = jogador.partida_atual
    if partida is None and lobby.partidas:
        partida = lobby.partidas[-1]
    if partida is None:
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

    if pagina == 1:
        if rodada is not None:
            emit('construtor_dados', {'quantidade': jogador.dados_qtd, 'espectador': espectador,
                                      'tempo_max': int(lobby.config.get('tempo_max_jogada', 0) or 0)},
                 to=jogador.client_id, ignore_queue=True)
            if not espectador and jogador.joguei_dados and jogador.dados:
                # Já rolou: repete o resultado pra reapresentar os dados na tela.
                emit('jogar_dados_resultado', {'jogador': jogador.client_id, 'dados_jogador': jogador.dados},
                     to=jogador.client_id, ignore_queue=True)
            emitir_status_rolagem(lobby)
        return

    if pagina == 2:
        if rodada is None:
            return
        turnos_lista = {
            j.username: [[t.dado_face, t.dado_qtd] for t in j.turnos[-3:][::-1]]
            for j in partida.jogadores
        }
        emit('construtor_html',
             {'rodada_n': rodada.rodada_num, 'turnos_lista': turnos_lista,
              'dados_tt': partida.dados_qtd}, to=jogador.client_id, ignore_queue=True)
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
        if not espectador:
            emitir_dispatcher_turno(lobby, jogador)
        return

    if pagina == 3:
        if rodada is not None and rodada.conferencia:
            emit('cards_conferencia', rodada.conferencia, to=jogador.client_id, ignore_queue=True)
        emitir_status_conferencia(lobby)
        return

    if pagina == 4:
        if partida.vencedor_final is not None:
            emit('vencedor_da_partida',
                 {'nome': partida.vencedor_final.username,
                  'tempo_max': int(lobby.config.get('tempo_max_jogada', 0) or 0)},
                 to=jogador.client_id, ignore_queue=True)
            nomes = [j.username for j in lobby.jogadores if j.username is not None]
            pontos = [j.pontos for j in lobby.jogadores if j.username is not None]
            emit('atualizar_pontos', {'nomes': nomes, 'pontos': pontos}, to=jogador.client_id, ignore_queue=True)
            if partida.seed_info:
                emit('auditoria_partida', partida.montar_auditoria(), to=jogador.client_id, ignore_queue=True)
            if not espectador and partida.vencedor_final == jogador:
                emit('botao_vencedor_ativ', to=jogador.client_id, ignore_queue=True)
        emitir_status_vitoria(lobby)


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
        "ids": ids,
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
    """
    emit("update_user_list", montar_payload_lista_usuarios(lobby), to=lobby.sala_room())
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


def validar_input(texto, tamanho_minimo=1, tamanho_maximo=8, permitir_espacos=True,
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
