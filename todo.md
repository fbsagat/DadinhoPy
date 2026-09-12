# TODO — Dadinho

<!-- Fase 2 concluída; Fase 3 em andamento. -->

Plano em fases para o objetivo atual: **subir o jogo na Vercel, com múltiplas salas, casual only** (sem contas, sem ranking, sem VPS).

Legenda: `[ ]` pendente · `[x]` concluído · `[~]` em andamento.

---

## Fase 0 — Base estável (limpar e corrigir o que existe)

Objetivo: partir de um código sem bugs conhecidos e sem lixo, antes de estruturar salas.

- [x] Adicionar `.gitignore` (`.venv/`, `__pycache__/`, `.idea/`) e remover `.idea/` do controle de versão (hoje versionado com mudanças locais).
- [x] Corrigir: first player (master) não consegue definir apelido — `script.js` desligava o input sem nunca reativar; o master entrava na partida como `null` nos cards e sumia da lista do lobby. Agora o apelido fica habilitado para todos no lobby.
- [x] Corrigir: `escolherImagemAleatoria` quebrava no load (`script.js:840-857`) — acessava `dado1..3` num DOM que só é construído dinamicamente; TypeError no console a cada página. Função e `window.onload` removidos.
- [x] Corrigir: som ausente — `script.js:325` referenciava `static/sounds/dice-roll.mp3`, pasta/arquivo inexistentes (`.play()` virava promise rejeitada). Som agora é sintetizado no navegador via Web Audio (`tocar_som_dados`), sem depender de arquivo externo.
- [x] Corrigir: `KeyError` nos handlers que indexavam `jogadores_online[client_id]` sem guarda — jogador pode desconectar entre o emit e o processamento. Coberto pela unificação abaixo (busca retorna `None` e os handlers abortam com segurança).
- [x] Remover código morto/duplicado:
  - seleção de dado duplicada em `script.js` (a 2ª usava `.img-button`, seletor inexistente; unificada em um único handler);
  - blocos grandes comentados em `jogo.html` (telas de dados/espectador, cards de exemplo, conferência) e `script.js` (controle de tecla "K");
  - regra dupla `body {}` em `custom_styles.css` (mesclada em uma única);
  - `static/imagens/dado/0.png` (código usa 1–6) — removido do projeto.
- [x] Unificar estado do jogador: removido o índice paralelo `jogadores_online`; tudo é acessado via `lobby_unico` (uma única fonte de verdade).

Extras corrigidos no caminho (não listados originalmente):
- `conferiram_vencedor` nunca era zerado (travava a tela de vitória nas partidas seguintes) — `Lobby.resetar_para_lobby()` zera o contador e o estado dos jogadores ao voltar ao lobby.
- `joguei_dados` nunca era reiniciado nas rodadas seguintes (pulava a rolagem da rodada 2+) — resetado a cada `construir_rodada`.
- `verificar_partida_anterior` podia dar `AttributeError` com `perdedor`/`vencedor` ausentes — agora com guardas.
- `int(dados['dados_qtd'])` sem proteção (`ValueError` em payload malformado) — `try/except` com fallback 1.
- `app.py` usava import wildcard e `random` vazado de `modelos` — imports explícitos.

## Fase 1 — Múltiplas salas (single instance, multi-publico)

Objetivo: existem N salas simultâneas no mesmo processo; prepara o split por sala que a Vercel exigirá.

- [x] Adicionar conceito de **sala** no modelo: identificar sala por URL/parâmetro (ex.: `/?sala=<id>` ou `/<sala>`), criar e juntar.
- [x] Usar Socket.IO rooms de verdade: `join_room`/`leave_room` no connect/disconnect; trocar `emit(..., broadcast=True)` do namespace global por `emit(..., to=sala)` em toda a cadeia (`funcoes_gerais.py`, `modelos.py`, `app.py`).
- [x] `lobby_unico` vira um registro múltiplo (ex.: dict sala → `Lobby`), removendo o singleton global.
- [x] Frontend: tela de criar/entrar sala (estender tela 0 ou nova tela), sem contas (apelido por sessão continua valendo).
- [x] Isolar estados por sala: `conferiram`/`conferiram_vencedor`/`master`/listas de jogadores não podem vazar entre salas.

Extras corrigidos no caminho (não listados originalmente):
- GC de sala vazia: ao desconectar o último jogador de uma sala, o `Lobby` é removido do registro `salas` (evita acúmulo de salas sem ninguém no processo).
- Sala com `?sala=` inválido/vazio cai na sala padrão `padrao` (`normalizar_sala` valida `[a-z0-9\-_]{1,24}`, minúsculas).
- Apelido persistido em `sessionStorage`: trocar de sala (recarregar página com novo `?sala=`) não força digitar o nome de novo.

## Fase 2 — Pronto para Vercel (serverless/stateless) ✅ concluída

Objetivo: código não depende mais de estado em memória de um único processo.

- [x] Abstrair o armazenamento de estado atrás de uma interface e implementar com serviço persistente: `store.py` expõe `carregar_sala`/`salvar_sala`/`remover_sala`/`listar_lobbys` com duas implementações — `ArmazenamentoMemoria` (dev) e `ArmazenamentoUpstash` (Redis REST/Upstash, via `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`). `DADINHO_STORE=memoria` força o modo local.
- [x] Refatorar modelo para o estado viver no store distribuído: `Lobby`/`Partida`/`Rodada`/`Turno`/`Jogador` agora serializam a árvore inteira (`Lobby.para_dict`/`Lobby.de_dict`, refs religadas por `client_id` + índices) e os handlers de `app.py` persistem a sala ao fim de cada evento mutável.
- [x] Transporte: config ajustável por ambiente — `DADINHO_ASYNC_MODE` (default `threading`) e `DADINHO_PERMITIR_WEBSOCKET` (default: `false` quando `VERCEL=1`, `true` em dev), com `ping_interval=15`/`ping_timeout=20`/`http_compression=False` para caber no limite de duração da função. Client CDN já é o 4.6.0 (protocolo v4/v5 compatível).
- [x] Configuração por ambiente: `app.secret_key` saiu do código → `DADINHO_SECRET_KEY` com fallback de dev (`supersecretkey`).
- [x] `vercel.json` (builder `@vercel/python` + rota catch-all) e `api/index.py` exportando `app.wsgi_app` (middleware Socket.IO do Flask-SocketIO), validado localmente com `VERCEL=1`.
- [x] Remover pressupostos locais: `socketio.run(app)` só roda quando `VERCEL != 1`.

Extras no caminho (não listados originalmente):
- Camada de estado agora permite que um tab novo/reconexão recupere a sala intacta (Fase 4 fica viável: snapshot no connect).
- Seleção de store por env vars, sem dependência nova no `requirements.txt` (cliente REST Upstash via `urllib` padrão).

## Fase 3 — Deploy e operação ✅ concluída

- [x] Publicar na Vercel e validar com 2+ navegadores/dispositivos (teste manual, único meio de verificação do projeto). Produção em https://dadinho-hazel.vercel.app (projeto `dadinho`, `fbsagats-projects`).
- [x] Validar limites free: duração máxima de função (300s/Hobby), conexões WebSocket simultâneas (sem WebSocket na Vercel — long-polling; sem leaderboard persistente).
- [x] Registrar no `AGENTS.md`/`README` o fluxo de deploy real (comandos, env vars).

## Fase 4 — Experiência pós-deploy (opcional)

- [ ] Heartbeat/reconexão: hoje um tab novo nunca sincroniza o estado de uma partida em andamento; enviar snapshot da sala no connect.
- [ ] Polir espectador/`reset_partida`/limpeza de sala vazia (GC de salas sem ninguém).
- [ ] UI: remover hardcodes de layout (alturas de card 240px etc.), revisar tipografia/exibição em mobile.