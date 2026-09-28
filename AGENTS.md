# AGENTS.md

"Dadinho" — jogo de blefe de dados multiplayer em tempo real no navegador. Backend Flask-SocketIO em Python, uma página HTML + um JS frontend.

**Leia antes de mudar comportamento de jogo:** a spec está em `Dadinho idéia.txt` (telas, regras, fluxo; reference `@regras`).
**Referência de arquitetura, fluxo/eventos e operação:** `docs/arquitetura.md`, `docs/fluxo.md`, `docs/verificacao.md` (verificação e deploy), `docs/runbook.md` (operação e incidente) e `docs/adr/` (decisões de arquitetura) (reference `@docs`). Planos de melhoria: `docs/plano-cross-instance.md` (Fases 24–26: lock distribuído + message queue entre instâncias). Habilidades (`evento-dadinho`, `i18n-dadinho`, `verificar-deploy`, `vps-ops-dadinho`, `multi-instancia-dadinho`) e revisores (`revisor-dadinho`, `rastrear-evento`) estão em `.opencode/`.

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
8. `Jogador.ia_estilo` (Fase 76) é **estado de jogo persistido** (vira 10 no store, migra com a sala) — não vire config de sala nem campo volátil: sem ele no store, outra instância reconstrói a sala e o prudente volta a ser o bot genérico do nível. Pelo mesmo motivo, mudar o **apelido guardado** no meio da partida (o `🤖` do substituto) exige `reconstruir_tela_sala(lobby)`: o apelido é a chave dos `id`s dos cards no cliente, e o `atualizar_turno` do turno seguinte não acha a linha de dados de um card com id velho.

## Pontos de atenção recorrentes

- **Serverless/cross-instance:** rooms/emits vivem por instância — salas de espera dependem do re-sync do heartbeat (espera SEMPRE fresco do store; partida via `carregar_sala_leve`). Não introduzir estado X no caminho que precise de broadcast entre instâncias sem tratar o re-sync. Fase 25: `DADINHO_MESSAGE_QUEUE` (URL `rediss://` Upstash) liga o `GerenciadorRedisSeguro` (pub/sub ~ emits entre instâncias); sem a env, manager local. Config (`opencode.json`) e skills/agents não são recarregados a quente — depois de editar `.opencode/`/`opencode.json`, reiniciar o opencode.
- **Partida só de IAs assistida (Fase 69):** quando não resta humano com dados e há espectador, `ia.processar` libera UM lance por chamada no ritmo do relógio persistido (`Rodada/Partida.proximo_lance_em`); o ritmo é pago pelo poll `espectador_leitura` (resposta `espectador_ritmo`) e o heartbeat é a rede de segurança. Sem espectador, o laço legado simula até acabar. **Não** trocar por sleep/timer nem por replay no cliente (ver ADR-009).
- **Camadas de rate limit (Fase 39):** cada uma guarda uma dimensão diferente — **não remover uma achando redundante**:
  1. **Firewall da Vercel** (plataforma, antes da função): regra `rate-limit-socketio` — 120 req/60s por IP no caminho `/socket.io/`, deny ao exceder. Cobre spam de conexões/upgrade e brute-force de códigos de sala (cada tentativa de `connect` é um request no caminho). Criada/publicada via `vercel firewall rules`/`publish` (draft → produção).
  2. **Cooldown por `sid`** (`funcoes_gerais.tem_cooldown`): anti-spam de handlers por socket na instância quente (V2) — protege o orçamento de comandos da Upstash. É por `sid`, não por IP; quem abre socket novo burla isto (por isso a camada 1 existe).
  3. **Lock distribuído por sala** (`store.trancar_sala_distribuida`, Fase 24): consistência do read-modify-write entre instâncias — não é rate limit.
- **Música é sequenciador, não render (Fase 70):** o cliente nunca usa `OfflineAudioContext` — o MIDI é parseado e as notas agendadas nota a nota no `AudioContext` vivo (`bombear_musica`, horizonte 0,6s, `setInterval` 120ms). Renderizar o tema inteiro (~50s, ~900 notas) custava ~30s de CPU e a música só ligava dezenas de segundos depois do clique. Ao mexer no motor: `parsear_midi` precisa devolver as notas **ordenadas por `inicio`** (o sequenciador anda com um índice só), toda voz criada precisa estar em `nos` para o `agendar_voz` desconectar no `onended` (o `lfo_ganho` é o esquecido clássico), o loop é reancoragem de ciclo com fade e o horizonte é **sempre finito** (aba oculta usa 15s — horizonte até o fim do ciclo faz a bomba ancorar ciclos sem parar). `verificar.py` falha se o `OfflineAudioContext` voltar.
- **Bot prudente (Fase 76):** `ia.eh_prudente` (exige `is_ia` **e** `ia_estilo == ESTILO_PRUDENTE`) desvia `decidir` para `_decidir_prudente` **antes** de personalidade/nível — daí a personalidade (`ia_risco`/`ia_agressividade`) ser inerte e o `ia_nivel` mandar só em tempo de pensamento/leitura, nunca na aposta. Três regras não negociáveis: **(1)** desconfiar só com `P < _limiar_prudente` (0,32 → 0,45 por lance; sem ruído/impulso), **(2)** aposta coberta (quantidade ≤ suporte do próprio dado, coringa contado) de menor exposição, **(3)** sem coberta, a mínima legal (abertura: 1 dado na face de maior suporte) — não existe "passar a vez", então a mínima é o mais perto disso. O limiar crescente é o que impede a mesa de arrastar quando sobra só prudente (ADR-010, `verificar.py` 4d + `simular_ia --estilo prudente`). Não criar evento/UI/i18n para o estilo: é invisível para o cliente.
- Novos textos/keys: ver skill `i18n-dadinho`; novos eventos: skill `evento-dadinho`; verificação/deploy: skill `verificar-deploy`.
- **Frontend sem build step (Fase 45/M6):** `static/script.js` (~154 KB) é um arquivo único clássico (functions globais + `socket.on`), carregado após `i18n.js`. **Decisão: não adotar bundler (esbuild)** — o projeto não tem tooling JS e o deploy é Python puro; o ganho não paga o custo de pipeline. Não splitar em múltiplas `<script>` tags sem bundler (quebraria hoisting entre arquivos).