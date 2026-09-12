from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from funcoes_gerais import (buscar_lobby_pelo_client_id, mudar_pagina, normalizar_sala, obter_sala,
                            atualizar_lista_usuarios, remover_sala, salvar_sala, validar_input, validar_numero,
                            enviar_snapshot_sala)
from modelos import Jogador
import os
import random
import time

app = Flask(__name__)
app.secret_key = os.environ.get("DADINHO_SECRET_KEY", "supersecretkey")

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
    Retorna o par (lobby, jogador); (None, None) caso não esteja em nenhuma sala.
    """
    lobby = buscar_lobby_pelo_client_id(client_id)
    if lobby is None:
        return None, None
    return lobby, lobby.buscar_jogador_pelo_client_id(client_id)


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
    lobby = obter_sala(sala_id)
    join_room(lobby.sala_room(), sid=client_id)

    jogador = lobby.buscar_jogador_pelo_client_id(client_id)
    if jogador is None:
        chave_resumo = request.args.get('chave_secreta', '')
        jogador = lobby.buscar_jogador_pela_chave(chave_resumo)
        if jogador is not None:
            # Retomando a mesma identidade: religa o sid novo ao mesmo Jogador.
            jogador.client_id = client_id
        else:
            master = False if lobby.verificar_jogador_master() else True
            jogador = Jogador.criar_jogador(client_id=client_id, master=master)
            lobby.adicionar_jogador(jogador)

    emit("connect_start",
         {"is_master": jogador.master, 'chave_secreta': jogador.chave_secreta, 'sala': lobby.sala_id,
          'username': jogador.username})
    atualizar_lista_usuarios(lobby)
    enviar_snapshot_sala(lobby, jogador)
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
    lobby, jogador = achar_jogador(client_id)
    if lobby is None:
        return
    leave_room(lobby.sala_room(), sid=client_id)

    lobby.remover_jogador(client_id)

    partida = jogador.partida_atual
    if partida is not None and jogador in partida.jogadores:
        rodada = jogador.rodada_atual
        indice_antigo = partida.jogadores.index(jogador)
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
            if rodada is not None and rodada.verificar_se_todos_ja_jogaram_seus_dados():
                lobby.pagina = 2
                time.sleep(random.randint(4, 5))
                mudar_pagina(2, sala=lobby.sala_id)

    if lobby.contar_jogadores() > 0:
        lobby.definir_master()
    atualizar_lista_usuarios(lobby)
    if lobby.contar_jogadores() == 0:
        remover_sala(lobby.sala_id)
    else:
        salvar_sala(lobby)


@socketio.on('apelido')
def escolher_apelido(data):
    """
    Esta função recebe o apelido do jogador no front-end e atualiza o seu modelo, antes faz umas validações.
    """
    client_id = request.sid
    _, jogador = achar_jogador(client_id)
    if jogador is None:
        return
    if jogador.partida_atual is None and jogador.rodada_atual is None and jogador.turno_atual is None:
        apelido = data.get("apelido_msg", '')
        apelido_n = jogador.lobby_atual.verificar_apelido(apelido if validar_input(apelido) else 'NOME_BUGADO')
        jogador.username = apelido_n
        emit("update_username", {'nome_jogador': jogador.username}, to=client_id)
        atualizar_lista_usuarios(jogador.lobby_atual)
        salvar_sala(jogador.lobby_atual)


@socketio.on('iniciar_partida')
def iniciar_partida(dados):
    """
    Esta função inicia uma nova partida, é executada pelo master do lobby da sala.
    :param dados: Vem do front, é o número de dados que cada jogador recebe para jogar.
    """
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or lobby is None or jogador.master is not True or lobby.contar_jogadores() < 2:
        return
    try:
        dados_qtd = int(dados.get('dados_qtd', 1))
    except (ValueError, TypeError):
        dados_qtd = 1
    valido = validar_numero(dados_qtd)
    partida = lobby.construir_partida(dados_qtd=dados_qtd if valido else 1)
    partida.construir_rodada()
    salvar_sala(lobby)


@socketio.on('jogar_dados')
def jogar_dados():
    """
    Esta função envia os números dos dados sorteados aos jogadores, cada jogador recebe seus
    respectivos dados sorteados.
    """
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or jogador.rodada_atual is None:
        return
    jogador.joguei_dados = True
    emit("jogar_dados_resultado", {"jogador": jogador.client_id, "dados_jogador": jogador.dados})
    salvar_sala(lobby)


@socketio.on('joguei_dados')
def joguei_dados(dados):
    """
    Esta função é executada por cada jogador da partida quando termina de executar e visualizar o resultado de seus
    dados. Ela deve redirecionar todos os jogadores para a próxima tela (2), onde se inicia a partida de fato, com os
    turnos, mas somente depois de todos os dados terem sido jogados.
    """
    chave = dados.get('chave_secreta', '')
    client_id = request.sid
    _, jogador = achar_jogador(client_id)

    if jogador is not None and jogador.rodada_atual is not None and jogador.chave_secreta == chave:
        emit('meus_dados', {'dados': jogador.dados})
        rodada = jogador.rodada_atual
        # Executar isso \/ quando o último jogar os dados
        if rodada.verificar_se_todos_ja_jogaram_seus_dados():
            jogador.lobby_atual.pagina = 2
            salvar_sala(jogador.lobby_atual)
            time.sleep(random.randint(4, 5))
            mudar_pagina(2, sala=jogador.lobby_atual.sala_id)


@socketio.on('apostar')
def aposta(dados):
    """
    Função executada pelo jogador quando ele faz uma aposta, mas antes verifica se o jogador está em uma rodada e se
    ele é o da vez no turno.
    """
    dados_n = dados.get('dados', {})
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
def desconfiar(dados):
    """
    Função executada pelo jogador quando ele desconfia de uma aposta, mas antes verifica se o jogador está em uma
    rodada e se ele é o da vez no turno.
    :param dados: Chave do jogador para verificação de autenticidade.
    """
    chave = dados.get('dados', {}).get('chave', '')
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or not chave:
        return
    if jogador.rodada_atual and jogador.rodada_atual.vez_atual == jogador and jogador.chave_secreta == chave and len(
            jogador.rodada_atual.turnos) > 0:
        jogador.rodada_atual.desconfiar(jogador=jogador)
        salvar_sala(lobby)


@socketio.on('conferencia_final')
def conferencia_final():
    """
    Quanto todos os participantes da rodada clicam em ok, na conferência final da rodada, esta função engatilha
    uma nova rodada na partida.
    """
    client_id = request.sid
    lobby, jogador = achar_jogador(client_id)
    if jogador is None or jogador.rodada_atual is None or jogador.partida_atual is None:
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
def vencedor_final():
    """
    Quanto todos os participantes da rodada clicam em ok, na tela de vencedor, esta função engatilha
    uma nova partida no lobby.
    """
    client_id = request.sid
    _, jogador = achar_jogador(client_id)
    if jogador is None or jogador.lobby_atual is None:
        return
    if jogador.confirmou_vencedor:
        return
    lobby = jogador.lobby_atual
    jogador.confirmou_vencedor = True
    lobby.conferiram_vencedor += 1
    if lobby.conferiram_vencedor == len(lobby.jogadores):
        lobby.resetar_para_lobby()
        mudar_pagina(0, sala=lobby.sala_id)
    salvar_sala(lobby)


@socketio.on('foguetear_click')
def foguetear():
    """
    Função que torna os fogos de comemoração compartilhados com todos na partida.
    """
    client_id = request.sid
    _, jogador = achar_jogador(client_id)
    if jogador is None or jogador.rodada_atual is None:
        return
    if jogador == jogador.rodada_atual.vencedor:
        emit('soltar_fogos', to=jogador.lobby_atual.sala_room())


if __name__ == '__main__':
    if os.environ.get("VERCEL") != "1":
        socketio.run(app, allow_unsafe_werkzeug=True)