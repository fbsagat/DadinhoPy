---
name: verificar-deploy
description: Use ao verificar, testar ou publicar o Dadinho — "verificar", "verificar.py", "rodar testes", "simular_ia", "deploy", "publicar", "Vercel", "VPS", "atualizar_vps", "Upstash". Cobre o pipeline local, o boot e o fluxo de deploy com validação.
---

# Verificação e deploy — Dadinho

Pipeline completo de verificação local e publicação. Referência estendida em `docs/verificacao.md`. **Produção = frontend na Vercel + API em Docker na VPS** (estado no `dadinho-redis`); o caminho 100% Vercel (Upstash) segue suportado como alternativa.

## 1. Verificação local (repo root, usar `.venv`)

- **`python verificar.py`** — único script (Fase 10): `py_compile` de todos os módulos, `node --check` de `static/script.js` e `static/i18n.js`, cobertura i18n (5 idiomas), boot `VERCEL=1` respondendo 200, round-trip/migração de serialização e integração `flask_socketio.test_client` (Fases 6/7 + `retomar_identidade` + `heartbeat-espera-fresco` + store Redis TCP/lock da Fase 46). **Tudo verde é pré-requisito para deploy.**
- **`python simular_ia.py --partidas 20 --dados 3`** — hierarquia dos bots 4>3>2>1 preservada, sem travamentos. Adicionar `--estilo prudente` quando mexer no arquétipo da Fase 76.
- **Teste manual obrigatório em 2 browser tabs:** criar sala, partida completa até vitória. Único meio de verificação do comportamento real.
- Rodar o servidor em dev: `python app.py` → http://localhost:5000.

## 2. Boot / produção

- Produção: frontend em https://dadinho.memetrigger.com (projeto `dadinho`, scope `fbsagats-projects`, GitHub `fbsagat/DadinhoPy`); API/socket em https://dadinho-api.memetrigger.com (VPS).
- Sem store configurado o código cai em memória em dev — só serve para validar local. Com `VERCEL=1` o boot **falha de propósito** (`store.py:1106-1127`): é por isso que a função da Vercel exige as envs do Upstash mesmo com a API na VPS.

## 3. Deploy (Vercel — frontend)

1. Pré-requisitos: `vercel whoami` logado; banco Redis REST da Upstash (URL REST + token REST) para a função subir.
2. Env vars em produção:
   - `DADINHO_SECRET_KEY` (`secrets.token_hex(32)`);
   - `UPSTASH_REDIS_REST_URL` e `UPSTASH_REDIS_REST_TOKEN`;
   - `DADINHO_API_URL` = URL da API na VPS (vazio = tudo na Vercel, estado no Upstash);
   - `VERCEL=1` automático; `DADINHO_PERMITIR_WEBSOCKET`/`DADINHO_ASYNC_MODE` deixam o default.
3. **`git push origin master`** (git integration; `vercel --prod` só pontualmente). `.vercelignore` exclui `.venv`/`.idea`/`__pycache__`/`.env*`/`.vercel`.
4. Validar em 2+ abas/navegadores, partida completa. Estado de jogo **não** está no Upstash no deploy atual (está no Redis da VPS) — o painel da Upstash só serve para o caminho 100% Vercel.

## 3.1 Deploy (VPS — **produção da API**; Fases 46/77)

Sem auto-deploy e sem git em `/opt/dadinho`: **`.\atualizar_vps.ps1 -Chave <caminho>`**
(copia com tar preservando `.env`/`cloudflared/config.yml`, `--build` de `api api2 api3 api4 nginx gc`,
recreate do tunnel **só** se `docker-compose.yml` mudou, smoke test com `gc --uma-vez` + borda nginx + público).
Procedimento passo a passo e o que cada container faz: `docs/verificacao.md` § VPS.

- Serviço novo no compose tem que entrar no `up` do script — se não entrar, o deploy
  "passa" e o serviço fica parado (foi o caso do `gc` na Fase 77).
- Depois do deploy, `docker compose ps gc` tem que estar `Up`; serviço em restart-loop
  é env faltando (quase sempre `DADINHO_REDIS_URL`) — `docs/runbook.md` §8.2.

## Alertas

- Nunca comitar `.env*` nem `.vercel` (token OIDC). `app.secret_key` vem de `DADINHO_SECRET_KEY`.
- Mudanças de `opencode.json`/`.opencode/` exigem reiniciar o opencode (config não é hot-reload).
- Regressões importantes ganham cobertura em `verificar.py` (padrão do projeto: `teste_*` no script).