# TODO — Dadinho

<!-- Fases 0 a 12 concluídas. -->

Plano em fases para o objetivo atual: **subir o jogo na Vercel, com múltiplas salas, casual only** (sem contas, sem ranking, sem VPS).

Legenda: `[ ]` pendente · `[x]` concluído · `[~]` em andamento.

## Índice das fases abertas

- **Fase 6** — Bugs críticos: travamentos e anti-trapaça. ✅ concluída
- **Fase 7** — Robustez serverless e segurança dos handlers. ✅ concluída
- **Fase 8** — Performance e escala do store (Upstash). ✅ concluída
- **Fase 9** — UX e melhorias de negócio. ✅ concluída
- **Fase 10** — Limpeza, organização e tooling. ✅ concluída
- **Fase 11** — Jogadores IA (4 níveis). ✅ concluída
- **Fase 14** — i18n (5 idiomas + fallback EN). ✅ concluída
- **Fases 15–22** — espectadores, GC unificado, heartbeat/visto_em, home sem sala, expulsão, personalidade dos bots, jogada automática e status de confirmação. ✅ concluídas (resumo no fim do arquivo)
- **Fases A–G** — revisão de segurança e custo (botão Ok, erro de rede no store, custo do heartbeat, chave fora da query, XSS defensivo, selo provably fair, docs). ✅ concluídas (resumo no fim do arquivo)
- **Fase 24** — Lock distribuído por sala (Upstash REST) para consistência entre instâncias. ✅ concluída
- **Fase 25** — Message queue (`socketio.RedisManager`) para emits em tempo real entre instâncias. ✅ concluída
- **Fase 26** — Otimizações pós-métricas (`ignore_queue`, detector CAS). 📄 `docs/plano-cross-instance.md` (opcional)
- **Fase 27** — Infra: ambiente, segredos e deploy (`.env.example`, fallback do store, `maxDuration`, cache de estáticos). ✅ concluída
- **Fase 28** — Infra: robustez do store e locks (blob corrompido, `Partida` vazia, `esquecer_sala`). ✅ concluída
- **Fase 29** — Regra de jogo: aposta irrespondível e cap de jogadores burlado. ✅ concluída
- **Fase 30** — Frontend: fila de alertas e seleção de dado stale. ✅ concluída
- **Fase 31** — Frontend: performance, CSS morto e CSP/i18n. ✅ concluída
- **Fase 33** — Mobile: menu sandwich, swipe no lobby e ação fixa na partida. ✅ concluída (resumo no fim do arquivo)

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

---

# Plano da auditoria (Fases 6–10)

Origem: auditoria completa do código (bugs, anti-trapaça, segurança, code smells, escala e negócio). Referências de arquivo/linha apontam o local exato no estado atual do código.

## Fase 6 — Bugs críticos: travamentos e anti-trapaça ✅ concluída

Objetivo: eliminar os travamentos por desconexão e fechar os vetores de trapaça/desync na aposta, antes de qualquer evolução.

- [x] **B1 — Desconexão no meio da partida não pode travar a conferência.** `handle_disconnect` (`app.py`) remove o jogador de `partida.jogadores`, mas **não** de `rodada.jogadores`; `conferencia_final` compara `rodada.conferiram == len(rodada.jogadores)` (`app.py:317`) e o fantasma impede a conferência de fechar. Fix: remover o desconectado de `rodada.jogadores` e decrementar `conferiram` se ele já tinha confirmado.
- [x] **B2 — Contador de vitória defasado após desconexão.** `vencedor_final` compara `lobby.conferiram_vencedor == len(lobby.jogadores)` (`app.py:337`); se o desconectado já tinha `confirmou_vencedor=True`, o contador fica maior que o lobby e o "Ok" da vitória nunca libera o reset. Fix: recalcular contadores no disconnect (ou comparar por conjunto de `client_id` confirmados).
- [x] **B3 — Validação de aposta (anti-trapaça).** `Rodada.construir_turno` (`modelos.py:685-691`) aceita `dado` fora de 1–6 e `quantidade < 1`; payload malformado (`dado` ausente/não-numérico) estoura `ValueError`/`KeyError` no handler. Apostar **"0 ases"** no 1º turno é aceito (`modelos.py:908-912`) e é vitória garantida ao ser desafiado (`quantidade >= qtd` vira `count >= 0`, `modelos.py:752`). Fix: usar `validar_numero`/range + `try/except`, rejeitando a jogada com `jogada_invalida`.
- [x] **B4 — `foguetear` deve checar `partida.vencedor_final`** (`app.py:353` checa `rodada.vencedor` hoje). Em partida encerrada por desconexão (`app.py:113`), `rodada.vencedor` é `None` e o "Comemorar" do vencedor não dispara.
- [x] **B6 — `bool("false") == True` em `definir_config`** (`modelos.py:318-322`): aceitar somente bool real para `com_coringa`/`publica`.
- [x] **B7 — Snapshot da página 2 em rodada 2+** deve usar `dados_qtd` por jogador em `construtor_html` (`funcoes_gerais.py:114` hoje usa `partida.dados_qtd` base).

Extras corrigidos no caminho (não listados originalmente):
- Guard de página no desbloqueio de rolagem do `handle_disconnect`: o bloco "se a rolagem só esperava este jogador" rodava em qualquer página — na conferência/vitória (3/4) todos já rolaram e a desconexão reverteria a tela para os turnos (página 2). Agora só roda com `lobby.pagina == 1`.

Verificação (local, `.venv`): `py_compile` de `app.py modelos.py funcoes_gerais.py store.py api/index.py`; `node --check static\script.js`; round-trip de serialização (versão 2, config com bools reais); boot `VERCEL=1` respondendo 200; integração via `flask_socketio.test_client` cobrindo aposta inválida/"0 ases"/payload malformado (B3), bools reais em `definir_config` (B6), desconexão na conferência e nova rodada sem fantasma (B1), snapshot de rodada 2+ com `reset_rodada` por jogador (B7), desconexão na vitória e reset liberado (B2) e vencedor por desconexão soltando fogos (B4). Script heap em `C:\Users\wwwfa\AppData\Local\Temp\opencode\teste_fase6.py`.

## Fase 7 — Robustez serverless e segurança dos handlers ✅ concluída

Objetivo: garantir consistência do estado distribuído e uniformizar autenticação/validação em todos os eventos Socket.IO.

- [x] **A4 — Prevenir lost-update no store.** Lock por sala **no processo** (`store.trancar_sala`, RLock por `sala_id`) cobrindo todo o read-modify-write dos handlers, com índice em processo `client_id → sala_id` (`funcoes_gerais.registrar_cliente`/`sala_do_cliente`) para achar a sala sem varrer o store e travar antes do load. `achar_jogador` passou a usar o índice (fallback na varredura completa se desatualizado). Connect/disconnect travam a sala (disconnect usa `?sala=`/índice e solta o lock antes de `esquecer_sala` quando a sala esvazia). Risco **cross-instance** continua documentado (mitigação imediata; evolução: check-and-set no Redis ou message queue).
- [x] **A3 — `chave_secreta` em todos os handlers mutáveis.** `jogar_dados`, `iniciar_partida`, `conferencia_final`, `vencedor_final` e `foguetear_click` agora exigem a chave (mesmo padrão de `aposta`/`desconfiar`/`configurar_partida`/`ficar_pronto`); `joguei_dados` já checava. Front-end atualizado para enviar `chave` nos 5 eventos.
- [x] **A6 — Guard de "já rolou" em `jogar_dados`.** Idempotência explícita por rodada: com `jogador.joguei_dados` já `True` (ou sem rodada), o evento é ignorado — spam de rolagem não re-rola nem sobrescreve os dados.
- [x] **V3 — Tratamento de payload malformado em todos os handlers.** Decorator `evento_mutavel` (escrita) e `evento_leitura` (leitura) com `try/except (ValueError, TypeError, KeyError, AttributeError)` + aborto silencioso, e guards `dados = dados or {}` / `isinstance(dict)` nos pontos de parse. Nenhum evento estoura exceção com payload `None`/não-dict.
- [x] **A5 — `secrets.choice` para `jogador_sorteado`** (`modelos.py:503`), espelhando `Jogador.jogar_dados`; `import random` removido de `modelos.py`.
- [x] **V2 — Rate limit/cooldown leve por sid.** `funcoes_gerais.tem_cooldown` (janela 0,5s em eventos de escrita, 2s na busca `listar_partidas`), aplicado nos decorators dos handlers — protege o free tier da Upstash (500k comandos/mês) contra spam/scripts.

Extras corrigidos no caminho (não listados originalmente):
- Ordem dos decorators: `@socketio.on` registra um wrapper interno e devolve a função original, então precisa ficar **por fora** de `@evento_mutavel`/`@evento_leitura` (senão o handler registrado não passava pelo cooldown/lock/segurança).
- `escolher_apelido` ganhou o wrapper `evento_mutavel` (estava sem cooldown/lock/segurança).

Verificação (local, `.venv`): `py_compile` de `app.py modelos.py funcoes_gerais.py store.py api/index.py`; `node --check static\script.js`; round-trip de serialização (árvore com partida/rodada e `jogador_sorteado`); boot `VERCEL=1` respondendo 200; integração via `flask_socketio.test_client` cobrindo A3 (chave errada recusada em todos os novos handlers + foguetear), A6 (re-rolar ignorado), V3 (payloads `None`/não-dict não estouram e o fluxo segue), V2 (cooldown real por sid) e partida completa até vitória com confirmações autenticadas. Script heap em `C:\Users\wwwfa\AppData\Local\Temp\opencode\teste_fase7.py`.

## Fase 8 — Performance e escala do store (Upstash) ✅ concluída

Objetivo: reduzir custo/latência e permitir mais salas simultâneas sem estourar o plano free.

- [x] **S1 — Índice `client_id → sala_id`** no store (`dadinho:sid:<client_id>` com TTL). `buscar_lobby_pelo_client_id` (`funcoes_gerais.py`) agora faz uma leitura pontual pelo índice em vez de deserializar **todas** as salas; a varredura completa fica só como último recurso. `registrar_cliente`/`desregistrar_cliente` sincronizam o índice do store no connect/disconnect.
- [x] **B8 — `lobby_num` sem `store.contar_salas()`** — `obter_sala` agora usa `store.proximo_numero()` (INCR distribuído em `dadinho:lobby_seq`), O(1), sem deserializar nada.
- [x] **Índice leve de resumos** para `listar_partidas` — `atualizar_lista_usuarios` grava `dadinho:resumo:<id>` (JSON leve) e `listar_resumos_partidas` lê esse índice (`store.listar_resumos`, SCAN de chaves pequenas) em vez de reidratar os `Lobby` inteiros (árvore Partida/Rodada/Turno). `iniciar_partida` atualiza o resumo quando o status vira `jogando`; `remover_sala` apaga o resumo no GC.
- [x] **TTL no Upstash para salas órfãs** — o layout deixou o hash único `dadinho:salas`: agora cada dado é chave própria com TTL (`dadinho:sala:<id>`, `dadinho:resumo:<id>`, `dadinho:sid:<client_id>`), renovado a cada `salvar_sala`. Se a função morre sem disconnect, a sala expira sozinha (SET com `EX` via body-style da REST, sem depender de TTL por campo de hash).

Extras corrigidos no caminho (não listados originalmente):
- `listar_lobbys` do Upstash virou fallback via `SCAN` + `GET` (só é usado se o índice de SIDs não achar a sala) — mantém a interface `listar_lobbys` sem custo no caminho quente.
- `_comando` (body-style POST com array JSON) para escritas com valores complexos — evita URL-encode de JSONs; leituras seguem path-style (`GET`/`INCR`/`SCAN`).

Notas/limitações registradas (aceitos para o público casual):
- O resumo da busca é um snapshot no momento em que a sala muda (connect/disconnect/config/pronto/início) — leve defasagem aceita; a busca já revalidava os filtros por leitura.
- TTL de 7 dias (sala/resumo) e 1 dia (SID): salas ativas renovam a cada `salvar_sala`, então só órfãs expiram; salas de espera paradas por >7 dias sem nenhum evento expiram (casual, aceito).

Verificação (local, `.venv`): `py_compile` de `app.py modelos.py funcoes_gerais.py store.py api/index.py`; `node --check static\script.js`; round-trip de serialização; boot `VERCEL=1` respondendo 200; integração via `flask_socketio.test_client` (connect→resumo em espera→iniciar→resumo `jogando`→busca usa o índice) + camada Upstash validada contra um Redis REST fake (SET/GET/DEL/INCR/SCAN em body-style e path-style). Script heap em `C:\Users\wwwfa\AppData\Local\Temp\opencode\teste_fase8.py`.

## Fase 9 — UX e melhorias de negócio ✅ concluída

Objetivo: reduzir atrito e incentivar reuso (casual only, sem contas/ranking).

- [x] **B5 — Remover o `time.sleep(random.randint(4, 5))`** entre rolagem e turnos (`app.py`): a transição para a página 2 agora é imediata assim que o último jogador confirma (`joguei_dados`); o sleep segurava o handler (ruim p/ serverless, custava tempo de função e lock) e só atrasava quem já tinha rolado. Removido também do `handle_disconnect` (desbloqueio de rolagem); imports `time`/`random` saíram de `app.py`.
- [x] **Código de sala gerado no servidor** — `funcoes_gerais.gerar_codigo_sala()`: charset sem ambíguos (`abcdefghjkmnpqrstuvwxyz23456789`, sem 0/o/1/l/i), tamanho 5, e checagem de colisão contra o store (10 tentativas). Novo evento `criar_sala` (somente-leitura) responde `sala_criada` com o código; `script.js` navega para ele (fim do código client-side).
- [x] **Assistir partidas em andamento pela busca** — o botão "Assistir" foi habilitado e navega para a sala; `enviar_snapshot_sala` agora emite o selo `espectador` para quem entra no meio (páginas 1-3; na 4 o selo é pulado pois o espectador precisa do "Ok" do reset). O espectador entra no lobby, mas não na partida.
- [x] **Mostrar "Rodada N"** na tela de turnos — o payload `rodada_n` de `construtor_html` era emitido como `0` e ignorado; agora leva o número real da rodada (`rodada_numero`) e o cliente o exibe em `#rodada_atual_txt` (novo elemento em `tela_partida`).
- [x] **Janela de reconexão (grace)** para quem caiu no meio da partida — `Jogador.desconectado_em` (serializado) marca o momento da queda; o jogador fica na sala por `GRACE_RECONEXAO_SEGUNDOS` (30s) e o reconnect via `chave_secreta` limpa o marcador. Expurgo é **lazy** (adequado a serverless): `achar_jogador` remove quem expirou (reusando a lógica de remoção do disconnect, extraída para `_remover_jogador_da_sala` — contadores, avanço de vez, vencedor); os clientes recebem `jogador_desconectado` e agendam `verificar_desconectados` para forçar o expurgo mesmo sem interação. Sem jogador ativo sobrando, a queda é removida na hora (fluxo antigo); se todos caírem, a sala é removida.
- [x] **S6 — Eliminar saves redundantes** — `atualizar_lista_usuarios` já persiste a sala e o resumo da busca; removidos os `salvar_sala` duplicados no connect, `escolher_apelido`, `vencedor_final` e no `else` do disconnect (que agora só chama `atualizar_lista_usuarios`).

Notas/limitações registradas (aceitos para o público casual):
- O expurgo da janela de graça é lazy: depende do próximo evento de um jogador ativo ou do timer do cliente (`verificar_desconectados`). Se ninguém estiver conectado para disparar nada, a sala fica até o TTL do store — aceito.
- Durante a graça, o jogador caído continua contando na lista do lobby e segura a vez até ser expurgado — é justamente o objetivo (dar tempo de voltar).
- O código de sala é checado, mas não reservado no store: há uma janela de colisão ínfima entre a checagem e o connect (casual, aceito).
- Espectadores que entram no meio contam em `len(lobby.jogadores)` para a conferência de vitória (precisam clicar "Ok") — comportamento pré-existente da Fase 4, agora mais visível com o "Assistir" liberado.

Verificação (local, `.venv`): `py_compile` de `app.py modelos.py funcoes_gerais.py store.py api/index.py`; `node --check static\script.js`; round-trip de serialização (com `desconectado_em`); boot `VERCEL=1` respondendo 200; integração via `flask_socketio.test_client` cobrindo gerador/evento de código, `rodada_n` real, grace (desconexão marca → reconexão limpa → expurgo remove → vencedor declarado → sala sem ativos removida) e espectador pela busca. Scripts heap em `C:\Users\wwwfa\AppData\Local\Temp\opencode\teste_fase9.py` e `teste_fase9b.py` (Fase 7 revalidada com `teste_fase7.py`).

## Fase 10 — Limpeza, organização e tooling ✅ concluída

Objetivo: pagar dívida técnica e dar verificação automatizada ao projeto (hoje sem teste/lint/CI).

- [x] **S2 — Remover código morto:** `validar_numero` (usar na Fase 6 ou remover), `Partida.contar_jogadores`, `Rodada.jogaram_dados` (só serializado), `Lobby.listar_jogadores`, `Jogador.criar_jogador` (wrapper trivial), `sala_room()` duplicado (`funcoes_gerais.py:9` vs `Lobby.sala_room`), chaves `rodada_n`/`coringa_atual` não usadas de `construtor_html`.
- [x] **S4 — `emit` explícito com `to=`** em toda a cadeia (`jogar_dados_resultado` `app.py:238` e `meus_dados` `app.py:254` hoje dependem do default "somente ao originador" — deixar explícito).
- [x] **S5 — Decorator/helper** para o boilerplate `achar_jogador` + guard de chave repetido em ~10 handlers.
- [x] **S3 — Mecanismo de migração** por `versao` em `Lobby.para_dict`/`de_dict` (hoje `versao: 3` é gravado e nunca validado).
- [x] **S7 — Limpezas JS:** variável morta `indicie_atual` (`script.js:341`), bloco `{}` solto no `mudar_pagina`, `diceImages` como constante global, typos `conringa_cancelado`/`corin_atual` (`script.js:408-409`).
- [x] **Script único de verificação** no repo (`py_compile` + `node --check` + boot `VERCEL=1` respondendo 200 + integração `flask_socketio.test_client` cobrindo Fase 6/7) — consolidar os scripts heap de `Temp` no projeto.

Extras no caminho (não listados originalmente):
- `sala_room()` virou uma função única em `modelos.py` (fonte do prefixo `sala_`); `Lobby.sala_room` delega e `funcoes_gerais` importa, eliminando a duplicata.
- A migração de versão é aplicada em `Lobby.de_dict` (`_migrar` sobe de v1/v2 até `VERSAO_ATUAL`); formato mais novo não é rebaixado. `Rodada.jogaram_dados` saiu da serialização sem exigir migração (leitura usa defaults).
- O helper de autenticação (`autenticar`) também centraliza o guard de master; `escolher_apelido`/`verificar_desconectados` usam `extrair_chave=None` (eventos sem chave).

Verificação (local, `.venv`): `python verificar.py` (script único, no repo) — `py_compile` de todos os módulos, `node --check static/script.js`, boot `VERCEL=1` com `GET /` = 200, round-trip de serialização + migrações v1→v3/v2→v3, e integração via `flask_socketio.test_client` cobrindo B3/B6/B1/B7/B2/B4 (Fase 6) e A3/A6/V3/V2/A4/A5 + partida completa (Fase 7). Também `python simular_ia.py --partidas 20 --dados 3` (hierarquia 4>3>2>1 preservada).

## Fase 11 — Jogadores IA (4 níveis) ✅ concluída

Objetivo: bots server-side para preencher partidas reais e permitir testes sem vários navegadores.

- [x] **Modelo (`modelos.py`)** — `Jogador.is_ia`/`ia_nivel` serializados (`versao` 3); `Jogador.criar_ia(nivel, username)`; `Lobby.definir_master` ignora bots; `Lobby.tem_humano()` (GC de sala só com bots); `resetar_para_lobby` mantém bots prontos; configs `substituir_desconectado_por_ia` e `ia_nivel_padrao` em `config_padrao`/`definir_config`.
- [x] **Validação pura** — `Rodada.jogada_valida` extraída de `Turno.verificar_validade_da_jogada` (que passa a delegar, mantendo o efeito do 1º turno); a IA usa a versão pura para gerar apostas legais.
- [x] **Motor (`ia.py`)** — `decidir` com 4 níveis: 1 Novato (aleatório), 2 Regular (aposta mínima + heurística binomial imperfeita), 3 Perito (binomial, limiar 0,40, aposta mais defensável), 4 Mestre (limiar 0,30 subindo em disputas longas + aposta de pressão com P≥0,60). Só usa os próprios dados + informação pública (nunca `rodada.todos_os_dados`).
- [x] **Orquestrador** — `ia.processar(lobby)` roda dentro do request (sem threads/timers) e avança rolagem/apostas/conferência/vitória até precisar de humano; chamado em `iniciar_partida`, `joguei_dados`, `aposta`, `desconfiar`, `conferencia_final`, `vencedor_final`, `handle_connect` e no expurgo da graça. `handle_disconnect` remove sala sem humano; bots confirmam nas páginas 3/4.
- [x] **Eventos/UI** — `adicionar_ia`/`completar_com_ias`/`remover_ia` (master + `chave_secreta`, só na espera); painel 🤖 no lobby (nível, quantidade, adicionar/completar/remover) e switch "Trocar desconectado por IA".
- [x] **Substituição na graça** — `_substituir_por_ia`: com a opção ligada e havendo outro humano ativo, o desconectado vira bot (preserva dados/turno) em vez de sair.

Verificação (local, `.venv`): `py_compile` de `app.py modelos.py funcoes_gerais.py store.py ia.py simular_ia.py api/index.py`; `node --check static/script.js`; boot respondendo 200; simulador headless `python simular_ia.py` (milhares de partidas — hierarquia 4>3>2>1 consistente em 1-4 dados e com/sem coringa, sem travamentos); integração `flask_socketio.test_client` com 1 humano + 2 bots até o fim (humano virou espectador, bots fecharam e voltaram ao lobby); testes de serialização v3, `definir_master`, prontidão dos bots após reset e substituição por IA. Scripts heap em `C:\Users\wwwfa\AppData\Local\Temp\opencode\` (`teste_integracao_ia.py`, `teste_modelo_ia.py`, `teste_substituicao_ia.py`, `sweep_ia.py`).

Notas/limitações registradas (aceitos para o casual):
- As ações dos bots chegam juntas no fim do request, mas o **cliente** as apresenta em sequência: uma fila serial (`script.js`) aplica o "tempo de pensamento" de cada nível (de `narrador.py`) antes de revelar a jogada, sem timers no servidor.
- `simular_ia.py` neutraliza `emit` e monta o `Lobby` direto no modelo — é ferramenta de verificação/balanceamento, não roda dentro do app.
- Sala só com bots é removida no disconnect do último humano; a substituição por IA exige outro humano ativo (senão não faria sentido continuar).

## Fase 12 — Tema oficial rotativo (12h) — concluída

Objetivo: a música de fundo mudar sozinha a cada 12h, de forma compatível com o alvo serverless (sem timers, threads de fundo ou estado persistente).

- [x] **Gerador parametrizável (`gerar_musica.py`)** — a composição passou a ser sorteada dentro de regras musicais (tonalidade, progressão, melodia, arpejo, baixo, contracanto, bateria e BPM); `gerar_variante(seed)` devolve `(midi_bytes, bpm)` e a CLI ganhou `-n/--quantidade` e `--seed` para gerar lotes e escolher uma.
- [x] **Tema derivado do relógio (`tema.py`)** — `tema_atual()` calcula a janela de 12h (00:00/12:00 UTC), deriva o `seed` por SHA-256 e gera o MIDI; determinístico entre instâncias e cacheado por janela em processo. `DADINHO_TEMA_SEED` congela uma música escolhida.
- [x] **Rota `GET /tema.mid` (`app.py`)** — serve o MIDI vigente com `Cache-Control` expirando na virada da janela (e headers `X-Dadinho-Tema-Seed`/`Bpm`); fallback para o `static/sons/dadinho_tema.mid` versionado se a geração falhar. Única exceção REST além de `/`.
- [x] **Cliente (`static/script.js`)** — `iniciar_musica` passou a buscar `/tema.mid` em vez do arquivo estático.

Verificação (local, `.venv`): `py_compile` de `app.py gerar_musica.py tema.py modelos.py funcoes_gerais.py store.py ia.py api/index.py`; `node --check static/script.js`; `tema_atual` idempotente na mesma janela e distinto na janela seguinte; rota `GET /tema.mid` respondendo 200 `audio/midi` com header `MThd` e bytes idênticos entre requests; CLI `gerar_musica.py -n 1 --seed 42` gerando arquivo válido.

## Fase 14 — i18n com 5 idiomas e fallback para inglês — concluída

Objetivo: jogar em inglês, português (BR), espanhol, francês e chinês simplificado, com o inglês como base/fallback, sem build step e sem quebrar o alvo serverless.

- [x] **Dicionário único (`static/i18n.js`)** — 5 dicionários (EN, pt-BR, es, fr, zh-CN) com a mesma cobertura de chaves; `t(chave, params)`, `t_list` e `traduzirSegmentos(segmentos, texto)`. Detecção `localStorage.dadinho_idioma` → `navigator.language` → inglês; chave ausente cai para o inglês.
- [x] **UI estática (`templates/jogo.html`)** — textos anotados com `data-i18n`/`data-i18n-html`/`data-i18n-title`/`data-i18n-placeholder`/`data-i18n-value`/`data-i18n-aria-label`; `#seletor_idioma` no canto superior e `i18n.js` carregado antes de `script.js`.
- [x] **Frontend dinâmico (`static/script.js`)** — todas as strings montadas em JS passam por `t()`; `dicas_por_pagina` e `NARRADOR_MODOS` guardam chaves; a narração é traduzida por `traduzirSegmentos`; o texto da conferência é remontado no cliente a partir de campos estruturados.
- [x] **Narração server-side (`narrador.py`)** — cada lance devolve `texto` (pt-BR, fallback) + `segmentos` de `{chave, params}` (prefixos, ações, arremates, rodada, vitória). O servidor segue agnóstico de idioma e emite uma única vez para a room.
- [x] **Mensagens do servidor (`modelos.py`/`app.py`)** — `pode_iniciar` devolve `motivo` `{chave, params}`; `jogada_invalida` emite `txtchave`/`txtparams`; a `conferencia` ganhou `dado_qtd`/`quantidade_real`/`verdadeira` para o cliente montar o texto traduzido.
- [x] **Verificação (`verificar.py`)** — checa `node --check` de `script.js` e `i18n.js` e a cobertura dos 4 idiomas em relação ao inglês.

Verificação (local, `.venv`): `python verificar.py` (tudo OK: `py_compile`, `node --check static/*.js`, cobertura i18n, boot `VERCEL=1`, round-trip e integração Flask-SocketIO) e `python simular_ia.py --partidas 20 --dados 3` (hierarquia preservada). Teste manual recomendado: abrir em 2 abas, trocar o idioma pelo seletor e jogar uma partida completa.

---

## Fases 15–22 — resumo

As fases seguintes foram documentadas de forma condensada (detalhes completos em `AGENTS.md`):

- **Fase 15** — Espectadores: quem entra no meio de uma partida vira `Jogador` em `lobby.espectadores` (nunca em `lobby.jogadores`); gates de página nas confirmações (`conferencia_final`/`vencedor_final` só nas páginas 3/4); GC unificado `app.py:_gc_sala` fecha sala sem humano conectado.
- **Fase 16** — Aposenta a sala padrão compartilhada `padrao` (sentinela de "sem código"); `handle_connect` não cria sala automaticamente.
- **Fase 17** — Heartbeat (`visto_em`) esconde resumos órfãos do serverless na busca (`LIMITE_RESUMO_PARADO_SEGUNDOS`).
- **Fase 18** — Home sem sala: `#painel_home` com "Criar sala" (`criar_sala`) e "Buscar partidas" (`listar_partidas`); re-sync da espera via heartbeat.
- **Fase 19** — Expulsão de jogador (`expulsar_jogador`, master + `chave_secreta`); `ids` no payload da lista.
- **Fase 20** — Personalidade dos bots (`ia_risco`/`ia_agressividade` sorteadas); modulam desconfiança, altura das apostas e tempo de pensamento.
- **Fase 21** — Jogada automática por tempo máximo (`tempo_max_jogada` + `autojogar`): rola/aposta/desconfia/confirma pelo atrasado com o motor da IA; referências de tempo persistidas (`rodada.vez_em`, `rodada.inicio_rolagem_em`, `rodada.conferencia_em`, `partida.vitoria_em`).
- **Fase 22** — Status de confirmação em tempo real (`rolagem_status`/`conferencia_status`/`vitoria_status` com `confirmados`/`pendentes`/`total` por apelido).

## Fases A–G — revisão de segurança e custo

Implementadas nesta revisão (refs em `AGENTS.md`):

- **Fase A** — Botão "Ok" da conferência/vitória volta ao estado inicial entre rodadas/partidas (`rearmar_ok` limpa `data-confirmado`).
- **Fase B** — `evento_mutavel` agora aborta silenciosamente também em falhas de rede/IO do store (`OSError`, `http.client.HTTPException`), evitando traceback e perda silenciosa de estado em blips da Upstash.
- **Fase C** — Custo do heartbeat: cadência da espera 5s → 20s; `heartbeat` não passa mais por `autenticar`; leitura via cache tolerante a defasagem `store.carregar_sala_leve` (TTL 25s, por sala, atualizado a cada `salvar_sala`); `ia.processar` só roda com leitura fresca; piso do `visto_em` 30s → 60s. Estourava o free tier com poucos jogadores ociosos.
- **Fase D** — `chave_secreta` sai da query string do handshake (vazava em logs): connect cria placeholder e a identidade é retomada pela primeira mensagem (`retomar_identidade`, `cooldown=None`); cliente manda só `tem_chave` (booleano não-secreto).
- **Fase E** — `innerHTML` do vencedor agora escapa o nome interpolado (`escapar_html`); apelidos já eram validados, isto é defesa em profundidade.
- **Fase F** — Selo "provably fair" (`js.fair.ativo`/`js.fair.inativo`) na busca e na sala de espera (`#badge_fair`), com `verificacao_ativa` no resumo.
- **Fase G** — Documentação (`AGENTS.md`/`todo.md`) alinhada às fases acima.
- **Fase E2** — Re-sync da sala de espera SEMPRE lê o estado fresco do store a cada batida (não só o master, e não via o cache da Fase C): o jogador não-master recebia a lista do cache defasado e o início da partida só era detectado quando o cache expirava — na Vercel o host não via quem entra/fica pronto e o jogador não avançava de tela. Regressão guardada em `verificar.py` (`heartbeat-espera-fresco`).

Verificação: `python verificar.py` (inclui `teste_retomar_identidade_por_evento`) e `python simular_ia.py`.

## Fases 24–26 — tempo real entre instâncias

Plano completo em `docs/plano-cross-instance.md` (decisões, mudanças por arquivo, critérios de aceite). Resumo:

- **Fase 24** — Lock distribuído por sala: `store.trancar_sala_distribuida` (SET `dadinho:lock:<id>` NX EX + release `DELEX IFEQ`, **no-op em memória**), aninhado ao lock local em `evento_mutavel`/`handle_connect`/`handle_disconnect`; exceção `TravaIndisponivel` → aborto silencioso; fake de `_comando`/`_pipeline` em `verificar.py` atualizado + teste do lock. Pré-requisito de consistência para a Fase 25. ✅ concluída
- **Fase 25** — Message queue: dep `redis` pinada; `GerenciadorRedisSeguro(socketio.RedisManager)` com o RLock das 5 correções; wiring em `app.py:82-93` por env `DADINHO_MESSAGE_QUEUE` (URL `rediss://`, `channel="dadinho"`); sem env, mantém `GerenciadorThreadSeguro`. Emits não mudam; cliente intocado. ✅ concluída
- **Fase 26** (opcional, após métricas) — `ignore_queue` em emits `to=<sid>`; detector CAS/version-token como alerta.

### Fase 24 — detalhe da implementação

- **`store.py`** — constantes `PREFIXO_TRAVA`/`TRAVA_TTL`(120s)/`TRAVA_TENTATIVAS`(10)/`TRAVA_ESPERA_BASE`(0.05s, backoff dobro cap 0.2s); `TravaIndisponivel(Exception)`; `trancar_sala_distribuida(sala_id)` via `@contextlib.contextmanager` — adquire com `SET NX EX` (token `secrets.token_hex(8)`, lease 120s), libera com `DELEX IFEQ` no `finally` (nunca derruba a trava re-adquirida por outra instância após o lease expirar), no-op se o store for memória.
- **`app.py`** — `evento_mutavel` aninha o lock distribuído **por dentro** do lock local (LIFO, sem inversão → sem deadlock) e soma `store.TravaIndisponivel` ao `except` (política de aborto silencioso da Fase B). `handle_connect`/`handle_disconnect` aninham o mesmo com `try/except TravaIndisponivel: return` (connect: cliente reconecta com backoff; disconnect: limpeza fica para o GC/heartbeat, como num blip de rede).
- **`verificar.py`** — fake do índice de resumos agora simula o lock (SET NX/EX → "OK"; DELEX IFEQ → compara e remove); novo `teste_trava_distribuida` (duas instâncias REST fake no mesmo Redis): exclusão mútua, release com token errado é no-op, lease expira sozinho e contenda levanta `TravaIndisponivel`.

Verificação (local, `.venv`): `python verificar.py` 100% verde (inclui `trava-distribuida`); dev local (`memoria`) com regressão zero (lock no-op). Produção: validar com 2 navegadores/instâncias, seguindo `docs/verificacao.md`. Custo: +2 comandos Upstash por evento mutável (SET NX + DELEX).

### Fase 25 — detalhe da implementação

- **`requirements.txt`** — linha nova pinada `redis==8.1.0` (resolvida pelo pip e instalada na `.venv`).
- **`app.py`** — `import socketio as pacote_socketio`; nova classe `GerenciadorRedisSeguro(pacote_socketio.RedisManager)` replicando o RLock das 5 correções (`connect`, `basic_enter_room`, `basic_leave_room`, `basic_disconnect`, `basic_close_room`) — a hierarquia `PubSubManager(Manager)` é preservada, então o `_handle_emit` da thread de listener segue chamando `Manager.emit` e as correções de corrida continuam valendo. Wiring por env `DADINHO_MESSAGE_QUEUE` (opt-in): com a env, `GerenciadorRedisSeguro(url_mq, channel="dadinho", redis_options={"ssl_cert_reqs": "required"} se rediss://)`; sem a env, mantém `GerenciadorThreadSeguro`. `RedisManager.initialize()` em `threading` não exige monkey-patch (só eventlet/gevent), então o listener roda em `threading.Thread` sem levantar.
- **`verificar.py`** — novo `teste_mq_wiring` (subprocess com `DADINHO_MESSAGE_QUEUE=rediss://` fake: manager é `GerenciadorRedisSeguro`, canal `dadinho`, boot não trava com URL inalcançável); rodado junto à integração.

Verificação (local, `.venv`): `python verificar.py` 100% verde (inclui `mq-wiring`); sem a env, regressão zero (`GerenciadorThreadSeguro` e todos os testes intocados). Com a env: `ia.processar` segue sem timer e `simular_ia.py` intocado. Produção: validar com 2 navegadores em instâncias diferentes vendo rolagem/aposta/conferência ao vivo, e monitorar comandos/conexões no painel Upstash (critérios de `docs/plano-cross-instance.md`).

---

# Plano da auditoria de infra e bugs (Fases 27–31)

Origem: auditoria de infra (ambiente, deploy, store) + varredura de código (bugs frontend/backend). Referências de arquivo/linha apontam o local exato no estado atual do código.

## Fase 27 — Infra: ambiente, segredos e deploy ✅ concluída

Objetivo: ambiente documentado, sem fallbacks silenciosos que zeram o estado em produção, e limites de execução compatíveis com a Vercel.

- [x] **I1 — Criar `.env.example`** com as 10 env vars lidas pelo código: `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` (obrigatórias em prod), `DADINHO_MESSAGE_QUEUE`, `DADINHO_SECRET_KEY`, `DADINHO_STORE`, `DADINHO_ASYNC_MODE`, `DADINHO_PERMITIR_WEBSOCKET`, `DADINHO_DRAND_URL`/`DADINHO_DRAND_CHAIN`, `DADINHO_TEMA_SEED` (`store.py:418-424`, `app.py:107-119`, `seed.py:53-54`, `tema.py:45`). Obs.: a env do beacon é `DADINHO_DRAND_CHAIN` (o `_PADRAO` é a constante interna). `.gitignore` ganhou `!.env.example` (o padrão `.env*` engolia o exemplo).
- [x] **I2 — Bloquear o fallback silencioso do store em produção** (`store.py:417-424`): com `DADINHO_STORE != memoria` e sem `UPSTASH_REDIS_REST_URL`/`TOKEN`, o app caía em `ArmazenamentoMemoria()` sem log — em serverless cada cold start vira um store vazio e todo o estado some sem sinal. Agora `_selecionar_armazenamento` levanta `RuntimeError` explícito no boot quando `VERCEL=1` e o store não está configurado; o fallback de memória fica só em dev (regressão zero).
- [x] **I3 — Remover o fallback `"supersecretkey"`** (`app.py:24`): `DADINHO_SECRET_KEY` agora vem da env, ou é aleatória por processo quando ausente (`secrets.token_hex(32)`) — sem valor fixo comodado (a sessão não é usada, então não há requisito de estabilidade entre requests).
- [x] **I4 — Runtime Python pinado**: `.python-version` com `3.12` (forma suportada pelo `@vercel/python`; o campo `runtime` do `builds` e o `maxDuration` no topo do `vercel.json` são inválidos nesse schema e quebravam o build — removidos). O app segue no default de duração da função (já funcionava antes).
- [x] **I5 — `.vercelignore`: excluir `material/`** — a pasta é gitignored mas entrava no deploy (imagens de referência e SFX sem licença própria não devem subir).
- [x] **I6 — Cache-Control para estáticos**: `after_request` no `app.py` injeta `Cache-Control: public, max-age=86400` nas respostas de `/static/*` (sem fingerprint nos URLs, 1 dia evita servir JS/CSS velhos após deploy).
- [x] **I7 — Remover `.env.local` stale** — `VERCEL_OIDC_TOKEN` expirado (escrito pelo CLI da Vercel; não comitado, limpeza).

Verificação (local, `.venv`): `python verificar.py` — novo checador `boot sem store falha (I2)` (subprocess com `VERCEL=1` e sem env do store: deve falhar com "Store não configurado") e o boot `VERCEL=1` passou a validar o `Cache-Control` do estático (I6); `DADINHO_STORE=memoria` mantém regressão zero. Deploy: configurar as env vars no painel da Vercel e validar com 2 navegadores, seguindo `docs/verificacao.md`.

## Fase 28 — Infra: robustez do store e dos locks ✅ concluída

Objetivo: estado corrompido não vira 500 e o lock por sala não tem janela de concorrência.

- [x] **H1 — `carregar_sala` blindado contra bloco corrompido** (`store.py:298-305`): `json.loads` levanta `ValueError`/`TypeError` e derruba o handler com 500; agora captura `(ValueError, TypeError, KeyError)` e devolve `None` (a sala é tratada como inexistente e recriada na próxima escrita — fluxo do GC), espelhando o tratamento que `listar_lobbys` já tinha.
- [x] **H1b — `Partida.__init__` com zero jogadores** (`modelos.py:962-976`): `secrets.choice(self.jogadores)` estourava `IndexError` (e o caminho da seed, `ZeroDivisionError`); com a lista vazia o sorteado agora fica `None` — sem 500 na desserialização de um blob que referencia jogadores ausentes (`de_dict` re-aponta `jogador_sorteado` quando o jogador existe).
- [x] **H4 — `esquecer_sala` chamado dentro da seção crítica** (`store.py:64-70`): remover a trava do registro enquanto um request ainda está dentro do `with trancar_sala()` permitia que o próximo adquirisse um RLock **novo** e mutasse o mesmo Lobby em paralelo. `trancar_sala` agora devolve um wrapper com **ref-count** (`_TravaSala`): todos apontam para a mesma entrada (mesmo RLock) e `esquecer_sala` durante uma seção crítica só marca `esquecida` — o registro é limpo quando o último holder solta a trava (`__exit__`). `handle_disconnect` (que já chamava `esquecer_sala` fora do lock) e o GC (`_gc_sala`, dentro do lock) ficam seguros; comportamento para quem usa o `with trancar_sala(...)` é idêntico.

Verificação (local, `.venv`): `python verificar.py` — novos testes `H1-blob-corrompido` (blob inválido e árvore inválida devolvem `None`), `H1b-partida-vazia` (construtor com lista vazia sem `IndexError`, seed sem `ZeroDivisionError`, `de_dict` com jogador fantasma) e `H4-lock-secao-critica` (thread A dentro do `with` enquanto a sala esvazia → thread B **não** adquire lock distinto antes de A sair, e a trava some após o último holder); regressão zero nas Fases 6/7/15-25. `python simular_ia.py` hierarquia 4>3>2>1 preservada.

## Fase 29 — Correções de regra de jogo ✅ concluída

Objetivo: fechar a aposta irrespondível e o bypass do limite de jogadores pelo placeholder.

- [x] **H2 — Aposta irrespondível** (`modelos.py:1246-1269`): `construir_turno` valida `dado` 1–6 e `quantidade >= 1`, mas não limitava `quantidade` ao total teórico de dados na mesa — apostar acima da soma tornava o desafiado incapaz de subir a aposta. Agora o servidor **clampeia** `dado_qtd` no total de dados vivos (`len(rodada.todos_os_dados)` com fallback na soma dos `dados_qtd`), mantendo a face; a regra do coringa (dobro para sair dos ases) fica à parte e segue na validação normal do turno. A IA não é afetada (`gerar_apostas_validas` já gera `quantidade` em `1..total`).
- [x] **H3 — Cap de jogadores burlado por `tem_chave=1`** (`app.py:478-494`): as checagens `MAX_ESPECTADORES`/`max_jogadores` só rodavam com `not tem_chave`; um connect com `tem_chave=1` (sinal booleano de possível retomada) criava placeholder sem respeitar o limite da sala (e sem GC). O cap agora vale para o placeholder também: sala `jogando` → cap em `MAX_ESPECTADORES`; sala de espera → cap em `max_jogadores`; senão `sala_cheia` (o cliente sai da room e o placeholder não é registrado). A retomada da chave só reaproveita se a sala ainda comportar.

Verificação (local, `.venv`): `python verificar.py` — novos testes `H2-aposta-max` (aposta "100" com 3 dados vira 3 e o turno é criado; o próximo é forçado a desconfiar e a conferência fecha) e `H3-cap-placeholder` (4º connect com `tem_chave=1` numa espera 3/3 leva `sala_cheia`; 21º espectador com `tem_chave=1` estoura `MAX_ESPECTADORES` e leva `sala_cheia`); regressão zero nas demais fases. `python simular_ia.py` hierarquia 4>3>2>1 preservada.

## Fase 30 — Frontend: fila de alertas e seleção de dado ✅ concluída

Objetivo: eliminar os bugs de interação que "travam" o jogador na tela.

- [x] **F1 — Race no resolver de alerta** (`static/script.js:1969-2004`): o resolver único `_alerta_resolver` era sobrescrito quando um 2º alerta abria sobre o 1º → a promise do 1º nunca resolvia e cadeias `.then()` morriam (ex.: `sala_cheia → criar_sala`, `expulso_da_sala → navegação`). Agora os alertas têm **fila**: `_alerta_ativo` (alerta aberto) + `_fila_alertas` (pendentes) — quando o atual fecha, o próximo abre e resolve a própria promise na ordem.
- [x] **F2 — Seleção de dado stale entre turnos** (`script.js:2844`, `1319`, `1653`): `selectedImageValue` não era resetado em `meu_turno`/`espera_turno`/`reset_rodada` — a aposta enviava a face do turno anterior quando o jogador não clicava de novo, e `ajustar_quantidade_minima` recorria à face velha. Novo helper `limpar_selecao_dado()` (zera a seleção e desmarca `.selected`) chamado nesses 3 handlers.
- [x] **F3 — Limite do `#increase`** (`script.js:2831-2834`): deixava exceder o total de dados da mesa; o servidor rebatia com `jogada_invalida` (e clampeava — Fase 29 H2). O handler de `dados_mesa` agora guarda `total_dados_mesa` e o botão `+` para de subir no total.
- [x] **F4 — Enter em alerta de confirmação** (`script.js:2091-2124`): `Enter` resolvia `true` mesmo no alerta de Cancelar. Agora o Enter só confirma (`fechar_alerta(true)`) no alerta de "Ok" (aviso/erro/info/sucesso); no `confirmar`, o Enter ativa o botão em foco (o padrão é o Cancelar → `false`) e o `Escape` resolve `false`.

Verificação: `node --check static/script.js` OK + `python verificar.py` 100% verde (integração existente). Teste manual em 2 abas: alerta sobre alerta (a cadeia do 1º continua — ex.: `sala_cheia` e a criação de sala em sequência), 2 turnos seguidos sem clicar em dado exigem nova seleção (pede `msg.selecione_dado`), `#increase` para no total da mesa.

## Fase 31 — Frontend: performance, CSS e segurança ✅ concluída

Objetivo: loop de confete sem custo ocioso, conflitos de CSS resolvidos e disciplina anti-XSS fechada.

- [x] **P1 — Gate no `requestAnimationFrame`** (`script.js:3082-3088`): `animate()` rodava para sempre e `drawParticles` fazia `clearRect` do viewport inteiro a cada frame mesmo sem partículas/confetes. Agora o loop é ligado sob demanda (`garantir_loop_animacao`, chamado em `iniciar_celebracao`/`soltar_fogos`) e roda só enquanto `celebrando || particles.length || confetes.length`; ao parar, limpa o canvas.
- [x] **P2 — `.selected` vs `:hover`** (`custom_styles.css:101-114` vs `126-133`): `:hover` tinha a mesma especificidade e, por vir depois, sobrescrevia `transform: scale(1.3)` da face selecionada (ela "des-selecionava" no hover). Nova regra `.image-button.selected img:hover` (específica) mantém `scale(1.3)` + brilho.
- [x] **P3 — Overlap `.narrador` × `.painel-dicas` no mobile** (`custom_styles.css:347-391`, `690-699`, `922-930`): ambos fixos no rodapé se sobrepunham em viewports ~600px. Em ≤768px a dica vai para o topo (`top: 64px`, abaixo dos botões/contador fixos); o narrador mantém o rodapé (e a regra ≤480px foi reconciliada).
- [x] **P4 — CSS morto**: removidos `.topo-fixo`, `.custom-list`, `.fixed-top-image` e `.row.no-gutters` (não casam com `jogo.html`; `no-gutters` é resíduo do Bootstrap 4 — os cards agora usam `g-1` do Bootstrap 5).
- [x] **P5 — Blindar `_interpolar`** (`i18n.js:1898-1908`): a interpolação agora escapa o valor (`_escapar_html`), então o valor nunca entra cru no `innerHTML` (ex.: `js.vitoria_texto`, que tem `<br>`); removida a dupla codificação no `vencedor_da_partida` e a função `escapar_html` (agora morta). **CSP avaliado e adiado**: o app tem ~21 handlers `onclick` inline + estilos inline + recursos de CDN (socket.io, Bootstrap, Google Fonts) — um CSP estrito exigiria `'unsafe-inline'` no `script-src` (valor de segurança baixo) e o refactor dos handlers exige teste real em navegador (o único meio de verificação do projeto).
- [x] **P6 — `<canvas>` com `z-index:-1`** (`custom_styles.css:194-201`): dependia do quirk de propagação do background do body (poderia sumir atrás do fundo). Agora `z-index: 0` + `pointer-events: none` (não intercepta cliques; os painéis com `z-index` 55+ seguem na frente).

Verificação: `node --check static/script.js`/`static/i18n.js` OK, `python verificar.py` 100% verde (cobertura i18n intocada — P5 não trocou chaves). Teste manual de perf no mobile/devtools: o `requestAnimationFrame` deve estar parado em telas sem festa (loop só roda na celebração).

---

# Plano mobile (Fase 33)

## Fase 33 — Mobile: menu sandwich, swipe no lobby e ação fixa na partida

Objetivo: transformar a exibição em telas pequenas (≤768px) num layout de "app": os botões de ferramenta saem do caminho da visão (menu sandwich), o lobby troca de painel por gesto lateral (sem rolar a página) e o controle de aposta fica sempre visível no rodapé da partida — o jogador não sobe e desce a tela o tempo todo. Desktop (≥992px) permanece intacto. Tudo é **client-side** (HTML/CSS/JS): nenhum evento, estado, env var ou serialização muda.

- [x] **M1 — Menu sandwich (hambúrguer) para os controles do topo.** Hoje 2 grupos de botões fixos disputam o topo com o jogo (`jogo.html:25-51`): idioma + som/música à direita, tutorial/dicas/narrador à esquerda. No mobile eles somem e viram um único botão `☰` (canto topo-direito, respeitando o safe-area) que abre um drawer sobreposto com as 6 ferramentas: **Tutorial** (❓), **Dicas/Help** (💡), **Narrador** (🎙️), **Idioma** (`#seletor_idioma`), **Sons** (🔊 + slider de volume) e **Música** (🎵 + slider de volume). Fecha no toque fora, no Esc e num botão ✖. O `#contador_jogada` e o `#bot_sair_da_sala` seguem fixos **fora** do menu. Desktop: manter os botões atuais como estão (o menu sandwich é só mobile).

- [x] **M2 — Lobby: swipe lateral para o menu do host.** `painel_jogador`/`painel_config`/`painel_ia` (`jogo.html:122-264`) empilham verticalmente e o host rola a página inteira pra chegar nas configurações. No mobile os 3 viram um carrossel horizontal: contêiner `display:flex; overflow-x:auto; scroll-snap-type:x mandatory`, cada painel `flex:0 0 100%` com `scroll-snap-align:center`. Tela 1 = **Jogadores** (apelido + lista + pronto/iniciar, padrão), tela 2 = **Configurações do host**, tela 3 = **Bots IA**. Dots indicadores + setas discretas nas bordas com `scrollIntoView({behavior:'smooth'})` — fallback acessível, swipe nunca é o único caminho. Não-master não vê as telas 2/3 (menos gestos); painéis ocultos ficam `display:none`. A lista de jogadores ganha scroll vertical interno (cresce sem estourar a tela).

- [x] **M3 — Partida: rodapé de ação fixo.** `#tela_partida` (`jogo.html:344-460`) vira flex-column com `height:100dvh` (fallback `100vh`) e `overflow:hidden`: **topo** com `rodada_atual_txt` + barra `meus_dados`/`dados_mesa`/`corin_atual` compacta (uma linha, dados menores); **meio** com `#cards` (`flex:1; min-height:0; overflow-y:auto`) — histórico rolável; **rodapé** fixo por construção (dentro do flex, não `position:fixed`) com `#painel_jogada`/`#painel_aguarde`. Minha vez: linha única de 6 dados de face compactos (`row-cols-6`, `overflow-x:auto` se apertar) + stepper `#quantidade` + Apostar/Desconfiar em fileira (~48px). Não minha vez: badge "Aguarde" + contador regressivo. Integrar o `#contador_jogada` (`jogo.html:61`) ao rodapé. Resolver o conflito com o `.narrador` mobile (`custom_styles.css:674-682`): quando a action bar existe, o narrador sobe para o topo esquerdo.

- [x] **M4 — Base mobile.** `<meta name="viewport">` (`jogo.html:6`) ganha `viewport-fit=cover` + `maximum-scale=1, user-scalable=no` (evita o zoom acidental ao tocar nos dados/botões); safe-areas `env(safe-area-inset-*)` nos botões fixos e no rodapé de ação (notch iOS); título `#div_titulo_img` reduzido no lobby mobile (20vh → ~14vh, `custom_styles.css:212`) e calibrado nas telas de jogo (`script.js:924-933`) para não estourar o `100dvh` — body vira flex-column e a tela ativa recebe `flex:1; min-height:0`.

Extras no caminho (não listados originalmente):
- `.app-main` nunca era fechado no HTML (quirk tolerado pelo navegador) — fechado corretamente após `#tela_vitoria`; o `<br>` entre cards e painel de jogada virou `margin-top` no `#rodape_acao` (desktop idêntico).
- Drawer/setas/dots ganharam aria-labels com chaves i18n (`ui.lobby.seta_esq`/`seta_dir`/`dots`); dots têm `role="tab"`/`aria-selected`.
- Sliders de volume (desktop e drawer) sincronizados com o valor persistido no load (regressão da refatoração evitada).
- A dica de swipe só aparece no mobile (gate por `matchMedia`), evitando vazamento para o desktop.

Notas/limitações (aceitas para o casual):
- O `#contador_jogada`, agora descendente de `#tela_partida`, sofre um glitch cosmético de ~350ms no desktop ao entrar na tela 2 (a animação `tela_aparecer` com `transform` cria um containing block temporário para o `position: fixed`) — só visível quando o timer está ativo no momento da troca de tela.
- `user-scalable=no` (M4) é decisão consciente para evitar zoom acidental ao tocar nos dados/botões (acessibilidade à parte, documentada).

Notas/limitações (aceitas para o casual):
- Scroll-snap e `100dvh` têm suporte em todos os navegadores modernos; `100vh` fica como fallback de altura.
- O swipe usa o scroll nativo (sem lib de touch, sem handlers manuais) — não compete com a rolagem vertical nem adiciona dependência.
- Novos textos (labels das abas/drawer, dica de swipe) passam pela skill `i18n-dadinho` (cobertura dos 5 dicionários e `verificar.py`).
- Nenhuma invariante de servidor é tocada (client-side puro); o re-sync serverless do lobby segue intacto.

Verificação (local, `.venv`): `python verificar.py` 100% verde (regressão zero — nenhuma chave i18n trocada, nenhum evento novo, serialização intocada) + `node --check static/script.js`; teste manual em 2 abas em device mode (Chrome DevTools, ex.: 375×667 e 414×896): drawer abre/fecha sem sobrepor a jogada, swipe alterna as telas do lobby (host chega na config sem rolar), apostar sem rolar a página, narrador não cobre a action bar, idioma/dicas/narrador seguem funcionando pelo menu; desktop ≥992px idêntico ao de hoje.