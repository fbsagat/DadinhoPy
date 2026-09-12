# Entrypoint WSGI para a Vercel. O Flask-SocketIO injeta o middleware de
# /socket.io em `app.wsgi_app` (socketio.WSGIApp), então basta exportá-lo.
from app import app

application = app.wsgi_app