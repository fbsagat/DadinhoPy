# ADR-006 — Múltiplos workers cooperativos: gevent + 4 réplicas + sticky por IP

- **Status:** Aceito (revisado por ADR-008)
- **Contexto:** Fase 61 do `todo.md` (substitui o `gthread -w 1` de 100 threads da Fase 46)
- **Decisores:** mantenedor

## Contexto

A configuração anterior da VPS era um único processo `gunicorn --worker-class
gthread -w 1` com 100 threads. As threads nativas disputam o GIL e não escalam
além de um certo ponto — com o tempo real (Socket.IO) e o processamento da IA, o
teto é o de um núcleo. A VPS (Oracle Ampere A1) tem vários núcleos disponíveis.

Restrições que limitam as opções:
- a session Engine.IO (handshake + polling + upgrade do WebSocket) vive na
  **memória da réplica**; requests do mesmo cliente precisam cair sempre na mesma
  réplica;
- `gunicorn -w N` **não** garante sticky session por conta própria; um único
  container com `-w 4` quebraria o polling/upgrade;
- o Redis local é um único ponto (ver ADR-007);
- o motor de IA roda dentro do handler (ADR-001/005), então preempção importa.

## Decisão

**4 containers × 1 worker gevent** por container, atrás do nginx com **sticky por
IP real**.

- **Motor: gevent** (não eventlet). O eventlet 0.41 encaminha para aposentadoria
  (aviso oficial do projeto); gevent é mantido e igualmente suportado por
  Flask-SocketIO/gunicorn/python-socketio. O `Dockerfile` roda
  `gunicorn --worker-class gevent -w 1 --bind 0.0.0.0:8000 app:app`.
- **Monkey-patch** no topo do `app.py`, condicionado a `DADINHO_ASYNC_MODE`
  (default `threading` p/ Vercel): `gevent.monkey.patch_all()` idempotente
  (`is_module_patched`) — o worker gevent do gunicorn já patcheia antes de
  importar o app; o guard cobre o dev local (`python app.py`).
- **4 réplicas** (`api`, `api2`, `api3`, `api4`) via anchor YAML `x-api-base`,
  todas usando a **mesma image** `dadinho-api` (build só no `api`), com
  `DADINHO_ASYNC_MODE=gevent`, healthcheck por réplica e portas loopback
  8000–8003 para smoke. O nginx espera as 4 saudáveis.
- **Sticky:** `upstream dadinho_api { hash $ip_real consistent; ... }` — por IP
  **real** (o `sid` muda a cada reconexão; o IP não). `keepalive 32` no upstream
  (com `Connection ""` fora de upgrade, para não matar o keepalive).
- Emits entre réplicas ficam por conta da **message queue** (ADR-002).

**Rejeitadas:**
- `gunicorn -w 4` num só container — sem sticky, quebra a session Engine.IO.
- sticky por `$arg_sid` — muda a cada reconexão e requests sem `sid` agrupariam
  tudo num membro; o IP real é estável.

## Consequências

- Positivas: 4× paralelismo real (4 núcleos) sem quebrar o Socket.IO; uma réplica
  cai e as outras seguem; o tunnel/rede não precisa saber de nada (nginx resolve).
- Positivas: serverless-safe — o modo VPS é só outro deploy do mesmo app
  (`DADINHO_ASYNC_MODE` decide threading×gevent).
- Negativas/trade-off: `ia.processar` é CPU-bound em Python puro e, sob gevent,
  **não preempta** outros greenlets da mesma réplica enquanto calcula (o mesmo GIL
  limitaria threads nativas). As 4 réplicas distribuem e o LRU (ADR-005) barateou
  cada cálculo — aceitável no casual.
- Negativas: +4 processos/containers para observar (ver `docs/runbook.md`);
  deploy precisa subir as 4 réplicas de uma vez.
- Proíbe: rodar gevent sem `DADINHO_ASYNC_MODE=gevent` (o app cairia em threading
  sob gevent); usar `-w > 1` por container sem resolver sticky; mudar o upstream
  para round-robin puro.