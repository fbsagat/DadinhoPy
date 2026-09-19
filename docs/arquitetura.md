# Arquitetura — Dadinho

Referência de arquitetura. Regras operacionais (comandos, convenções, invariantes curtas) ficam no `AGENTS.md`; o mapa de eventos e o fluxo do jogo ficam em `docs/fluxo.md`; verificação/deploy em `docs/verificacao.md`.

## Visão geral

- **Socket.IO only, sem REST** além de `/` (serve `templates/jogo.html`) e `/tema.mid` (asset gerado, Fase 12). Todo o fluxo do jogo é orientado a eventos (`flask_socketio.emit`).
- **Alvo: Vercel** (serverless/edge). Premissa de **infraestrutura sem estado**: nada de pressupostos de servidor único, nada de estado em memória persistente entre requests. O estado de jogo vive no store distribuído (`store.py`).
- **Casual only**: sem contas, sem ranking, sem leaderboard. O estado do jogador reseta por partida; identidade = Socket.IO `request.sid`.

## Camada de estado (`store.py`)

Interface distribuída (não em processo):

- `carregar_sala` / `salvar_sala` / `remover_sala` / `listar_lobbys`
- Índices (Fase 8): `salvar_resumo` / `listar_resumos` e `registrar_sid` / `sala_do_sid` / `desregistrar_sid`
- Implementações: `ArmazenamentoMemoria` (dev, `DADINHO_STORE=memoria`) e `ArmazenamentoUpstash` (Redis REST via `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN`). Sem Upstash configurado, cai **silenciosamente** em memória (`store.py:257-266`) — quebra o estado entre instâncias serverless, só serve para validar na hora.

Layout do store (Upstash, Fase 8) — chaves próprias com TTL, nada de hash único:

| Chave | Conteúdo | TTL |
|---|---|---|
| `dadinho:sala:<id>` | JSON do `Lobby` | renovado a cada `salvar_sala` |
| `dadinho:resumo:<id>` | resumo leve da busca | idem |
| `dadinho:resumos` | SET com os ids dos resumos (SMEMBERS+MGET em vez de SCAN) | — |
| `dadinho:sid:<client_id>` | índice `client_id → sala_id` (para `achar_jogador` sem varrer o store) | 1 dia |
| `dadinho:lobby_seq` | INCR para numerar lobbies | — |

- `store.salvar_resumo` é deduplicado por conteúdo (cache em processo) para não reescrever resumo idêntico.
- TTL resolve salas órfãs: função morre sem disconnect → sala expira sozinha.
- Escritas complexas usam `_comando` (body-style POST com array JSON); leituras usam path-style (`GET`/`INCR`/`SCAN`).

## Isolamento por sala e modelagem

- Cada sala é uma room Socket.IO `sala_<id>` (`sala_room()` em `modelos.py`, fonte única do prefixo `sala_`) com seu próprio `Lobby`, `master` e estado. Isolamento via `join_room`/`leave_room` no connect/disconnect e **`emit(..., to=sala_room)`** em toda a cadeia — **nada de `broadcast=True` global**.
- Hierarquia: `Lobby` → `Partida` → `Rodada` → `Turno` (todos em `modelos.py`). Os models **emitem eventos Socket.IO diretamente** (`from flask_socketio import emit`) — a "view layer" é o navegador; `app.py` só registra handlers e faz checagens leves de autenticação.
- A árvore inteira é serializável (`Lobby.para_dict`/`Lobby.de_dict`, refs religadas por `client_id`/índices) para persistir no store. Migração por `versao` via `_migrar` (v1→v2→v3, até `VERSAO_ATUAL`); formato mais novo não é rebaixado.

## Handleratória de eventos (`app.py`)

### Decorators

- `@socketio.on('...')` registra um wrapper interno e devolve a função original → precisa ficar **por fora** de `@evento_mutavel`/`@evento_leitura`/`@autenticar`.
- `evento_mutavel` (escrita): rate limit leve por sid (`tem_cooldown`, `COOLDOWN_ESCRITA`), **lock por sala no processo** (`store.trancar_sala`, cobre o read-modify-write) e aborto silencioso de payload malformado. Eventos idempotentes e espaçados pelo fluxo usam `cooldown=None` (confirmações `conferencia_final`/`vencedor_final` e o commit-reveal `comprometer_seed`/`revelar_seed` — um drop silencioso pelo cooldown deixaria a sala presa).
  - Aborta também em falha de rede/IO do store (`OSError`, `http.client.HTTPException`, Fase B) e invalida o cache da sala (`store.invalidar_cache_sala`) — objeto vivo do cache pode ter sido poluído.
- `evento_leitura`: só o rate limit (`COOLDOWN_BUSCA`), para eventos como `listar_partidas`.
- `autenticar(exigir_master=False, extrair_chave=_chave_simples)`: localiza `(lobby, jogador)` pelo sid, valida a `chave_secreta` (passe `extrair_chave=None` para eventos sem chave), injeta `(dados, lobby, jogador)` no handler. Aposta/desconfiança usam `_chave_aninhada` (chave dentro de `dados['dados']['chave']`).

### Invariantes de todo handler que muta estado

1. Terminar com `salvar_sala(lobby)` (senão turno/rodada se perde entre instâncias).
2. Após mutações de jogo (início, rolagem, aposta, conferência, vitória, expurgo), chamar `ia.processar(lobby)` para o motor de IA avançar até precisar de humano.
3. `emit` sempre com `to=` explícito (room ou `jogador.client_id`).
4. Payload `None`/não-dict não pode estourar — guards `dados = dados or {}` / `isinstance(dict)`.
5. Todo handler novo que o cliente possa chamar com efeito precisa do check de `chave_secreta` (via `autenticar`).

### Identidade e chave secreta

- Player identity = `request.sid`; é a chave no `Lobby` (fonte única de verdade). O estado vivo (`partida_atual`, `rodada_atual`, `turno_atual`, `dados_qtd`, `joguei_dados`) vive como atributos do objeto `Jogador`.
- Cada jogador recebe `chave_secreta` (`secrets.token_hex(16)`) no connect; o cliente ecoa em `joguei_dados`, `aposta` (`dados['chave']`) e `desconfiar`. Todo evento mutável novo precisa desse check.
- **Fase D:** a chave **não trafega na query string** do handshake (vazava em logs). O connect cria um Jogador "placeholder" e a identidade é retomada pela **primeira mensagem** (`retomar_identidade`, `cooldown=None`), que troca o placeholder pela identidade real: religa o sid, encerra a graça, devolve humano substituído por bot, reavalia o master e reemite o snapshot. O cliente só envia `tem_chave` (booleano não-secreto) no handshake.
- Primeira conexão de cada sala vira `master`; reescolha no disconnect via `handle_disconnect` → `achar_jogador` → `Lobby.definir_master()` (ignora bots).
- Índices `client_id → sala_id`: em processo (`funcoes_gerais` `registrar_cliente`/`sala_do_cliente`) e no store (`dadinho:sid:`) alimentam `achar_jogador` e o lock (não substituem o store).

## GC de sala e vida da sala

- **`app.py:_gc_sala`** é o ponto único: expurga a janela de reconexão e fecha a sala quando `app._tem_humano_recente` é falso (sem humano conectado **nem** dentro da janela de reconexão). Chamado em `achar_jogador` (todo handler mutável), `handle_connect` (sala não-vazia) e `verificar_desconectados`; `handle_disconnect` mantém o fechamento explícito pós-lock.
- **Fase 23:** o último humano de uma partida só com IAs ganha a janela de reconexão mesmo sem outro humano ativo — blips (tab em segundo plano estoura `ping_timeout` de 20s, reciclagem da função na Vercel) não removem mais o humano nem apagam a sala; o expurgo fica a cargo de GC posterior (novo humano no connect, `verificar_desconectados` ou TTL do store).
- `funcoes_gerais.remover_sala` limpa store, resumo, índice em processo e sids. O resumo (`humanos`) esconde salas sem humano conectado na busca.
- **`Lobby.marcar_visto()`** (Fase 17): carimbado em `atualizar_lista_usuarios`/`iniciar_partida` e renovado pelo `heartbeat`. A busca descarta resumo sem `visto_em` ou parado há `funcoes_gerais.LIMITE_RESUMO_PARADO_SEGUNDOS` — esconde fantasmas de instância que morreu sem `disconnect`.

## Jogadores IA (`ia.py`, Fase 11/20)

- Bots são `Jogador` com `is_ia=True` e `ia_nivel` (1-4), sem socket (`client_id=ia:<hex>`); **nunca viram master** e a sala é removida quando não resta humano conectado nem na janela de reconexão.
- Cada bot tem **personalidade própria** (`ia_risco`/`ia_agressividade`, 0-1, sorteadas em `criar_ia`/`sorteiar_personalidade`, inclusive ao substituir desconectado): modulam o limiar de desconfiança, a altura das apostas e o tempo de pensamento (`FAIXAS_PENSAMENTO`); ousados/agressivos decidem mais rápido. Ruído por lance mantém o bot imprevisível.
- O motor de decisão é **puro** (só os próprios dados + informação pública — **nunca** `rodada.todos_os_dados`).
- `ia.processar(lobby)` é o orquestrador e roda **dentro do request** (sem threads/timers, serverless-safe): chamado ao fim dos handlers mutáveis, avança rolagem/apostas/conferência/vitória até precisar de humano. Quando **só restam IAs com dados** (`somente_ias_na_partida`), os bots jogam ~30% mais rápido.
- **Fase 69 (partida só de IAs assistida):** quando o último humano com dados é eliminado e há humano na sala sem estar na mesa, `ia.processar` deixa de simular a partida inteira numa tacada e libera **um lance por chamada**, no ritmo do relógio persistido (`Rodada.proximo_lance_em`/`Partida.proximo_lance_em`, `versoes` 8→9). O intervalo é o tempo de pensamento dos bots (`narrador.tempo_pensamento(..., so_ias=True)`), limitado por `INTERVALO_LANCE_MIN_MS`/`MAX`. Quem paga o ritmo é o **poll do espectador** (`espectador_leitura` → `espectador_ritmo` com `restante_ms`); o `heartbeat` entra como rede de segurança e, **sem espectador**, o modo legado volta (simula até acabar) para a sala não ficar presa. Detalhes/decisão no ADR-009.
- Eventos `adicionar_ia`/`completar_com_ias`/`remover_ia` (master + `chave_secreta`, só na espera). Configs `substituir_desconectado_por_ia` e `ia_nivel_padrao`: no expurgo da graça, o desconectado vira bot (preserva dados/turno) se ainda houver outro humano ativo.
- A narração em pt-BR de cada lance e o "tempo de pensamento" vêm de `narrador.py`; o atraso é aplicado no **cliente** (fila serial de eventos em `script.js`), então o servidor continua sem timers.
- Simulação headless: `python simular_ia.py` (neutraliza `emit` e monta o `Lobby` direto; é ferramenta de verificação/balanceamento, não roda dentro do app).

## Verificação provably fair (`seed.py`, Fase 13)

- Opt-in do master (`config.verificacao_ativa`). A entropia é o **nonce secreto do servidor** (revelado só na auditoria); o cliente só compromete depois de ver `compromisso_servidor`.
- Commit-reveal em duas fases: `comprometer_seed` envia **só** `SHA256("dadinho:v1:commit|"+nonce)` (o nonce fica no cliente), imutável (primeiro vale); quando todos comprometem, o servidor emite `seed_revelar` e o cliente responde `revelar_seed` com o nonce, validado contra o compromisso (`Lobby.registrar_revelacao`).
- A revelação é **pública** (`seed_revelacao` para a room): o cliente guarda os nonces e a auditoria em `static/script.js` (`crypto.subtle`) recalcula a seed — trocar um nonce no servidor faz a conferência falhar. `pode_iniciar` só libera com revelações completas.
- O servidor fixa `seed_final` em `Lobby.finalizar_seed()` antes de criar a `Partida` (nonce ausente cai no fallback `H(compromisso)`, marcado `sem_reveal`). Dados e jogador inicial derivam por HMAC (`seed.valor`/`seed.indice_inicial`). Nonces são de uso único por partida (`resetar_para_lobby` zera/regenera).
- O beacon drand (`seed.beacon_*`) não é mais usado: com revelações públicas ele vazaria os dados antes do jogo.

## Tema oficial rotativo (`tema.py`, Fase 12)

- A música de fundo troca a cada 12h **sem agendador**: `tema.tema_atual()` deriva a composição deterministicamente de uma janela de 12h (00:00/12:00 UTC) e `gerar_musica.gerar_variante(seed)` gera o MIDI; toda instância chega ao mesmo arquivo, sem estado persistente.
- Servida em `GET /tema.mid` (única exceção REST além de `/`) com `Cache-Control` expirando na virada da janela e fallback para `static/sons/dadinho_tema.mid` versionado; o cliente busca a rota em `iniciar_musica` (`script.js`).
- `DADINHO_TEMA_SEED` congela uma música escolhida (curadoria via `python gerar_musica.py -n N`).

## Deploy/entrypoint

- `api/index.py` exporta `application = app.wsgi_app` (middleware Socket.IO); `vercel.json` usa builder `@vercel/python` com rota catch-all. `app.secret_key` vem de `DADINHO_SECRET_KEY` (fallback dev `supersecretkey`).
- Transporte: `DADINHO_ASYNC_MODE`, `DADINHO_PERMITIR_WEBSOCKET` (default `true`; `=0` desliga o upgrade). O cliente pede `['websocket']` (transporte **único**, `static/script.js`; Fase 66/ADR-008) — Vercel suporta WebSocket nativamente desde jun/2026; o WS prende a conexão numa instância; o long-polling quebrava porque cada request de poll caía numa instância sem a sessão Engine.IO (`Invalid session`), e na VPS multi-réplica o polling fragmentava quando o IP real mudava no meio da conexão (rede móvel). O erro de WS agora é sinalizado ao usuário (Fase 65/M1).

## Deploy na VPS (Fase 46)

**Cenário:** a Vercel não garante a persistência dos processos (serverless recicla a função e derruba o socket). Com uma VPS, a API vira um **processo persistente** (Docker + gunicorn) e o frontend continua na Vercel. Detalhes operacionais em `docs/verificacao.md`.

- **Topologia:** "só a API na VPS" — a Vercel continua servindo a página (`/`, estáticos, `/tema.mid`, robots/sitemap); o `io()` do cliente conecta **cross-origin** na VPS. A URL da API é injetada no template pelo servidor: `DADINHO_API_URL` → `<meta name="dadinho-api-url">` → `static/script.js` (`io(api_url || undefined, {...})`). Vazio = mesmo host (regressão zero no deploy 100% Vercel).
- **CORS:** `DADINHO_CORS_ORIGINS` (lista separada por vírgula ou `*`) no `SocketIO(...)`; vazio = same-origin (comportamento atual). O CSP `connect-src` inclui a origem da API quando `DADINHO_API_URL` está definida.
- **Estado:** `store.py` ganhou `ArmazenamentoRedis` (Redis TCP local via redis-py, mesmo layout/TTL do Upstash) selecionado por `DADINHO_REDIS_URL` (ex.: `redis://redis:6379/0` no docker-compose). O lock distribuído (`trancar_sala_distribuida`) também funciona sobre ele (SET NX/EX + DELEX IFEQ via script Lua). A message queue (`DADINHO_MESSAGE_QUEUE`) usa o MESMO Redis local (`redis://`) para emits entre instâncias.
- **Execução:** `Dockerfile` + `docker-compose.yml` sobem `api` (gunicorn `-w 1 --threads 100`, async_mode `threading` + simple-websocket = WebSocket OK) e `redis:7-alpine` com AOF. `-w 1` é obrigatório: o load balancer do gunicorn não faz sticky session (escala = múltiplas instâncias atrás de um LB + message queue).
- **Exposição (Cloudflare Tunnel):** a porta 8000 da API fica **em loopback** (`127.0.0.1:8000`); o container `dadinho-tunnel` (`cloudflare/cloudflared`, `network_mode: host`) expõe `dadinho-api.memetrigger.com → http://localhost:8000` via ingress local em `cloudflared/config.yml` (exemplo versionado). No DNS da zona é preciso um **CNAME manual** `dadinho-api → <tunnel-id>.cfargotunnel.com` (a "hostname route" do painel não cria o CNAME). O UFW da VPS não abre porta nova.
- **Diferença vs. serverless:** na VPS o heartbeat/re-sync entre instâncias continua funcionando (harmless), mas a instância única + message queue local eliminam o gap de tempo real da partida que existia entre instâncias da Vercel.

## Limitação conhecida (parcialmente mitigada)

Rooms/emits do Socket.IO vivem em memória **por instância**; dois jogadores podem cair em instâncias diferentes e não ver os emits um do outro (o estado persiste no Upstash e é reidratado no reconnect).

- **Sala de espera:** gap coberto pelo re-sync do heartbeat (Fases 18/19): o cliente bate a cada 20s e o servidor responde `update_user_list` direcionado ao cliente que bateu, lido do store compartilhado (`montar_payload_lista_usuarios`). **Fase E2:** a espera SEMPRE recarrega o estado **fresco do store em toda batida** (não o cache) — antes, o não-master recebia lista defasada e o início da partida só era detectado quando o cache expirava (regressão guardada em `verificar.py` como `heartbeat-espera-fresco`). **Fase E:** o heartbeat também re-sincroniza página — se `pagina` do cliente divergir da autoritativa, devolve `enviar_snapshot_sala`; o botão de iniciar do master fica sempre ativo (servidor valida `pode_iniciar` fresco e devolve `iniciar_negado` com motivo).
- **Heartbeat da partida:** cadência 60s; `heartbeat` **não passa por `autenticar`** (um GET + deserialização na Upstash por batida estourava o free tier), usa índice em processo + cache tolerante a defasagem `store.carregar_sala_leve` (TTL 25s, por sala, atualizado a cada `salvar_sala`). Com estado do cache ele **não roda `ia.processar`** (mutação só com leitura fresca). Piso do `visto_em` de 60s para não reescrever o resumo a cada batida curta.
- **Gap durante a partida** (apostas/turnos em tempo real entre instâncias) continua; se quebrar partidas de verdade, a saída é um message queue (`socketio.RedisManager` via Upstash/Redis TCP) — iteração futura.
- **Refresh/reconnect (Fase 73):** o rejoin é o caminho mais pesado (dois round-trips: `handle_connect` placeholder + `retomar_identidade`). Como os abortos de lock/stale são silenciosos, o cliente ganhou um **watchdog de `connect_start`** (derruba/reabre a conexão se o handshake não completar em ~9s) e o servidor passou a **logar os abortos** (`connect_abortado` em `handle_connect`, `handler_abortado` em `evento_mutavel`) — antes, a recuperação dependia do ping timeout do socket.io (~20s+). Não substitui o snapshot; só encurta a janela até a próxima tentativa.