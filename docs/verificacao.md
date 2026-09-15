# Verificação e deploy — Dadinho

## Verificar (local, repo root, usar `.venv`)

- **`python verificar.py`** — script único de verificação (Fase 10, fundido no repo):
  - `py_compile` de todos os módulos Python;
  - `node --check` de `static/script.js` e `static/i18n.js`;
  - cobertura i18n (4 idiomas em relação ao inglês — toda chave precisa existir nos 5 dicionários);
  - boot com `VERCEL=1` respondendo 200;
  - round-trip e migrações de serialização (v1→v3 / v2→v3);
  - integração via `flask_socketio.test_client` cobrindo Fases 6/7 (B3/B6/B1/B7/B2/B4, A3/A6/V3/V2/A4/A5 + partida completa) e `teste_retomar_identidade_por_evento` (Fase D);
  - regressões guardadas: `heartbeat-espera-fresco` (Fase E2).
- **`python simular_ia.py --partidas 20 --dados 3`** — simulação headless dos bots (hierarquia 4>3>2>1 preservada, sem travamentos). Uso de balanceamento/verificação, não roda dentro do app.
- **Sempre complementar com o teste manual em dois browser tabs**: criar sala, rodar partida completa até vitória. Único meio de verificação real do comportamento em produção.

## Publicar na Vercel (fluxo real, Fase 3 do `todo.md`)

0. **Produção atual:** https://dadinho.memetrigger.com (domínio custom do projeto `dadinho` da Vercel, scope `fbsagats-projects`; alias de projeto também em https://dadinho-hazel.vercel.app). Git integration conectado ao `fbsagat/DadinhoPy` com **Production Branch = `master`**.

1. **Pré-requisitos:** conta Vercel + CLI logado (`vercel whoami`), e um banco Redis REST da Upstash (node → panel → create database; copiar URL REST e token REST). Sem Upstash o código cai silenciosamente em `ArmazenamentoMemoria` (`store.py:257-266`), quebra o estado entre instâncias serverless — só serve para validar na hora.

2. **Env vars na Vercel** (dashboard → Settings → Environment Variables, ou `vercel env add <NOME> production`):
   - `DADINHO_SECRET_KEY` — string longa aleatória (`secrets.token_hex(32)`).
   - `UPSTASH_REDIS_REST_URL` e `UPSTASH_REDIS_REST_TOKEN` — o par REST do banco Upstash.
   - `VERCEL=1` é setado automaticamente pela plataforma (muda transportes/`socketio.run`); `DADINHO_PERMITIR_WEBSOCKET` e `DADINHO_ASYNC_MODE` não precisam de valor (padrão já é o correto em produção).

3. **Publicar:** `git push origin master` — a git integration deploya e promove para produção automaticamente (Production Branch = `master`), e `dadinho.memetrigger.com` acompanha na hora. Não é preciso `vercel --prod` manual; use apenas pontualmente se quiser publicar um estado local sem push (`.vercelignore` exclui `.venv`/`.idea`/`__pycache__`).

4. **Validar:** abrir a URL de produção em 2+ abas/navegadores/dispositivos, criar sala, rodar partida completa até vitória.

## Notas operacionais (validadas na Fase 3)

- **Hobby (free):** função serverless até 300s (5 min); 2 GB memória; concorrência ~30k; região única (`iad1`, Virgínia); ~100 deploys/dia. WebSocket é o transporte padrão (beta na Vercel, jun/2026): a conexão fica presa a uma instância e só cai ao atingir a duração máxima da função (cliente reconecta), evitando o loop de reconexão do long-polling.
- **Upstash free:** 256 MB, 500 mil comandos/mês, 10 GB banda. Detalhes do layout das chaves em `docs/arquitetura.md`. `salvar_resumo` é deduplicado por conteúdo em processo (não reescreve resumo idêntico). TTL resolve salas órfãs (função morreu sem disconnect → a sala expira sozinha).
- **Custo do heartbeat (Fase C):** cadência da espera 5s → 20s; `heartbeat` não passa por `autenticar`; partida usa o cache tolerante `store.carregar_sala_leve` (TTL 25s) e só a espera recarrega fresco; piso do `visto_em` 30s → 60s. Estourava o free tier com poucos jogadores ociosos.
- **Limitação conhecida:** rooms/emits do Socket.IO vivem por instância → dois jogadores podem cair em instâncias diferentes e não ver emits um do outro (estado persiste no Upstash e é reidratado no reconnect). Coberta na espera pelo re-sync do heartbeat; gap durante a partida é iteração futura (message queue). Detalhes em `docs/arquitetura.md`.
- **Sem leaderboard/estado de longo prazo:** casual only; o store guarda só o lobby atual de cada sala.
- **Proteção de deploy (Vercel Authentication):** o projeto tem `ssoProtection` = `all_except_custom_domains`. Os domínios registrados (`dadinho.memetrigger.com` e `dadinho-hazel.vercel.app`) são isentos e servem o jogo; os aliases `.vercel.app` não-registrados (ex.: `dadinho-git-master-fbsagats-projects.vercel.app`) caem na tela de login/proteção da Vercel — não é outra versão do deploy.
- **Segredos:** `DADINHO_SECRET_KEY`/tokens Upstash vêm de env vars — não comitar. Não subir `.env*`/`.vercel` (OIDC token) para a Vercel.

## Publicar na VPS (Fase 46 — API própria em processo persistente)

Cenário: a Vercel sozinha não garante a persistência dos processos (serverless recicla a
função e derruba o socket). Com uma VPS, a **API** (Socket.IO) roda como processo
persistente em Docker; o **frontend continua na Vercel** (só a API na VPS).

1. **Repositório:** o `Dockerfile`/`docker-compose.yml` na raiz sobem a API (gunicorn
   `threading` + simple-websocket, `-w 1` obrigatório — sem sticky session no gunicorn)
   e um Redis local com AOF (`redis:7-alpine`).

2. **Variáveis de ambiente no `.env` da VPS** (ou no ambiente):
   - `DADINHO_REDIS_URL=redis://redis:6379/0` — estado do jogo (`store.ArmazenamentoRedis`).
   - `DADINHO_MESSAGE_QUEUE=redis://redis:6379/0` — emits entre instâncias no mesmo Redis.
   - `DADINHO_SECRET_KEY` — string longa aleatória (`secrets.token_hex(32)`).
   - `DADINHO_CORS_ORIGINS` — origens do frontend (Vercel). Ex.:
     `https://dadinho.memetrigger.com,https://dadinho-hazel.vercel.app`, ou `*` (casual).
   - `DADINHO_PERMITIR_WEBSOCKET=true`.

3. **Frontend apontando para a VPS:** na Vercel, setar `DADINHO_API_URL` (ex.:
   `https://api.dadinho.memetrigger.com`). O servidor injeta essa URL no `<meta
   name="dadinho-api-url">` e o `script.js` conecta o `io()` na VPS (CSP `connect-src`
   já cobre). Vazio = mesmo host (regressão zero).

4. **Subir:** `docker compose up -d` (na VPS). Validar com 2+ abas/navegadores conectando
   na VPS (a página vem da Vercel, o socket vai para a VPS).

5. **Proxy/TLS:** colocar nginx/Caddy na frente do container (porta 8000) para HTTPS +
   `ip_hash` se escalar para múltiplas instâncias de API atrás do mesmo domínio.
   **Obrigatório:** a página vem da Vercel em HTTPS; se `DADINHO_API_URL` apontar para
   `http://` (sem TLS), o browser bloqueia o socket (mixed content) e ninguém conecta.
   `DADINHO_REDIS_URL`/`DADINHO_MESSAGE_QUEUE` são para a VPS — a Vercel não alcança um
   Redis local (e o boot com `VERCEL=1` segue exigindo o Upstash).

## Observabilidade e alertas (Fase 43)

- **Error tracking:** adiado — o mantenedor decidiu não usar Sentry por enquanto. Se retomado, a
  opção avaliada era `sentry-sdk` opt-in por env `SENTRY_DSN` (capturar aborts silenciosos de
  rede/store/lock em `evento_mutavel` e blobs corrompidos no `store.py`, com
  `max_request_body_size="never"` + redação de Authorization/cookies, sem PII). Ver `todo.md` O1.
- **Alerta de custo/uso Vercel:** regra `dadinho - anomalia de uso (invocacoes/duration)` (id
  `ar_01a0a21c-43cd-74fc-9f93-a67a7461f7f0`, project `dadinho`) — `usage_anomaly` nas métricas
  `function_invocations` e `fluid_duration` (detecção de anomalia, não teto fixo). Gerenciar via
  `vercel alerts rules add/ls/rm --body <json>` (schema: `vercel alerts rules schema --type usage_anomaly`).
- **Alerta Upstash (manual, pendente):** no console da Upstash → database → **Alerts**, criar alertas de
  **comandos/mês** (free tier = 500 mil — sugestão: alertar a ~400 mil, 80%) e de **banda** (10 GB —
  sugestão: ~8 GB). Não há CLI para isso; conferir no painel antes de um pico de abuso pegar de surpresa.
- **Funil sem PII (Fase 42):** Vercel Web Analytics com eventos `sala_criada`/`partida_iniciada`/
  `partida_concluida`/`jogador_saiu_antes` — sem `client_id`/`chave_secreta` (habilitar no dashboard).