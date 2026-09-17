# ADR-008 — WebSocket como transporte único (revisa o sticky por IP do ADR-006)

- **Status:** Aceito
- **Contexto:** Fases 64–66 do `todo.md`; revisa a premissa de sticky do ADR-006
- **Decisores:** mantenedor

## Contexto

O ADR-006 introduziu 4 réplicas gevent atrás do nginx com
`hash $ip_real consistent;` para manter a session Engine.IO na mesma réplica. A
decisão assumia como premissa que **o IP real é estável** durante uma conexão.

O bug "criar sala trava no mobile" (Fases 64–66) mostrou que a premissa não se
sustenta em **rede móvel**: sob CGNAT da operadora, troca de torre ou
alternância wifi↔dados, o `Cf-Connecting-Ip` pode mudar **no meio** de uma
tentativa de conexão. Como o cliente usava `['websocket', 'polling']`, as
requests de polling da MESMA tentativa podiam hashear para réplicas diferentes —
que não compartilham a sessão Engine.IO — e a conexão nunca fechava. O cliente
seguia tentando em silêncio (`connect_error` genérico caía num `return`), então
a tela parecia normal e o clique não fazia nada.

Forças: o polling é o transporte que fragmenta (sequência de requisições
independentes). O WebSocket handshake é um **único** upgrade HTTP.

## Decisão

**WebSocket como transporte único** (`transports: ['websocket']` no cliente,
`static/script.js`).

- A tentativa de conexão inteira passa a ser **um** upgrade HTTP: uma única
  decisão de roteamento do nginx. O sticky por IP deixa de ser necessário para
  a conexão **funcionar** — passa a importar só para distribuição de carga.
- O sticky por IP do ADR-006 é **mantido** (ainda espalha as conexões); o que
  muda é que uma conexão não depende mais dele.
- A Fase 65/M1 garante que, quando o WS não fecha, o erro é **explícito**
  (`status_conexao` → "sem conexão" após N tentativas) em vez de hang silencioso.

**Rejeitada (Opção B):** sticky por cookie de sessão Engine.IO
(`hash $cookie_io`). Mais robusto, mas exige `withCredentials: true` no cliente
(handshake/polling cross-origin Vercel↔VPS), CORS com `supports_credentials` e
cookie `SameSite=None; Secure` — mais partes móveis e risco para ganho marginal
sobre o WS puro.

## Consequências

- Positivas: o bug do IP móvel deixa de afetar a conexão; some a dependência de
  o polling cair sempre na mesma réplica.
- Positivas: menos requests (sem upgrade + polling) e um caminho de falha
  observável (Fase 65).
- Negativas / trade-off: redes que **bloqueiam WebSocket cru** (algumas
  corporativas/escolares; raro em operadora) perdem o fallback de polling — vira
  `connect_error` explícito em vez de degradar. Aceito no casual.
- Proíbe: reintroduzir `'polling'` em `transports` **sem** resolver o sticky da
  sessão Engine.IO (é exatamente a regressão que este ADR fecha). Se um dia o
  polling voltar, precisa de sticky por cookie/session-id com credenciais
  cross-origin tratadas.
