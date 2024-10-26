from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)


@app.route("/")
def index():
    return render_template("index.html")


@socketio.on("send_message")
def handle_send_message(data):
    print(f"Mensagem recebida: {data['username']}: {data['message']}")
    emit("receive_message", {"username": data["username"], "message": data["message"]}, broadcast=True)


if __name__ == "__main__":
    socketio.run(app, debug=True)
