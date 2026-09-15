# AGENTS.md

"Dadinho" — jogo de blefe de dados multiplayer em tempo real no navegador. Backend Flask-SocketIO em Python, uma página HTML + um JS frontend.

**Leia antes de mudar comportamento de jogo:** a spec está em `Dadinho idéia.txt` (telas, regras, fluxo; reference `@regras`).
**Referência de arquitetura, fluxo/eventos e operação:** `docs/arquitetura.md`, `docs/fluxo.md`, `docs/verificacao.md` (reference `@docs`). Planos de melhoria: `docs/plano-cross-instance.md` (Fases 24–26: lock distribuído + message queue entre instâncias). Habilidades (`evento-dadinho`, `i18n-dadinho`, `verificar-deploy`) e revisores (`revisor-dadinho`, `rastrear-evento`) estão em `.opencode/`.

## Constraints para código novo

- **Alvo: Vercel (serverless).** Sem pressupostos de servidor único, sem estado em memória entre requests — o estado de jogo vive no store distribuído (`store.py`). Sem threads/timers no servidor (`ia.processar` roda dentro do request).
- **Modo VPS (Fase 46):** a API também pode rodar como processo persistente na VPS (Docker + gunicorn, `Dockerfile`/`docker-compose.yml` na raiz) com o frontend na Vercel. Estado via `DADINHO_REDIS_URL` (`store.ArmazenamentoRedis`, Redis TCP local) e message queue no mesmo Redis. Exposição pública via Cloudflare Tunnel (`dadinho-tunnel`, ingress local em `cloudflared/config.yml`) — a porta da API fica em loopback. O código continua serverless-safe — o modo VPS é um deploy alternativo, não um caminho paralelo.
- **Múltiplas salas existem:** sala = `?sala=<id>`; cada sala é uma room `sala_<id>` com seu próprio `Lobby`. Nunca hard-code um lobby único.
- **Casual only:** sem contas, ranking ou leaderboard. Identidade = `request.sid`; estado reseta por partida.

## Commands

- Rodar o servidor: `python app.py` (com o `.venv`, da raiz do repo). Sobe em http://localhost:5000. Dev local — produção é a Vercel (ou a VPS: em `/opt/dadinho`, `docker compose up -d`). Não há auto-deploy do Dadinho na VPS: após novo push, rodar `.\atualizar_vps.ps1 -Chave <caminho>` (copia com tar preservando `.env`/`cloudflared/config.yml`, rebuilda a api, recrea o tunnel só se `docker-compose.yml` mudou e faz smoke test) — procedimento detalhado em `docs/verificacao.md`.
- Verificação: `python verificar.py` (Fase 10; `.venv`, da raiz) — `py_compile`, `node --check` de `static/*.js`, cobertura i18n, boot `VERCEL=1` 200, serialização/migração, integração `flask_socketio.test_client` (Fases 6/7 + `retomar_identidade` + `heartbeat-espera-fresco` + `store Redis TCP`/`lock Redis`, Fase 46). Bots headless: `python simular_ia.py --partidas 20 --dados 3`. Complementar sempre com o teste manual em dois browser tabs.
- **CI (Fase 37):** `.github/workflows/ci.yml` roda os mesmos comandos (setup Python 3.12 + `pip install -r requirements.txt`; `verificar.py`; `node --check` dos estáticos; `simular_ia.py --partidas 20 --dados 3`) em todo push/PR para `master` — é a segunda linha de verificação além do teste manual em 2 abas. Todo PR deve estar com o CI verde antes do merge.
- Deploy: seguir `docs/verificacao.md`.

## Conventions

- Comentários, docstrings, nomes de variáveis/eventos Socket.IO e mensagens de commit em **pt-BR** (`app.py:20-23` é o estilo).
- `requirements.txt` é totalmente pinado — adicione deps pinadas igual.
- `app.secret_key` vem de `DADINHO_SECRET_KEY`; tokens Upstash via env vars — não comitar segredos.

## Invariantes (toda mudança que toca o jogo)

1. Eventos escopados à sala: `emit(..., to=sala_room())` ou `to=jogador.client_id` — **nunca** `broadcast=True` global.
2. Todo handler que **muta** estado de sala termina com `salvar_sala(lobby)`, passa pelo lock (`trancar_sala`) e roda `ia.processar(lobby)` quando a mutação avança o jogo.
3. Todo handler novo mutável exige a `chave_secreta` do jogador (`autenticar`); ordene os decorators com `@socketio.on` **por fora** de `evento_mutavel`/`autenticar`. Confirmações idempotentes/commit-reveal usam `cooldown=None`.
4. Payload malformado nunca estoura: guards `dict` + aborto silencioso.
5. O servidor **nunca escolhe idioma**: emite chaves + parâmetros (`txtchave`/`txtparams`, `segmentos`, `motivo` {chave, params}) — o cliente resolve via `t()`/i18n.
6. Ao tocar num `emit` do servidor, achar primeiro o `socket.on` correspondente em `static/script.js` (mapa completo em `docs/fluxo.md`).
7. Motor de IA puro (só dados próprios + informação pública, nunca `rodada.todos_os_dados`); bots nunca viram master.

## Pontos de atenção recorrentes

- **Serverless/cross-instance:** rooms/emits vivem por instância — salas de espera dependem do re-sync do heartbeat (espera SEMPRE fresco do store; partida via `carregar_sala_leve`). Não introduzir estado X no caminho que precise de broadcast entre instâncias sem tratar o re-sync. Fase 25: `DADINHO_MESSAGE_QUEUE` (URL `rediss://` Upstash) liga o `GerenciadorRedisSeguro` (pub/sub ~ emits entre instâncias); sem a env, manager local. Config (`opencode.json`) e skills/agents não são recarregados a quente — depois de editar `.opencode/`/`opencode.json`, reiniciar o opencode.
- **Camadas de rate limit (Fase 39):** cada uma guarda uma dimensão diferente — **não remover uma achando redundante**:
  1. **Firewall da Vercel** (plataforma, antes da função): regra `rate-limit-socketio` — 120 req/60s por IP no caminho `/socket.io/`, deny ao exceder. Cobre spam de conexões/upgrade e brute-force de códigos de sala (cada tentativa de `connect` é um request no caminho). Criada/publicada via `vercel firewall rules`/`publish` (draft → produção).
  2. **Cooldown por `sid`** (`funcoes_gerais.tem_cooldown`): anti-spam de handlers por socket na instância quente (V2) — protege o orçamento de comandos da Upstash. É por `sid`, não por IP; quem abre socket novo burla isto (por isso a camada 1 existe).
  3. **Lock distribuído por sala** (`store.trancar_sala_distribuida`, Fase 24): consistência do read-modify-write entre instâncias — não é rate limit.
- Novos textos/keys: ver skill `i18n-dadinho`; novos eventos: skill `evento-dadinho`; verificação/deploy: skill `verificar-deploy`.
- **Frontend sem build step (Fase 45/M6):** `static/script.js` (~154 KB) é um arquivo único clássico (functions globais + `socket.on`), carregado após `i18n.js`. **Decisão: não adotar bundler (esbuild)** — o projeto não tem tooling JS e o deploy é Python puro; o ganho não paga o custo de pipeline. Não splitar em múltiplas `<script>` tags sem bundler (quebraria hoisting entre arquivos).