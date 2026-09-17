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
- **Fase 33** — Mobile vs desktop: menu ☰/drawer, carrossel do lobby, layout de partida e limpeza do swipe morto. ✅ concluída

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

## Fase 33 — Exibição distinta desktop x mobile ✅ concluída

Objetivo: no mobile os controles fixos do topo, o painel de jogada e o lobby disputavam o viewport pequeno; em desktop o código de swipe morreu órfão após o revert. Aperto mobile-first (≤768px), desktop intocado, tudo client-side e sem novo estado no caminho do jogo.

- [x] **M4 — Viewport** (`templates/jogo.html`): `viewport-fit=cover` (safe-areas do notch iOS) + `maximum-scale=1, user-scalable=no` (evita zoom acidental ao tocar nos dados); `theme-color` fixo.
- [x] **M1 — Menu ☰/drawer** (`jogo.html`, `custom_styles.css`, `script.js`): as duas `barra-topo-desktop` (Tutorial/Dicas/Narrador à esquerda; Idioma/Sons/Música à direita) viram `display:none` no mobile e entram num drawer (`#menu_drawer`, largura min(84vw,320px)) aberto pelo `#botao_menu`. Drawer fecha no ✖, no toque fora, no Esc; foco vai para o botão de fechar e o idioma/volume/música do drawer são sincronizados com os do topo (`seletor_idioma_mobile`, `menu_volume_musica`, `menu_botao_musica`, `alternar_musica`). Desktop mantém os controles atuais.
- [x] **M2 — Carrossel do lobby** (`#lobby_seta_*`, `#lobby_dots`, `#lobby_swipe_dica`): `lobby-linha` vira trilho com `scroll-snap-type: x mandatory`; os painéis Jogadores/Config/IA são slides (`lobby-slide`). Os dots são reconstruídos conforme os painéis visíveis (não-master só vê Jogadores — `body.nao-master`), setas desabilitam nas pontas e `marcar_ponto_atual` sincroniza dots no scroll. Desktop mantém o grid (`display:contents` no wrapper `col-lg-7` só no mobile).
- [x] **M3 — Layout de partida (app)** (`#area_mesa` + `#rodape_acao`): `#tela_partida` vira flex-column `100dvh` (classe `tela-partida-ativa` no mobile); `area_mesa` é o meio rolável e `rodape_acao` o rodapé fixo por construção com `safe-area-inset-bottom`. O `#contador_jogada` sai do topo e entra no rodapé (`position: static` no mobile; desktop mantém `position: fixed` no topo). Ação compactada: 6 dados numa linha rolável, `Apostar`/`Desconfiar`/stepper em fileira, cards e barra de status encolhidos; `body.em_tela_2 .narrador` sobe para o topo esquerdo.
- [x] **Limpeza do swipe morto** (o commit `efbceab` ficou órfão após o revert do `c014742`): removidos `lobby_dots`/`status_dots` antigos (sem CSS), `init_swipe_lobby` (referenciava `lobby_panels_wrapper` inexistente) e `init_swipe_status` (afilava scroll numa panel sem scroll) e seus functores/resize listeners.
- [x] **Bug: "Sair da sala" × controles de som/música** (z-index 60 sobre 50, mesmo canto): no mobile o botão fica à esquerda do ☰ (`right: safe-area + 64px`); no desktop foi empurrado para baixo da coluna de controles (`top: safe-area + 140px`).
- [x] **Bug: narrador × dicas em telas médias** (800-1200px): `.painel-dicas` era centralizado no rodapé e o `.narrador` (bottom-left) o cobria. Agora a dica ancora à direita no desktop (`left:auto; right:12px; transform:none`); o mobile (≤768px) mantém a dica no topo (Fase 31 P3).
- [x] **Bug: `font-weight-bold` morto no BS5** (`script.js`): cabeçalhos da lista de jogadores usavam classe BS4 — trocado por `fw-bold`.
- [x] **Bug: conferência transbordando no mobile** (`#cards_conferencia`): com 6 dados de 40px, 2 cards por linha estouravam; em ≤400px os cards viram 1 por linha (`flex: 0 0 100%`).
- [x] **10 chaves i18n novas** nos 5 dicionários (`ui.menu.*`, `ui.lobby.*`): `abrir`, `fechar`, `titulo`, `tutorial`, `dicas`, `narrador`, `idioma`, `som`, `musica`, `swipe`, `aba`, `seta_esq`, `seta_dir`, `dots`. `_montar_seletor_idioma` popula o seletor do drawer junto com o do topo.
- [x] **Bug: carrossel do lobby no mobile** (`jogo.html`, `custom_styles.css`, `script.js`): o trilho usava a utility Bootstrap `justify-content-center` (com `!important`), que anulava o `flex-start` do carrossel — o overflow era centralizado, empurrando o 1º card para fora da tela à esquerda (inalcançável) e deixando só 2 telas de 3. Removida a utility do `.lobby-linha` (o desktop não depende dela: `col-lg-5/4/3` somam 12). Além disso, as telas de Config/IA deixaram de ser escondidas para o não-master no mobile (`body.nao-master`): agora o carrossel tem sempre as 3 telas (Jogadores/Config/IA) para host e cliente, com os controles read-only no cliente (inputs já desabilitados por `aplicar_master`) — igual ao desktop. Slides consolidados numa regra `.lobby-linha .lobby-slide` (especificidade vence o Bootstrap sem `!important`).

Verificação: `node --check static/script.js`/`static/i18n.js` OK, `python verificar.py` 100% verde (cobertura i18n OK; integração das Fases 6/7/15 existente inalterada — nada de servidor). Teste manual em 2 abas no desktop (lobby grid, partida com contador no topo, dicas à direita, "Sair da sala" abaixo dos controles) e em um celular/emulação (devtools): ☰ abre/fecha o drawer; lobby rola por scroll-snap com dots/setas; partida vira app com `area_mesa` rolável e `rodape_acao` fixo; narrador no topo esquerdo durante a partida; conferência com cards 1 por linha em tela estreita; `user-scalable=no` bloqueia o zoom ao tocar nos dados.


# TODO — Dadinho (Fases 36–45)

Continuação do `todo.md` do projeto, a partir da auditoria externa de código/negócio/escalabilidade
Vercel/fraude/agentes/docs. Mesma convenção: `[ ]` pendente · `[x]` concluído · `[~]` em andamento.
Códigos de item seguem o padrão do repo (letra da categoria + número): **S** segurança,
**C** custo/escala Vercel, **O** observabilidade, **N** negócio/produto, **M** manutenção/agentes.

## Índice das fases propostas

- **Fase 36** — Correções rápidas: estático fora da função Python + comparação de segredo. Prioridade alta, esforço baixo. ✅ concluída
- **Fase 37** — CI: `verificar.py`/`simular_ia.py`/`node --check` em GitHub Actions. Prioridade alta, esforço baixo. ✅ concluída
- **Fase 38** — Migrar `vercel.json` de `builds`/`routes` para `functions`. Prioridade média, esforço médio. ✅ concluída (C2/C3; C4 = checagem manual do Fluid compute no dashboard)
- **Fase 39** — Rate limit de rede (Firewall Vercel + limite de tentativas por sala/IP). Prioridade média-alta, esforço médio. ✅ concluída
- **Fase 40** — Otimização pós-métricas (`ignore_queue`, detector CAS) — retomada do `docs/plano-cross-instance.md` Fase 26. Prioridade média, esforço baixo-médio. ✅ concluída
- **Fase 41** — Cliente Upstash com sessão HTTP reaproveitável. Prioridade média, esforço médio. ✅ concluída
- **Fase 42** — OG dinâmico por sala + analytics leve sem PII. Prioridade média (alto valor de negócio), esforço médio. ✅ concluída
- **Fase 43** — Observabilidade: error tracking + alerta de custo Vercel/Upstash. Prioridade média, esforço baixo-médio. ✅ concluída (O2/O3; O1 = error tracking adiado sem Sentry)
- **Fase 44** — CSP real (retomar a decisão adiada na Fase 31). Prioridade baixa-média, esforço alto. ✅ concluída (S5/S6/S7 em Report-Only; falta revisão manual no navegador antes de virar bloqueante)
- **Fase 45** — Modularização de `modelos.py` / `verificar.py` / `script.js`. Prioridade baixa, esforço alto. ✅ concluída (M4/M5 ✅; M6 avaliado: não adotar bundler)

---

## Fase 36 — Correções rápidas de custo e segurança

Objetivo: eliminar dois itens de baixo esforço e alto retorno encontrados na auditoria — estático
sendo cobrado/servido pela função Python e comparação de segredo não constant-time.

- [x] **C1 — Estáticos fora da função Python** (`vercel.json`, `app.py:32-42`). Hoje `/static/*`
  (2,6 MB de imagens + 384 KB de sons) passa pelo catch-all e é servido pelo Flask dentro da função
  serverless — o próprio comentário em `_cache_estaticos` já registra isso. Adicionar
  `{"handle": "filesystem"}` antes da rota catch-all em `vercel.json` para que arquivos existentes no
  build sejam servidos direto pela CDN/edge da Vercel, sem invocar a função Python. Validar que os
  headers de cache atuais (`Cache-Control: public, max-age=86400`) continuam corretos vindos do
  filesystem handler (senão manter um fallback de header via configuração de `headers` no
  `vercel.json`).
- [x] **S1 — `chave_secreta` com comparação constant-time** (`app.py:443`, dentro de `autenticar`):
  trocar `jogador.chave_secreta != extrair_chave(dados)` por
  `not hmac.compare_digest(jogador.chave_secreta, extrair_chave(dados))` (import `hmac` no topo de
  `app.py`). Fecha um canal de timing teórico contra o segredo de 16 bytes usado para autenticar
  toda jogada.

Verificação (local, `.venv`): `python verificar.py` deve continuar 100% verde (nenhuma mudança de
comportamento esperado); testar manualmente em 2 abas que `/static/...` ainda carrega (imagens,
sons, CSS, JS) após o deploy com `{"handle": "filesystem"}`; teste de integração novo cobrindo
`autenticar` com chave errada/correta (comportamento idêntico, só a forma de comparar muda).

---

## Fase 37 — CI (verificação automática em todo PR/push)

Objetivo: hoje `python verificar.py`/`simular_ia.py`/`node --check` só rodam se o dev lembrar de
rodar localmente — nada impede um push de ir direto para a branch principal sem passar pela própria
rede de segurança que o projeto já tem.

- [x] **M1 — Workflow de CI** (`.github/workflows/ci.yml`, novo arquivo): job único rodando em
  `push`/`pull_request` para a branch principal:
  1. Setup Python (versão de `.python-version`) + `pip install -r requirements.txt`.
  2. `python verificar.py` (falha o job se não sair 100% verde).
  3. `node --check static/script.js` e `node --check static/i18n.js`.
  4. `python simular_ia.py --partidas 20 --dados 3` (falha se travar ou quebrar a hierarquia
     4>3>2>1 dos bots).
- [x] **M2 — Badge de status** no `README.md` apontando para o workflow.
- [x] **M3 — Registrar no `AGENTS.md`** (seção Commands) que o CI roda os mesmos comandos do
  `verificar-deploy`, para os agentes saberem que existe uma segunda linha de verificação além do
  teste manual em 2 abas.

Verificação: abrir um PR de teste com uma quebra proposital (ex.: remover uma chave de um dos 5
dicionários de `i18n.js`) e confirmar que o CI falha antes do merge; reverter e confirmar que passa.

---

## Fase 38 — Migrar `vercel.json` de `builds`/`routes` para `functions`

Objetivo: `builds` é configuração legada e não pode ser combinada com `functions` — hoje isso
bloqueia configurar `maxDuration`, memória por função e `excludeFiles` no projeto. Não é urgente
(Hobby trava em 300s de qualquer forma), mas é dívida técnica que trava qualquer ajuste fino futuro
e a adoção plena do Fluid compute.

- [x] **C2 — Novo `vercel.json`** usando o formato moderno: remover `builds`/`routes`, configurar via
  `functions` + `rewrites` (entrypoint `api/index.py` — preserva o wrapper Socket.IO e o supressor de
  `ConnectionError`; estáticos servidos pelo filesystem antes dos rewrites, como o C1 pretendia):
  ```json
  {
    "functions": {
      "api/index.py": { "maxDuration": 300, "excludeFiles": "docs/**,Dadinho idéia.txt,todo.md,.opencode/**" }
    },
    "rewrites": [{ "source": "/(.*)", "destination": "/api/index" }]
  }
  ```
  `maxDuration` mantido em 300s (= atual default Hobby; o valor 60 do esboço cortaria a vida do
  WebSocket para 60s — regressão no tempo real da partida). Confirmar o path da chave conforme o
  entrypoint resolvido pela Vercel em preview antes de apontar para produção.
- [x] **C3 — `excludeFiles`** no bloco de `functions` para excluir do bundle da função tudo que não
  precisa rodar em runtime Python (`docs/`, `Dadinho idéia.txt`, `todo.md`, `.opencode/`),
  mantendo o bundle Python enxuto (limite de 500 MB, hoje longe disso, mas boa prática).
- [ ] **C4 — Confirmar Fluid compute ativo** nas configurações do projeto `dadinho` no dashboard da
  Vercel (projetos criados antes de abril/2025 podem não ter o padrão ligado automaticamente).
  **Passo manual** — checar no painel antes do próximo deploy.

Verificação: deploy em ambiente de preview primeiro (não direto em produção); validar boot
`VERCEL=1` respondendo 200 (`verificar.py` já cobre isso localmente, mas testar preview real);
teste manual em 2 abas, partida completa; só promover para produção depois de validado.

---

## Fase 39 — Rate limit de rede e proteção contra abuso de conexão

Objetivo: o cooldown atual (`funcoes_gerais.tem_cooldown`) é por `sid` — um script que abre conexões
WebSocket novas ignora completamente o limite, porque cada conexão ganha um `sid` novo. Isso é um
vetor barato de "denial of wallet" (spam de `criar_sala`/`connect` custando comandos no Upstash e
invocações de função), não só de indisponibilidade.

- [x] **S2 — Firewall/rate limit da Vercel na rota de upgrade WS**: regra criada e **publicada em
  produção** via `vercel firewall rules add/publish` — `rate-limit-socketio`: path prefix
  `/socket.io/`, 120 req/60s por IP (`--rate-limit-keys ip`, fixed_window), `deny` ao exceder.
  Filtra antes do handler Python (cobre spam de conexões/upgrade).
- [x] **S3 — Limite de tentativas de entrada por sala por IP**: coberto pela mesma regra do Firewall —
  cada tentativa de `connect` com `?sala=<código>` é um request no caminho `/socket.io/`; o teto de
  120 req/60s por IP torna o brute-force de códigos (33M combinações) inviável sem tocar no código
  (opção do esboço "via o mesmo Firewall da Vercel").
- [x] **S4 — Documentar no `AGENTS.md`** a decisão de onde cada camada de rate limit vive (Firewall
  Vercel vs. cooldown por `sid` em `funcoes_gerais.py`), para agentes futuros não removerem uma
  achando redundante.

Verificação: testar com um script simples abrindo N conexões WebSocket em sequência rápida e
confirmar que o Firewall bloqueia antes do handler `connect` ser executado; `verificar.py` não deve
regredir (o rate limit fica fora do código Python, na camada de plataforma).

---

## Fase 40 — Otimização pós-métricas (retomada da Fase 26 do `plano-cross-instance.md`)

Objetivo: a Fase 25 (message queue via `socketio.RedisManager`) já está em produção, mas a Fase 26
(otimização) ficou marcada como opcional/pendente. Com a fila ativa, todo `emit` — inclusive os de
destinatário único — publica no pub/sub à toa.

- [x] **C5 — `ignore_queue=True`** nos `emit(..., to=jogador.client_id)` (destinatário único):
  mapeados os `emit` individuais vs. de sala (docs/fluxo + código). Aplicado **só** onde o
  destinatário é provadamente o próprio sid do request (local à instância): respostas de handler
  em `app.py` (connect_start, retomar_negado, update_username, iniciar_negado, auditoria_partida,
  saiu_da_sala, partidas_listadas, sala_criada, update_user_list do heartbeat, jogar_dados_resultado,
  meus_dados) e todo o snapshot (`enviar_snapshot_sala` + `emitir_dispatcher_turno` — sempre o
  requester). Emits a OUTROS jogadores continuam na fila (`master_def`, `expulso_da_sala`,
  `meu_turno`/`espera_turno` de troca de vez, `construtor_dados` por jogador, room emits).
- [x] **C6 — Detector CAS como alerta** (não substitui o lock distribuído): campo **`revisao`** no
  `Lobby` (`versao` já é o schema da migração) incrementado a cada `store.salvar_sala`, com
  checagem de divergência logando `Fase 40 (CAS)` quando um save stale chega (lost-update em
  potencial) — visibilidade para calibrar o TTL do lock (`store.TRAVA_TTL`). É por instância
  (alerta intra-instância); cross-instance continua sob o lock. Teste `revisao-cas` no `verificar.py`.
- [x] **C7 — Revisar `docs/plano-cross-instance.md`** marcando a Fase 26 como implementada (via Fase
  40), mantendo o heartbeat como está (o socket ainda morre no `max-duration`, o re-sync continua
  necessário — não remover).

Verificação: `python verificar.py` verde com os testes de integração da Fase 25 intactos; validar em
produção (dashboard Upstash) que o número de comandos por partida cai após `ignore_queue` nos emits
individuais.

---

## Fase 41 — Cliente Upstash com sessão HTTP reaproveitável

Objetivo: `ArmazenamentoUpstash` (`store.py`) abre uma conexão nova via `urllib.request` a cada
`_pedido`/`_comando`/`_pipeline` (handshake TLS do zero toda vez). Cada evento mutável já encadeia
2-4 chamadas HTTP sequenciais (lock, leitura, gravação, unlock) — isso soma latência real por
jogada.

- [x] **C8 — Sessão HTTP com keep-alive**: trocado `urllib.request.urlopen` por um pool
  `http.client` (`_PoolHTTPS` em `store.py`) com keep-alive, protegido por trava (seguro no
  `async_mode='threading'`; uma conexão por thread por vez). Sem dependência nova (stdlib) —
  `requests.Session()` exigiria pinar 5 pacotes e é desencorajado para compartilhar entre threads.
  `_pedido`/`_comando`/`_pipeline` reescritos sobre `_enviar`; exceções continuam
  `OSError`/`http.client.HTTPException` (mesma política de aborto silencioso do `evento_mutavel`).
- [x] **C9 — Retry com backoff nas leituras/escritas simples** (fora do lock, que já tem seu próprio
  backoff): `_enviar` faz **1 retry rápido** (0.05s→0.1s) em timeout/reset/5xx antes de levantar;
  timeout/erro persistente aborta silenciosamente via `evento_mutavel` como hoje. Teste
  `upstash-transporte` no `verificar.py` (servidor HTTP fake local): keep-alive reutiliza a mesma
  conexão e 5xx é retentado até o sucesso.

Verificação: medir latência média por jogada (aposta → confirmação) antes/depois em produção;
`python verificar.py` cobrindo a camada Upstash contra o fake REST precisa continuar passando sem
mudança de comportamento externo (só a camada de transporte HTTP muda).

---

## Fase 42 — OG dinâmico por sala + analytics leve sem PII

Objetivo: o Open Graph atual (`templates/jogo.html`) é estático no HTML e só é sobrescrito por JS no
navegador — bots de preview (WhatsApp, Telegram, Discord, X) não executam JS, então todo link
compartilhado (inclusive `?sala=<id>`) mostra sempre a mesma prévia genérica. Sendo o
compartilhamento de sala o principal canal de aquisição de um jogo sem contas, isso é oportunidade
de negócio real, não só polimento técnico. Além disso, o projeto não tem nenhuma visibilidade de
funil (lobby → partida iniciada → concluída).

- [x] **N1 — OG dinâmico por sala**: `app.py` (`index()` + `_og_sala`) lê `request.args.get('sala')`,
  busca o resumo leve (`store.carregar_resumo` novo, GET pontual) e passa `titulo`/`descricao`/`url`
  para `render_template`; o Jinja preenche `<title>` e `og:`/`twitter:` ("Mesa do Zé — 2/6
  jogador(es). Sem cadastro, entre e jogue..."). Sala inexistente/padrão cai no genérico. O
  `og:image` permanece estático (gerar imagem por sala exigiria serviço de renderização). A
  localização por idioma segue como fallback client-side (`aplicar_meta_seo`). Teste
  `og-dinamico` no `verificar.py`.
- [x] **N2 — Analytics leve sem PII**: snippet do Vercel Web Analytics no `jogo.html` (stub
  `window.va` + `/ _vercel/insights/script.js`) e eventos de funil em `script.js` via
  `rastrear_funil()`: `sala_criada` (`sala_criada`), `partida_iniciada`/`partida_concluida`
  (`mudar_pagina` 1/4), `jogador_saiu_antes` (`saiu_da_sala`). Sem `client_id`/`chave_secreta`.
  **Passo manual:** habilitar Web Analytics no dashboard do projeto (o script é no-op sem isso).
- [x] **N3 — Link de retorno ao MemeTrigger** na tela de vitória/lobby, discreto — a vitória já tinha
  o tagline; adicionado no lobby (`tela_jogadores`) reusando a key `ui.subtitulo` (sem tradução
  nova).

Verificação: testar preview de link (`?sala=<id>`) nos debuggers oficiais de card social
(Facebook Sharing Debugger, Twitter Card Validator) antes/depois; `python verificar.py` cobrindo o
novo teste de `index()` com/sem `sala` válida; confirmar que analytics não registra nenhum dado
pessoal (nem `client_id`, nem `chave_secreta`, nem IP em texto claro no dashboard).

---

## Fase 43 — Observabilidade: error tracking + alerta de custo

Objetivo: hoje não existe error tracking, nem alerta de custo configurado no Vercel/Upstash — se
algo quebrar silenciosamente em produção, só se descobre se um jogador reclamar; e um pico de abuso
(Fase 39) só aparece numa fatura surpresa se ninguém estiver olhando o dashboard.

- [ ] **O1 — Error tracking**: **adiado por decisão do mantenedor (sem Sentry por enquanto)**.
  Opção avaliada: Sentry SDK Python opt-in por env `SENTRY_DSN` capturando os aborts silenciosos
  reais (rede/store/lock em `evento_mutavel`, blobs corrompidos no `store.py`) com
  `max_request_body_size="never"` + `before_send` redigindo Authorization/cookies (sem PII). Se
  retomado: adicionar `sentry-sdk` pinado e o init opt-in; reavaliar alternativa de logs estruturados.
- [x] **O2 — Alerta de custo/uso**: **Vercel** — regra `dadinho - anomalia de uso
  (invocacoes/duration)` (id `ar_01a0a21c-43cd-74fc-9f93-a67a7461f7f0`) criada via
  `vercel alerts rules add`: `usage_anomaly` em `function_invocations` e `fluid_duration`.
  **Upstash — pendente/manual**: console → database → Alerts (comandos ~400k/mês e banda ~8 GB do
  free tier); sem CLI para isso.
- [x] **O3 — Registrar em `docs/verificacao.md`** seção "Observabilidade e alertas (Fase 43)": onde
  o Sentry/DSN vive, o id da regra da Vercel e os limiares sugeridos do Upstash, para o próximo
  deploy/fase saber que existem.

Verificação: disparar um erro proposital em ambiente de preview e confirmar que aparece no error
tracker; confirmar recebimento do alerta de teste de custo (se a ferramenta permitir simular).

---

## Fase 44 — CSP real

Objetivo: retomar a decisão registrada como adiada na Fase 31 ("CSP avaliado e adiado" — ~21
handlers `onclick` inline impediam um CSP estrito sem `'unsafe-inline'`, de valor de segurança
baixo). Item de segurança em aberto, esforço alto porque exige refactor testável só por navegador
real (único meio de verificação do projeto para o frontend).

- [x] **S5 — Migrar handlers `onclick` inline para `addEventListener`**: os 22 `onclick=` do
  `templates/jogo.html` viraram `data-acao="<nome>"` (e `data-resultado` para o `fechar_alerta`),
  com um listener de delegação único em `static/script.js` (fim do arquivo) que roteia o clique
  pelo `data-acao` — ações são `function` globais (hoisted). Zero `onclick` inline restante.
- [x] **S6 — CSP sem `'unsafe-inline'` no `script-src`**: o único script inline executável era o
  stub do `window.va` (Fase 42) — removido (o `/ _vercel/insights/script.js` define o `va` ao
  carregar). Com `ld+json` (dado, não executa) e sem outros `<script>` inline, `script-src` dispensa
  nonce/hash. `style-src` mantém `'unsafe-inline'` **documentado**: o jogo usa `style=` inline e
  `element.style` em massa no JS (endurecer é refactor separado).
- [x] **S7 — CDN allowlist no CSP**: política em `app.py` (`CSP`) com `script-src` (self + socket.io
  + jsdelivr), `style-src` (self + unsafe-inline + jsdelivr + fonts.googleapis), `font-src`
  (fonts.gstatic), `img-src` (self + data:), `connect-src` (self + fonts.gstatic +
  va.vercel-scripts.com), `object-src 'none'`, `base-uri`, `frame-ancestors`. Servida em
  **Report-Only** por padrão (`Content-Security-Policy-Report-Only`); `DADINHO_CSP_MODO=bloqueante`
  aplica a política de verdade. Checagem do header no `og-dinamico`.

**Pendente (manual, navegador real):** rodar em 2 abas cobrindo todas as telas com o Report-Only,
revisar as violações reportadas e só então virar bloqueante (`DADINHO_CSP_MODO=bloqueante`) e
remover o "adiado" do registro da Fase 31.

---

## Fase 45 — Modularização de arquivos grandes

Objetivo: `modelos.py` (1672 linhas), `verificar.py` (2737 linhas) e `static/script.js` (~152 KB)
concentram lógica demais num único arquivo — mais contexto para carregar a cada mudança (humana ou
de agente), diffs maiores, revisão mais difícil. Esforço alto, mas mecânico; fazer incrementalmente
com `verificar.py` como rede de segurança a cada passo.

- [x] **M4 — Splitar `modelos.py`**: virou o pacote `modelos/` por entidade — `comum.py`
  (`sala_room` + `somente_ias_na_partida`), `migracao.py` (VERSAO_ATUAL/VAGAS_RECENTES_SEGUNDOS/
  MIGRACOES), `jogador.py`, `turno.py`, `rodada.py`, `partida.py`, `lobby.py`, com `__init__.py`
  re-exportando tudo (`from modelos import ...` intacto). Grafo de dependências **acíclico**
  (só `lobby` instancia as demais; `partida`/`rodada`/`turno` usam `self.da_*`). O `emit` do
  Socket.IO agora tem binding próprio por submódulo: `simular_ia` e os testes de `verificar.py`
  que neutralizavam `modelos.emit` passaram a patchear a lista de módulos (`_salvar_emit`/
  `_silenciar_emit`/`_restaurar_emit`). `modelos/` adicionado ao `py_compile` do `verificar.py`.
- [x] **M5 — Splitar `verificar.py`**: runner + estáticas + round-trip ficam em `verificar.py`
  (~260 linhas); a infraestrutura (globals/helpers/constantes) foi para `tests/base.py`; os ~70
  testes de integração para `tests/test_integracao.py`. Tudo importado LAZY (o runner chama
  `_preparar_integracao()` antes de importar os testes, que fazem `from tests.base import *` —
  mesmo módulo, sem o problema de `__main__` vs. nome). `python verificar.py` continua o único
  comando. Split feito por script AST (movimentação mecânica, sem transcrição manual).
- [x] **M6 — Avaliar bundler leve para `static/script.js`**: **avaliado e NÃO adotado**. `script.js`
  tem ~154 KB / 3994 linhas (carregado uma vez, cacheado) — não é problema de performance nem de
  manutenção real. O projeto **não tem tooling JS** (sem `package.json`/`node_modules`) e o deploy é
  Python puro (`@vercel/python`/functions, `vercel.json` sem build step): adotar esbuild exigiria
  injetar npm/build no deploy + CI, ou commitar bundle gerado (fonte-da-verdade quebrada). O ganho
  (arquivos menores por tela) não paga o custo de pipeline para um jogo casual. **Decisão: manter
  `script.js` único.** Se um dia o arquivo virar problema real, esbuild é a ferramenta certa
  (concatenação preserva hoisting/ordem — split por múltiplas `<script>` tags sem bundler quebraria
  hoisting entre arquivos) — reavaliar só então.

Verificação: cada split é um commit isolado e reversível; `python verificar.py` 100% verde após cada
um (imports/paths atualizados); `node --check` no bundle final gerado, se M6 for adotado; teste
manual em 2 abas ao final de cada sub-etapa.

---

## Fases 50–54 — Bugs, Segurança e Arquitetura

Continuação do `todo.md` do projeto. Fases focadas em corrigir vulnerabilidades de segurança, melhorar a performance no ambiente serverless (Vercel/Upstash), garantir consistência de estado (CAS) e refatorar o monólito do frontend.

Legenda: `[ ]` pendente · `[x]` concluído · `[~]` em andamento.

## Índice das fases propostas

- **Fase 50** — Segurança: Timing Attacks e Validação de Payloads. Prioridade crítica, esforço baixo. ✅ concluída
- **Fase 51** — Performance: Cache de Leitura no Store e Tratamento de Erros. Prioridade alta, esforço médio. ✅ concluída
- **Fase 52** — Concorrência: Tratamento de Lost-Updates (CAS) e Serialização. Prioridade alta, esforço médio. ✅ concluída
- **Fase 53** — Frontend: Namespacing e Robustez do Heartbeat. Prioridade média, esforço alto. ✅ concluída
- **Fase 54** — Testes: Integração Cross-Instance. Prioridade baixa, esforço médio. ✅ concluída

---

## Fase 50 — Segurança: Timing Attacks e Validação de Payloads ✅ concluída

Objetivo: Eliminar vulnerabilidades de comparação de strings e garantir que payloads malformados nunca causem exceções não tratadas (crash do worker serverless).

- [x] **Auditoria de Comparações (`app.py` e handlers)** — Toda comparação de `chave_secreta`/`chave` agora usa `hmac.compare_digest()`. `autenticar` (`app.py:463`) já comparava constant-time (Fase 36 S1); faltavam dois pontos com `==`/`!=`: `sair_da_sala` (`app.py:1104`) — recusa sair do lobby com chave errada via `not hmac.compare_digest(...)` — e `Lobby.buscar_jogador_pela_chave` (`modelos/lobby.py:813/816`) — retomada de identidade agora varre com `compare_digest` (guard `isinstance(str)` + skip de chave vazia, comportamento idêntico).
- [x] **Validação Defensiva de Payloads** — Todos os handlers de Socket.IO abortam silenciosamente com payload não-dict. O padrão `dados = dados if isinstance(dados, dict) else {}` já está centralizado no decorator `autenticar` (coerce para `{}`) e nos handlers sem chave (`retomar_identidade`, `heartbeat`); único vão fechado: `listar_partidas` usava `dados = dados or {}` (string/array truthy vazava `.get` → AttributeError) — trocado pelo mesmo guard.
- [x] **Sanitização de Inputs de Texto** — Já coberta (auditado, sem mudança): apelidos passam por `validar_input` (regex + `1..12` chars, `app.py:880-881`/`funcoes_gerais.py:494`) e o nome da sala é truncado em 30 chars (`definir_config`, `modelos/lobby.py:414`) — nada de texto entra cru no `Lobby`.

Verificação: `python verificar.py` 100% verde (inclui `S1`/`V3` e a integração de `sair_da_sala` com chave errada — Fase 30; comportamento idêntico, só o mecanismo de comparação muda). Teste manual: `socket.emit('apelido', "string_em_vez_de_dict")`/`listar_partidas` com payload inválido não gera traceback no console do servidor.

---

## Fase 51 — Performance: Cache de Leitura no Store e Tratamento de Erros ✅ concluída

Objetivo: Reduzir a latência das chamadas síncronas à API REST do Upstash, que é o maior gargalo no ambiente serverless da Vercel.

- [x] **Cache de Leitura de Curta Duração (`store.py`)** — **já existia** (Fase C, `carregar_sala_leve` + `_cache_salas`): o heartbeat lê do cache tolerante a defasagem (TTL 25s), atualizado a cada `salvar_sala` e descartado em `remover_sala`/aborto — é exatamente o caminho de re-leituras em sequência que o item aponta. **Não** estendeu-se o cache ao `carregar_sala` geral (TTL 0): handlers que mutam leem SEMPRE frescos do store (comentário em `store.py` já registra a decisão) — uma defasagem de 2-5s numa leitura de handler reverteria escrita de outra instância mesmo sob o lock distribuído (regressão de consistência; o aborto CAS é a Fase 52). Hardening novo: **teto do cache** (`CACHE_SALA_MAX` 4096, evicção da entrada mais antiga) para o processo persistente da VPS não acumular salas distintas por dias.
- [x] **Tratamento de Erros de Rede (`store.py`)** — novo `_ERROS_DE_REDE` (`OSError`, `http.client.HTTPException`, `RedisError`, `TimeoutError`) + `_leitura_segura(funcao, fallback)`: **leituras** do store que falham (Upstash fora/REST, Redis TCP da VPS) devolvem `None`/`[]` com `log.warning` em vez de estourar o worker. Aplicado aos helpers públicos `carregar_sala`, `carregar_resumo`, `listar_resumos`, `listar_lobbys`, `sala_do_sid` e ao miss de `carregar_sala_leve` — a rota do OG (`_og_sala`) não 500 mais num blip, e handlers abortam no guard `lobby is None`. **Escritas continuam levantando** (a política de aborto silencioso de `evento_mutavel` segue valendo). `app.py`: `handle_connect`/`handle_disconnect` passaram a capturar também `OSError`/`http.client.HTTPException` (blip de rede no INCR/gravação do connect/disconnect abortava só `RedisError`/`TravaIndisponivel` antes).
- [x] **Otimização do Pool HTTP** — **já implementada e testada** (Fase 41 C8/C9): `_PoolHTTPS` com keep-alive (uma conexão por thread por vez, `_enviar` com 1 retry rápido). O teste `upstash-transporte` (servidor HTTP fake local) comprova a reutilização da MESMA conexão entre chamadas e o retry de 5xx.

Verificação: `python verificar.py` 100% verde — novo teste `leitura-segura-rede` (Fase 51): com `ArmazenamentoUpstash` apontando para porta morta, `carregar_sala`/`carregar_resumo`/`sala_do_sid` devolvem `None` e `listar_resumos`/`listar_lobbys` devolvem `[]` (sem exceção). Regressão zero nas Fases 6/7/15-30/40-46. Em produção: medir latência média por jogada antes/depois; o número de GETs por rodada já é o mesmo (o cache de leitura do heartbeat já evitava os GETs repetidos).

---

## Fase 52 — Concorrência: Tratamento de Lost-Updates (CAS) e Serialização ✅ concluída

Objetivo: Garantir que o ambiente serverless (múltiplas instâncias processando eventos simultaneamente) não corrompa o estado do jogo.

- [x] **Abortar em Caso de Lost-Update (`store.py` / `salvar_sala`)** — o detector de revisão (Fase 40) passou de ALERTA para ABORTO: `store.salvar_sala` agora levanta `ConflitoDeEstado` quando um lobby stale chega para persistir (revisão menor que a última salva na instância), em vez de logar e sobrescrever (corrupção silenciosa). `evento_mutavel` (que já invalida o cache no aborto) e `handle_connect`/`handle_disconnect` capturam `ConflitoDeEstado` e abortam silenciosamente. O rastreador é por instância (como documentado na Fase 40) — a defesa cross-instance continua sendo o lock distribuído; este aborto fecha a janela intra-instância que o lock teria deixado passar. Notificação `erro_concorrencia` ao cliente **não** foi adicionada (decisão registrada): a condição é inalcançável com os locks em ordem (todos os mutadores usam o lock — ver item 3), o heartbeat já re-sincroniza o cliente após um aborto e um evento de frontend novo seria código morto só verificável manualmente em navegador.
- [x] **Limpeza de Histórico (Poda)** — `resetar_para_lobby` já poda `lobby.partidas` para a última (teste `poda-partidas` existente). Novo teste `json-tamanho-100-rodadas`: roda 100 rodadas REAIS (`construir_rodada`, com turnos típicos) e verifica que o blob serializado do Lobby fica bem abaixo de 500KB e que o round-trip preserva o histórico.
- [x] **Locks Distribuídos (auditoria)** — auditado: todos os handlers que MUTAM passam por `evento_mutavel` (lock local + `trancar_sala_distribuida`) ou adquirem explicitamente (connect/disconnect). `heartbeat` MUTA (`marcar_visto`, `ia.processar`, `salvar_resumo`) — mantém o lock corretamente. Único ajuste: `solicitar_auditoria` era somente-leitura com `evento_mutavel` (adquiria o lock à toa) — virou `evento_leitura` (só cooldown, como `listar_partidas`/`criar_sala`).

Verificação: `python verificar.py` 100% verde — teste `revisao-cas` atualizado (save stale agora levanta `ConflitoDeEstado`, não sobrescreve, revisão não é bumpada) e `json-tamanho-100-rodadas` novo. `python simular_ia.py --partidas 20 --dados 3` hierarquia 4>3>2>1 preservada (o simulador recria o Lobby `'sim'` por partida no mesmo processo — `store.remover_sala('sim')` zera o rastreador de revisão entre partidas, como numa sala real criada do zero).

---

## Fase 53 — Frontend: Namespacing e Robustez do Heartbeat ✅ concluída

Objetivo: Tornar o `static/script.js` (3994 linhas) mais manutenível e corrigir bugs sutis de estado e conectividade.

- [x] **Namespacing (IIFE)** — `script.js` inteiro roda dentro de um IIFE (`(function () { ... })()`): as dezenas de globals (`indiceAtual`, `chave_secreta`, `sala_atual`, `sou_master`, `contexto_min_aposta`, `eh_espectador`, `vez_atual_nome`, ...) deixaram de vazar para `window`. O `data-acao` depende de funções globais por nome (a delegação usava `window[acao]`), então as 17 ações existentes são expostas num único global `window.Dadinho` e a delegação passou a resolver `window.Dadinho[acao]` — `fechar_alerta` mantém o caso especial com `data-resultado`. Sem `"use strict"` (arquivo clássico/sloppy; strict poderia quebrar comportamento). Decisão de manutenção registrada no código: novo `data-acao` em `jogo.html` exige exportar a função no `window.Dadinho` do fim do arquivo. Verificado que nenhuma referência externa aos globals existia (HTML sem `onclick`/`onload` inline, i18n.js autocontido, nenhum script inline chamando funções do jogo).
- [x] **Correção do Heartbeat Recursivo** — `agendar_heartbeat()` ganhou um timer único guardado (`_timer_heartbeat`): chamadas duplicadas não criam timers paralelos (spam), o callback está em `try/catch` (uma exceção no `socket.emit`/acesso a estado não mata a batida nem impede o re-agendamento) e o re-agendamento é garantido no `finally` do fluxo (a variável é zerada antes de emitir, então o loop continua sempre com um único timer pendente).
- [x] **Fila de Eventos** — a fila serial agora limita o ATRASO acumulado (`MAX_ATRASO_FILA` 4000ms): quando já há 4s de pausa pendente (ex.: 4 bots jogando em sequência), os próximos eventos entram com atraso 0 — a ORDEM é preservada e **nenhum evento é descartado**; só as pausas de "pensamento" extras são puladas, evitando o lag acumulado na UI. O contador é debitado a cada evento processado.

Verificação: `node --check static/script.js` e `static/i18n.js` OK + `python verificar.py` 100% verde (cobertura i18n intocada — nenhuma chave trocada). Teste manual em navegador (único meio de verificação do frontend): 5 abas, `window` no console deve ter só `Dadinho` (e `io`/`t`/... externos), clicar nas ações do `data-acao` (menu, config, IA, alertas, tutorial, dicas) e jogar partida completa; deixar 1h aberto e confirmar heartbeat batendo sem multiplicar (uma batida por intervalo por aba, visível no painel do servidor/Upstash).

---

## Fase 54 — Testes: Integração Cross-Instance ✅ concluída

Objetivo: Validar que a arquitetura serverless (Vercel + Upstash + Redis) funciona corretamente sob condições reais de concorrência.

- [x] **Simulador de Múltiplas Instâncias** — novo `tests/test_cross_instance.py` (standalone `python tests/test_cross_instance.py` e rodado no fim do `verificar.py`). Duas "instâncias" são simuladas por threads disputando a MESMA sala contra um store compartilhado: `store.armazenamento` é trocado por um `ArmazenamentoUpstash` cujos `_comando`/`_pedido`/`_pipeline` apontam para um `_FakeRedis` em memória (sufixo completo: get/set/del/incr/scan/sadd/smembers/srem/mget + pipeline + **SET NX/EX e DELEX IFEQ do lock distribuído**, com URL-decode das chaves). Assim o lock distribuído fica ATIVO (não é no-op como no modo memória), cada handler deserializa um Lobby NOVO do blob (como entre instâncias reais) e o aborto CAS da Fase 52 vigora. O lock de processo também serializa (teste mais estrito, nunca menos).
- [x] **Cenários de Teste** — os 4 cenários do plano, com o final validado lendo o Lobby direto do store compartilhado:
  1. Dois jogadores `ficar_pronto` simultâneos (barreira de threads) → AMBOS aplicados, revisão avançou.
  2. Dois jogadores `apostar` no mesmo turno (o da vez aposta válido; o outro aposta inválido em paralelo) → exatamente **1 turno** criado, do jogador da vez, ninguém perde dado.
  3. Desconexão de um humano no meio da partida com IA jogando → fica na graça, o jogo segue, reconexão por chave (`retomar_identidade`) limpa a graça e restaura a identidade no meio da partida.
  4. Heartbeat batendo enquanto a sala é modificada (apelidos em paralelo) → estado final consistente (apelido aplicado, jogadores intactos).
- [x] **Validação de Estado Final** — cada cenário carrega `store.carregar_sala` do fake (fonte da verdade) e verifica integridade: jogadores, prontidão, turnos, `dados_qtd`, janela de graça, revisão monotônica.

Verificação: `python tests/test_cross_instance.py` passa sem erros de concorrência/timeouts (o fake local é determinístico); `python verificar.py` 100% verde incluindo os 4 novos `[OK]` cross-instance. O que não é coberto (registrado): a fila de mensagens (`DADINHO_MESSAGE_QUEUE`) entre duas instâncias REAIS continua validada em produção com 2 navegadores, conforme `docs/plano-cross-instance.md` — o lock distribuído e o re-sync do heartbeat são exatamente o que este teste cobre localmente.


# TODO — Segurança, Performance, Escalabilidade e Qualidade (Fases 59–62)

Continuação do `todo.md`. Fases focadas em **endurecer a VPS para produção real**, **bloquear abusos automatizados**, **otimizar performance do runtime** e **preparar a infraestrutura para escala horizontal**.

Legenda: `[ ]` pendente · `[x]` concluído · `[~]` em andamento.

## Índice das fases propostas

- **Fase 59** — Segurança na VPS: rate limit, anti-fraude técnica e hardening. Prioridade crítica, esforço médio.
- **Fase 60** — Performance e Otimizações Técnicas. Prioridade alta, esforço médio.
- **Fase 61** — Escalabilidade Real: reverse proxy, múltiplos workers e Redis HA. Prioridade média, esforço alto.
- **Fase 62** — Documentação e Agentes: runbooks, skills e ADRs. Prioridade baixa, esforço médio.

---

## Fase 59 — Segurança na VPS: rate limit, anti-fraude e hardening

Objetivo: a Fase 39 protege a Vercel, mas o Cloudflare Tunnel da Fase 46 expõe a VPS diretamente. Um atacante que descobra `dadinho-api.memetrigger.com` pode spammar a API sem passar pelo firewall da Vercel. Além disso, scripts automatizados podem explorar o motor de IA para obter vantagem injusta.

- [x] **Nginx como reverse proxy na VPS** — Substituir o `EXPOSE 8000` direto do gunicorn por nginx escutando na porta 80/443 (loopback), com:
  - Rate limit por IP (`limit_req_zone`): 60 req/s por IP no `/socket.io/`, 10 req/s no resto.
  - Body size limit: 100KB (alinhado com `max_http_buffer_size` do Flask-SocketIO).
  - Timeout de idle: 60s para WebSocket (evita conexões zumbis).
  - Logs estruturados em JSON para auditoria.
- [x] **CORS restritivo em produção** — `DADINHO_CORS_ORIGINS` nunca deve ser `*` em produção. Validação no `app.py`: se `VERCEL_ENV=production` ou `DADINHO_ENV=production` e CORS for `*`, log de WARNING e fallback para as origens fixas do frontend (`dadinho.memetrigger.com` + alias `dadinho-hazel.vercel.app`). O compose da VPS seta `DADINHO_ENV=production`.
- [x] **Detecção de múltiplas contas por IP** — Novo índice no Redis (`dadinho:ip:<ip>` → SET de `client_id`s ativos, TTL 6h). Handler `connect` limita os sockets simultâneos por IP **opt-in** (`DADINHO_LIMITE_SOCKETS_IP`, default `0` = desligado; ativar em picos com folga para NAT/CGNAT). Excesso retorna `connect_error` com motivo `muitas_contas`. IP vindo de `Cf-Connecting-Ip`/`X-Forwarded-For` validado como IP antes de virar chave.
- [x] **Anti-automação (Captcha opcional)** — Adicionar `DADINHO_CAPTCHA_ATIVO` (default: false). Quando ativo, o handler `connect` exige `captcha_token` validado via `https://challenges.cloudflare.com/turnstile/v0/siteverify` (Cloudflare Turnstile, invisível). Separação frontend/VPS: `CAPTCHA_WIDGET` exige só a sitekey (`DADINHO_TURNSTILE_SITEKEY`, renderiza o widget — usado na Vercel) e `CAPTCHA_ATIVO` exige sitekey + `TURNSTILE_SECRET` (valida o token — só na API da VPS); faltando algo não derruba connects, só avisa no log. Só ativado em picos de abuso (rate limit da Fase 39 estourado). Front-end carrega o widget sob demanda.
- [x] **Detecção de bots por padrão de jogo** — Novo módulo `anti_fraude.py` com análise de padrões:
  - `tempo_entre_acoes`: humano raramente joga em <200ms consistentemente.
  - `acuracia_binomial`: humano erra cálculos; bots acertam 100% das apostas matematicamente ótimas.
  - `padrao_horario`: atividade 24/7 sem pausas é suspeito.
  - Flag `suspeito` no `Jogador` que, se ativado, força delay adicional nas ações.
- [x] **Logs estruturados de eventos suspeitos** — Novo módulo `observabilidade.py` com funções `log_evento_suspeito(tipo, client_id, ip, dados)`: tipos como `aposta_rapida_demais` (<200ms entre apostas), `desconfianca_em_rajada` (3+ desconfianças em 5s), `multiplas_contas` (detecção do item 3). Logs vão para stdout em JSON.
- [x] **Sanitização de logs** — Garantir que `chave_secreta`, `nonce_seed`, `dados` do jogador NUNCA apareçam nos logs. Auditar `app.py` com grep por `log`/`print` e substituir por `observabilidade.log_redigido`.
- [ ] **Cloudflare WAF rules específicas** — No painel Zero Trust, criar regras para o tunnel `dadinho-api`:
  - Bloquear user-agents de bot conhecidos (Python-urllib, curl, wget sem headers custom).
  - Rate limit por ASN (bloquear data centers suspeitos).
  - Challenge automático quando rate limit é estourado.

Verificação:
- Script de teste `tests/test_anti_fraude.py`: abre 10 sockets do mesmo IP, confirma que só 3 conectam.
- Teste manual: `ab -n 1000 -c 50 http://localhost/socket.io/` deve ser limitado pelo nginx (503 após exceder).
- Log de auditoria: `docker logs dadinho-api` deve mostrar eventos estruturados sem PII.

---

## Fase 60 — Performance e Otimizações Técnicas

Objetivo: reduzir latência percebida pelos jogadores, eliminar gargalos conhecidos no runtime e otimizar o uso de recursos (CPU do GIL, I/O do Redis, memória do processo). Esta fase não adiciona features, apenas torna o motor do jogo mais rápido e eficiente sob carga.

- [x] **Heartbeat com path de leitura rápido** — O handler `heartbeat` (`app.py`) hoje adquire o lock distribuído (`trancar_sala_distribuida`) mesmo quando é 95% leitura (renova `visto_em`, envia snapshot). Refatorado com `@evento_mutavel(lock_distribuido=False)`:
  - Sala de espera: re-sync SEMPRE fresco do store (Fase E2 preservada), mas SEM lock distribuído — `ia.processar` é inerte na página 0 e o re-sync é leitura pura (sem risco de lost-update).
  - Partida quieta servida do cache (`carregar_sala_leve` + página/vez corretas): só renova o resumo, sem lock.
  - Só adquire o lock quando há mutação possível: leitura fresca (cache estourou) OU divergência de página/vez, em sala **em partida** — e então RE-lê fresco DENTRO do lock antes de `ia.processar` (evita mover o turno com estado pré-lock). Se a leitura fresca da espera revelar que a partida começou, escala para o caminho lockado.
  - Esperado: redução de 70%+ nas aquisições de lock em salas ociosas (coberto por `tests/test_performance.py` — `heartbeat-fast-path`).
- [x] **Cache agressivo de `carregar_resumo`** — Adicionado cache em processo por 5s (`CACHE_RESUMO_TTL`, max `CACHE_RESUMO_MAX`=2048, guarda com `threading.Lock`) em `store.py` (`_cache_resumos`), populado em `salvar_resumo`/`salvar_sala_com_resumo` e invalidado em `remover_resumo`. `None` NUNCA é cacheado (resumo recém-nascido não pode ficar invisível por 5s). Evita GET repetido no Redis para a mesma sala em rajadas de listagem/OG.
- [x] **Migrar cálculo probabilístico da IA para LRU** — Aplicado `functools.lru_cache(maxsize=1024)` na função pura `probabilidade_verdade(face, quantidade, suporte, desconhecidos, coringa)` (`ia.py`). **Decisão:** cache na função pura e NÃO em `_probabilidade_aposta` (receberia `Jogador`/`Rodada` vivos → retenção de memória). Args numéricos hasháveis = seguro.
- [x] **Batch de operações no Redis** — Novo `store.salvar_sala_com_resumo(lobby, resumo)` público (CAS/revisão da `salvar_sala` + dedup de assinatura da `salvar_resumo`) nas 3 classes: Memória (trivial), Upstash (pipeline SET sala + SET resumo + SADD índice num request) e Redis TCP (`self._redis.pipeline()`). `atualizar_lista_usuarios` (`funcoes_gerais.py`) e o heartbeat passaram a usar — antes eram 2-3 commands em sequência.
- [x] **Lazy import do `redis` no `ArmazenamentoRedis`** — Removido o `try: import redis` do topo do `store.py`; a tupla de erros de rede virou `store.erros_de_rede()`, função LAZY que importa o pacote só quando ele é preciso (e guarda a classe em `_REDIS_ERRO_LAZY`). O verdadeiro cliente TCP continua só no `ArmazenamentoRedis.__init__`. **Nota honesta:** o flask_socketio→`socketio.redis_manager` já carrega o pacote `redis` no boot mesmo em modo Memória/Upstash, então o ganho de cold start é parcial (store standalone e Vercel sem socketio no caminho); o ganho real é o store nunca INSTANCIAR o cliente TCP na Vercel. Coberto em `tests/test_performance.py`.
- [ ] **Pool de threads dedicado para `ia.processar`** — **NÃO implementado (decisão de arquitetura).** Viola a invariante do AGENTS.md "Sem threads/timers no servidor (`ia.processar` roda dentro do request)": em serverless a thread de fundo é morta junto com a resposta (Vercel), e a fila por sala reintroduziria estado em memória entre requests. O caminho serverless-safe continua sendo rodar a IA dentro do handler que mutou o estado — os caches (LRU + resumo + save combinado) reduzem o custo de cada processamento sem quebrar essa invariante.
- [x] **Compressão de blobs no Redis** — Adicionada no `ArmazenamentoRedis` (VPS/Vercel TCP) apenas: `_comprimir`/`_descomprimir` com `zlib` nível 6 → `base64` (cliente com `decode_responses=True`), marcador `gz1:`, limiar de 512 bytes (blobs pequenos e os que não encolhem seguem crus). Compat retroativa: blob antigo sem o marcador carrega direto. Aplicado a `salvar_sala`, `carregar_sala` e `salvar_sala_com_resumo`.

Revisão (revisor-dadinho, pós-implementação):
- **P1 (corrigido):** `ArmazenamentoRedis.listar_lobbys` lia o blob cru com `json.loads` → sala salva comprimida (>512 B, i.e. praticamente qualquer sala com >1 jogador) era silenciosamente pulada, quebrando o fallback `buscar_lobby_pelo_client_id` após restart/expiração do índice. Agora passa por `_descomprimir` (igual ao `carregar_sala`) + teste `lista-lobbys-comprime`.
- **P2 (corrigido):** assinatura do resumo e watermark de revisão do CAS eram gravados ANTES da escrita; numa escrita abortada, o conteúdo nunca-gravado ficava marcado como salvo (dedup ignoraria o save seguinte) e a revisão presa abortava todos os saves seguintes como `ConflitoDeEstado` até `remover_sala` (sala presa). `invalidar_cache_sala` agora também limpa `_cache_resumos`, `_resumos_assinatura` e `_revisoes_salvas` — e passou a ser chamado no `except` de `evento_mutavel`, `handle_connect` e `handle_disconnect` + teste `invalida-estado-aborto`.
- **P3 (corrigido junto do P2):** `invalidar_cache_sala` só limpava `_cache_salas`; a mutação revertida podia servir resumo velho ao OG por até 5s.

Verificação:
- Teste de benchmark `tests/test_performance.py` (Fase 60): assertões DETERMINÍSTICAS (o CI não pode depender de timing) — LRU da IA (2ª chamada idêntica = cache hit), cache de resumo (miss→fill→hit→TTL→invalidate), dedup do save combinado, compressão+compat retroativa (fast fake do Redis), `listar_lobbys` com blob comprimido (P1), invalidação de estado pós-aborto (P2/P3) e o fast path do heartbeat (contagem de aquisições do lock distribuído: 0 na espera e na partida quieta, 1 na divergência).
- `verificar.py` verde (34s) com a suite completa + `simular_ia.py --partidas 20 --dados 3` ok (distribuição normal de vitórias).
- Lazy import: coberto por assert funcional no subprocess (store Memória nunca instancia o cliente TCP; `_REDIS_ERRO_LAZY` fica `None` até o 1º uso).

---

## Fase 61 — Escalabilidade Real: múltiplos workers cooperativos + Redis HA (adiado)

Objetivo: escalar o backend da VPS além de 1 processo gunicorn threaded. Hoje a
VPS roda **1 worker × 100 threads** (`Dockerfile`, pré-Fase 61): ~50 jogadores
simultâneos. Com 4 réplicas gevent + sticky por IP no nginx + message queue,
dá para crescer para 100+ jogadores sem perder estado de Socket.IO.

Decisões tomadas (com o mantenedor, 2026-09-16):

- **Motor:** **gevent** e não eventlet. O eventlet 0.41.2 carrega aviso oficial
  dos mantenedores no PyPI ("usages in new projects are discouraged... plan the
  retirement of eventlet"); o gevent é mantido ativamente e é suportado do
  mesmo jeito por Flask-SocketIO/gunicorn/python-socketio.
- **Topologia:** **4 containers × 1 worker gevent** (e não `-w 4` num único
  container). A session Engine.IO vive na memória do worker e o gunicorn não faz
  sticky session — com `-w 4` num processo, o long-polling/upgrade cairia em
  worker errado ("Invalid session", loop de reconexão). Com réplicas separadas,
  o nginx faz o sticky.
- **Redis HA:** **postergado** — ver item 2.

- [x] **Migrar o gunicorn para gevent e escalar por réplicas (sticky no nginx)**:
  - `requirements.txt` + pins: `gevent==26.9.0`, `gevent-websocket==0.10.1`
    (WebSocket do driver gevent do python-engineio), `greenlet==3.5.6`,
    `zope.event==6.2`, `zope.interface==8.6`.
  - `Dockerfile`: `gunicorn --worker-class gevent -w 1` (1 processo por container;
    a escala é por réplicas, não por workers internos).
  - `app.py`: guard de `monkey.patch_all()` no TOPO (antes dos imports de
    socket/ssl/threading do Flask/redis/socketio), opt-in por env — o worker
    gevent do gunicorn já aplica o patch antes de importar o app; o guard cobre o
    dev local (`python app.py` com `DADINHO_ASYNC_MODE=gevent`) e é idempotente
    (`is_module_patched`). Também preserva o caminho eventlet (só se pedir).
  - `docker-compose.yml`: serviço `api` vira **4 réplicas** (`api`/`api2`/`api3`/
    `api4`, anchor YAML `x-api-base`), todas usando a MESMA image `dadinho-api`
    (build só no `api`; as outras não rebuilam), `DADINHO_ASYNC_MODE=gevent` no
    ambiente, portas loopback 8000-8003 (smoke), healthcheck por réplica.
  - `nginx/nginx.conf`: upstream com as 4 réplicas e **`hash $ip_real consistent;`**
    — sticky por IP REAL (Cf-Connecting-Ip, estável — o `sid` muda a cada
    reconexão; por IP o handshake+upgrade+pols do mesmo cliente caem na mesma
    réplica). `keepalive 32` no upstream. Emits entre réplicas seguem pela
    message queue (`DADINHO_MESSAGE_QUEUE` → `GerenciadorRedisSeguro`, Fase 25).
  - `atualizar_vps.ps1`: rebuild `api api2 api3 api4 nginx` (um build sobe as 4).
  - **Trade-off anotado:** com gevent, `ia.processar` (CPU-bound, puro Python)
    roda dentro do handler — não preempta outros greenlets DA MESMA réplica
    enquanto calcula (mesmo GIL limitaria threads nativas). As 4 réplicas
    distribuem e o LRU da IA (Fase 60) barateou cada cálculo. Ok para casual.
- [x] **Redis HA: documentar SPOF e adiar implementação** — O Redis local
  (`redis:7-alpine` + AOF) é o único ponto de falha da VPS: AOF cobre restart do
  container, não disaster (reset zera salas ativas/dados em andamento). Aceitável
  num jogo casual cujo estado é por partida e se regenera (TTL limpa órfãos). O
  caminho de upgrade fica aberto sem mudança de código: `store.ArmazenamentoRedis`
  já é agnóstico à URL (`DADINHO_REDIS_URL`) — apontar para um Redis gerenciado
  com HA ou subir Sentinel/replica quando necessário. Registrado em
  `docs/verificacao.md` (passo 1 da VPS).

Verificação:
- `verificar.py` novo bloco **3c**: boot em subprocesso com `DADINHO_ASYNC_MODE=gevent`
  (import do `app` + `socketio.async_mode == 'gevent'`) — valida que o motor
  cooperativo importa limpo sem afetar o resto da suite (que segue em threading).
- Nginx: `docker run --rm ... nginx -t` com os hostnames das réplicas → **config ok**.
  **Achado corrigido:** o `nginx/nginx.conf` do repo (untracked, criado na Fase 59)
  não tinha `events {}`/`http {}` — config de borda inválido como arquivo principal
  do nginx (falharia no boot; a VPS provavelmente roda cópia divergente editada à
  mão). Reescrito completo e válido; o próximo `atualizar_vps.ps1` sobrescreve o do
  `/opt/dadinho` com a versão correta (já com as 4 réplicas + sticky).
- Compose: `docker compose config --quiet` → **ok** (interpola `api`/`api2`/`api3`/
  `api4`/`redis`/`nginx`/`tunnel`).
- Smoke gevent local (Windows): gunicorn NÃO roda em Windows (sem `fcntl` — prod é
  Linux/Docker), então validou-se pelo caminho dev: `python app.py` com
  `DADINHO_ASYNC_MODE=gevent` → `/robots.txt` 200 e handshake
  `0{"sid":...,"upgrades":["websocket"],...}` (WebSocket do driver gevent ativo).
- Resto do pipeline (py_compile, node/i18n, boot VERCEL, integração, cross-instance,
  anti-fraude, performance) inalterado e verde.
- Deploy: seguir `docs/verificacao.md` (VPS). Smoke test local agora cobre
  `127.0.0.1:8000` (réplica 1) e `127.0.0.1:8090` (nginx/borda). Validar em 2+
  abas/navegadores conectando (página Vercel, socket VPS) e, na VPS,
  `docker compose ps` deve mostrar `dadinho-api`, `dadinho-api-2/3/4`,
  `dadinho-redis`, `dadinho-nginx`, `dadinho-tunnel`.

---

## Fase 62 — Documentação e Agentes: runbooks, skills e ADRs

Objetivo: o conhecimento operacional das Fases 46/59/60/61 estava espalhado em
comentários, no `todo.md` e na cabeça do mantenedor. Esta fase cria os lugares
canônicos: **runbook de incidente** (o que fazer quando quebra), **ADRs** (por que
decidimos) e **skills** (para o agente aplicar o checklist sozinho).

- [x] **Runbook operacional (`docs/runbook.md`)** — playbooks por sintoma, com
  comandos reais da VPS (`/opt/dadinho`, `docker compose`, `redis-cli`):
  topologia; triagem em 30s; §4 público fora (tunnel/DNS/nginx); §5 réplica
  unhealthy; §6 Redis down/SPOF (ADR-007); §7 deploy quebrado → rollback (VPS:
  sem git → reenviar commit bom via `atualizar_vps.ps1`; Vercel: Promote/Rollback);
  §8 salas presas/locks (`TRAVA_TTL=120s`, chaves `dadinho:sala|resumo|sid|ip|lock`);
  §9 abuso/rate limit (503 do `limit_req`, camadas não redundantes, captcha opt-in);
  §10 custo/alertas; §11 pós-incidente. Regras de ouro (nunca `rm -rf
  /opt/dadinho/*`, nunca `down -v`, não editar blob à mão).
- [x] **ADRs (`docs/adr/`)** — índice + template (`README.md`) e 7 decisões:
  001 serverless Vercel + API VPS opcional; 002 lock por sala + message queue;
  003 nginx de borda com rate limit por IP real; 004 anti-fraude heurístico +
  captcha opt-in; 005 performance do store (cache/batch/compressão/LRU) e
  rejeição do pool de threads da IA; 006 gevent + 4 réplicas + sticky; 007 Redis
  local SPOF com HA **adiado**. Cada um com Contexto/Decisão/Consequências +
  "o que proíbe"; ADR é imutável (mudança = novo ADR).
- [x] **Skills novas (`.opencode/skills/`)** —
  `vps-ops-dadinho` (triagem/incidente → aponta para `docs/runbook.md`, regras de
  ouro) e `multi-instancia-dadinho` (checklist das invariantes cross-instance:
  escopo de emit, lock+`salvar_sala`, sem estado em memória, invalidação de cache
  e o trade-off do gevent). Ambas com `description` enxuta com palavras-gatilho.
- [x] **Referências atualizadas** — `AGENTS.md` e `opencode.json` (descrição da
  reference `docs`) agora citam `docs/runbook.md` e `docs/adr/`; lista de skills
  inclui as duas novas. **Lembrete:** config/skills não recarregam a quente —
  reiniciar o opencode após editar.
- [x] **Resíduos da Fase 61 em `docs/verificacao.md`** — o passo da VPS ainda
  dizia "proxy para a `api:8000`" e `--build api nginx` (API única). Corrigido
  para as 4 réplicas (`api api2 api3 api4 nginx`) e sticky.

Verificação:
- Cross-check de fatos do runbook/ADRs contra o repo: nomes de serviço/container
  (`docker compose config` → `api`/`api2`/`api3`/`api4`/`redis`/`nginx`/`tunnel`),
  script `atualizar_vps.ps1` (`--build api api2 api3 api4 nginx`), chaves e TTLs
  do `store.py` (`dadinho:sala|resumo|resumos|sid|ip|lobby_seq|lock`, TTL 7d/24h/6h,
  `TRAVA_TTL=120`), zones do nginx (60r/s e 10r/s) — conferidos linha a linha.
- `nginx -t` da config do repo (hostnames das réplicas) → ok; `python
  verificar.py` inalterado (a fase é documental, sem código de jogo).
- Skills/ADRs/runbook são **texto**: a verificação é o cross-check acima + o
  teste manual de que eles respondem aos sintomas reais (rodar a triagem §3 numa
  VPS de verdade quando houver incidente).

# TODO — Dadinho: bug crítico "criar sala trava no mobile" (Fases 64–66)

Investigação a partir do relato: clique em "Criar sala" trava ocasionalmente, reproduzido
em celular. Mesma convenção: `[ ]` pendente · `[x]` concluído · `[~]` em andamento.

## Diagnóstico (leia antes de aplicar qualquer fix)

**Hipótese principal, com alta confiança:** desde a Fase 61 / ADR-006
(`docs/adr/006-gevent-4-replicas-sticky.md`), a API roda em 4 réplicas atrás do
`nginx/nginx.conf`, roteadas por `upstream dadinho_api { hash $ip_real consistent; }`
— necessário porque a sessão Engine.IO (handshake + polling + upgrade do
WebSocket) vive só na memória de UMA réplica. O próprio ADR assume "o IP real é
estável" como premissa da decisão.

Em rede móvel essa premissa **não se sustenta**: o IP público visto pelo
Cloudflare (`Cf-Connecting-Ip`) pode mudar no meio de uma conexão por CGNAT da
operadora, troca de torre, ou alternância wifi↔dados. Quando isso acontece
durante o handshake, requisições sequenciais da MESMA tentativa de conexão
podem hashear para réplicas diferentes — que não compartilham a sessão Engine.IO
entre si — e a conexão nunca fecha de fato.

Isso é agravado por `static/script.js:119-126`
(`socket.on('connect_error', ...)`): o handler só reage quando o servidor manda
um `motivo`/`chave` explícito (recusa por captcha/limite de IP — Fase 59). Um
erro de transporte genérico — exatamente o caso de handshake fragmentado entre
réplicas — cai no `return` silencioso da linha 122: nenhuma atualização de
`status_conexao`, nenhum alerta. O socket.io-client continua tentando sozinho
(reconexão automática, backoff padrão), mas a tela parece 100% normal e o
clique em "criar sala" não produz efeito visível nenhum — daí o "trava" sem
erro no console. Explica tanto o "ocasionalmente" (só quando a rede do celular
está instável naquele instante) quanto o "num celular" (troca de IP em rede
móvel é comum; em wifi/desktop é raro).

---

## Fase 64 — Confirmar a hipótese antes de mexer em produção

Objetivo: hoje não há como provar, só pelos logs atuais, que o handshake de um
cliente específico está sendo fragmentado entre réplicas diferentes. Confirmar
isso primeiro evita aplicar uma correção estrutural (Fase 66) às cegas.

- [x] **D1 — Logar a réplica de destino**: adicionar `$upstream_addr` ao
  `log_format dadinho_json` em `nginx/nginx.conf` (campo novo, ex.:
  `"upstream":"$upstream_addr"`). Hoje o log já tem `ip_real`/`uri`/`status`,
  mas não registra qual réplica (`api`/`api2`/`api3`/`api4`) atendeu cada
  requisição.
- [x] **D2 — Correlacionar no runbook**: em `docs/runbook.md`, seção 9 (Abuso/bot/
  rate limit) ou uma nova subseção, documentar o comando de verificação:
  `docker compose logs nginx | grep '"ip_real":"<ip-do-usuário>"'` e conferir se
  o campo `upstream` varia entre requisições próximas no tempo (poucos
  segundos) para o mesmo `ip_real` — isso é a assinatura do bug. Feito em §9.1
  (inclui o map IP:porta → réplica via `docker inspect`).
- [ ] **D3 — Reproduzir com throttling** (requer teste manual): no Chrome DevTools mobile emulation,
  usar "Network Conditions" para simular perda de pacote/latência alta (não
  reproduz troca de IP diretamente, mas ajuda a isolar se o problema é
  timeout de handshake vs. roteamento) — e, se possível, testar trocando de
  wifi para dados móveis no meio do carregamento da página (reproduz a troca
  de IP de verdade).

Verificação: com D1 em produção, pedir para o usuário que relatou o bug
reproduzir de novo e, junto com o horário aproximado, localizar as linhas do
log correspondentes — confirmar se `upstream` mudou entre requisições da mesma
tentativa de conexão.

---

## Fase 65 — Mitigação imediata no cliente (sem mudar a infra)

Objetivo: mesmo que a Fase 66 (correção estrutural) leve mais tempo pra validar
com segurança, ninguém deveria ficar preso numa tela sem nenhum sinal de erro.
Isso pode subir independente do diagnóstico da Fase 64.

- [x] **M1 — `connect_error` genérico também sinaliza**: em
  `static/script.js:119-126`, quando `erro` não tem `motivo.chave` (transporte
  genérico, não recusa intencional), atualizar `status_conexao` para
  "reconectando" (mesmo texto/classe já usados em `disconnect`, linha ~2153-2158)
  em vez de retornar em silêncio. Contar tentativas consecutivas — implementado
  contando no próprio `connect_error` (dispara a cada tentativa que falha,
  inclusive a primeira; mais confiável que `socket.io.on('reconnect_attempt')`);
  a partir de 5 tentativas sem sucesso, trocar a cor/texto para
  algo mais explícito (ex.: "sem conexão — tentando reconectar") em vez do
  "reconectando" indefinido de sempre.
- [x] **M2 — Watchdog no `criar_sala`**: em `static/script.js:485-489`
  (`function criar_sala()`), guardar o instante do emit; se `sala_criada` não
  chegar em ~6s, mostrar um alerta (`mostrar_alerta`, já usado em outros
  fluxos) oferecendo "Tentar de novo" — em vez de deixar o clique
  silenciosamente sem efeito. Cuidado para não reemitir automaticamente sem
  o usuário pedir (evita duplicar `criar_sala` se a resposta só está
  atrasada, não perdida).
- [x] **M3 — Mesma lógica para `listar_partidas`**: o evento de busca
  (`socket.emit('listar_partidas', ...)`) tem exatamente o mesmo risco
  (`evento_leitura`, mesma dependência de conexão) — vale o mesmo watchdog de
  timeout, já que provavelmente trava pelo mesmo motivo se o usuário tentar
  buscar em vez de criar.

Verificação: em dev local, forçar um `connect_error` genérico (ex.: derrubar o
servidor por alguns segundos com o cliente já carregado) e confirmar que
`status_conexao` reflete o problema; testar `criar_sala` com o servidor
propositalmente sem responder ao evento (comentar o `emit` no handler por um
teste local) e confirmar que o alerta de timeout aparece em ~6s.

---

## Fase 66 — Correção estrutural do roteamento sticky

Objetivo: resolver a causa raiz (premissa de IP estável não vale para clientes
móveis), não só mascarar o sintoma. Duas opções, com trade-offs diferentes —
decisão do mantenedor após ver os dados da Fase 64.

- [x] **E1 — Opção A: WebSocket como transporte único** (`transports:
  ['websocket']` em vez de `['websocket', 'polling']`, `static/script.js:65`).
  Com WS puro, a conexão inteira é UM único upgrade HTTP — uma única decisão
  de roteamento do nginx por tentativa de conexão, não uma sequência de
  requisições de polling que podem hashear para réplicas diferentes entre si.
  Isso torna o sticky-por-IP quase irrelevante para a correção (só passa a
  importar pra distribuição de carga, não pra funcionar). Trade-off: redes que
  bloqueiam WebSocket bruto (algumas corporativas/escolares, raramente
  operadoras móveis) perdem o fallback de polling — mas hoje, com o roteamento
  quebrando o polling de qualquer forma nesse cenário, o resultado prático já
  é falha; a diferença é que viraria um `connect_error` explícito (pego pela
  Fase 65/M1) em vez de um hang silencioso. **Escolhida pelo mantenedor** (A).
- [x] **E2 — Opção B: sticky por cookie em vez de IP**. **Rejeitada** em favor
  da Opção A (registrado no ADR-008): exigiria `withCredentials: true` no
  cliente (cross-origin Vercel↔VPS), CORS com credentials e cookie
  `SameSite=None; Secure` — mais partes móveis e risco para ganho marginal.
  (Mantida descrita aqui caso o polling volte a ser necessário.)
- [x] **E3 — Atualizar o ADR-006**: a premissa "IP real é estável" não vale
  para clientes móveis. Seguindo a convenção de ADR imutável (README), a
  revisão virou **ADR-008** (`docs/adr/008-websocket-unico-transporte.md`),
  referenciado a partir do ADR-006 (status `Aceito (revisado por ADR-008)`) e do
  índice.

Verificação: `python verificar.py` continua verde (mudança é só transporte/
proxy, não lógica de jogo); testar em produção (ou staging) alternando a rede
do celular entre wifi e dados móveis durante o carregamento da página — antes
da correção deveria reproduzir o hang (confirmando o diagnóstico da Fase 64);
depois, a conexão deve se recuperar (Opção A: reconectar limpo; Opção B:
manter a sessão mesmo com o IP mudando). Repetir o teste de `docker compose
logs nginx` da Fase 64/D2 e confirmar que `upstream` não varia mais dentro de
uma mesma tentativa de conexão.

## Fase 64–66 — estado da implementação (2026-09-17)

- **Local (feito):** `python verificar.py` 100% verde (38s) — inclui `node
  --check static/script.js` + `i18n.js`, cobertura i18n das 3 chaves novas
  (`js.sem_conexao`, `msg.criar_sala_timeout`, `msg.buscar_timeout`) e a
  integração completa. `nginx -t` **não** rodou localmente (daemon do Docker
  desligado na máquina); a mudança no `log_format` é aditiva (um campo
  `$upstream_addr`) e a validação fica no deploy da VPS (`docs/runbook.md` §4).
- **Pendente (produção/manual):** D3 (reprodução com throttling/troca de rede);
  pedir ao usuário que relatou o bug para reproduzir com D1 em produção e
  correlacionar o `upstream` (§9.1 do runbook); retestar no celular alternando
  wifi↔dados; `docker compose logs nginx` confirmando `upstream` estável por
  tentativa de conexão; `docker compose up -d --build api api2 api3 api4 nginx`
  para aplicar o `log_format` novo.
- **Fase 66:** Opção A adotada pelo mantenedor (`transports: ['websocket']`),
  registrada no ADR-008 (ADR-006 marcado como revisado). Nenhuma mudança no
  nginx além do log; o sticky por IP segue só para distribuição de carga.
