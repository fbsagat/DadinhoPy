from flask import Flask, render_template, request, url_for
from flask_socketio import SocketIO, emit
from datetime import datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)

# Armazenar informações dos usuários
jogadores = {}
jogador_count = 0


def jogador_on(client_id):
    global jogador_count
    master = False
    nenhum_master_verdadeiro = all(not item['master'] for item in jogadores.values())
    if nenhum_master_verdadeiro:
        master = True
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
            return True  # Retorna True se a modificação foi feita
        return False  # Retorna False se não houve modificação

    def remover_item_por_client_id(dicionario, client_id):
        for chave_item in list(dicionario.keys()):  # Usar list para evitar alteração no dicionário durante a iteração
            if dicionario[chave_item]['client_id'] == client_id:
                del dicionario[chave_item]  # Remove o item correspondente
                return True  # Retorna True se o item foi removido
        return False  # Retorna False se nenhum item foi encontrado

    remover_item_por_client_id(jogadores, client_id)
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


@app.route("/")
def index():
    return render_template("jogo.html")


@socketio.on('connect')
def handle_connect():
    print('Um usuário conectado')
    client_id = request.sid
    jogador_on(client_id)
    atualizar_lista_usuarios()
    # emit("user_role", {"is_master": master})


# Evento para desconexão de usuários
@socketio.on('disconnect')
def handle_disconnect():
    print('Um usuário desconectado')
    client_id = request.sid
    jogador_off(client_id)
    atualizar_lista_usuarios()
    # emit("user_role", {"is_master": first_value}, broadcast=True)


# Evento para receber texto do cliente
@socketio.on('apelido')
def escolher_apelido(data):
    def numero_por_client_id(dicionario, client_id):
        for chave, item in dicionario.items():
            if item['client_id'] == client_id:
                return chave

    apelido = data["apelido_msg"]
    client_id = request.sid
    jogador_n = numero_por_client_id(jogadores, client_id)
    jogadores[jogador_n]['username'] = apelido
    print(f'Recebido apelido: {apelido} de {jogador_n}, {client_id}')
    print(jogadores)
    atualizar_lista_usuarios()
    # emit("user_role", {"is_master": jogadores[client_id]['master']})


if __name__ == '__main__':
    socketio.run(app)
