# Plano: tempo real entre instâncias (lock distribuído + message queue)

Limitação conhecida do serverless (ver `arquitetura.md:101-107`): rooms/emits do Socket.IO
vivem em memória **por instância**. Dois jogadores em instâncias diferentes não se veem em
tempo real; o estado persiste no Upstash e é reidratado no reconnect. A sala de espera já é
coberta pelo re-sync do heartbeat; o **gap real fica na partida** (apostas/turnos/confirmação
em tempo real entre instâncias).

Este plano resolve o gap em **duas fases encadeadas** — uma de consistência (pré-requisito)
e uma de transporte — mais uma fase opcional de otimização após medição em produção.

## Visão geral

| Fase | Objetivo | Entrega | Risco que cobre |
|---|---|---|---|
| **24** | Exclusão mútua do Lobby **entre** instâncias no read-modify-write | Lock distribuído por sala via Upstash REST | Lost-update do estado de jogo (aumenta com a Fase 25) |
| **25** | Emits alcançam qualquer instância | `socketio.RedisManager` (pub/sub) via rediss:// + wrapper thread-safe | Gap de tempo real na partida |
| **26** (opcional) | Cortar custo de comandos após métricas | `ignore_queue`, detector CAS, tuning de TTL | Verba/free tier da Upstash |

Regra de bolso: **F24 sozinho é uma melhoria standalone e reversível**; F25 **só entra sobre
F24**, porque ela aumenta a concorrência real entre handlers de instâncias diferentes e o lock
da Fase 7 (`store.trancar_sala`) é por processo. Ambas são opt-in por env e caem no
comportamento atual sem configuração.

---

## Fase 24 — Lock distribuído por sala

### Objetivo

Serializar o read-modify-write do `Lobby` entre **instâncias** (a Fase 7 só cobre o processo
quente). Com o lock, mutações concorrentes de instâncias diferentes não se sobrescrevem.

### Primitivas (confirmadas na Upstash via REST, sem dependência nova)

- **Adquirir:** `SET dadinho:lock:<sala_id> <token> NX EX <ttl>` → resposta `{"result": "OK"}`
  (adquiriu) ou `{"result": null}` (ocupado). Atomicidade garantida pelo próprio comando.
- **Liberar com segurança:** `DELEX dadinho:lock:<sala_id> IFEQ <token>` — apaga **só** se o
  valor ainda for o seu token (nunca derruba a trava de outra instância se a sua expirou e foi
  re-adquirida). É o mesmo papel do script Lua compare-and-del, num comando.
- **Fallback de liberação** (se o REST da Upstash não expuser `DELEX` num ambiente futuro):
  `EVAL "<if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) else return 0 end>" 1 <chave> <token>` (Scripting é suportado).

### Decisões de design

- **Chave:** prefixo `dadinho:lock:` (não colide com `dadinho:sala:`/`dadinho:sid:`).
- **Token:** único por aquisição (`secrets.token_hex(8)`), guardado no contexto do `with`.
- **TTL (lease):** 120s. Handlers são de segundos; o único caso longo é `ia.processar` com só
  IAs. Se o lease estourar no meio, degrada ao comportamento atual (o `salvar_sala` só acontece
  no fim da mutação) — perda de exclusão pontual e documentada. **Sem renovação por thread**
  (serverless-unsafe).
- **Aquisição com backoff:** ~10 tentativas, espera `min(0.05 * 2**tentativa, 0.2)s` (<1s total).
  Se não adquirir, lança `store.TravaIndisponivel` → o wrapper de `evento_mutavel` aborta
  silencioso (mesma política de `app.py:288-297`); o heartbeat re-sincroniza o cliente depois.
- **No-op em memória:** `if not isinstance(armazenamento, ArmazenamentoUpstash): yield; return`.
  Dev local (`DADINHO_STORE=memoria`) e os testes de `verificar.py` não mudam e não pagam nada.
- **Ordem de aninhamento:** local (`trancar_sala`) **por fora**, distribuído por dentro; o `with`
  libera no LIFO. Sem inversão em lugar nenhum → sem deadlock entre instâncias.

### Mudanças por arquivo

**`store.py`**
1. Constantes: `PREFIXO_TRAVA = "dadinho:lock:"`, `TRAVA_TTL = 120`,
   `TRAVA_TENTATIVAS = 10`, `TRAVA_ESPERA_BASE = 0.05`.
2. `class TravaIndisponivel(Exception)` — exceção de aquisição (contenda ou falha de rede).
3. Context manager `trancar_sala_distribuida(sala_id)`:
   - memória → `yield` puro;
   - Upstash → loop `armazenamento._comando("SET", chave, token, "NX", "EX", TRAVA_TTL)`;
     adquiriu → `yield`; não adquiriu → `raise TravaIndisponivel`;
     `finally` → `armazenamento._comando("DELEX", chave, "IFEQ", token)` se adquiriu.

**`app.py`**
1. `evento_mutavel` (`app.py:286`): aninhar `with trancar_sala_distribuida(sala_id):` dentro do
   `with trancar_sala(sala_id):` e adicionar `store.TravaIndisponivel` ao tuplo do `except`
   (linhas 288-292). Bônus: `autenticar`/`achar_jogador`/`_gc_sala` passam a rodar **sob** o lock.
2. `handle_connect` (`app.py:405`): aninhar o mesmo. O connect não tem try/except — envolver o
   `with` num `try/except TravaIndisponivel: return` (o cliente reconecta com backoff e o
   heartbeat re-sincroniza).
3. `handle_disconnect` (`app.py:551`): idem aninhamento + `except TravaIndisponivel: return`
   (degradado: a limpeza espera a próxima batida/GC — mesmo de hoje em dia com blip de rede).

**`verificar.py`**
1. Os fakes de `_comando`/`_pipeline` (`verificar.py:1438-1464`) devolvem `{"result": None}` por
   default — com o lock, todo handler mutável abortaria em silêncio e a integração quebraria.
   Implementar no fake: `SET` com `NX/EX` guarda o token e responde `"OK"`; `DELEX IFEQ` compara
   e remove. Único passo obrigatório de teste junto com esta fase.
2. Novo teste unitário do lock com dois "clientes REST" fake (instâncias): exclusão mútua
   (segundo não adquire enquanto o primeiro segura), release com token errado não apaga
   (`DELEX IFEQ` no-op), TTL expira sozinho, falha de aquisição levanta `TravaIndisponivel`.

### Custo

+2 comandos Upstash por evento mutável (`SET NX` + `DELEX`), ~100–200ms de latência extra por
ação. Heartbeat (leitura) intocado. Free tier 500K comandos/mês → folga para um jogo casual.

### Critérios de aceite

- `python verificar.py` 100% verde com os fakes atualizados + novo teste do lock.
- Dev local (`memoria`): zero mudança de comportamento (lock no-op, testes de integração intactos).
- Produção com Upstash real: duas instâncias não perdem apostas/estado em ações simultâneas
  (validar com logs e estado final, ou dois navegadores em regiões distintas).

---

## Fase 25 — Message queue (emits entre instâncias)

### Objetivo

`emit(..., to=sala_room())` e `emit(..., to=jogador.client_id)` passam a alcançar clientes de
**qualquer** instância — o gap em tempo real da partida some.

### Como funciona (confirmado na fonte instalada: `.venv/Lib/site-packages/socketio/`)

- `socketio.RedisManager(PubSubManager)`, e `PubSubManager(Manager)` — **a hierarquia do
  `Manager` atual é preservada**, então as correções de corrida do `GerenciadorThreadSeguro`
  continuam aplicáveis por herança (ver `redis_manager.py:47`, `pubsub_manager.py:9`).
- `PubSubManager.emit` (`pubsub_manager.py:54-93`) entrega local **e** publica no canal. A thread
  de listener de cada instância recebe e re-emite para os **sids locais** da room
  (`_handle_emit` → `Manager.emit`). Ou seja: a fila broadcasta a mensagem com o nome da room e
  cada instância filtra os próprios membros. **Nenhum `emit` do jogo precisa mudar.**
- Rooms continuam locais por instância (`enter_room`/`leave_room` só publicam para sid remoto,
  que nenhuma outra instância tem) — nada de estado de sala na fila.
- `async_mode='threading'`: `RedisManager.initialize()` (`redis_manager.py:97-110`) só exige
  monkey-patch para eventlet/gevent; em `threading` não levanta. Listener roda em
  `threading.Thread` — OK na Vercel.

### Decisões de design

- **Opt-in por env:** `DADINHO_MESSAGE_QUEUE` (URL completa `rediss://...`). Sem ela, mantém o
  `GerenciadorThreadSeguro` atual. Canal: `channel="dadinho"` (isola de outros apps no mesmo Redis).
- **Dependência nova:** pacote `redis` (redis-py) — sem ele `RedisManager` levanta
  `RuntimeError` ao conectar (`redis_manager.py:112-120`). Adicionar ao `requirements.txt`
  (pinado: `pip install redis` e pinar a versão resolvida).
- **REST não basta:** pub/sub exige TCP/TLS. A env é `rediss://:<TOKEN>@<endpoint>:<porta>/0`
  (Endpoints/credenciais "REDIS_URL" do console Upstash — nomenclatura; a REST
  `UPSTASH_REDIS_REST_URL/TOKEN` continua sendo o que o `store.py` usa). `redis_options` com
  `ssl_cert_reqs="required"` (Upstash exige TLS e não desliga).
- **Wrapper thread-safe:** `GerenciadorRedisSeguro(socketio.RedisManager)` replicando o mesmo
  RLock das 5 correções (`connect`, `basic_enter_room`, `basic_leave_room`, `basic_disconnect`,
  `basic_close_room`) — o fix do `app.py:34-69` passa a valer sobre o manager pub/sub.
- **Cliente:** sem mudança — websocket continua obrigatório (`script.js:37`); a sessão
  Engine.IO é por instância e a fila não migra conexão. O heartbeat/resync permanece para o
  `max-duration` da Vercel (Hobby 300s).

### Mudanças por arquivo

**`requirements.txt`** — nova linha pinada: `redis==<versão resolvida pelo pip>`.

**`app.py`**
1. `import socketio as pacote_socketio` no topo (já é dependência transitiva do Flask-SocketIO).
2. Nova classe `GerenciadorRedisSeguro(pacote_socketio.RedisManager)` com as 5 sobrecargas com
   `self._trava_registro = threading.RLock()`.
3. Wiring em `app.py:82-93`:
   ```python
   url_mq = os.environ.get("DADINHO_MESSAGE_QUEUE", "").strip()
   if url_mq:
       redis_options = {"ssl_cert_reqs": "required"} if url_mq.startswith("rediss://") else {}
       gerenciador = GerenciadorRedisSeguro(url_mq, channel="dadinho",
                                            redis_options=redis_options)
   else:
       gerenciador = GerenciadorThreadSeguro()
   socketio = SocketIO(app, async_mode=async_mode, client_manager=gerenciador, ...)
   ```

### Custo e riscos

- +1 conexão TCP/TLS persistente por instância quente (pub/sub). Limite de conexões
  concorrentes do plano existe (`ERR max concurrent connections exceeded`). Com Vercel Hobby
  (poucas instâncias) cabe; **monitorar no dashboard Upstash.**
- Cada `emit` = 1 PUBLISH contabilizado no comando mensal (via TCP). Custo dobro no fluxo de
  jogo em relação a hoje — irrelevante em escala casual, mas medir.
- Cold start: primeira emissão reconecta; `_redis_listen_with_retries` re-subscribe com backoff
  (1..60s).
- **Ordem de mensagens cross-instance não é globalmente serializada** — é exatamente por isso
  que F24 precede: quem muta é sempre um handler sob o lock; emit nunca é fonte de estado.

### Critérios de aceite

- Sem `DADINHO_MESSAGE_QUEUE`: comportamento 100% atual (`verificar.py` verde, regressão zero).
- Com a env: dois navegadores (idealmente em instâncias diferentes) veem rolagem/aposta/
  conferência ao vivo, sem depender do heartbeat para re-sync de turno.
- `ia.processar` segue avançando sem timer e os bots headless (`simular_ia.py`) intocados.

---

## Fase 26 (opcional) — Otimização pós-métricas

Fazer **somente depois** de alguns dias em produção e leitura do dashboard (comandos, conexões,
banda). Ideias, em ordem de retorno:

1. `ignore_queue=True` em emits de destinatário único (`to=<sid>`) — hoje até um emit
   individual publica na fila (`pubsub_manager.py:65`). Auditoria prévia: mapear quais `emit`
   da cadeia são `to=sid`.
2. Detector CAS/version-token como **alerta** (não substitui o lock): campo `versao` no Lobby +
   checagem no `salvar_sala` registra divergência — visibilidade para calibrar o TTL do lock.
3. Fundir demanda de comandos: aproveitar `_pipeline`/lotes onde o lock e o `salvar_resumo`
   disputarem a mesma janela (ganho pequeno; só se o número apertar).

Não consolidar/remover o heartbeat: o socket continua morrendo no `max-duration`, o re-sync
continua necessário.

---

## Operação e deploy

- Seguir `docs/verificacao.md` (o `python verificar.py` verde é pré-requisito de cada fase).
- **Ordem:** F24 primeiro; validar em produção; F25 depois. Cada fase é um deploy separado e
  reversível (rollback = remover a env `DADINHO_MESSAGE_QUEUE` ou voltar o commit).
- Env novas na Vercel: F24 usa apenas o Upstash já configurado (sem env nova); F25 adiciona
  `DADINHO_MESSAGE_QUEUE` (URL TCP/TLS) — nunca logar o token (segredos via env, como
  `DADINHO_SECRET_KEY`).
- Monitorar no painel Upstash após F25: contagem de comandos, conexões concorrentes e banda.