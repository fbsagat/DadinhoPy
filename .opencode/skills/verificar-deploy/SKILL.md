---
name: verificar-deploy
description: Use ao verificar, testar ou publicar o Dadinho — "verificar", "verificar.py", "rodar testes", "simular_ia", "deploy", "publicar", "Vercel", "Upstash". Cobre o pipeline local, o boot e o fluxo de deploy com validação.
---

# Verificação e deploy — Dadinho

Pipeline completo de verificação local e publicação na Vercel. Referência estendida em `docs/verificacao.md`.

## 1. Verificação local (repo root, usar `.venv`)

- **`python verificar.py`** — único script (Fase 10): `py_compile` de todos os módulos, `node --check` de `static/script.js` e `static/i18n.js`, cobertura i18n (5 idiomas), boot `VERCEL=1` respondendo 200, round-trip/migração de serialização e integração `flask_socketio.test_client` (Fases 6/7 + `retomar_identidade` + `heartbeat-espera-fresco`). **Tudo verde é pré-requisito para deploy.**
- **`python simular_ia.py --partidas 20 --dados 3`** — hierarquia dos bots 4>3>2>1 preservada, sem travamentos.
- **Teste manual obrigatório em 2 browser tabs:** criar sala, partida completa até vitória. Único meio de verificação do comportamento real.
- Rodar o servidor em dev: `python app.py` → http://localhost:5000.

## 2. Boot / produção

- Produção: https://dadinho-hazel.vercel.app (projeto `dadinho`, scope `fbsagats-projects`, GitHub `fbsagat/DadinhoPy`).
- Sem Upstash configurado o código cai em memória (`store.py:257-266`) — só serve para validar local.

## 3. Deploy (Vercel)

1. Pré-requisitos: `vercel whoami` logado; banco Redis REST da Upstash (URL REST + token REST).
2. Env vars em produção:
   - `DADINHO_SECRET_KEY` (`secrets.token_hex(32)`);
   - `UPSTASH_REDIS_REST_URL` e `UPSTASH_REDIS_REST_TOKEN`;
   - `VERCEL=1` automático; `DADINHO_PERMITIR_WEBSOCKET`/`DADINHO_ASYNC_MODE` deixam o default.
3. **`vercel --prod`** (ou git integration / push). `.vercelignore` exclui `.venv`/`.idea`/`__pycache__`/`.env*`/`.vercel`.
4. Validar em 2+ abas/navegadores, partida completa. Checar `API commands` no painel da Upstash se algo parar (orçamento de 500k comandos/mês).

## Alertas

- Nunca comitar `.env*` nem `.vercel` (token OIDC). `app.secret_key` vem de `DADINHO_SECRET_KEY`.
- Mudanças de `opencode.json`/`.opencode/` exigem reiniciar o opencode (config não é hot-reload).
- Regressões importantes ganham cobertura em `verificar.py` (padrão do projeto: `teste_*` no script).