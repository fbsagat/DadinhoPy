from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import uuid

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)

# Armazenar informações dos usuários
users = {}


@app.route("/")
def index():
    return render_template("lobby.html")


@socketio.on("connect")
def handle_connect():
    # Se não houver um mestre, este usuário se torna o mestre
    if not any(user.get("master") for user in users.values()):
        master_status = True
    else:
        master_status = False

    user_id = str(uuid.uuid4())  # Gera um UUID único
    users[request.sid] = {"id": user_id, "username": None, "master": master_status}
    print(f"Usuário conectado: {user_id}, Master: {master_status}")

    # Envia ao cliente se ele é o "mestre" ou não
    emit("user_role", {"is_master": master_status})


@socketio.on("set_username")
def handle_set_username(data):
    user_sid = request.sid
    none_count = sum(1 for user in users.values() if user['username'] is not None)
    master = True if none_count < 1 else False
    if user_sid in users:
        users[user_sid]["username"] = data["username"]  # Define o nome do usuário
        users[user_sid]["master"] = master  # Define se vai ser o servidor
        print(f"Nome definido para {user_sid}: {data['username']}, master: {master}")
        emit("update_user_list", {"users": [user["username"] for user in users.values() if user["username"]]},
             broadcast=True)


# @socketio.on("send_message")
# def handle_send_message(data):
#     user_sid = request.sid
#     if user_sid in users:
#         username = users[user_sid]["username"]  # Obtém o nome do usuário
#         print(f"Mensagem recebida de {username}: {data['message']}")
#         emit("receive_message", {"username": username, "message": data["message"]}, broadcast=True)


@socketio.on("disconnect")
def handle_disconnect():
    user_sid = request.sid
    if user_sid in users:
        print(f"Usuário desconectado: {users[user_sid]['username'] or users[user_sid]['id']}")
        del users[user_sid]  # Remove o usuário da lista ao desconectar
        emit("update_user_list", {"users": [user["username"] for user in users.values() if user["username"]]},
             broadcast=True)


if __name__ == "__main__":
    socketio.run(app, debug=True)
