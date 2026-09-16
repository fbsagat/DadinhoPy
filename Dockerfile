# Dadinho — API (Socket.IO) para rodar como processo persistente numa VPS
# (Fase 46). Frontend fica na Vercel; esta imagem serve só o backend
# (/socket.io) + as rotas REST auxiliares (/, /tema.mid, /static).
#
# Build:  docker build -t dadinho-api .
# Rodar:  ver docker-compose.yml (sobe junto com o Redis local).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Fase 61: cada container roda 1 worker gevent (cooperativo — milhares de
# sockets por processo num único thread, em vez de 100 threads nativos). Exige
# `DADINHO_ASYNC_MODE=gevent` no ambiente (docker-compose seta) e o gunicorn
# aplica o monkey-patch antes de importar o app. O WebSocket vem do driver
# gevent do python-engineio sobre `simple-websocket`: NÃO instalar
# `gevent-websocket` — com ele presente o engineio passa a exigir
# `environ['wsgi.websocket']`, que só existe no worker
# `geventwebsocket.gunicorn.workers.GeventWebSocketWorker`; no worker `gevent`
# puro (o de baixo) TODO handshake WebSocket responde 500 e o cliente, que pede
# `['websocket', 'polling']`, fica preso sem cair no polling.
#
# -w 1 por container: a session Engine.IO vive na memória do worker e o gunicorn
# não faz sticky session; a escala horizontal é por RÉPLICAS do container
# (api/api2/api3/api4 no docker-compose) atrás do nginx com hash por IP real
# (`hash $ip_real consistent;`) + `DADINHO_MESSAGE_QUEUE` p/ emits entre
# instâncias.
EXPOSE 8000
CMD ["gunicorn", "--worker-class", "gevent", "-w", "1", \
     "--bind", "0.0.0.0:8000", "app:app"]