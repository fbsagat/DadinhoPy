from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import uuid

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)

users = {}


@app.route("/")
def index():
    return render_template("lobby.html")


@socketio.on("send_message")
def handle_send_message(data):
    users[request.sid] = data['username']
    print(users)
    print(f"Mensagem recebida: {data['username']}: {data['message']}")
    emit("receive_message", {"username": data["username"], "message": data["message"]}, broadcast=True)


if __name__ == "__main__":
    socketio.run(app, debug=True)
