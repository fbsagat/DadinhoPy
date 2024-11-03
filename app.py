from flask import Flask, render_template, request, url_for
from flask_socketio import SocketIO, emit
from datetime import datetime
import random

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)

# Armazenar informações dos usuários
jogadores = {}
jogador_count = 0
dados_jogador = {}
limite_jogadores = 6


def virar_master():
    # Qualquer um executa, mas quem vira o master é o que está true naa lista
    def obter_client_id_master(dicionario):
        for dados in dicionario.values():
            if dados.get('master') is True:  # Verifica se master é True
                return dados.get('client_id')  # Retorna o client_id correspondente
        return None  # Retorna None se não encontrar

    print('virar_master executado por: ', request.sid)
    sid_jogador_master = obter_client_id_master(jogadores)
    emit("master_def", {"is_master": True}, to=sid_jogador_master)


def mudar_pagina():
    print('mudar_pagina executado')
    emit("mudar_pagina", broadcast=True)


def jogador_on(client_id):
    global jogador_count
    master = False
    nenhum_master_verdadeiro = all(not item['master'] for item in jogadores.values())
    if nenhum_master_verdadeiro:
        master = True
        virar_master()
    jogador = {'client_id': client_id, 'username': None, 'master': master, 'pontos': 0, 'entrou': datetime.now()}
    jogadores[jogador_count] = jogador
    jogador_count += 1
    print(jogadores)
    print('total conectados: ', len(jogadores))


def jogador_off(client_id):
    def modificar_master(dicionario):
        # Verificar se nenhum item tem master = True
        nenhum_master_verdadeiro = all(not item['master'] for item in dicionario.values())

        if nenhum_master_verdadeiro:
            # Modificar a chave master do primeiro item para True
            primeiro_item_chave = list(dicionario.keys())[0]  # Pega a chave do primeiro item
            dicionario[primeiro_item_chave]['master'] = True
            virar_master()
            return True  # Retorna True se a modificação foi feita
        return False  # Retorna False se não houve modificação

    def remover_player_por_client_id(dicionario, client_id):
        for chave_item in list(dicionario.keys()):  # Usar list para evitar alteração no dicionário durante a iteração
            if dicionario[chave_item]['client_id'] == client_id:
                del dicionario[chave_item]  # Remove o item correspondente

                if chave_item in dados_jogador:
                    dados_jogador.pop(chave_item)  # Apagar o registro de dados_partida tbm

                return True  # Retorna True se o item foi removido
        return False  # Retorna False se nenhum item foi encontrado

    remover_player_por_client_id(jogadores, client_id)
    if len(jogadores) > 0:
        modificar_master(jogadores)
    print(jogadores)
    print('total conectados: ', len(jogadores))


def atualizar_lista_usuarios():
    emit("update_user_list", {
        "users": [user["username"] for user in jogadores.values() if user["username"] is not None],
        "pontos": [user["pontos"] for user in jogadores.values() if user["pontos"] is not None],
        "masters": [user["master"] for user in jogadores.values() if user["master"] is not None]},
         broadcast=True)


def numero_por_client_id(dicionario, client_id):
    # Retorna o número do jogador no dicionário 'jogadores' pelo client_id
    for chave, item in dicionario.items():
        if item['client_id'] == client_id:
            return chave


@app.route("/")
def index():
    return render_template("jogo.html")


@socketio.on('connect')
def handle_connect():
    print('Um usuário conectado')
    client_id = request.sid
    jogador_on(client_id)
    atualizar_lista_usuarios()
    jognum = numero_por_client_id(jogadores, client_id)
    master = jogadores[jognum]['master']
    emit("connect_start", {"is_master": master})


# Evento para desconexão de usuários
@socketio.on('disconnect')
def handle_disconnect():
    print('Um usuário desconectado')
    client_id = request.sid
    jogador_off(client_id)
    atualizar_lista_usuarios()


# Evento para receber os apelidos dos jogadores
@socketio.on('apelido')
def escolher_apelido(data):
    apelido = data["apelido_msg"]
    client_id = request.sid
    jogador_n = numero_por_client_id(jogadores, client_id)
    jogadores[jogador_n]['username'] = apelido
    print(f'Recebido apelido: {apelido}, Num:{jogador_n}, ID:{client_id}')
    print(jogadores)
    atualizar_lista_usuarios()


@socketio.on('ir_jogar_dados')
def ir_jogar_dados():
    client_id = request.sid
    jogador_n = numero_por_client_id(jogadores, client_id)
    jogador = jogadores[jogador_n]
    if jogador['master'] is True and len(jogadores) >= 2:
        mudar_pagina()


@socketio.on('jogar_dados')
def jogar_dados():
    client_id = request.sid
    jogador_n = numero_por_client_id(jogadores, client_id)
    jogador = jogadores[jogador_n]
    print(f'{jogador['username']} jogou dados')
    nums = [1, 2, 3, 4, 5, 6]
    dados_r = random.sample(nums, k=3)
    dados_jogador[jogador_n] = dados_r
    print('dados_jogador', dados_jogador)
    emit("jogar_dados_resultado", {"jogador": jogador_n, "dados_jogador": dados_r})
    # if (len(dados_jogador) == len(jogadores)) and len(dados_jogador) <= limite_jogadores:
    #     mudar_pagina()  # Antes de mudar página executar a animação e exibição do resultado pros jogadores


@socketio.on('joguei_dados')
def joguei_dados(data):
    print('joguei_dadosAAA', data) # PAREI AQUI


if __name__ == '__main__':
    socketio.run(app)
