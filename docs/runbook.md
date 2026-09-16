# Runbook — operação do Dadinho (VPS + Vercel)

Guia de **resposta a incidente** da topologia de produção (Fase 62 do `todo.md`).
Para o *como fazer* de rotina (verificar local, deploy), ver
`docs/verificacao.md`; para o *porquê* das escolhas, ver `docs/adr/`. Aqui é o
**o que fazer quando algo quebra**.

Premissa: o estado do jogo é **por partida** e se regenera. Na dúvida entre
"restaurar tudo perfeito" e "voltar ao ar rápido", prefira voltar ao ar — os
invariantes garantem que ninguém corrompe o jogo.

## 1. Topologia de produção

| Peça | Onde | O que é | Se cair |
| --- | --- | --- | --- |
| Frontend (HTML/JS) | **Vercel** — `dadinho.memetrigger.com` | página + `script.js`; conecta o socket onde o `<meta name="dadinho-api-url">` manda | Vercel tem rollback por deploy; jogo fica sem UI |
| API (Socket.IO) | **VPS** — 4 réplicas `dadinho-api`/`-2`/`-3`/`-4`, gevent, loopback 8000–8003 | jogo de verdade; estado no Redis | réplica saudável absorve; ver §5 |
| Borda + rate limit | **VPS** — `dadinho-nginx`, loopback `127.0.0.1:8090` | proxy/rate limit por IP real | todo o tráfego público da API cai; ver §4 |
| Estado + message queue | **VPS** — `dadinho-redis` (AOF, volume `dadinho_redis_data`) | `dadinho:sala:*`, resumos, sids, IPs, locks, pub/sub | API inteira falha; ver §6 |
| Exposição pública | **VPS** — `dadinho-tunnel` (cloudflared, `network_mode: host`) | `dadinho-api.memetrigger.com` → `localhost:8090` | público não resolve; ver §4 |

No caminho Vercel puro (sem `DADINHO_API_URL`), o estado vive no **Upstash REST** e
o rate limit é a **regra de firewall da Vercel** `rate-limit-socketio` (120 req/60s
por IP em `/socket.io/`). As duas topologias compartilham o mesmo código
(ADR-001).

## 2. Acesso e comandos básicos

```powershell
# SSH (o deploy atual usa ubuntu + memetrigger-vps.key; ver atualizar_vps.ps1)
ssh -i "D:\Downloads\Meme_Trigger\chave_nova\memetrigger-vps.key" ubuntu@167.126.27.4
```

Na VPS, **tudo em `/opt/dadinho`** (não há git clone do Dadinho ali):

```bash
cd /opt/dadinho

# Estado dos containers (API, redis, nginx, tunnel)
sudo docker compose ps

# Logs (as 4 réplicas sobem juntas pelo nome do serviço)
sudo docker compose logs -f --tail=200 api      # inclui api/api2/api3/api4
sudo docker compose logs -f --tail=200 nginx    # JSON com IP real + status
sudo docker compose logs -f --tail=200 redis
sudo docker compose logs -f --tail=200 tunnel
sudo docker logs --tail=100 dadinho-api-2       # réplica específica

# Saúde por container e testes de borda
sudo docker inspect --format '{{.Name}} {{.State.Health.Status}}' dadinho-api dadinho-api-2 dadinho-api-3 dadinho-api-4
curl -s -o /dev/null -w 'api:%{http_code}\n'    http://127.0.0.1:8000/robots.txt
curl -s -o /dev/null -w 'nginx:%{http_code}\n'  http://127.0.0.1:8090/robots.txt
curl -s 'http://127.0.0.1:8090/socket.io/?EIO=4&transport=polling' | head -c 120
```

Público (de qualquer lugar): `curl -s -o /dev/null -w '%{http_code}\n'
https://dadinho-api.memetrigger.com/robots.txt` (esperado `200`).

## 3. Triagem em 30 segundos

1. **Local responde em 8000?** Não → a API não subiu (§5) ou o Redis está fora (§6).
2. **Local responde, nginx não (8090)?** → borda/rede (§4) ou nenhuma réplica
   saudável (§5).
3. **nginx responde, público não?** → tunnel/DNS/Cloudflare (§4).
4. **Tudo responde mas o jogo "trava"?** → Redis/lock/estado (§6, §8).

## 4. Público fora do ar (tunnel, DNS, borda)

Sintoma: `https://dadinho-api.memetrigger.com` não responde / 502 / 1033; local
(8000/8090) ok.

```bash
sudo docker compose ps tunnel nginx
sudo docker compose logs --tail=100 tunnel    # erros de token/ingress/DNS
sudo docker compose logs --tail=100 nginx     # 502 = réplicas ruins; ver §5
```

- **Tunnel parado/reiniciando:** `sudo docker compose up -d --force-recreate tunnel`.
  Confirme o `cloudflared/config.yml` em `/opt/dadinho` (ingress
  `dadinho-api.memetrigger.com → http://localhost:8090`; nunca `:8000` — é a borda
  nginx, ADR-003). Esse arquivo é **só da VPS** (gitignored) e não é sobrescrito pelo
  deploy.
- **Token inválido/rotacionado:** `TUNNEL_TOKEN` no `/opt/dadinho/.env` (Zero Trust
  → tunnels); após corrigir, recrie o container.
- **DNS:** o CNAME manual   `dadinho-api → <tunnel-id>.cfargotunnel.com` precisa
  existir na zona (a rota do painel **não** cria o CNAME — ver
  `docs/verificacao.md`).
- **nginx não sobe:** valide a config **antes** de culpar a VPS:
  `docker run --rm --add-host api:127.0.0.1 --add-host api2:127.0.0.1 --add-host api3:127.0.0.1 --add-host api4:127.0.0.1 -v "$PWD/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" nginx:1.27-alpine nginx -t`.
  `map`/`upstream`/`server` exigem `events {}`/`http {}` (o arquivo é config
  completa). Config editada à mão na VPS é sobrescrita no próximo deploy.

## 5. Réplica da API ruim (healthcheck unhealthy / 502 intermitente)

Sintoma: `docker compose ps` mostra `dadinho-api-*` como `unhealthy`; nginx loga
502/504 esporádico; parte dos jogadores reconecta.

```bash
sudo docker inspect --format '{{.Name}} {{.State.Health.Status}}' dadinho-api dadinho-api-2 dadinho-api-3 dadinho-api-4
sudo docker logs --tail=200 dadinho-api-2
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/robots.txt   # smoke da réplica 2
```

- **Uma réplica só:** `sudo docker restart dadinho-api-2` — o nginx mantém as
  outras 3 (sticky por IP). Quem estava nela reconecta (o Engine.IO reconecta) e
  cai numa réplica viva.
- **Duas ou mais / todas:** normalmente é causa comum — Redis (§6) ou deploy
  quebrado (§7). `docker compose up -d --build api api2 api3 api4 nginx` sobe as 4
  de uma vez.
- **MemoryError/OOM:** veja `docker stats`; o blob comprimido e o LRU (ADR-005)
  reduzem a memória, mas um bug de vazamento aparece em `docker stats` crescendo
  sem parar — anote e abra bug.

### 5.1. `connect` falha / não cria sala — WebSocket 500 (`gevent-websocket`)

Sintoma: o jogo **não conecta em nenhuma tela** (home vazia, "Criar sala" sem
efeito, "Buscar partidas" sem resposta), mas as réplicas estão `healthy` e o
polling responde. O log do nginx mostra `"uri":"/socket.io/","status":500`
repetido pelo IP do cliente; no log da API:
`RuntimeError: The gevent-websocket server is not configured appropriately`.

Causa: `gevent-websocket` instalado na imagem. Com ele presente o python-engineio
deixa de usar o `simple-websocket` e passa a exigir `environ['wsgi.websocket']`,
que só existe no worker `geventwebsocket.gunicorn.workers.GeventWebSocketWorker`
— o Dockerfile usa o worker `gevent` puro, que não fornece essa chave. O cliente
pede `transports: ['websocket','polling']` e o socket.io **não cai no polling**
quando o WebSocket falha, então a conexão trava em loop de reconexão.

Correção: manter `gevent-websocket` **fora** de `requirements.txt` (o engineio
usa o `simple-websocket`, que funciona com o worker `gevent`). A regressão está
guardada no `verificar.py` (assert `SimpleWebSocketWSGI is not None` no boot
gevent). Rebuild: `docker compose up -d --build api api2 api3 api4 nginx`.

Diagnóstico rápido na VPS:

```bash
# Deve imprimir None (pacote ausente); se achar o pacote, é a causa.
sudo docker exec dadinho-api python -c "import importlib.util as u; print(u.find_spec('geventwebsocket'))"
# Handshake público: esperado 101 (não 500).
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
  -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  'https://dadinho-api.memetrigger.com/socket.io/?EIO=4&transport=websocket'
```

Obs.: um cliente que manda `Origin: https://dadinho-api...` (a própria API) toma
`502` do Cloudflare — é bloqueio de borda, não a API; o browser manda o
`Origin` do frontend e conecta normal.

## 6. Redis fora / perda de estado (SPOF conhecido — ADR-007)

Sintoma: `/robots.txt` pode responder 200 (o app sobe), mas `connect`/handlers
falham com erro de rede; `docker compose ps` mostra `dadinho-redis` não saudável;
logs da API com erro de Redis/lock.

```bash
sudo docker compose ps redis
sudo docker logs --tail=100 dadinho-redis
sudo docker exec -it dadinho-redis redis-cli ping     # esperado PONG
sudo docker exec -it dadinho-redis redis-cli dbsize
```

- **Só o Redis reiniciou:** o AOF recarrega no boot; espere o healthcheck e a API
  volta (o `ArmazenamentoRedis` é lazy e o `depends_on` espera o ping). A perda é
  só do que não foi persistido.
- **Volume/host perdido:** o estado (salas ativas) **não volta**. Suba o Redis e
  deixe as salas se regenerarem (TTL limpa órfãs). Aceito no casual — ver
  ADR-007. Não tente "reconstruir" estado à mão.
- **`maxmemory`/OOM no Redis:** `redis-cli info memory`; o Redis não é configurado
  com `maxmemory` no compose. Se crescer, as TTLs (sala/resumo 7d, sid 24h, ip 6h)
  deveriam podar — um vazamento de chave sem TTL é bug.
- **Recuperação de disaster (decisão futura):** o upgrade é **só env** — apontar
  `DADINHO_REDIS_URL`/`DADINHO_MESSAGE_QUEUE` para um Redis gerenciado/HA
  (ADR-007). Nenhuma mudança de código.

## 7. Deploy quebrado → rollback

### VPS (não há auto-deploy nem git em `/opt/dadinho`)

O código é copiado por tar (`atualizar_vps.ps1`). Não existe "versão anterior" no
servidor — **rollback = voltar o repo local e reenviar**:

1. No repo local: `git checkout <commit-bom>` (o deploy é o working tree), depois
   rode normalmente:
   ```powershell
   .\atualizar_vps.ps1 -Chave "D:\Downloads\Meme_Trigger\chave_nova\memetrigger-vps.key"
   ```
2. Se nem o script roda (imagem que não builda), o caminho rápido é consertar
   para frente: corrija no repo, `python verificar.py`, reenvie.
3. **Nunca** `rm -rf /opt/dadinho/*` (apaga `.env` e `cloudflared/config.yml`, que
   não estão no repo) nem `docker compose down -v` (apaga o volume do Redis/AOF)
   sem intenção explícita.

### Vercel

- Dashboard → projeto `dadinho` → **Deployments** → deploy anterior → **Promote to
  Production**; ou CLI `vercel rollback` (volta o alias de produção ao deploy
  anterior). Depois valide em 2+ abas.

## 8. Salas presas / locks / `ConflitoDeEstado`

Sintoma: uma sala específica não evolui; logs com `ConflitoDeEstado` ou
`TravaIndisponivel`.

- **Lock preso:** o lease do lock distribuído tem TTL curto (`TRAVA_TTL`, 120s) —
  numa falha de handler ele **expira sozinho**; não é preciso "destravar à mão".
- **`ConflitoDeEstado` em série (sala presa):** era o bug P2/P3 da Fase 60 (o
  watermark de revisão avançava antes da escrita e travava a sala). Já corrigido;
  se reaparecer, é regressão — capture o log e abra bug.
- **Inspeção de uma sala** (as chaves do `store.py`):
  ```bash
  sudo docker exec -it dadinho-redis redis-cli --scan --pattern 'dadinho:sala:*'
  sudo docker exec -it dadinho-redis redis-cli get dadinho:sala:<id>   # blob (gz1: = comprimido)
  sudo docker exec -it dadinho-redis redis-cli ttl dadinho:sala:<id>
  sudo docker exec -it dadinho-redis redis-cli smembers dadinho:resumos
  sudo docker exec -it dadinho-redis redis-cli get dadinho:sid:<client_id>
  sudo docker exec -it dadinho-redis redis-cli get dadinho:lock:<id>    # lock ativo, se houver
  ```
  **Não** edite o blob à mão — é serialização de `Lobby` (ADR-005); uma sala
  quebrada deve ser descartada (`del`) e recriada, nunca "consertada".

## 9. Abuso / bot / rate limit

Sintoma: usuários legítimos com erro 5xx ao conectar; pico de conexões; logs de
evento suspeito.

- **Rate limit do nginx** devolve **503** (default do `limit_req`) por IP real
  (60/s no `/socket.io/`, 10/s no resto — ADR-003). Confirme no log JSON do nginx
  (`status:503`, `ip_real`). Falso positivo de rede móvel/CGNAT é possível: ajuste
  o `rate`/`burst` em `nginx/nginx.conf`, valide com `nginx -t` (ver §4) e reenvie.
- **Camadas (não são redundantes):** firewall da Vercel (120 req/60s, `/socket.io/`)
  → cooldown por `sid` (por instância) → lock por sala (consistência, não rate
  limit). Não remova uma por achar que outra cobre.
- **Limite de sockets por IP:** `DADINHO_LIMITE_SOCKETS_IP` — **0 = desligado**
  (default, opt-in); ativar em picos. Índice `dadinho:ip:<ip>` (TTL 6h). Excesso
  retorna `connect_error` `msg.muitas_contas`. Cuidado: IPs compartilhados
  (CGNAT de operadora, rede corporativa) agregam jogadores legítimos — um teto
  baixo bloqueia todos eles; prefira folga.
- **Captcha (opt-in, Cloudflare Turnstile):** em pico de abuso, setar
  `DADINHO_CAPTCHA_ATIVO=true` + `DADINHO_TURNSTILE_SITEKEY` + `TURNSTILE_SECRET`
  no `.env` da VPS (API) e recriar as réplicas; na **Vercel** (frontend) setar
  `DADINHO_CAPTCHA_ATIVO=true` + `DADINHO_TURNSTILE_SITEKEY` e redeployar (o
  secret fica só na API). Rodar sem sitekey = widget não aparece; sem secret, a
  API só renderiza e não valida (aviso no log). Desligar quando o pico passar.
- **Logs de auditoria:** eventos suspeitos saem no stdout da API
  (`observabilidade.py`, JSON redigido): `docker compose logs api | grep -i
  suspeit`.

## 10. Custo / alertas disparando

- **Upstash (Vercel):** console → database → **Alerts** (comandos/mês ~80% de 500
  mil; banda ~80% de 10 GB). Não há CLI — conferir no painel antes de um pico.
- **Vercel:** regra `dadinho - anomalia de uso (invocacoes/duration)` (project
  `dadinho`) já criada; gerenciar com `vercel alerts rules ls/add/rm`. Boot com
  `VERCEL=1` **exige** Upstash — sem ele o código cai em memória e o estado quebra
  entre instâncias (não é um deploy válido).
- **Sintoma de regressão de custo:** o heartbeat (cadência 20s na espera) e o fast
  path da Fase 60 existem justamente para isso; se os comandos subirem de novo,
  suspeite de handler novo adquirindo lock/Redis desnecessariamente (ADR-005).

## 11. Pós-incidente

1. O incidente está descrito aqui? Se **não**, abra/adicionar um playbook nesta
   seção (é o contrato da Fase 62).
2. A causa raiz **contraria** um ADR ou invariante do `AGENTS.md`? Então a decisão
   precisa ser revisitada num **novo ADR** (não editar o antigo).
3. Regressão reproduzível → deve virar teste no `verificar.py`/`tests/` antes de
   fechar o incidente.
