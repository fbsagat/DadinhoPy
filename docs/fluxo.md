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

- **Sala de espera (0):** o master edita `Lobby.config` via `configurar_partida` (nome, `dados_qtd`, `max_jogadores`, `com_coringa`, `publica`, `substituir_desconectado_por_ia`, `ia_nivel_padrao`, `verificacao_ativa`) e controla bots (`adicionar_ia`/`completar_com_ias`/`remover_ia`); jogadores alternam prontidão (`ficar_pronto`); `iniciar_partida` libera somente com `Lobby.pode_iniciar()` (>=2, todos com apelido, todos os não-master prontos — bots já entram prontos; com verificacao_ativa, exige revelações de seed completas). Sala cheia recusa connect (`sala_cheia`). `status` vira `"jogando"` ao iniciar e volta a `"espera"` no `resetar_para_lobby`.
- **Rolagem (1):** cada um rola (`jogar_dados` → dados derivados; `joguei_dados` confirma ao servidor; `rolagem_status` mostra confirmados). Quando todos confirmam, `mudar_pagina 2`.
- **Turnos/apostas (2):** o jogador da vez aposta (`apostar`) ou desconfia (`desconfiar`). Aposta válida avança a vez (`atualizar_turno`/`meu_turno`/`espera_turno`); desconfiança abre a conferência (página 3). Coringa (`atualizar_coringa`) segue as regras de `config.com_coringa`.
- **Conferência (3):** todos confirmam `conferencia_final` (gated por `lobby.pagina == 3`); `cards_conferencia` + `rendimento` narrado. Perdedor perde dados; fim da rodada → `reset_rodada` (ou `reset_partida` com pontos e nova rodada) e volta à página 1 (ou página 4 se alguém zerou).
- **Vitória (4):** `vencedor_da_partida` + `soltar_fogos`; todos confirmam `vencedor_final` (gated por `lobby.pagina == 4`) para `reset_partida` → página 0.
- **Status de confirmação (Fase 22):** servidor emite `rolagem_status`/`conferencia_status`/`vitoria_status` (`{confirmados, pendentes, total}` com apelidos) sempre que alguém rola/confirma (também para IAs em `ia.processar`, remoção por desconexão e no snapshot). O cliente mostra fichas `✓ nome`/`⏳ nome` em `renderizar_status_confirmacao`.
- **Jogada automática (Fase 21):** `tempo_max_jogada` + `autojogar` rola/aposta/desconfia/confirma pelo atrasado com o motor da IA; referências de tempo persistidas (`rodada.vez_em`, `rodada.inicio_rolagem_em`, `rodada.conferencia_em`, `partida.vitoria_em`).

## Home sem sala e busca

- **Home sem sala (Fase 18):** `handle_connect` sem `?sala=` (ou `?sala=padrao` inválida) **não cria sala automaticamente** — emite `connect_start` sem sala (`chave_secreta` vazia) e o cliente fica em `#painel_home`: "Criar sala" (`criar_sala` → `sala_criada` → navega via `gerar_codigo_sala`) ou "Buscar partidas" (`listar_partidas`). Entrar por código: busca ou link compartilhado.
- **Busca:** tela client-side (fora do ciclo de páginas), `listar_partidas` → `partidas_listadas` (somente leitura, `to=client_id`). Filtros: nome/código, status, coringa, vaga, ordenação (`funcoes_gerais.listar_resumos_partidas`). Salas privadas não aparecem.

## Espectadores (Fase 15)

Quem entra em sala com `status == 'jogando'` vira `Jogador` em `lobby.espectadores` (nunca em `lobby.jogadores`), limite `funcoes_gerais.MAX_ESPECTADORES`. Não conta para lotação, `pode_iniciar`, vitória nem GC (`tem_humano_conectado`) — mas, por estar conectado, mantém a sala viva. Recebe snapshot + selo `espectador` e é promovido a jogador no `resetar_para_lobby`. Confirmações ganham gates por `lobby.pagina` (3/4) e por ser jogador da sala.

## Expulsão (Fase 19)

Master expulsa via `expulsar_jogador` (master + `chave_secreta`); expulso recebe `expulso_da_sala` e a room recebe `jogador_expulso`.

## Mapa de eventos

### Cliente → servidor (emits de `static/script.js` → handlers em `app.py`)

| Evento (payload chave) | Handler | Decorator/Guard |
|---|---|---|
| `connect` (handshake `?sala=`, `tem_chave`) | `handle_connect` | — |
| `retomar_identidade` (`chave`) | `retomar_identidade` | cooldown=None, sem autenticar |
| `apelido` (`apelido_msg`) | `escolher_apelido` | evento_mutavel, extrair_chave=None |
| `configurar_partida` (`chave`, `config`) | `configurar_partida` | master + chave |
| `ficar_pronto` (`chave`) | `ficar_pronto` | + chave |
| `iniciar_partida` (`chave`, `dados_qtd`) | `iniciar_partida` | master + chave, valida `pode_iniciar` |
| `comprometer_seed` (`chave`, `compromisso`) | `comprometer_seed` | chave, cooldown=None |
| `revelar_seed` (`chave`, `nonce`) | `revelar_seed` | chave, cooldown=None |
| `solicitar_auditoria` | `solicitar_auditoria` | chave |
| `adicionar_ia`/`completar_com_ias`/`remover_ia` (chave) | app.py:712/723/734 | master + chave |
| `expulsar_jogador` (`chave`, `client_id`) | `expulsar_jogador` | master + chave |
| `listar_partidas` (`filtros`, `sala_atual`) | `listar_partidas` | evento_leitura |
| `criar_sala` | `criar_sala` | — |
| `verificar_desconectados` | `verificar_desconectados` | extrair_chave=None |
| `heartbeat` (`chave`, `pagina`) | `heartbeat` | cooldown=None, sem autenticar |
| `jogar_dados` (`chave`) | `jogar_dados` | + chave |
| `joguei_dados` (`chave_secreta`) | `joguei_dados` | chave (campo `chave_secreta`), idempotente por rodada |
| `autojogar` (`chave`) | `autojogar` | + chave |
| `apostar` (`{dados:{chave, dado, quantidade}}`) | `apostar` | `_chave_aninhada` |
| `desconfiar` (`{dados:{chave}}`) | `desconfiar` | `_chave_aninhada` |
| `conferencia_final` (`chave`) | `conferencia_final` | chave, cooldown=None, gated página 3 |
| `vencedor_final` (`chave`) | `vencedor_final` | chave, cooldown=None, gated página 4 |
| `foguetear_click` (`chave`) | `foguetear_click` | + chave |

### Servidor → cliente (emits → `socket.on` em `static/script.js`)

Eventos para a room (`to=sala_room()`) salvo indicação contrária:

| Evento | Origem (ex) | Escopo | `script.js` |
|---|---|---|---|
| `connect_start` | app.py:445 | cliente | 1661 |
| `sala_cheia` | app.py:426/432 | cliente | 432 |
| `retomar_negado` | app.py:487 | cliente | 1717 |
| `update_username` | app.py:592 | cliente | 1740 |
| `atualizar_pontos` | funcoes_gerais:327 | sala | 597 |
| `master_def` | funcoes_gerais:354 | cliente | 607 |
| `atualizar_lista_usuarios`/`update_user_list` | funcoes_gerais:388 / app.py:889 | sala / cliente | 468 |
| `jogador_substituido_por_ia` | app.py:191 | sala | 778 |
| `expulso_da_sala`/`jogador_expulso` | app.py:771/773 | cliente/sala | 799/811 |
| `jogador_desconectado` | app.py:558 | cliente | 1808 |
| `mudar_pagina` | funcoes_gerais:178/230 | sala/cliente | 832 |
| `meus_dados` | app.py:933 | cliente | 899 |
| `dados_mesa` | funcoes_gerais:280 | cliente | 925 |
| `atualizar_coringa` | funcoes_gerais:282 | cliente/sala | 936 |
| `construtor_dados` | funcoes_gerais:252 | cliente | 1009 |
| `construtor_html` | funcoes_gerais:269 | cliente | 1117 |
| `atualizar_turno` | modelos:1554 | sala | 1183 |
| `meu_turno` | modelos:1502 | cliente | 1270 |
| `espera_turno` | modelos:1505 | cliente | 1306 |
| `reset_rodada` | funcoes_gerais:276 | cliente | 1316 |
| `reset_partida` | modelos:508 | sala | 1340 |
| `formatador_coletivo` | funcoes_gerais:292 | cliente | 1371 |
| `botao_vencedor_ativ` | funcoes_gerais:331 | cliente | 1405 |
| `vencedor_da_partida` | funcoes_gerais:321 | cliente | 1410 |
| `soltar_fogos` | app.py:1144 | sala | 1424 |
| `cards_conferencia` | funcoes_gerais:315 | cliente | 1466 |
| `rolagem_status`/`conferencia_status`/`vitoria_status` | funcoes_gerais:208/213/218 | sala | 1595/1599/1603 |
| `espectador` | funcoes_gerais:248 | cliente | 1608 |
| `narracao` | modelos:1062 | sala | 214 |
| `jogar_dados_resultado` | app.py:916 | cliente | 1744 |
| `jogada_invalida` | modelos:1256 (`txtchave`/`txtparams`) | cliente | 1795 |
| `iniciar_negado` | app.py:612 (`motivo`) | cliente | 438 |
| `sala_criada` | app.py:804 | cliente | 259 |
| `partidas_listadas` | app.py:790 | cliente | 367 |
| `seed_compromissos` | app.py:670 | sala | 3155 |
| `seed_revelar` | funcoes_gerais:361 | sala | 3161 |
| `seed_revelacao` | app.py:695 | sala | 3175 |
| `auditoria_partida` | funcoes_gerais:329 | cliente | 3300 |

> Legenda de escopo: "sala" = `to=lobby.sala_room()`; "cliente" = `to=jogador.client_id`. Confira sempre o `emit` real antes de assumir.