# ADR-004 — Anti-fraude heurístico + observabilidade; captcha opt-in

- **Status:** Aceito
- **Contexto:** Fase 59 do `todo.md` (hardening da VPS)
- **Decisores:** mantenedor

## Contexto

Sendo um jogo de blefe, um **script automatizado** tem vantagem injusta: joga mais
rápido que o razoável, calcula a probabilidade ótima sem errar e fica 24/7 farmando
partidas. Bloquear por IP sozinho é grosseiro (NAT, VPN) e um captcha permanente
mata a experiência casual (fricção no `connect`).

Forças: casual only (sem contas), pouca memória de longo prazo no servidor, e
necessidade de **não punir** o jogador humano ocasional com latência artificial
injustificada.

## Decisão

Duas camadas complementares:

1. **Anti-fraude heurístico** (`anti_fraude.py`) — analisa padrões em processo:
   - `tempo_entre_acoes`: aposta em < 200ms de forma consistente;
   - `desconfianca_em_rajada`: 3+ desconfianças em 5s;
   - `acuracia_binomial`: acerto de apostas otimamente calculadas acima do
     plausível humano (amostra mínima + taxa suspeita);
   - `padrao_horario`: atividade 24/7 sem pausas.
   Suspeito recebe flag no `Jogador` e um **delay adicional** (`delay_adicional`),
   nunca um ban imediato. `limpar(client_id)` zera o estado no `disconnect` e há
   teto de `client_id`s rastreados (`MAX_CLIENTES`) — a heurística é por socket,
   sem crescer sem limite no processo persistente da VPS.

2. **Observabilidade** (`observabilidade.py`) — `log_evento_suspeito(tipo,
   client_id, ip, dados)` e `log_redigido` emitem JSON no stdout, com **redação de
   campos sensíveis** (`chave_secreta`, `nonce_seed`, dados do jogador nunca vão
   para o log).

3. **Captcha opt-in** — `DADINHO_CAPTCHA_ATIVO` (default `false`): quando
   estourado o rate limit/abuso, o `connect` passa a exigir `hcaptcha_token`
   validado em `api.hcaptcha.com/siteverify` (só liga de fato com SITEKEY +
   SECRET; faltando um, fica desligado para não bloquear todos os connects); o
   widget é carregado sob demanda no frontend. Ligado só durante picos, não como
   estado permanente.

O índice `dadinho:ip:<ip>` (SET de `client_id`s ativos, TTL) habilita o limite de
sockets simultâneos por IP (`DADINHO_LIMITE_SOCKETS_IP`, **0 = desligado** por
padrão; ativar em picos, com folga para NAT/CGNAT) — limita farming de contas sem
bloquear IP.

## Consequências

- Positivas: bots ficam mais lentos que humanos (perdem a vantagem) sem afetar a
  maioria legítima; evidência de abuso fica auditável em log estruturado; zero
  fricção no fluxo normal (captcha off).
- Positivas: nada de ban automático — humano com padrão estranho continua jogando.
- Negativas: heurística tem teto (bot lento e paciente passa); estado é por
  partida, então o histórico não persiste entre sessões; captcha é validação de
  rede externa (outra dependência em pico de abuso).
- Proíbe: logar `chave_secreta`/`nonce_seed`/dados do jogador (usar
  `log_redigido`); banir por IP; tornar o captcha obrigatório por padrão.