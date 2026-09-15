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

# Gunicorn em modo threaded (async_mode='threading' + simple-websocket dá
# suporte a WebSocket — ver docs/fluxo e docs/plano-cross-instance.md).
# -w 1: o algoritmo de load balancing do gunicorn não faz sticky session, então
# múltiplos workers num único processo não funcionam com Socket.IO. Escala-se
# com múltiplas instâncias/containers atrás de um LB (nginx) + DADINHO_MESSAGE_QUEUE.
EXPOSE 8000
CMD ["gunicorn", "--worker-class", "gthread", "--threads", "100", \
     "--bind", "0.0.0.0:8000", "app:app"]