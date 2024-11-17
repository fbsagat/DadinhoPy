from flask import Flask, render_template, request
from flask_socketio import SocketIO
from funcoes_gerais import *
from modelos import *

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)
jogadores_online = {}


@app.route("/")
def index():
    return render_template("jogo.html")


@socketio.on('connect')
def handle_connect():
    """
    Esta função é executada no momento da conexão de um cliente web do servidor.
    Ela deve criar uma instância de jogador, e decidir se ele é master, caso não haja algum,
    Ela deve criar ums instância de partida caso não haja alguma também, e inserir o jogador master nela
    """
    global jogadores_online
    client_id = request.sid
    master = False if lobby_unico.verificar_jogador_master() else True
    jogador = Jogador.criar_jogador(client_id=client_id, master=master)
    lobby_unico.adicionar_jogador(jogador)
    jogadores_online[jogador.client_id] = jogador
    emit("connect_start",
         {"is_master": master, 'chave_secreta': jogador.chave_secreta})
    atualizar_lista_usuarios()


@socketio.on('disconnect')
def handle_disconnect():
    """
    Esta função é executada no momento da desconexão de um cliente web do servidor.
    Esta função deve remover o jogador da partida e caso este jogador seja um master e haja mais jogadores no lobby
    dele, Selecionar outro jogador, por ordem de entrada, mais antigo pro mais novo, para se tornar o novo master do
     lobby, caso não seja um master, apenas remover, caso apenas ele no lobby, reiniciar o servidor(por enquanto).
    """
    client_id = request.sid
    lobby_unico.remover_jogador(client_id)
    del jogadores_online[client_id]
    if lobby_unico.contar_jogadores() > 0:
        # Definir novo master
        lobby_unico.definir_master()
    atualizar_lista_usuarios()


@socketio.on('apelido')
def escolher_apelido(data):
    """
    Esta função recebe o apelido do jogador no front-end e atualiza o seu modelo
    """
    apelido = validar_input(data["apelido_msg"])
    if apelido:
        client_id = request.sid
        jogador = lobby_unico.buscar_jogador_pelo_client_id(client_id)
        apelido_n = lobby_unico.verificar_apelido(apelido)
        jogador.username = apelido_n
        emit("update_username", {'nome_jogador': jogador.username}, to=client_id)
        atualizar_lista_usuarios()


@socketio.on('iniciar_partida')
def iniciar_partida():
    # dados_qtd = int(data['dados_qtd'])
    # print('dados_qtd', dados_qtd)
    client_id = request.sid
    jogador = lobby_unico.buscar_jogador_pelo_client_id(client_id)
    if jogador.master is True and lobby_unico.contar_jogadores() >= 2:
        partida = lobby_unico.construir_partida()
        partida.construir_rodada()
        # print('Iniciando nova partida: ', partida)


@socketio.on('jogar_dados')
def jogar_dados():
    """
    Esta função envia os números dos dados aos jogadores, cada jogador recebe seus respectivos dados sorteados
    """
    client_id = request.sid
    jogador = lobby_unico.buscar_jogador_pelo_client_id(client_id)
    jogador.joguei_dados = True
    emit("jogar_dados_resultado", {"jogador": jogador.client_id, "dados_jogador": jogador.dados})


@socketio.on('joguei_dados')
def joguei_dados(dados):
    """
    Esta função é executada por cada jogador da partida quando termina de executar e visualizar o resultado de seus
    dados. Ela deve redirecionar todos os jogadores para a próxima tela (2), onde se inicia a partida de fato, com os
    turnos, mas somente depois de todos os dados terem sido jogados.
    """
    global jogadores_online
    chave = dados['chave_secreta']
    client_id = request.sid
    jogador = jogadores_online[client_id]

    if jogador.chave_secreta == chave:
        emit('meus_dados', {'dados': jogador.dados})
        rodada = jogador.rodada_atual
        # Executar isso \/ quando o último jogar os dados
        if rodada.verificar_se_todos_ja_jogaram_seus_dados():
            # time.sleep(random.randint(3, 4)) ATIVAR NO FINAL -=--------------------------------------------------
            mudar_pagina(2, broadcast=True)


@socketio.on('apostar')
def aposta(dados):
    chave = dados['dados']['chave'][:]
    dados = dados['dados']
    del dados['chave']
    client_id = request.sid
    jogador = jogadores_online[client_id]
    rodada = jogador.rodada_atual
    if rodada:
        # print('')
        # print(f"{jogador.username} apostou na rodada {rodada}")
        # print('Verificar se é o da vez: Vez de:', rodada.vez_atual.username, 'Quem jogou:', jogador.username)
        if jogador.chave_secreta == chave and rodada.vez_atual == jogador:
            # print('PASSOU')
            # Se o jogador está em uma rodada / Se o jogador é realmente o dono do username / Se é a vez dele na rodada
            jogador.rodada_atual.construir_turno(jogador=jogador, dados=dados)


@socketio.on('desconfiar')
def desconfiar(dados):
    chave = dados['dados']['chave']
    client_id = request.sid
    jogador = jogadores_online[client_id]
    if jogador.rodada_atual and jogador.rodada_atual.vez_atual == jogador and jogador.chave_secreta == chave and len(
            jogador.rodada_atual.turnos) > 0:
        # Verifica se o jogador que enviou a requisição é o da vez
        # Verificar se já é a partir do segundo turno
        jogador.rodada_atual.desconfiar(jogador=jogador)


@socketio.on('conferencia_final')
def conferencia_final():
    client_id = request.sid
    jogador = jogadores_online[client_id]
    if jogador.rodada_atual:
        jogador.rodada_atual.conferiram += 1
        if jogador.rodada_atual.conferiram == len(jogador.rodada_atual.jogadores):
            jogador.partida_atual.construir_rodada()


@socketio.on('vencedor_final')
def vencedor_final():
    client_id = request.sid
    jogador = jogadores_online[client_id]
    jogador.lobby_atual.conferiram_vencedor += 1
    if jogador.lobby_atual.conferiram_vencedor == len(jogador.lobby_atual.jogadores):
        mudar_pagina(0, broadcast=True)


@socketio.on('foguetear_click')
def foguetear():
    client_id = request.sid
    jogador = jogadores_online[client_id]
    if jogador.rodada_atual:
        if jogador == jogador.rodada_atual.vencedor:
            emit('soltar_fogos', broadcast=True)


if __name__ == '__main__':
    socketio.run(app)
