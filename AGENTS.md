# AGENTS.md

"Dadinho" — jogo de blefe de dados multiplayer em tempo real no navegador. Backend Flask-SocketIO em Python, uma página HTML + um JS frontend.

**Leia antes de mudar comportamento de jogo:** a spec está em `Dadinho idéia.txt` (telas, regras, fluxo; reference `@regras`).
**Referência de arquitetura, fluxo/eventos e operação:** `docs/arquitetura.md`, `docs/fluxo.md`, `docs/verificacao.md` (reference `@docs`). Habilidades (`evento-dadinho`, `i18n-dadinho`, `verificar-deploy`) e revisores (`revisor-dadinho`, `rastrear-evento`) estão em `.opencode/`.

## Constraints para código novo

- **Alvo: Vercel (serverless).** Sem pressupostos de servidor único, sem estado em memória entre requests — o estado de jogo vive no store distribuído (`store.py`). Sem threads/timers no servidor (`ia.processar` roda dentro do request).
- **Múltiplas salas existem:** sala = `?sala=<id>`; cada sala é uma room `sala_<id>` com seu próprio `Lobby`. Nunca hard-code um lobby único.
- **Casual only:** sem contas, ranking ou leaderboard. Identidade = `request.sid`; estado reseta por partida.

## Commands

- Rodar o servidor: `python app.py` (com o `.venv`, da raiz do repo). Sobe em http://localhost:5000. Dev local — produção é a Vercel.
- Verificação: `python verificar.py` (Fase 10; `.venv`, da raiz) — `py_compile`, `node --check` de `static/*.js`, cobertura i18n, boot `VERCEL=1` 200, serialização/migração, integração `flask_socketio.test_client` (Fases 6/7 + `retomar_identidade` + `heartbeat-espera-fresco`). Bots headless: `python simular_ia.py --partidas 20 --dados 3`. Complementar sempre com o teste manual em dois browser tabs.
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

- **Serverless/cross-instance:** rooms/emits vivem por instância — salas de espera dependem do re-sync do heartbeat (espera SEMPRE fresco do store; partida via `carregar_sala_leve`). Não introduzir estado X no caminho que precise de broadcast entre instâncias sem tratar o re-sync.
- **Config (`opencode.json`)** e skills/agents não são recarregados a quente — depois de editar `.opencode/`/`opencode.json`, reiniciar o opencode.
- Novos textos/keys: ver skill `i18n-dadinho`; novos eventos: skill `evento-dadinho`; verificação/deploy: skill `verificar-deploy`.