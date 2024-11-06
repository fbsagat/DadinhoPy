from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from funcoes_gerais import *
from modelos import *

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)


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
    emit("connect_start", {"is_master": master, 'chave_secreta': jogador.chave_secreta})
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
    apelido_n = lobby_unico.verificar_apelido(apelido)
    jogador.username = apelido_n
    atualizar_lista_usuarios()


@socketio.on('ir_jogar_dados')
def ir_jogar_dados():
    client_id = request.sid
    jogador = lobby_unico.buscar_jogador_pelo_client_id(client_id)
    if jogador.master is True and lobby_unico.contar_jogadores() >= 2:
        jogadores = lobby_unico.listar_jogadores()
        partida.jogadores = jogadores
        partida.jogar_dados()
        mudar_pagina(1, broadcast=True)


@socketio.on('jogar_dados')
def jogar_dados():
    """
    Esta função envia os números dos dados aos jogadores, cada jogador recebe seus respectivos dados sorteados
    """
    client_id = request.sid
    jogador = lobby_unico.buscar_jogador_pelo_client_id(client_id)
    emit("jogar_dados_resultado", {"jogador": jogador.client_id, "dados_jogador": jogador.dados})


@socketio.on('joguei_dados')
def joguei_dados(data):
    """
    Esta função é executada por cada jogador da partida quando termina de executar e visualizar o resultado de seus
    dados. Ela deve redirecionar todos so jogadores para a próxima tela (2), onde se inicia a partida de fato, com os
    turnos, mas somente depois de todos os dados terem sido jogados.
    """
    jogadores = partida.jogadores
    jogador = [jogador for jogador in jogadores if jogador.client_id == data][0]
    partida.todos_os_dados += jogador.dados
    emit('meus_dados', {'dados': jogador.dados})

    # Executar isso \/ quando o último jogar os dados
    if partida.verificar_se_todos_ja_jogaram_seus_dados():
        partida.iniciar_partida()
        # time.sleep(random.randint(3, 4))
        mudar_pagina(2, broadcast=True)


@socketio.on('apostar')
def aposta(dados):
    # PAREI AQUI!
    # A PARTIR DE AGORA O SERVIDOR DEVE CRIAR UM WHILE, CADA VOLTA CRIA UM TURNO E ADICIONA NA PARTIDA, CADA TURNO
    # RECEBE INFOS DESTA FUNCAO COM A JOGADA DO JOGADOR DE VEZ, FAZENDO UMA VALIDAÇÃO DE AUTENTICIDADE VALORES
    # DEPOIS DISSO DAR CONTINUIDADE A PARTIDA
    print(dados)


@socketio.on('desconfiar')
def aposta(dados):
    print(dados)


if __name__ == '__main__':
    socketio.run(app)
