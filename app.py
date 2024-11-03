from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from modelos import *

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)
lobby_unico = Lobby()


def mudar_pagina():
    emit("mudar_pagina", broadcast=True)


def atualizar_lista_usuarios():
    lista = lobby_unico.listar_jogadores()
    usernames = [jogador.username for jogador in lista if jogador.username is not None]
    pontos = [jogador.pontos for jogador in lista if jogador.username is not None]
    masters = [jogador.master for jogador in lista if jogador.username is not None]
    o_master = lobby_unico.retornar_master()
    if o_master:
        emit("master_def", {"is_master": True}, to=o_master.client_id)
    emit("update_user_list", {"users": usernames, "pontos": pontos, "masters": masters}, broadcast=True)


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
    client_id = request.sid
    master = False if lobby_unico.verificar_jogador_master() else True
    jogador = Jogador.criar_jogador(client_id=client_id, master=master)
    lobby_unico.adicionar_jogador(jogador)
    emit("connect_start", {"is_master": master})
    atualizar_lista_usuarios()


@socketio.on('disconnect')
def handle_disconnect():
    """
    Esta função é executada no momento da desconexão de um cliente web do servidor.
    Esta função deve remover o jogador da partida e caso este jogador seja um master e haja mais jogadores no lobby dele,
    Selecionar outro jogador, por ordem de entrada, mais antigo pro mais novo, para se tornar o novo master do lobby,
    caso não seja um master, apenas remover, caso apenas ele no lobby, reiniciar o servidor(por enquanto).
    """
    client_id = request.sid
    lobby_unico.remover_jogador(client_id)
    # print(lobby_unico)
    if lobby_unico.contar_jogadores() > 0:
        # Definir novo master
        lobby_unico.definir_master()
    atualizar_lista_usuarios()


@socketio.on('apelido')
def escolher_apelido(data):
    """
    Esta função recebe o apelido do jogador no front-end e atualiza o seu modelo
    """
    apelido = data["apelido_msg"]
    client_id = request.sid

    jogador = lobby_unico.buscar_jogador_pelo_client_id(client_id)
    jogador.username = apelido
    atualizar_lista_usuarios()


@socketio.on('ir_jogar_dados')
def ir_jogar_dados():
    client_id = request.sid
    jogador = lobby_unico.buscar_jogador_pelo_client_id(client_id)
    if jogador.master is True and lobby_unico.contar_jogadores() >= 2:
        mudar_pagina()


@socketio.on('jogar_dados')
def jogar_dados():
    client_id = request.sid
    jogador = lobby_unico.buscar_jogador_pelo_client_id(client_id)
    print('Cheguei em jogar_dados')
    # dados = jogador.partida.jogar_dados()
    # nums = [1, 2, 3, 4, 5, 6]
    # dados_r = random.sample(nums, k=3)
    # dados_jogador[jogador_n] = dados_r
    # # print('dados_jogador', dados_jogador)
    # emit("jogar_dados_resultado", {"jogador": jogador_n, "dados_jogador": dados_r})
    # if (len(dados_jogador) == len(jogadores)) and len(dados_jogador) <= limite_jogadores:
    #     mudar_pagina()  # Antes de mudar a página, executar a animação e exibição do resultado pros jogadores


@socketio.on('joguei_dados')
def joguei_dados(data):
    pass
    # print('joguei_dadosAAA', data)  # PAREI AQUI


if __name__ == '__main__':
    socketio.run(app)
