from flask import Flask, render_template, request, url_for
from flask_socketio import SocketIO, emit
from datetime import datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)

# Armazenar informações dos usuários
jogadores = {}


@app.route("/")
def index():
    return render_template("lobby.html")


# Evento para conexão de novos usuários
@socketio.on('connect')
def handle_connect():
    client_id = request.sid
    jogadores_qtd = len(jogadores)
    master = False
    if jogadores_qtd == 0:
        print('temos', len(jogadores), 'jogadores, portanto MASTER True')
        master = True
    jogadores[client_id] = {'username': None, 'master': master, 'pontos': 0, 'entrou': datetime.now()}
    print(f'Client {client_id} connected')
    print('Jogadores conectados: ', len(jogadores), jogadores)
    print(master)
    emit("user_role", {"is_master": master})


# Evento para desconexão de usuários
@socketio.on('disconnect')
def handle_disconnect():
    client_id = request.sid
    era_master = False
    first_value = False
    if jogadores[client_id]['master'] is True:
        era_master = True
    if client_id in jogadores:
        del jogadores[client_id]
        if era_master is True:
            # Ordenando o dicionário pelos valores de 'entrou'
            sorted_data = dict(sorted(jogadores.items(), key=lambda item: item[1]['entrou']))
            first_key, first_value = next(iter(sorted_data.items()))
            first_value['master'] = first_value = True
            print('sorted_data, primeiro vira master', sorted_data)
    print('Client disconnected')
    emit("update_user_list", {
        "users": [
            f"{user["username"]} ({user["pontos"]} pontos)" + (str(' (Master)') if user["master"] is True else str(''))
            for user in
            jogadores.values() if user["username"]]},
         broadcast=True)
    emit("user_role", {"is_master": first_value}, broadcast=True)


# Evento para receber texto do cliente
@socketio.on('apelido')
def handle_apelido(data):
    print(f'Received apelido: {data["apelido_msg"]}')
    client_id = request.sid
    jogadores[client_id]['username'] = data["apelido_msg"]
    print('Jogadores conectados: ', len(jogadores), jogadores)
    emit("update_user_list", {
        "users": [
            f"{user["username"]} ({user["pontos"]} pontos)" + (str(' (Master)') if user["master"] is True else str(''))
            for user in
            jogadores.values() if user["username"]]},
         broadcast=True)
    emit("user_role", {"is_master": jogadores[client_id]['master']})


@socketio.on('jogar_dados')
def jogar_dados():
    # Próximo passo: Iniciar a nova tela onde os jogadores vão sortear seus dados
    print('jogar dados')


if __name__ == '__main__':
    socketio.run(app)
