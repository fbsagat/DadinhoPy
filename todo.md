# TODO — Dadinho

<!-- Fase 3 e Fase 4 concluídas. -->

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

## Fase 4 — Experiência pós-deploy (opcional) ✅ concluída

- [x] Heartbeat/reconexão: snapshot da sala no connect — `funcoes_gerais.enviar_snapshot_sala(lobby, jogador)` reemite `mudar_pagina` (0/1/2/3/4) + os eventos de reconstrução do estado (`construtor_dados`, `construtor_html`, `dados_mesa`, `atualizar_coringa`, `meus_dados`, `formatador_coletivo`, `atualizar_turno`/`meu_turno`/`espera_turno`, `cards_conferencia`, `vencedor_da_partida`, `atualizar_pontos`, `botao_vencedor_ativ`, `espectador`).
- [x] Retomada de identidade por `chave_secreta`: cada jogador guarda a chave no `sessionStorage` (`dadinho_chave`) e reencanta no connect (`Lobby.buscar_jogador_pela_chave`), reaproveitando o mesmo `Jogador` (pontos, partida/rodada/turno atuais) — refresh/tab novo volta ao mesmo lugar; sid antigo fica órfão e é limpo no disconnect.
- [x] Estado extra persistido no store para o snapshot: `Lobby.pagina`, `Rodada.conferencia`, `Partida.vencedor_final`, e flags `Jogador.confirmou_rodada`/`confirmou_vencedor` (dedup de clique duplo em conferência/vitória).
- [x] `handle_disconnect` resiliente a partida em andamento: remove o jogador de `partida.jogadores`, avança `vez_atual` (e reemite `atualizar_front_pro_da_vez`) quando o da vez cai, destrava a rolagem quando o que faltava rolar cai, e declara vencedor quando só sobra 1 (sem travamento).
- [x] Polir `reset_partida`/GC: `resetar_para_lobby` define `pagina=0` e zera `confirmou_*`; cliente limpa DOM de vitória (h1 e texto) ao rejogar; sala sem ninguém continua sendo removida do store no disconnect do último jogador.
- [x] UI sem hardcodes de layout: cards com `min-height` fluido (200px no lugar de 240px fixo), painéis flex com wrap (`flex: 1 1 200px; min-width: 0`), lista de jogadores `width:100%`/`max-width:400px`, botões de aposta/desconfiar com wrap, `body` com `overflow-y:auto` em vez de `height:100vh` travada, media query `@media (max-width:768px)` para título (22vh/65%), `h1_vencedor` e botões menores, `painel_aguarde` em 90%.
- [x] Status de conexão visível (elemento `status_conexao` no HTML + handlers `connect`/`disconnect` no JS) e `connect_start` agora devolve `username` (restaura o apelido do `sessionStorage` sem re-tipar).

Notas/limitações registradas (aceitos para o público casual):
- Duas abas com a mesma chave no `sessionStorage`: a 2ª "rouba" a identidade e a 1ª vira zumbi (desconectada na sequência) — comportamento aceito.
- Race de refresh: se o disconnect antigo chegar antes do connect novo com a chave, o jogador é recriado como espectador da partida (visível, mas sem identidade) — degradado, não quebrado.
- Quem entra no meio da partida conta em `len(lobby.jogadores)` para a conferência de vitória (precisa clicar "Ok" mesmo não tendo jogado) — comportamento pré-existente mantido.
- Snapshot reinvoca apenas os handlers clientes já existentes (nenhum evento novo no `script.js`), e o branch da página 4 retorna antes do `emit('espectador')` final — espectador na tela de vitória mantém o "Ok".

Verificação (local, `.venv`): `py_compile` de `app.py modelos.py funcoes_gerais.py store.py api/index.py`; round-trip de serialização da árvore `Lobby`; `node --check static\script.js`; boot `VERCEL=1` respondendo 200; e teste de integração via `flask_socketio.test_client` cobrindo lobby→página 2→aposta→conferência→resume por chave→dedup e desconexões no meio do jogo (da vez cai → vez avança; quem não rolou cai → rolagem destrava). Script heap em `C:\Users\wwwfa\AppData\Local\Temp\opencode\teste_fase4.py`.

## Fase 5 — Sala de espera, configurações e busca de partidas ✅ concluída

Objetivo: transformar a tela 0 numa sala de espera de verdade (nome da partida, configurações pelo master, botão "ficar pronto" com trava de início) e adicionar a busca/listagem de partidas públicas com filtros.

- [x] **Modelo (`modelos.py`)** — `Lobby` ganha `nome`, `status` ("espera"/"jogando"), `criado_em` e `config` (dados_qtd, max_jogadores, com_coringa, publica); `Jogador` ganha `pronto`. `Lobby.definir_config` valida os valores; `Lobby.pode_iniciar()` devolve `(bool, motivo)` com as regras (>=2 jogadores, todos com apelido, todos os não-master prontos, dentro do limite); `Lobby.resumo_partida()` monta o resumo público da listagem. `Partida`/`Rodada` agora respeitam `config.com_coringa` (persistido na serialização, `versao` do Lobby bumpada p/ 2).
- [x] **Listagem/filtros (`funcoes_gerais.py`)** — `listar_resumos_partidas(filtros, sala_atual)` lê `store.listar_lobbys()` e filtra por busca (nome/código), status, vaga, coringa e ordenação (recentes/jogadores/nome); privadas não aparecem. `atualizar_lista_usuarios` agora também envia `nome`, `status`, `config`, `prontos`, `pode_iniciar` e `motivo`.
- [x] **Eventos (`app.py`)** — `configurar_partida` (master + `chave_secreta`), `ficar_pronto` (toggle com `chave_secreta`) e `listar_partidas` (somente leitura). `iniciar_partida` passou a exigir `pode_iniciar()` (senão emite `iniciar_negado`) e a usar `config.dados_qtd`. Connect recusa sala de espera cheia (`max_jogadores`) com `sala_cheia`; `construir_partida` marca `status='jogando'` e `resetar_para_lobby` volta para `espera` + zera prontidão (com `atualizar_lista_usuarios` no `vencedor_final`).
- [x] **Frontend** — Tela 0 virou sala de espera: título da partida, badges de status/prontidão, painel de configurações (somente master edita; auto-save via `change`), botão "Ficar pronto" e trava do "Iniciar partida". Nova tela **Buscar partidas** (client-side, fora do ciclo de páginas do servidor): filtros (nome/código, status, coringa, ordenar, com vaga) e lista com botão Entrar/Lotada/Assistir; `mudar_pagina` fecha a busca ao receber navegação do servidor.
- [x] **CSS** — painel de config e listagem (`#lista_partidas` com scroll + hover), selects/inputs da busca no tema escuro.

Notas/limitações registradas (aceitos para o público casual):
- `listar_partidas` reidrata todos os lobbies do store para montar os resumos — ok para escala casual, mas se a Upstash crescer muito, um índice leve (só resumo) seria a evolução natural.
- Salas privadas não aparecem na busca; quem tem o link (`?sala=`) entra direto.
- Sala cheia bloqueia novo connect na sala de espera; entrar no meio de partida em andamento só pelo link direto (vira espectador).

Verificação (local, `.venv`): `py_compile` de `app.py modelos.py funcoes_gerais.py store.py api/index.py`; `node --check static\script.js`; round-trip de serialização (versão 2, config + prontos + status + com_coringa); regras de `pode_iniciar`; filtros de listagem (busca/privada/status/coringa/vaga); boot `VERCEL=1` respondendo 200; integração via `flask_socketio.test_client` (master configura, não-master não, pronto libera início, partida inicia, busca lista a sala). Scripts heap em `C:\Users\wwwfa\AppData\Local\Temp\opencode\teste_fase5.py` e `teste_integracao_fase5.py`.