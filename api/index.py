# Entrypoint WSGI para a Vercel. O Flask-SocketIO injeta o middleware de
# /socket.io em `app.wsgi_app` (socketio.WSGIApp).
#
# No async_mode 'threading', o `simple-websocket` que o engineio usa detecta o
# `werkzeug.socket` do runtime da Vercel e entra no modo 'werkzeug'. Ao encerrar
# a sessão WebSocket ele levanta `ConnectionError`, que é o sinal consumido pelo
# servidor de desenvolvimento do Werkzeug para não escrever uma resposta HTTP
# sobre o socket já sequestrado. O runtime da Vercel não trata esse sinal e a
# exceção vira um traceback (status 0) no log de toda conexão WS — inclusive no
# carregamento da página inicial, que abre e fecha o socket ao redirecionar para
# a sala nova. Como o 101 já foi enviado direto no socket pelo handshake, engolir
# o `ConnectionError` aqui é seguro e limpa o log. O app local (`socketio.run`)
# não passa por este wrapper, então o Werkzeug continua tratando o sinal.
#
# O detector de entrypoint da Vercel prefere a variável de topo `app` (antes de
# `application`), então é ela que precisa carregar o wrapper — por isso a
# instância Flask é importada como `_flask_app` e `app`/`application` apontam
# para o wrapper.
from app import app as _flask_app


class _SuprimirConnectionErrorWSGI:
    def __init__(self, app_wsgi):
        self.app_wsgi = app_wsgi

    def __call__(self, environ, start_response):
        try:
            return self.app_wsgi(environ, start_response)
        except ConnectionError:
            return []


app = _SuprimirConnectionErrorWSGI(_flask_app.wsgi_app)
application = app
