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

0. **Produção atual:** https://dadinho-hazel.vercel.app (projeto `dadinho` da Vercel, scope `fbsagats-projects`, GitHub `fbsagat/DadinhoPy` conectado).

1. **Pré-requisitos:** conta Vercel + CLI logado (`vercel whoami`), e um banco Redis REST da Upstash (node → panel → create database; copiar URL REST e token REST). Sem Upstash o código cai silenciosamente em `ArmazenamentoMemoria` (`store.py:257-266`), quebra o estado entre instâncias serverless — só serve para validar na hora.

2. **Env vars na Vercel** (dashboard → Settings → Environment Variables, ou `vercel env add <NOME> production`):
   - `DADINHO_SECRET_KEY` — string longa aleatória (`secrets.token_hex(32)`).
   - `UPSTASH_REDIS_REST_URL` e `UPSTASH_REDIS_REST_TOKEN` — o par REST do banco Upstash.
   - `VERCEL=1` é setado automaticamente pela plataforma (muda transportes/`socketio.run`); `DADINHO_PERMITIR_WEBSOCKET` e `DADINHO_ASYNC_MODE` não precisam de valor (padrão já é o correto em produção).

3. **Publicar:** `vercel --prod` (submete o diretório local; `.vercelignore` exclui `.venv`/`.idea`/`__pycache__`). Alternativa: git integration (push builda automaticamente).

4. **Validar:** abrir a URL de produção em 2+ abas/navegadores/dispositivos, criar sala, rodar partida completa até vitória.

## Notas operacionais (validadas na Fase 3)

- **Hobby (free):** função serverless até 300s (5 min); 2 GB memória; concorrência ~30k; região única (`iad1`, Virgínia); ~100 deploys/dia. WebSocket é o transporte padrão (beta na Vercel, jun/2026): a conexão fica presa a uma instância e só cai ao atingir a duração máxima da função (cliente reconecta), evitando o loop de reconexão do long-polling.
- **Upstash free:** 256 MB, 500 mil comandos/mês, 10 GB banda. Detalhes do layout das chaves em `docs/arquitetura.md`. `salvar_resumo` é deduplicado por conteúdo em processo (não reescreve resumo idêntico). TTL resolve salas órfãs (função morreu sem disconnect → a sala expira sozinha).
- **Custo do heartbeat (Fase C):** cadência da espera 5s → 20s; `heartbeat` não passa por `autenticar`; partida usa o cache tolerante `store.carregar_sala_leve` (TTL 25s) e só a espera recarrega fresco; piso do `visto_em` 30s → 60s. Estourava o free tier com poucos jogadores ociosos.
- **Limitação conhecida:** rooms/emits do Socket.IO vivem por instância → dois jogadores podem cair em instâncias diferentes e não ver emits um do outro (estado persiste no Upstash e é reidratado no reconnect). Coberta na espera pelo re-sync do heartbeat; gap durante a partida é iteração futura (message queue). Detalhes em `docs/arquitetura.md`.
- **Sem leaderboard/estado de longo prazo:** casual only; o store guarda só o lobby atual de cada sala.
- **Segredos:** `DADINHO_SECRET_KEY`/tokens Upstash vêm de env vars — não comitar. Não subir `.env*`/`.vercel` (OIDC token) para a Vercel.