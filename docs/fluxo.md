# Fluxo do jogo e mapa de eventos — Dadinho

> **Regra de ouro ao mexer num `emit` do servidor:** ache o `socket.on` correspondente em `static/script.js` primeiro.

## Páginas (`mudar_pagina`)

| Página | Tela |
|---|---|
| 0 | lobby / sala de espera |
| 1 | rolagem de dados |
| 2 | turnos / apostas |
| 3 | conferência da rodada |
| 4 | vitória |

Eventos sempre escopados à room da sala (`to=sala_<id>`) no namespace global.

## Ciclo do jogo

- **Sala de espera (0):** o master edita `Lobby.config` via `configurar_partida` (nome, `dados_qtd`, `max_jogadores`, `com_coringa`, `publica`, `substituir_desconectado_por_ia`, `ia_nivel_padrao`, `verificacao_ativa`) e controla bots (`adicionar_ia`/`completar_com_ias`/`remover_ia`/`renomear_ia`); o apelido (`apelido`) pode ser trocado quantas vezes quiser enquanto o jogador não está pronto — travado ao ficar pronto (e destravado ao desfazer); jogadores alternam prontidão (`ficar_pronto`); `iniciar_partida` libera somente com `Lobby.pode_iniciar()` (>=2, todos com apelido, todos os não-master prontos — bots já entram prontos; com verificacao_ativa, exige revelações de seed completas). Sala cheia recusa connect (`sala_cheia`). `status` vira `"jogando"` ao iniciar e volta a `"espera"` no `resetar_para_lobby`.
- **Rolagem (1):** cada um rola (`jogar_dados` → dados derivados; `joguei_dados` confirma ao servidor; `rolagem_status` mostra confirmados). Quando todos confirmam, `mudar_pagina 2`.
- **Confirmação da rolagem (Fase 80):** `jogar_dados` marca a rolagem mas **não** abre a página 2 — a supressão é de propósito (`ia.processar(..., permitir_virada_pagina=False)`), para o cliente ver a animação e o resultado antes da virada. Quem abre é o `joguei_dados`, emitido 2s depois do resultado, e o gatilho é a **primeira** confirmação que chega depois do último dado (o judge é `verificar_se_todos_ja_jogaram_seus_dados`, sobre a rolagem, não sobre a confirmação). Como esse emit era o único e saía uma vez só, o cliente passou a **reenviá-lo enquanto a tela não mudar** (watchdog da confirmação: 4s, teto de 6 tentativas, `setTimeout` sobrevive a socket caiu), e o servidor o trata como confirmação: `cooldown=None` (não divide o balde do `sid` cru — um descarte mudo custava a partida parada), guard `jogador.joguei_dados` (retry de rodada anterior não confirma dados velhos) e, com a sala **já** virada, `enviar_snapshot_sala` — o mesmo reparo do heartbeat na divergência de página, que fecha a janela de 60s. Idempotente: o guard de `lobby.pagina == 1` impede re-roda de `iniciar_turnos` (ver abaixo).
- **Turnos/apostas (2):** o jogador da vez aposta (`apostar`) ou desconfia (`desconfiar`). Aposta válida avança a vez (`atualizar_turno`/`meu_turno`/`espera_turno`); desconfiança abre a conferência (página 3). Coringa (`atualizar_coringa`) segue as regras de `config.com_coringa`.
- **Conferência (3):** todos confirmam `conferencia_final` (gated por `lobby.pagina == 3`); `cards_conferencia` + `rendimento` narrado. Perdedor perde dados; fim da rodada → `reset_rodada` (ou `reset_partida` com pontos e nova rodada) e volta à página 1 (ou página 4 se alguém zerou).
- **Vitória (4):** `vencedor_da_partida` + `soltar_fogos`; todos confirmam `vencedor_final` (gated por `lobby.pagina == 4`) para `reset_partida` → página 0.
- **Status de confirmação (Fase 22):** servidor emite `rolagem_status`/`conferencia_status`/`vitoria_status` (`{confirmados, pendentes, total}` com apelidos) sempre que alguém rola/confirma (também para IAs em `ia.processar`, remoção por desconexão e no snapshot). O cliente mostra fichas `✓ nome`/`⏳ nome` em `renderizar_status_confirmacao`.
- **Jogada automática (Fase 21):** `tempo_max_jogada` + `autojogar` rola/aposta/desconfia/confirma pelo atrasado com o motor da IA; referências de tempo persistidas (`rodada.vez_em`, `rodada.inicio_rolagem_em`, `rodada.conferencia_em`, `partida.vitoria_em`). O relógio do **primeiro turno** começa quando a rolagem acaba: `Rodada.iniciar_turnos` (chamado por `joguei_dados` quando o último confirma) recarimba `vez_em` com o tempo cheio — senão o primeiro da vez pagava a rolagem com o tempo do turno. Para ser idempotente, `joguei_dados` só faz a transição na **página 1** (`lobby.pagina == 1`): um reenvio já na mesa não re-roda `iniciar_turnos` nem deixa o jogador da vez estender o próprio turno.
- **Rede de segurança da jogada automática (Fase 75):** o `autojogar` nasce do contador regressivo do **cliente**, então uma aba em segundo plano, um socket reconectado em outra instância ou um evento perdido deixavam a sala parada esperando aquele humano (sem erro e sem aviso). O `heartbeat` passou a ser a rede: `_tem_prazo_vencido` (lê o cache, só decide se vale entrar no lock) força o caminho lockado, e `_autojogar_vencidos` age por **todos** os humanos vencidos dentro do lock, com leitura fresca, rodando o motor da IA exatamente como o `autojogar` faria. O handler `autojogar` continua jogador-específico. `tempo_max_jogada=0` desliga os dois caminhos.
- **Contador da jogada automática (Fase 75):** o badge `#contador_jogada` vive na camada `#camada_contador`, **irmã** das telas (fora do `#app-main`). Antes ele morava dentro de `#tela_partida`, que ganha `display:none` em toda troca de página — o relógio corria invisível nas páginas 1/3/4 e o servidor auto-confirmava o "Ok" sem o jogador ver. `posicionar_contador_jogada` (chamada em `mudar_pagina`) move o elemento no DOM: na página de turnos (2) ele volta para dentro de `#rodape_acao` (rodapé do layout de app do mobile, Fase 33/M3) e nas demais fica na camada, que nunca é escondida. Espectador não tem botão de "Ok" nem é da vez, então não recebe relógio.

## Home sem sala e busca

- **Home sem sala (Fase 18):** `handle_connect` sem `?sala=` (ou `?sala=padrao`) **não cria sala automaticamente** — emite `connect_start` sem sala (`chave_secreta` vazia) e o cliente fica em `#painel_home`: "Criar sala" (`criar_sala` → `sala_criada` → navega via `gerar_codigo_sala`) ou "Buscar partidas" (`listar_partidas`). Entrar por código: busca ou link compartilhado.
  - **Código inválido (Fase 77):** `?sala=` presente mas formato quebrado (ex: `?sala=abc!`) — o servidor emite `sala_invalida` em vez de `connect_start` e o cliente avisa + limpa a query string, sem nunca materializar a sala padrão.
- **Busca:** tela client-side (fora do ciclo de páginas), `listar_partidas` → `partidas_listadas` (somente leitura, `to=client_id`). Filtros: nome/código, status, coringa, vaga, ordenação (`funcoes_gerais.listar_resumos_partidas`). Salas privadas não aparecem.

## Espectadores (Fase 15)

Quem entra em sala com `status == 'jogando'` vira `Jogador` em `lobby.espectadores` (nunca em `lobby.jogadores`), limite `funcoes_gerais.MAX_ESPECTADORES`. Não conta para lotação, `pode_iniciar`, vitória nem GC (`tem_humano_conectado`) — mas, por estar conectado, mantém a sala viva. Recebe snapshot + selo `espectador` e é promovido a jogador no `resetar_para_lobby`. Confirmações ganham gates por `lobby.pagina` (3/4) e por ser jogador da sala.

**Fase 69 (partida só de IAs assistida):** quando o último humano com dados é eliminado (ou a sala é só de bots) e há humano na sala fora da mesa, o motor para de simular a partida inteira numa tacada: cada lance espera o relógio do lobby (`proximo_lance_em`). O espectador paga o ritmo com o evento `espectador_leitura`, disparado a cada `narracao` de IA e reagendado por `espectador_ritmo` (`restante_ms`). Sem espectador, o motor volta ao modo legado (simula até o fim) — a sala nunca fica presa. Ver ADR-009.

## Expulsão (Fase 19)

Master expulsa via `expulsar_jogador` (master + `chave_secreta`); expulso recebe `expulso_da_sala` e a room recebe `jogador_expulso`.

## Renomear bot (Fase 75)

Master renomeia os bots da espera via `renomear_ia` (master + `chave_secreta`, `client_id` + `apelido`). O editor nasce na própria célula do nome (input + "ok", Enter salva, Escape/blur cancela) e vem das linhas marcadas em `update_user_list.bots`; `marcador_ia`/`limite_nome_ia` do mesmo payload montam o input sem duplicar a constante no JS. O servidor recoloca o `🤖`, resolve colisão com sufixo `_1` dentro do orçamento e devolve o nome final no `update_user_list` do broadcast; recusa vai como `renomear_ia_negado` com `{motivo: {chave, params}}`. Fora da espera o evento é no-op (o apelido já está nas fichas de confirmação, no narrador e no histórico da rodada).

## Substituto do desconectado (Fase 76)

Com `substituir_desconectado_por_ia` ligada, `verificar_desconectados` expurga a janela de reconexão (`_gc_sala`) e `_substituir_por_ia` (app.py) converte o jogador que caiu em bot **prudente** (`ia.ESTILO_PRUDENTE`) e marca o apelido guardado com o `🤖` (`ia.marcar_substituto`) — o mesmo marcador do bot natural, então o card de partida, as fichas, a narração e a lista da espera passam a mostrar que ali tem máquina sem evento novo. Dados, vez e `chave_secreta`/`client_id` são preservados; a sala é avisada pela narração `narr.substituicao.*`. Como o apelido é a chave dos `id`s dos cards no cliente, a troca **reconstrói a tela da sala inteira** (`funcoes_gerais.reconstruir_tela_sala`, mesmo caminho do snapshot de reconexão) antes de `ia.processar` jogar o turno do substituto. O caminho de decisão é o de `ia.decidir` → `_decidir_prudente` (aposta só o que o próprio dado sustenta, mínima jogada legal quando não há coberta, desconfia só com a conta abaixo de `_limiar_prudente`), no nível `ia_nivel_padrao` da sala. `retomar_identidade` do mesmo humano (sid novo) limpa `ia_estilo`/`ia_nivel`, tira o `🤖` e reconstrói os cards dos demais. Ver ADR-010.

## Mapa de eventos

### Cliente → servidor (emits de `static/script.js` → handlers em `app.py`)

| Evento (payload chave) | Handler | Decorator/Guard |
|---|---|---|
| `connect` (handshake `?sala=`, `tem_chave`) | `handle_connect` | — |
| `retomar_identidade` (`chave`) | `retomar_identidade` | cooldown=None, sem autenticar |
| `apelido` (`apelido_msg`) | `escolher_apelido` | evento_mutavel, extrair_chave=None |
| `configurar_partida` (`chave`, `config`) | `configurar_partida` | master + chave; cooldown próprio (`cooldown_chave='config_sala'`) |
| `ficar_pronto` (`chave`) | `ficar_pronto` | + chave, guarda `username is None` (emit `pronto_sem_nome`) |
| `iniciar_partida` (`chave`, `dados_qtd`) | `iniciar_partida` | master + chave, valida `pode_iniciar` |
| `comprometer_seed` (`chave`, `compromisso`) | `comprometer_seed` | chave, cooldown=None |
| `revelar_seed` (`chave`, `nonce`) | `revelar_seed` | chave, cooldown=None |
| `solicitar_auditoria` | `solicitar_auditoria` | chave |
| `adicionar_ia`/`completar_com_ias`/`remover_ia` (chave) | app.py:1396/1414/1428 | master + chave; cooldown próprio (`cooldown_chave='ia_sala'`), para o `configurar_partida` do seletor de nível não consumir a janela do botão logo abaixo |
| `renomear_ia` (`chave`, `client_id`, `apelido`) | `renomear_ia` | master + chave, mesmo balde `ia_sala`; só na espera; recusa → `renomear_ia_negado` |
| `expulsar_jogador` (`chave`, `client_id`) | `expulsar_jogador` | master + chave |
| `sair_da_sala` (`chave`) | `sair_da_sala` | cooldown=None, espectador sem chave; jogador na espera/eliminado: exige chave e remove sem janela de reconexão; jogador ativo na partida: no-op |
| `listar_partidas` (`filtros`, `sala_atual`) | `listar_partidas` | evento_leitura |
| `criar_sala` | `criar_sala` | — |
| `verificar_desconectados` | `verificar_desconectados` | extrair_chave=None |
| `heartbeat` (`chave`, `pagina`, `vez`) | `heartbeat` | sem autenticar, `lock_distribuido=False`; **herda `COOLDOWN_ESCRITA` (0,5s) na janela do `sid` cru** — compete com os handlers mutáveis que não isolaram balde |
| `espectador_leitura` (`chave`, `pagina`) | `espectador_leitura` | cooldown=None, + chave (poll do espectador, Fase 69) |
| `jogar_dados` (`chave`) | `jogar_dados` | + chave |
| `joguei_dados` (`chave_secreta`) | `joguei_dados` | chave (campo `chave_secreta`), cooldown=None (Fase 80: confirmação, não pode ser descartada pelo balde do `sid`); guard `jogador.joguei_dados`; idempotente por rodada; com a sala já na página 2, responde `enviar_snapshot_sala` (retry do cliente) |
| `autojogar` (`chave`) | `autojogar` | + chave |
| `apostar` (`{dados:{chave, dado, quantidade}}`) | `apostar` | `_chave_aninhada` |
| `desconfiar` (`{dados:{chave}}`) | `desconfiar` | `_chave_aninhada` |
| `conferencia_final` (`chave`) | `conferencia_final` | chave, cooldown=None, gated página 3 |
| `vencedor_final` (`chave`) | `vencedor_final` | chave, cooldown=None, gated página 4 |
| `foguetear_click` (`chave`) | `foguetear_click` | + chave |
| `enviar_emoji_chat` (`chave`, `emoji`, `categoria`) | `enviar_emoji_chat` (Fase 77) | + chave; cooldown=COOLDOWN_CHAT; lock_distribuido=False; valida emoji contra whitelist (invariante #4) |
| `chat_reagindo` (`chave`, `emoji`, `categoria`) | `chat_reagindo` (Fase 77) | + chave; cooldown próprio (`cooldown_chave='chat_reagindo'`), para o preview não consumir a janela do `enviar_emoji_chat`; preview de reação antes do emoji (typing indicator) |

### Servidor → cliente (emits → `socket.on` em `static/script.js`)

Eventos para a room (`to=sala_room()`) salvo indicação contrária:

| Evento | Origem (ex) | Escopo | `script.js` |
|---|---|---|---|
| `connect_start` | app.py:445 | cliente | 1661 |
| `sala_invalida` (`motivo` {chave, params}; Fase 77: código de sala inválido na URL — avisa e limpa a query sem ficar na sala padrão) | app.py:895 | cliente | `socket.on('sala_invalida')` |
| `sala_cheia` | app.py:426/432 | cliente | 432 |
| `retomar_negado` (`motivo` {chave, params}; Fase 30: `msg.vaga_perdida_inatividade` vs `msg.retomar_outra_sala`; Fase 77: `msg.partida_cancelada`, quando a lápide diz que a sala foi cancelada por abandono — vem acompanhado de `connect_start`+snapshot da sala zerada, senão a tela trava) | app.py:1088 (Fase 77) | cliente | 1729 |
| `update_username` | app.py:592 | cliente | 1740 |
| `atualizar_pontos` | funcoes_gerais:327 | sala | 597 |
| `master_def` | funcoes_gerais:354 | cliente | 607 |
| `atualizar_lista_usuarios`/`update_user_list` | funcoes_gerais:388 / app.py:889 | sala / cliente | 468 |
| `lobby_lotado` | app.py:1463 (`_avisar_lobby_lotado`, em `adicionar_ia`/`completar_com_ias`) | cliente (só o master que pediu; dispara mesmo quando nenhum bot coube, para "sala cheia" não ser indistinguível de um drop) | fecha o drawer de configurações (script.js:1630) |
| `bot_adicionado` (`quantidade`) | app.py:1482 (`_confirmar_bots_ao_master`, em `adicionar_ia`/`completar_com_ias`, Fase 79) | cliente (só o master que pediu; só quando o bot entrou mesmo) | bip sintetizado (`tocar_som_bot`, script.js:1638), um por bot |
| `renomear_ia_negado` (`motivo` {chave, params}: `msg.motivo.ia_invalido`/`ia_ocupado`/`ia_alvo`) | `renomear_ia` (Fase 75) | cliente (só o master) | mostra o alerta da recusa |
| `expulso_da_sala`/`jogador_expulso` | app.py:771/773 | cliente/sala | 799/811 |
| `saiu_da_sala` | app.py:949 | cliente | 824 |
| `jogador_desconectado` | app.py:699 | cliente | 1835 |
| `mudar_pagina` | funcoes_gerais:178/230 | sala/cliente | 880 |
| `meus_dados` | app.py:933 | cliente | 899 |
| `dados_mesa` | funcoes_gerais:280 | cliente | 925 |
| `atualizar_coringa` | funcoes_gerais:282 | cliente/sala | 936 |
| `construtor_dados` | funcoes_gerais:252 | cliente | 1009 |
| `construtor_html` | funcoes_gerais:269 | cliente | 1117 |
| `atualizar_turno` | modelos/turno.py:53 | sala | 1183 |
| `meu_turno` | modelos/rodada.py:375 / funcoes_gerais:236 (dispatcher D2) | cliente | 1270 |
| `espera_turno` | modelos/rodada.py:382 / funcoes_gerais:242 (dispatcher D2) | cliente | 1306 |
| `reset_rodada` | funcoes_gerais:276 | cliente | 1316 |
| `reset_partida` | modelos/lobby.py:406 | sala | 1340 |
| `formatador_coletivo` | funcoes_gerais:292 | cliente | 1371 |
| `botao_vencedor_ativ` | funcoes_gerais:331 | cliente | 1405 |
| `vencedor_da_partida` | funcoes_gerais:321 | cliente | 1410 |
| `soltar_fogos` | app.py:1144 | sala | 1424 |
| `cards_conferencia` | funcoes_gerais:315 | cliente | 1466 |
| `rolagem_status`/`conferencia_status`/`vitoria_status` | funcoes_gerais:208/213/218 | sala | 1595/1599/1603 |
| `espectador` | funcoes_gerais:248 | cliente | 1608 |
| `espectador_ritmo` | app.py:espectador_leitura (Fase 69) | cliente | handler do poll |
| `narracao` (Fase 11/30: substituição em app.py:414 e retorno em app.py:1003) | modelos/partida.py:127 | sala | 214 |
| `jogar_dados_resultado` | app.py:916 | cliente | 1744 |
| `jogada_invalida` | modelos/rodada.py:98 (`txtchave`/`txtparams`) | cliente | 1795 |
| `iniciar_negado` | app.py:612 (`motivo`) | cliente | 438 |
| `pronto_sem_nome` | app.py:1237 (guard do `ficar_pronto`) | cliente | — |
| `sala_criada` | app.py:804 | cliente | 259 |
| `partidas_listadas` | app.py:790 | cliente | 367 |
| `seed_compromissos` | app.py:670 | sala | 3155 |
| `seed_revelar` | funcoes_gerais:361 | sala | 3161 |
| `seed_revelacao` | app.py:695 | sala | 3175 |
| `auditoria_partida` | funcoes_gerais:329 | cliente | 3300 |
| `chat_emoji` (`jogador`, `emoji`, `categoria`) | app.py:enviar_emoji_chat (Fase 77) | sala | 5871 |
| `chat_reagindo` (`jogador`, `emoji`, `categoria`) | app.py:chat_reagindo (Fase 77) | sala | 5862 |
| `chat_emoji` (bot) | funcoes_gerais:bot_enviar_emoji ← ia.py (Fase 77) | sala | — |

> **Bot emojis (Fase 77):** os bots reagem com emojis de forma inteligente — `ia.py` decide o emoji com base na ação (blefe, aposta segura, desafio certo/errado, vitória), personalidade (`ia_risco`, `ia_agressividade`, `ia_estilo`) e contexto de dados. A emissão passa por `funcoes_gerais.bot_enviar_emoji`, que valida contra a whitelist global e aplica rate limit por `client_id` (`COOLDOWN_EMOJI_BOT`; `ignorar_cooldown` libera a rajada de vitória/derrota). Reações durante a partida são esparsas (`CHANCE_REACAO_EMOJI`/`CHANCE_REACAO_OBSERVADOR`); vitória/derrota do desafio (`CHANCE_REACAO_CONFERENCIA`) e da partida (`CHANCE_REACAO_VITORIA`) têm chance alta e podem mandar 2–3 emojis. Os ganchos vivem em `_processar_turno` (aposta + observadores), `_processar_conferencia` (desafio) e `_processar_vitoria` (campeão); nos dois últimos o guard `confirmou_alguma` garante UMA reação por conferência/vitória (senão cada `processar` — heartbeat/OK/poll — re-lançava e acumulava). No cliente, `chat_emoji`/`chat_reagindo` **furam a fila serial de animação** (`socket.onevent`, que insere as pausas de pensamento dos bots nas narrações): sem isso as reações ficavam presas atrás dos `atraso` e só saíam no fim da rodada ou na vez do jogador. Exceção: reação de bot com uma troca de página **pendente** na fila é segurada (`_segurar_emoji`) até o `mudar_pagina` concluir, senão nasce antes de o card entrar e sai sem âncora (era o caso da conferência); a reação do próprio jogador nunca é segurada. O emoji nasce em cima do card de quem reagiu (`_card_do_jogador`), sem exibir o nome; sem card visível (jogar dados/vitória/observador) mantém o nome à direita. Rajadas de `chat_emoji` (vários bots no mesmo `processar`) passam por uma fila com espaçamento de 260 ms (`_enfileirar_emoji`), para não aparecerem todas no mesmo frame.

> Legenda de escopo: "sala" = `to=lobby.sala_room()`; "cliente" = `to=jogador.client_id`. Confira sempre o `emit` real antes de assumir.