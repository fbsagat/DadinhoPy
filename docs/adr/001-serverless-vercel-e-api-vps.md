# ADR-001 — Serverless na Vercel com store distribuído e API persistente opcional na VPS

- **Status:** Aceito
- **Contexto:** Fases 2 e 46 do `todo.md` (decisão contínua desde o início do projeto)
- **Decisores:** mantenedor

## Contexto

O jogo é casual, sem contas, e precisa rodar barato. A plataforma escolhida foi a
Vercel (Python serverless), que **recicla a função** e derruba o socket; o estado
não pode viver na memória do processo. Ao mesmo tempo, o Socket.IO se beneficia de
um processo persistente — o que a Vercel não garante.

Forças em jogo:
- custo baixo / sem servidor para manter;
- múltiplas instâncias serverless (estado obrigatório fora do processo);
- WebSocket é o transporte preferido (Vercel tem suporte a WS em beta);
- sem contas/leaderboard — o estado é por partida e pode ser regenerado.

## Decisão

**Serverless-first na Vercel**, com todo o estado de jogo no **store distribuído**
(`store.py`), escolhido por env var:

- `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` → `ArmazenamentoUpstash`
  (Redis REST, usado na Vercel);
- `DADINHO_REDIS_URL` → `ArmazenamentoRedis` (Redis TCP, usado na VPS);
- `DADINHO_STORE=memoria` → `ArmazenamentoMemoria` (só dev local).

Como o serverless sofre com o reciclo do socket, foi aberta uma **segunda
topologia suportada**: a **API** roda como processo persistente na VPS (Docker +
gunicorn + nginx + Redis local), enquanto o **frontend continua na Vercel**. O
`script.js` lê `<meta name="dadinho-api-url">` (`DADINHO_API_URL`) e conecta o
Socket.IO à VPS; vazio = mesmo host (regressão zero, caminho Vercel puro).

O código é o **mesmo** nas duas topologias: sem estado em memória entre requests,
sem threads/timers no servidor, `socketio.run` condicionado a `VERCEL != 1`. A VPS
é um **deploy alternativo**, não um caminho paralelo.

## Consequências

- Positivas: deploy quase gratuito e sem operação; escala automática na Vercel;
  o esforço de "estado no store" (Fase 8) já habilita escala horizontal em
  qualquer topologia.
- Positivas: a API na VPS resolve o socket persistente sem reescrever o app.
- Negativas: o código precisa ser **serverless-safe para sempre** — quebra da
  invariante em qualquer topologia quebra a Vercel; o mesmo estado é acessado por
  latência de rede (REST/TCP), não ponteiro local.
- Proíbe: guardar estado de sala em variável global/dicionário de módulo, usar
  threads/timers de fundo, `broadcast=True` global (ver ADR-002) ou assumir um
  único lobby. Detalhes dos invariantes no `AGENTS.md`.