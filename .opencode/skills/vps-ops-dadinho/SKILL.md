---
name: vps-ops-dadinho
description: Use ao operar, diagnosticar ou responder a incidentes do Dadinho em produção (VPS + Vercel) — "runbook", "incidente", "VPS caiu", "API fora do ar", "tunnel", "cloudflared", "redis down", "rate limit", "502", "unhealthy", "rollback", "deploy quebrado", "docker compose logs/ps". Direciona a triagem e o playbook certo.
---

# Skill: operação e incidente da VPS do Dadinho

Fonte de verdade: **`docs/runbook.md`** (playbooks por sintoma). Deploy de rotina:
**`docs/verificacao.md`**. Decisões/porquês: **`docs/adr/`**. Não improvise
comandos destrutivos — leia o playbook.

## Triagem em 30s (ordem do runbook)

1. `curl -s -o /dev/null -w 'api:%{http_code}\n' http://127.0.0.1:8000/robots.txt`
   (na VPS) — API não subiu → réplica/Redis.
2. `curl -s -o /dev/null -w 'nginx:%{http_code}\n' http://127.0.0.1:8080/robots.txt`
   — local ok, borda não → §4 (nginx/tunnel).
3. `curl -s -o /dev/null -w '%{http_code}\n' https://dadinho-api.memetrigger.com/robots.txt`
   — borda ok, público não → §4 (tunnel/DNS/Cloudflare).
4. Tudo responde mas o jogo trava → §6/§8 (Redis/lock/estado).

## Comandos básicos (na VPS, `cd /opt/dadinho`)

```bash
sudo docker compose ps
sudo docker compose logs -f --tail=200 api     # as 4 réplicas
sudo docker compose logs -f --tail=200 nginx   # JSON: ip_real + status
sudo docker inspect --format '{{.Name}} {{.State.Health.Status}}' dadinho-api dadinho-api-2 dadinho-api-3 dadinho-api-4
sudo docker exec -it dadinho-redis redis-cli ping
```

Componentes: `dadinho-api`/`-2`/`-3`/`-4` (gevent, 8000–8003), `dadinho-nginx`
(loopback 8080), `dadinho-redis` (AOF + message queue), `dadinho-tunnel`. As 4
réplicas sobem juntas: `up -d --build api api2 api3 api4 nginx`.

## Regras de ouro (violá-las causa perda de estado)

- **Nunca** `rm -rf /opt/dadinho/*` — apaga `.env` e `cloudflared/config.yml`
  (não estão no repo). Use `atualizar_vps.ps1` (tar com excludes preserva os dois).
- **Nunca** `docker compose down -v` sem intenção — apaga o volume do Redis (AOF).
- **Não** edite blobs de sala no Redis à mão (serialização de `Lobby`, comprimida
  com `gz1:`); descarte/recrie a sala.
- **Não** aponte o tunnel para `:8000` — a borda é o nginx em `:8080` (ADR-003).
- Lock distribuído tem TTL 120s: **não** "destrave à mão", ele expira sozinho.
- Redis é SPOF conhecido e aceito (ADR-007): perda de volume = perda das salas
  ativas; recuperação é subir o Redis e deixar regenerar, não "consertar".

## Quando abrir ADR novo

Se a causa raiz **contraria** um ADR/invariante do `AGENTS.md`, a decisão precisa
ser revisitada num **novo ADR** (não editar o antigo). Regressão reproduzível vira
teste em `verificar.py`/`tests/` antes de o incidente ser fechado.
