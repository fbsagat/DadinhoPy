from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from funcoes_gerais import (buscar_lobby_pelo_client_id, mudar_pagina, normalizar_sala, obter_sala,
                            atualizar_lista_usuarios, remover_sala, salvar_sala, validar_input,
                            enviar_snapshot_sala, listar_resumos_partidas,
                            registrar_cliente, desregistrar_cliente, sala_do_cliente, tem_cooldown,
                            gerar_codigo_sala, GRACE_RECONEXAO_SEGUNDOS)
from modelos import Jogador
from store import trancar_sala, esquecer_sala
from datetime import datetime
import functools
import os
import store

app = Flask(__name__)
app.secret_key = os.environ.get("DADINHO_SECRET_KEY", "supersecretkey")

# Janelas de rate limit leve por sid (Fase 7, V2): protegem o free tier da Upstash.
COOLDOWN_ESCRITA = 0.5
COOLDOWN_BUSCA = 2.0

# Transporte e armazenamento ajustáveis por ambiente (ver Fase 2 do todo.md).
async_mode = os.environ.get("DADINHO_ASYNC_MODE", "threading").strip() or "threading"
padrao_permitir_websocket = "false" if os.environ.get("VERCEL") == "1" else "true"
permitir_websocket = os.environ.get("DADINHO_PERMITIR_WEBSOCKET", padrao_permitir_websocket).strip().lower() \
    not in ("0", "false", "nao", "no")
socketio = SocketIO(
    app,
    async_mode=async_mode,
    allow_upgrades=permitir_websocket,
    ping_interval=15,
    ping_timeout=20,
    http_compression=False,
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
                # Era a vez do desconectado: passa o turno pro próximo.
                proximo = partida.jogadores[min(indice_antigo, len(partida.jogadores) - 1)]
                rodada.vez_atual = proximo
                rodada.atualizar_front_pro_da_vez(proximo)
            # Se a rolagem só esperava este jogador, desbloqueia quem já jogou.
            # Só na página de rolagem (1): na conferência/vitória todos já rolaram
            # e o desbloqueio reverteria a tela para os turnos.
            if (lobby.pagina == 1 and rodada is not None
                    and rodada.verificar_se_todos_ja_jogaram_seus_dados()):
                lobby.pagina = 2
                mudar_pagina(2, sala=lobby.sala_id)


def _purgar_desconectados(lobby):
    """
    Remove da sala os jogadores cuja janela de reconexão (grace) já expirou
    (Fase 9). Devolve True se algum jogador foi removido.
    """
    agora = datetime.now()
    removidos = False
    for jogador in list(lobby.jogadores):
        if jogador.desconectado_em is None:
            continue
        if (agora - jogador.desconectado_em).total_seconds() >= GRACE_RECONEXAO_SEGUNDOS:
            _remover_jogador_da_sala(lobby, jogador)
            removidos = True
    if removidos:
        lobby.definir_master()
    return removidos


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
        except (ValueError, TypeError, KeyError, AttributeError):
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


@app.route("/")
def index():
    return render_template("jogo.html")


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
            else:
                # Sala de espera lotada (config 'max_jogadores'): não deixa entrar mais ninguém.
                if lobby.status == 'espera' and len(lobby.jogadores) >= int(lobby.config.get('max_jogadores', 6)):
                    emit('sala_cheia', {'sala': lobby.sala_id}, to=client_id)
                    leave_room(lobby.sala_room(), sid=client_id)
                    return
                master = False if lobby.verificar_jogador_master() else True
                jogador = Jogador.criar_jogador(client_id=client_id, master=master)
                lobby.adicionar_jogador(jogador)

        registrar_cliente(client_id, sala_id)

        emit("connect_start",
             {"is_master": jogador.master, 'chave_secreta': jogador.chave_secreta, 'sala': lobby.sala_id,
              'username': jogador.username})
        atualizar_lista_usuarios(lobby)
        enviar_snapshot_sala(lobby, jogador)


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

        # Fase 9: janela de reconexão (grace). Quem cai no meio de uma partida
        # fica marcado (desconectado_em) por GRACE_RECONEXAO_SEGUNDOS e pode
        # voltar via chave_secreta (handle_connect limpa o marcador). Fora de
        # partida (lobby), ou sem nenhum jogador ativo sobrando, remove na hora.
        if jogador.partida_atual is not None:
            outros_ativos = sum(1 for j in lobby.jogadores
                                if j is not jogador and j.desconectado_em is None)
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
        todos_desconectados = all(j.desconectado_em is not None for j in lobby.jogadores)
        if lobby.contar_jogadores() == 0 or todos_desconectados:
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
def escolher_apelido(data):
    """
    Esta função recebe o apelido do jogador no front-end e atualiza o seu modelo, antes faz umas validações.
    """
    client_id = request.sid
    _, jogador = achar_jogador(client_id)
    if jogador is None:
        return
    if jogador.partida_atual is None and jogador.rodada_atual is None and jogador.turno_atual is None:
        apelido = (data or {}).get("apelido_msg", '')
        apelido_n = jogador.lobby_atual.verificar_apelido(apelido if validar_input(apelido) else 'NOME_BUGADO')
        jogador.username = apelido_n
        emit("update_username", {'nome_jogador': jogador.username}, to=client_id)
        atualizar_lista_usuarios(jogador.lobby_atual)


@socketio.on('iniciar_partida')
@evento_mutavel
def iniciar_partida(dados):
    """
    Esta função inicia uma nova partida, é executada pelo master do lobby da sala.
    Só libera quando todos os jogadores (não-master) estiverem prontos e houver ao menos 2.
    :param dados: Vem do front, é o número de dados que cada jogador recebe para jogar.
    """
    dados = dados or {}
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or lobby is None or jogador.master is not True:
        return
    # Fase 7 (A3): não confia só no flag master — exige a chave secreta também.
    if jogador.chave_secreta != dados.get('chave', ''):
        return
    if 'dados_qtd' in dados:
        try:
            lobby.definir_config({'dados_qtd': int(dados.get('dados_qtd', 1))})
        except (ValueError, TypeError):
            pass
    pode, motivo = lobby.pode_iniciar()
    if not pode:
        emit('iniciar_negado', {'motivo': motivo}, to=client_id)
        return
    partida = lobby.construir_partida(dados_qtd=int(lobby.config.get('dados_qtd', 1)))
    partida.construir_rodada()
    salvar_sala(lobby)
    # Fase 8: status virou 'jogando' — atualiza o resumo da busca de partidas.
    store.salvar_resumo(lobby.sala_id, lobby.resumo_partida())


@socketio.on('configurar_partida')
@evento_mutavel
def configurar_partida(dados):
    """
    Aplica as configurações da partida definidas pelo master na sala de espera
    (nome, quantidade de dados, máximo de jogadores, coringa, pública).
    """
    dados = dados or {}
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or lobby is None or not jogador.master:
        return
    if jogador.chave_secreta != dados.get('chave', ''):
        return
    if lobby.status != 'espera':
        return
    if lobby.definir_config(dados.get('config', {})):
        atualizar_lista_usuarios(lobby)


@socketio.on('ficar_pronto')
@evento_mutavel
def ficar_pronto(dados):
    """
    Alterna a prontidão do jogador na sala de espera. O jogo só inicia quando
    todos os jogadores (não-master) estiverem prontos.
    """
    dados = dados or {}
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or lobby is None:
        return
    if jogador.chave_secreta != dados.get('chave', ''):
        return
    if lobby.status != 'espera':
        return
    jogador.pronto = not jogador.pronto
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
def verificar_desconectados(dados):
    """
    Os clientes agendam este evento após receberem 'jogador_desconectado'
    (Fase 9): garante que alguém expurgue, após a janela de graça, quem caiu no
    meio da partida e não voltou — sem depender de timer no servidor.
    achar_jogador já faz o expurgo; aqui só persistimos se algo saiu.
    """
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or lobby is None:
        return
    if _purgar_desconectados(lobby):
        atualizar_lista_usuarios(lobby)


@socketio.on('jogar_dados')
@evento_mutavel
def jogar_dados(dados):
    """
    Esta função envia os números dos dados sorteados aos jogadores, cada jogador recebe seus
    respectivos dados sorteados.
    """
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or jogador.rodada_atual is None:
        return
    # Fase 7 (A3): autentica o dono do sid.
    if jogador.chave_secreta != (dados or {}).get('chave', ''):
        return
    # Fase 7 (A6): idempotência explícita por rodada — já rolou não rola de novo.
    if jogador.joguei_dados:
        return
    jogador.joguei_dados = True
    emit("jogar_dados_resultado", {"jogador": jogador.client_id, "dados_jogador": jogador.dados})
    salvar_sala(lobby)


@socketio.on('joguei_dados')
@evento_mutavel
def joguei_dados(dados):
    """
    Esta função é executada por cada jogador da partida quando termina de executar e visualizar o resultado de seus
    dados. Ela deve redirecionar todos os jogadores para a próxima tela (2), onde se inicia a partida de fato, com os
    turnos, mas somente depois de todos os dados terem sido jogados.
    """
    chave = (dados or {}).get('chave_secreta', '')
    client_id = request.sid
    _, jogador = achar_jogador(client_id)

    if jogador is not None and jogador.rodada_atual is not None and jogador.chave_secreta == chave:
        emit('meus_dados', {'dados': jogador.dados})
        rodada = jogador.rodada_atual
        # Executar isso \/ quando o último jogar os dados
        if rodada.verificar_se_todos_ja_jogaram_seus_dados():
            jogador.lobby_atual.pagina = 2
            salvar_sala(jogador.lobby_atual)
            mudar_pagina(2, sala=jogador.lobby_atual.sala_id)


@socketio.on('apostar')
@evento_mutavel
def aposta(dados):
    """
    Função executada pelo jogador quando ele faz uma aposta, mas antes verifica se o jogador está em uma rodada e se
    ele é o da vez no turno.
    """
    dados_n = (dados or {}).get('dados', {})
    if not isinstance(dados_n, dict):
        return
    chave = dados_n.get('chave', '')
    dados_aposta = dados_n.copy()
    dados_aposta.pop('chave', None)
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or not chave:
        return
    rodada = jogador.rodada_atual
    if rodada and jogador.chave_secreta == chave and rodada.vez_atual == jogador:
        jogador.rodada_atual.construir_turno(jogador=jogador, dados=dados_aposta)
        salvar_sala(lobby)


@socketio.on('desconfiar')
@evento_mutavel
def desconfiar(dados):
    """
    Função executada pelo jogador quando ele desconfia de uma aposta, mas antes verifica se o jogador está em uma
    rodada e se ele é o da vez no turno.
    :param dados: Chave do jogador para verificação de autenticidade.
    """
    chave = (((dados or {}).get('dados')) or {}).get('chave', '')
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or not chave:
        return
    if jogador.rodada_atual and jogador.rodada_atual.vez_atual == jogador and jogador.chave_secreta == chave and len(
            jogador.rodada_atual.turnos) > 0:
        jogador.rodada_atual.desconfiar(jogador=jogador)
        salvar_sala(lobby)


@socketio.on('conferencia_final')
@evento_mutavel
def conferencia_final(dados):
    """
    Quanto todos os participantes da rodada clicam em ok, na conferência final da rodada, esta função engatilha
    uma nova rodada na partida.
    """
    chave = (dados or {}).get('chave', '')
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or jogador.rodada_atual is None or jogador.partida_atual is None:
        return
    # Fase 7 (A3): autentica o dono do sid.
    if jogador.chave_secreta != chave:
        return
    if jogador.confirmou_rodada:
        return
    rodada = jogador.rodada_atual
    jogador.confirmou_rodada = True
    rodada.conferiram += 1
    if rodada.conferiram == len(rodada.jogadores):
        jogador.partida_atual.construir_rodada()
    salvar_sala(lobby)


@socketio.on('vencedor_final')
@evento_mutavel
def vencedor_final(dados):
    """
    Quanto todos os participantes da rodada clicam em ok, na tela de vencedor, esta função engatilha
    uma nova partida no lobby.
    """
    chave = (dados or {}).get('chave', '')
    client_id = request.sid
    _, jogador = achar_jogador(client_id)
    if jogador is None or jogador.lobby_atual is None:
        return
    # Fase 7 (A3): autentica o dono do sid.
    if jogador.chave_secreta != chave:
        return
    if jogador.confirmou_vencedor:
        return
    lobby = jogador.lobby_atual
    jogador.confirmou_vencedor = True
    lobby.conferiram_vencedor += 1
    if lobby.conferiram_vencedor == len(lobby.jogadores):
        lobby.resetar_para_lobby()
        atualizar_lista_usuarios(lobby)
        mudar_pagina(0, sala=lobby.sala_id)


@socketio.on('foguetear_click')
@evento_mutavel
def foguetear(dados):
    """
    Função que torna os fogos de comemoração compartilhados com todos na partida.
    """
    client_id = request.sid
    _, jogador = achar_jogador(client_id)
    if jogador is None:
        return
    # Fase 7 (A3): autentica o dono do sid.
    if jogador.chave_secreta != (dados or {}).get('chave', ''):
        return
    partida = jogador.partida_atual
    rodada = jogador.rodada_atual
    # Fase 6 (B4): partida encerrada por desconexão não define rodada.vencedor,
    # mas sim partida.vencedor_final — o vencedor precisa poder comemorar.
    if rodada is not None and rodada.vencedor == jogador:
        emit('soltar_fogos', to=jogador.lobby_atual.sala_room())
    elif partida is not None and partida.vencedor_final == jogador:
        emit('soltar_fogos', to=jogador.lobby_atual.sala_room())


if __name__ == '__main__':
    if os.environ.get("VERCEL") != "1":
        socketio.run(app, allow_unsafe_werkzeug=True)