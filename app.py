from flask import Flask, Response, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from funcoes_gerais import (buscar_lobby_pelo_client_id, mudar_pagina, normalizar_sala, obter_sala,
                            atualizar_lista_usuarios, remover_sala, salvar_sala, validar_input,
                            enviar_snapshot_sala, listar_resumos_partidas,
                            registrar_cliente, desregistrar_cliente, sala_do_cliente, tem_cooldown,
                            gerar_codigo_sala, GRACE_RECONEXAO_SEGUNDOS, MAX_ESPECTADORES)
from modelos import Jogador
from store import trancar_sala, esquecer_sala
from datetime import datetime
from socketio.manager import Manager as GerenciadorSocketIOBase
import functools
import os
import store
import ia
import tema
import threading

app = Flask(__name__)
app.secret_key = os.environ.get("DADINHO_SECRET_KEY", "supersecretkey")

# Janelas de rate limit leve por sid (Fase 7, V2): protegem o free tier da Upstash.
COOLDOWN_ESCRITA = 0.5
COOLDOWN_BUSCA = 2.0


class GerenciadorThreadSeguro(GerenciadorSocketIOBase):
    """
    Corrige uma corrida do python-socketio em async_mode 'threading' (a instância
    quente da Vercel atende requests concorrentes): basic_leave_room apaga o
    namespace quando a última sala sai, enquanto outro thread acabou de registrar
    o sid em manager.connect. O join_room seguinte então estoura
    "sid is not connected to requested namespace" (ou KeyError), o handler de
    connect falha e o cliente entra em loop de reconexão.

    Serializa as mutações do registro de rooms com um RLock reentrante; connect,
    join_room e leave_room passam a ser atômicos entre si.
    """

    def __init__(self):
        super().__init__()
        self._trava_registro = threading.RLock()

    def connect(self, eio_sid, namespace):
        with self._trava_registro:
            return super().connect(eio_sid, namespace)

    def basic_enter_room(self, sid, namespace, room, eio_sid=None):
        with self._trava_registro:
            return super().basic_enter_room(sid, namespace, room, eio_sid=eio_sid)

    def basic_leave_room(self, sid, namespace, room):
        with self._trava_registro:
            return super().basic_leave_room(sid, namespace, room)

    def basic_disconnect(self, sid, namespace, **kwargs):
        with self._trava_registro:
            return super().basic_disconnect(sid, namespace, **kwargs)

    def basic_close_room(self, room, namespace):
        with self._trava_registro:
            return super().basic_close_room(room, namespace)


# Transporte e armazenamento ajustáveis por ambiente (ver Fase 2 do todo.md).
async_mode = os.environ.get("DADINHO_ASYNC_MODE", "threading").strip() or "threading"
padrao_permitir_websocket = "false" if os.environ.get("VERCEL") == "1" else "true"
permitir_websocket = os.environ.get("DADINHO_PERMITIR_WEBSOCKET", padrao_permitir_websocket).strip().lower() \
    not in ("0", "false", "nao", "no")
socketio = SocketIO(
    app,
    async_mode=async_mode,
    client_manager=GerenciadorThreadSeguro(),
    allow_upgrades=permitir_websocket,
    ping_interval=15,
    ping_timeout=20,
    http_compression=False,
    # Fase 15: os payloads do cliente são minúsculos (aposta, chave, nonce).
    # Limitar a entrada (default 1 MB) reduz a superfície de abuso/DoS.
    max_http_buffer_size=100_000,
)


def achar_jogador(client_id):
    """
    Procura o jogador com o client_id informado em todas as salas.
    Usa o índice em processo (sala_do_cliente) para achar a sala direto no store,
    caindo na varredura completa caso o índice esteja desatualizado.
    Antes de responder, expurga jogadores cuja janela de reconexão expirou (Fase 9).
    Retorna o par (lobby, jogador); (None, None) caso não esteja em nenhuma sala.
    """
    sala_id = sala_do_cliente(client_id)
    if sala_id is not None:
        lobby = store.carregar_sala(sala_id)
        if lobby is not None:
            if _purgar_desconectados(lobby):
                atualizar_lista_usuarios(lobby)
            jogador = lobby.buscar_jogador_pelo_client_id(client_id)
            if jogador is not None:
                return lobby, jogador
    lobby = buscar_lobby_pelo_client_id(client_id)
    if lobby is None:
        return None, None
    if _purgar_desconectados(lobby):
        atualizar_lista_usuarios(lobby)
    return lobby, lobby.buscar_jogador_pelo_client_id(client_id)


def _remover_jogador_da_sala(lobby, jogador):
    """
    Remove o jogador de uma sala (lobby + partida/rodada se estiver jogando),
    cuidando dos contadores, do avanço da vez e da declaração de vencedor.
    Extraído do handle_disconnect para ser reusado pela janela de reconexão (Fase 9).
    """
    # Fase 6 (B2): se o desconectado já tinha confirmado a vitória, o contador
    # fica maior que o lobby atual e o "Ok" da vitória nunca libera o reset.
    if jogador.confirmou_vencedor:
        lobby.conferiram_vencedor = max(0, lobby.conferiram_vencedor - 1)
    lobby.remover_jogador(jogador.client_id)

    partida = jogador.partida_atual
    if partida is not None and jogador in partida.jogadores:
        rodada = jogador.rodada_atual
        indice_antigo = partida.jogadores.index(jogador)
        # Fase 6 (B1): remove o desconectado também da rodada e desfaz a
        # confirmação dele, senão a conferência espera um fantasma pra sempre.
        if rodada is not None and jogador in rodada.jogadores:
            if jogador.confirmou_rodada:
                rodada.conferiram = max(0, rodada.conferiram - 1)
            rodada.jogadores.remove(jogador)
        if jogador in partida.jogadores:
            partida.jogadores.remove(jogador)
        if len(partida.jogadores) == 1:
            # Sobrou só um jogador com dado: é o vencedor da partida.
            partida.declarar_vencedor(partida.jogadores[0])
        elif len(partida.jogadores) > 1:
            if rodada is not None and rodada.vez_atual == jogador:
                # Era a vez do desconectado: passa o turno pro próximo da ordem
                # circular (se ele era o último da lista, volta pro primeiro).
                proximo = partida.jogadores[indice_antigo % len(partida.jogadores)]
                rodada.vez_atual = proximo
                rodada.atualizar_front_pro_da_vez(proximo)
            # Se a rolagem só esperava este jogador, desbloqueia quem já jogou.
            # Só na página de rolagem (1): na conferência/vitória todos já rolaram
            # e o desbloqueio reverteria a tela para os turnos.
            if (lobby.pagina == 1 and rodada is not None
                    and rodada.verificar_se_todos_ja_jogaram_seus_dados()):
                lobby.pagina = 2
                mudar_pagina(2, sala=lobby.sala_id)


def _substituir_por_ia(lobby, jogador):
    """
    Converte um desconectado em bot (Fase 11), quando o master ativou a opção:
    preserva dados/turno e deixa a partida seguir. Só vale se ainda houver outro
    humano ativo — senão a sala seguiria só com bots.
    """
    if not lobby.config.get('substituir_desconectado_por_ia'):
        return False
    if jogador.partida_atual is None:
        return False
    tem_humano_ativo = any(not j.is_ia and j is not jogador and j.desconectado_em is None
                           for j in lobby.jogadores)
    if not tem_humano_ativo:
        return False
    jogador.is_ia = True
    jogador.ia_nivel = int(lobby.config.get('ia_nivel_padrao', 2) or 2)
    jogador.desconectado_em = None
    jogador.pronto = True
    emit('jogador_substituido_por_ia', {'nome': jogador.username or ''}, to=lobby.sala_room())
    return True


def _purgar_desconectados(lobby):
    """
    Remove da sala os jogadores cuja janela de reconexão (grace) já expirou
    (Fase 9). Com a opção do master ligada, em vez de remover, o desconectado
    vira bot (Fase 11) e a partida continua. Devolve True se algo mudou.
    """
    agora = datetime.now()
    mudou = False
    removidos = False
    for jogador in list(lobby.jogadores):
        if jogador.desconectado_em is None:
            continue
        if (agora - jogador.desconectado_em).total_seconds() >= GRACE_RECONEXAO_SEGUNDOS:
            if _substituir_por_ia(lobby, jogador):
                mudou = True
                continue
            _remover_jogador_da_sala(lobby, jogador)
            removidos = True
            mudou = True
    if removidos:
        lobby.definir_master()
    if mudou:
        ia.processar(lobby)
    return mudou


def evento_mutavel(func):
    """
    Wrapper padrão para handlers que mutam estado de sala (Fase 7):
    - V2: rate limit leve por sid;
    - A4: lock por sala no processo, cobrindo todo o read-modify-write;
    - V3: payload malformado aborta silenciosamente (nunca exceção no evento).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        client_id = request.sid
        if tem_cooldown(client_id, COOLDOWN_ESCRITA):
            return
        sala_id = sala_do_cliente(client_id)
        try:
            if sala_id is None:
                return func(*args, **kwargs)
            with trancar_sala(sala_id):
                return func(*args, **kwargs)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError):
            return
    return wrapper


def evento_leitura(func):
    """
    Wrapper para eventos somente-leitura (ex.: busca de partidas): só o rate limit (V2).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if tem_cooldown(request.sid, COOLDOWN_BUSCA):
            return
        return func(*args, **kwargs)
    return wrapper


def _chave_simples(dados):
    """Extrai a chave secreta do payload no formato padrão {'chave': ...}."""
    return dados.get('chave', '')


def _chave_aninhada(dados):
    """Extrai a chave do payload de aposta/desconfiança: {'dados': {'chave': ...}}."""
    internos = dados.get('dados')
    if not isinstance(internos, dict):
        return ''
    return internos.get('chave', '')


def autenticar(exigir_master=False, extrair_chave=_chave_simples):
    """
    Centraliza o boilerplate de autenticação dos handlers de jogador (Fase 10, S5):
    localiza (lobby, jogador) pelo sid, valida a chave secreta extraída do payload
    (passe `extrair_chave=None` para eventos sem chave) e, opcionalmente, exige que
    o jogador seja o master. Em falha, aborta silenciosamente; no sucesso injeta
    (dados, lobby, jogador) na assinatura do handler decorado.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(dados=None, *args, **kwargs):
            dados = dados if isinstance(dados, dict) else {}
            lobby, jogador = achar_jogador(request.sid)
            if jogador is None or lobby is None:
                return
            if exigir_master and not jogador.master:
                return
            if extrair_chave is not None and jogador.chave_secreta != extrair_chave(dados):
                return
            return func(dados, lobby, jogador, *args, **kwargs)
        return wrapper
    return decorator


@app.route("/")
def index():
    return render_template("jogo.html")


@app.route("/tema.mid")
def tema_midi():
    """
    Serve o tema oficial vigente (Fase 12). A música é gerada
    deterministicamente a partir da janela de 12h (ver `tema.py`), então todas
    as instâncias devolvem a mesma composição sem persistência nem timers.
    Cache-Control expira exatamente na virada da janela; se a geração falhar,
    cai no MIDI estático versionado como fallback.
    """
    try:
        midi, bpm, seed = tema.tema_atual()
    except Exception:
        return send_from_directory(os.path.join(app.root_path, 'static', 'sons'),
                                   'dadinho_tema.mid', mimetype='audio/midi')
    resposta = Response(midi, mimetype='audio/midi')
    resposta.headers['Cache-Control'] = f'public, max-age={max(0, tema.segundos_ate_virada())}'
    resposta.headers['X-Dadinho-Tema-Seed'] = str(seed)
    resposta.headers['X-Dadinho-Tema-Bpm'] = str(bpm)
    return resposta


@socketio.on('connect')
def handle_connect():
    """
    Esta função é executada no momento da conexão de um cliente web do servidor.
    Ela deve determinar a sala do cliente (via ?sala= na URL/front-end), juntá-lo à room da sala,
    criar uma instância de jogador, e decidir se ele é master, caso não haja algum na sala.

    Fase 4: se já existir um jogador com este sid (reconexão da mesma sessão) ou com a
    chave secreta guardada no sessionStorage (refresh), reaproveita-o em vez de duplicar,
    e envia um snapshot da sala para o cliente reconstruir a tela (página atual intacta).
    """
    client_id = request.sid
    sala_id = normalizar_sala(request.args.get('sala'))
    with trancar_sala(sala_id):
        lobby = obter_sala(sala_id)
        join_room(lobby.sala_room(), sid=client_id)

        jogador = lobby.buscar_jogador_pelo_client_id(client_id)
        if jogador is None:
            chave_resumo = request.args.get('chave_secreta', '')
            jogador = lobby.buscar_jogador_pela_chave(chave_resumo)
            if jogador is not None:
                # Retomando a mesma identidade: religa o sid novo ao mesmo Jogador
                # e encerra a janela de reconexão (Fase 9).
                jogador.client_id = client_id
                jogador.desconectado_em = None
            elif lobby.status == 'jogando':
                # Fase 15: entrou no meio da partida (pela busca) — vira
                # espectador, sem ocupar vaga nem contar como jogador.
                if len(lobby.espectadores) >= MAX_ESPECTADORES:
                    emit('sala_cheia', {'sala': lobby.sala_id}, to=client_id)
                    leave_room(lobby.sala_room(), sid=client_id)
                    return
                jogador = Jogador(client_id=client_id, master=False)
                jogador.lobby_atual = lobby
                lobby.espectadores.append(jogador)
            else:
                # Sala de espera lotada (config 'max_jogadores'): não deixa entrar mais ninguém.
                if len(lobby.jogadores) >= int(lobby.config.get('max_jogadores', 6)):
                    emit('sala_cheia', {'sala': lobby.sala_id}, to=client_id)
                    leave_room(lobby.sala_room(), sid=client_id)
                    return
                master = False if lobby.verificar_jogador_master() else True
                jogador = Jogador(client_id=client_id, master=master)
                lobby.adicionar_jogador(jogador)

        registrar_cliente(client_id, sala_id)

        emit("connect_start",
             {"is_master": jogador.master, 'chave_secreta': jogador.chave_secreta, 'sala': lobby.sala_id,
              'username': jogador.username})
        atualizar_lista_usuarios(lobby)
        enviar_snapshot_sala(lobby, jogador)
        # Fase 11: se a partida parou na vez de uma IA (ex.: troca de instância),
        # o connect destrava o fluxo.
        if ia.processar(lobby):
            salvar_sala(lobby)


@socketio.on('disconnect')
def handle_disconnect():
    """
    Esta função é executada no momento da desconexão de um cliente web do servidor.
    Ela deve remover o jogador da sala e caso este jogador seja um master e haja mais jogadores no lobby
    dele, selecionar outro jogador, por ordem de entrada, mais antigo pro mais novo, para se tornar o novo master do
    lobby, caso não seja um master, apenas remover, caso apenas ele no lobby, reinicia tudo.

    Fase 4: se o desconectado ainda estiver numa partida em andamento, ele é removido também da
    partida (senão travaria a rolagem/conferência/turno já que a partida continua esperando ele);
    se for a vez dele, o turno passa pro próximo; se sobrar apenas um, ele é declarado vencedor.
    """
    client_id = request.sid
    sala_id = sala_do_cliente(client_id)
    if sala_id is None:
        return
    sala_esvaziou = False
    with trancar_sala(sala_id):
        lobby = store.carregar_sala(sala_id)
        desregistrar_cliente(client_id, sala_id)
        if lobby is None:
            return
        jogador = lobby.buscar_jogador_pelo_client_id(client_id)
        if jogador is None:
            return
        leave_room(lobby.sala_room(), sid=client_id)

        # Fase 15: espectador não é jogador — sai na hora, sem janela de graça.
        if jogador in lobby.espectadores:
            lobby.espectadores.remove(jogador)
        elif jogador.partida_atual is not None:
            # Fase 9: janela de reconexão (grace). Quem cai no meio de uma partida
            # fica marcado (desconectado_em) por GRACE_RECONEXAO_SEGUNDOS e pode
            # voltar via chave_secreta (handle_connect limpa o marcador).
            # Fase 15: só faz sentido esperar se restar outro HUMANO ativo — um
            # bot não justifica segurar a sala (senão ela ficaria órfã).
            outros_ativos = sum(
                1 for j in lobby.jogadores
                if j is not jogador and not j.is_ia and j.desconectado_em is None
            )
            if outros_ativos < 1:
                _remover_jogador_da_sala(lobby, jogador)
            else:
                jogador.desconectado_em = datetime.now()
                emit('jogador_desconectado',
                     {'nome': jogador.username or '', 'grace': GRACE_RECONEXAO_SEGUNDOS},
                     to=lobby.sala_room())
        else:
            _remover_jogador_da_sala(lobby, jogador)

        if lobby.contar_jogadores() > 0:
            lobby.definir_master()
        # Fase 11/15: sala sem nenhum humano (jogador ou espectador) é removida.
        if not lobby.tem_humano():
            remover_sala(lobby.sala_id)
            sala_esvaziou = True
        else:
            # S6: atualizar_lista_usuarios já persiste a sala (e o resumo da busca).
            atualizar_lista_usuarios(lobby)
    # Depois de soltar o lock (evita corrida com um connect novo da mesma sala).
    if sala_esvaziou:
        esquecer_sala(sala_id)


@socketio.on('apelido')
@evento_mutavel
@autenticar(extrair_chave=None)
def escolher_apelido(dados, lobby, jogador):
    """
    Esta função recebe o apelido do jogador no front-end e atualiza o seu modelo, antes faz umas validações.
    """
    if jogador.partida_atual is None and jogador.rodada_atual is None and jogador.turno_atual is None:
        apelido = dados.get("apelido_msg", '')
        apelido_n = lobby.verificar_apelido(apelido if validar_input(apelido) else 'NOME_BUGADO')
        jogador.username = apelido_n
        emit("update_username", {'nome_jogador': jogador.username}, to=jogador.client_id)
        atualizar_lista_usuarios(lobby)


@socketio.on('iniciar_partida')
@evento_mutavel
@autenticar(exigir_master=True)
def iniciar_partida(dados, lobby, jogador):
    """
    Esta função inicia uma nova partida, é executada pelo master do lobby da sala.
    Só libera quando todos os jogadores (não-master) estiverem prontos e houver ao menos 2.
    :param dados: Vem do front, é o número de dados que cada jogador recebe para jogar.
    """
    if 'dados_qtd' in dados:
        try:
            lobby.definir_config({'dados_qtd': int(dados.get('dados_qtd', 1))})
        except (ValueError, TypeError):
            pass
    pode, motivo = lobby.pode_iniciar()
    if not pode:
        emit('iniciar_negado', {'motivo': motivo}, to=jogador.client_id)
        return
    # Verificação ativa: resolve a entropia e fixa a seed ANTES de criar a partida.
    seed_info = lobby.finalizar_seed()
    partida = lobby.construir_partida(dados_qtd=int(lobby.config.get('dados_qtd', 1)), seed_info=seed_info)
    partida.construir_rodada()
    ia.processar(lobby)
    salvar_sala(lobby)
    # Fase 8: status virou 'jogando' — atualiza o resumo da busca de partidas.
    store.salvar_resumo(lobby.sala_id, lobby.resumo_partida())


@socketio.on('configurar_partida')
@evento_mutavel
@autenticar(exigir_master=True)
def configurar_partida(dados, lobby, jogador):
    """
    Aplica as configurações da partida definidas pelo master na sala de espera
    (nome, quantidade de dados, máximo de jogadores, coringa, pública).
    """
    if lobby.status != 'espera':
        return
    if lobby.definir_config(dados.get('config', {})):
        atualizar_lista_usuarios(lobby)


@socketio.on('ficar_pronto')
@evento_mutavel
@autenticar()
def ficar_pronto(dados, lobby, jogador):
    """
    Alterna a prontidão do jogador na sala de espera. O jogo só inicia quando
    todos os jogadores (não-master) estiverem prontos.
    """
    if lobby.status != 'espera':
        return
    jogador.pronto = not jogador.pronto
    atualizar_lista_usuarios(lobby)


@socketio.on('comprometer_seed')
@evento_mutavel
@autenticar()
def comprometer_seed(dados, lobby, jogador):
    """
    Verificação de integridade (provably fair), fase de compromisso: o cliente
    envia apenas o compromisso SHA-256 do nonce dele (o nonce fica no cliente).
    O servidor publica o compromisso e, quando todos comprometeram, pede a
    revelação dos nonces.
    """
    if not lobby.config.get('verificacao_ativa') or lobby.status != 'espera':
        return
    if lobby.registrar_compromisso(jogador, dados.get('compromisso')):
        emit('seed_compromissos', lobby.info_publica_seed(), to=lobby.sala_room())
        if lobby.compromissos_completos():
            emit('seed_revelar', {'sala': lobby.sala_id}, to=lobby.sala_room())
        salvar_sala(lobby)


@socketio.on('revelar_seed')
@evento_mutavel
@autenticar()
def revelar_seed(dados, lobby, jogador):
    """
    Verificação de integridade (provably fair), fase de revelação: o cliente
    revela o nonce e o servidor confere contra o compromisso publicado. A
    revelação é transmitida à sala (pública) para que qualquer cliente recompute
    a seed e detecte substituição do nonce pelo servidor. A partida só libera
    quando todos revelam (ver `Lobby.pode_iniciar`).
    """
    if not lobby.config.get('verificacao_ativa') or lobby.status != 'espera':
        return
    if lobby.registrar_revelacao(jogador, dados.get('nonce')):
        emit('seed_revelacao', {'client_id': jogador.client_id, 'nonce': jogador.nonce_seed},
             to=lobby.sala_room())
        # Recalcula `pode_iniciar`/motivo e atualiza os botões de todos.
        atualizar_lista_usuarios(lobby)


@socketio.on('solicitar_auditoria')
@evento_mutavel
@autenticar()
def solicitar_auditoria(dados, lobby, jogador):
    """Reenvia o payload de auditoria da partida atual (ex.: reconexão na tela 4)."""
    partida = jogador.partida_atual
    if partida is None or not partida.seed_info:
        return
    emit('auditoria_partida', partida.montar_auditoria(), to=jogador.client_id)


@socketio.on('adicionar_ia')
@evento_mutavel
@autenticar(exigir_master=True)
def adicionar_ia(dados, lobby, jogador):
    """O master adiciona bots à sala de espera (níveis 1-4, Fase 11)."""
    if lobby.status != 'espera':
        return
    if ia.adicionar_bots(lobby, dados.get('nivel', 2), dados.get('quantidade', 1)):
        atualizar_lista_usuarios(lobby)


@socketio.on('completar_com_ias')
@evento_mutavel
@autenticar(exigir_master=True)
def completar_com_ias(dados, lobby, jogador):
    """O master preenche as vagas restantes da sala com bots (Fase 11)."""
    if lobby.status != 'espera':
        return
    if ia.completar_bots(lobby, dados.get('nivel', 2)):
        atualizar_lista_usuarios(lobby)


@socketio.on('remover_ia')
@evento_mutavel
@autenticar(exigir_master=True)
def remover_ia(dados, lobby, jogador):
    """O master remove bots da sala de espera, por nível ou todos (Fase 11)."""
    if lobby.status != 'espera':
        return
    if ia.remover_bots(lobby, dados.get('nivel')) > 0:
        atualizar_lista_usuarios(lobby)


@socketio.on('listar_partidas')
@evento_leitura
def listar_partidas(dados):
    """
    Retorna a listagem de partidas públicas (com filtros) para a tela de busca.
    Responde apenas ao cliente que pediu (to=client_id).
    """
    dados = dados or {}
    client_id = request.sid
    filtros = dados.get('filtros', {})
    sala_atual = dados.get('sala_atual')
    resumos = listar_resumos_partidas(filtros, sala_atual=sala_atual)
    emit('partidas_listadas', {'partidas': resumos}, to=client_id)


@socketio.on('criar_sala')
@evento_leitura
def criar_sala(dados=None):
    """
    Gera um código de sala no servidor (Fase 9): charset sem caracteres ambíguos
    e checagem de colisão no store. O cliente navega para a sala devolvida.
    Evento somente-leitura (não cria o Lobby; o connect o faz).
    """
    codigo = gerar_codigo_sala()
    if codigo is None:
        return
    emit('sala_criada', {'sala': codigo}, to=request.sid)


@socketio.on('verificar_desconectados')
@evento_mutavel
@autenticar(extrair_chave=None)
def verificar_desconectados(dados, lobby, jogador):
    """
    Os clientes agendam este evento após receberem 'jogador_desconectado'
    (Fase 9): garante que alguém expurgue, após a janela de graça, quem caiu no
    meio da partida e não voltou — sem depender de timer no servidor.
    achar_jogador já faz o expurgo; aqui só persistimos se algo saiu.
    """
    if _purgar_desconectados(lobby):
        atualizar_lista_usuarios(lobby)


@socketio.on('jogar_dados')
@evento_mutavel
@autenticar()
def jogar_dados(dados, lobby, jogador):
    """
    Esta função envia os números dos dados sorteados aos jogadores, cada jogador recebe seus
    respectivos dados sorteados.
    """
    if jogador.rodada_atual is None:
        return
    # Fase 7 (A6): idempotência explícita por rodada — já rolou não rola de novo.
    if jogador.joguei_dados:
        return
    jogador.joguei_dados = True
    # Fase 10 (S4): escopo explícito — o resultado é só de quem rolou.
    emit("jogar_dados_resultado", {"jogador": jogador.client_id, "dados_jogador": jogador.dados},
         to=jogador.client_id)
    salvar_sala(lobby)


@socketio.on('joguei_dados')
@evento_mutavel
@autenticar(extrair_chave=lambda d: d.get('chave_secreta', ''))
def joguei_dados(dados, lobby, jogador):
    """
    Esta função é executada por cada jogador da partida quando termina de executar e visualizar o resultado de seus
    dados. Ela deve redirecionar todos os jogadores para a próxima tela (2), onde se inicia a partida de fato, com os
    turnos, mas somente depois de todos os dados terem sido jogados.
    """
    if jogador.rodada_atual is None:
        return
    # Fase 10 (S4): escopo explícito — os dados são só de quem confirmou.
    emit('meus_dados', {'dados': jogador.dados}, to=jogador.client_id)
    rodada = jogador.rodada_atual
    # Executar isso \/ quando o último jogar os dados
    if rodada.verificar_se_todos_ja_jogaram_seus_dados():
        lobby.pagina = 2
        mudar_pagina(2, sala=lobby.sala_id)
    ia.processar(lobby)
    salvar_sala(lobby)


@socketio.on('apostar')
@evento_mutavel
@autenticar(extrair_chave=_chave_aninhada)
def aposta(dados, lobby, jogador):
    """
    Função executada pelo jogador quando ele faz uma aposta, mas antes verifica se o jogador está em uma rodada e se
    ele é o da vez no turno.
    """
    internos = dados.get('dados')
    if not isinstance(internos, dict):
        return
    dados_aposta = internos.copy()
    dados_aposta.pop('chave', None)
    rodada = jogador.rodada_atual
    if rodada and rodada.vez_atual == jogador:
        rodada.construir_turno(jogador=jogador, dados=dados_aposta)
        ia.processar(lobby)
        salvar_sala(lobby)


@socketio.on('desconfiar')
@evento_mutavel
@autenticar(extrair_chave=_chave_aninhada)
def desconfiar(dados, lobby, jogador):
    """
    Função executada pelo jogador quando ele desconfia de uma aposta, mas antes verifica se o jogador está em uma
    rodada e se ele é o da vez no turno.
    """
    rodada = jogador.rodada_atual
    if rodada and rodada.vez_atual == jogador and len(rodada.turnos) > 0:
        rodada.desconfiar(jogador=jogador)
        ia.processar(lobby)
        salvar_sala(lobby)


@socketio.on('conferencia_final')
@evento_mutavel
@autenticar()
def conferencia_final(dados, lobby, jogador):
    """
    Quanto todos os participantes da rodada clicam em ok, na conferência final da rodada, esta função engatilha
    uma nova rodada na partida.
    """
    if jogador.rodada_atual is None or jogador.partida_atual is None:
        return
    # Fase 15: só vale na tela de conferência (3). Sem este gate, um cliente
    # podia confirmar durante os turnos e adiantar/encerrar a rodada.
    if lobby.pagina != 3:
        return
    if jogador.confirmou_rodada:
        return
    rodada = jogador.rodada_atual
    jogador.confirmou_rodada = True
    rodada.conferiram += 1
    if rodada.conferiram == len(rodada.jogadores):
        jogador.partida_atual.construir_rodada()
    ia.processar(lobby)
    salvar_sala(lobby)


@socketio.on('vencedor_final')
@evento_mutavel
@autenticar()
def vencedor_final(dados, lobby, jogador):
    """
    Quanto todos os participantes da rodada clicam em ok, na tela de vencedor, esta função engatilha
    uma nova partida no lobby.
    """
    if jogador.confirmou_vencedor:
        return
    # Fase 15: só vale na tela de vitória (4) e para jogadores da sala — um
    # espectador não pode contar para o reset.
    if lobby.pagina != 4 or jogador not in lobby.jogadores:
        return
    jogador.confirmou_vencedor = True
    lobby.conferiram_vencedor += 1
    if lobby.conferiram_vencedor == len(lobby.jogadores):
        lobby.resetar_para_lobby()
        atualizar_lista_usuarios(lobby)
        mudar_pagina(0, sala=lobby.sala_id)
    ia.processar(lobby)
    salvar_sala(lobby)


@socketio.on('foguetear_click')
@evento_mutavel
@autenticar()
def foguetear(dados, lobby, jogador):
    """
    Função que torna os fogos de comemoração compartilhados com todos na partida.
    """
    partida = jogador.partida_atual
    rodada = jogador.rodada_atual
    # Fase 6 (B4): partida encerrada por desconexão não define rodada.vencedor,
    # mas sim partida.vencedor_final — o vencedor precisa poder comemorar.
    if rodada is not None and rodada.vencedor == jogador:
        emit('soltar_fogos', to=lobby.sala_room())
    elif partida is not None and partida.vencedor_final == jogador:
        emit('soltar_fogos', to=lobby.sala_room())


if __name__ == '__main__':
    if os.environ.get("VERCEL") != "1":
        socketio.run(app, allow_unsafe_werkzeug=True)