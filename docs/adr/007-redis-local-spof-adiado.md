# ADR-007 — Redis local é SPOF documentado; HA adiado

- **Status:** Adiado
- **Contexto:** Fase 61 (item 2) do `todo.md`; decisão de **não** implementar HA agora
- **Decisores:** mantenedor

## Contexto

Na VPS, o estado do jogo e a message queue vivem num container `redis:7-alpine`
único, com AOF (`--appendonly yes`) e volume `dadinho_redis_data`. Um Redis
gerenciado com HA (ou Sentinel/réplica) resolveria o **único ponto de falha**,
mas adiciona custo e/ou complexidade operacional (failover, split-brain, split
dns) que não se justificam para um jogo casual cujo estado é **por partida**.

Forças: AOF cobre restart do container, **não** disaster (perda do volume/host).
Um reset zera salas ativas e dados em andamento — raramente fatal num jogo que se
regenera.

## Decisão

**Não** implementar HA agora. Documentar o SPOF e deixar o caminho de upgrade
aberto **sem mudança de código**:

- `store.ArmazenamentoRedis` é **agnóstico à URL** (`DADINHO_REDIS_URL`, e
  `DADINHO_MESSAGE_QUEUE` para o pub/sub);
- o upgrade é apontar a env para um Redis gerenciado com HA, ou subir
  Sentinel/réplica, quando houver necessidade real;
- TTL das chaves limpa salas órfãs sozinho (estado regenerável).

## Consequências

- Positivas: menos custo e menos superfície operacional agora; nada de código novo
  a manter; o deploy atual não muda.
- Negativas: perda do volume/host = perda das salas em andamento (aceito).
- Negativas: uma falha do Redis para a API inteira (as 4 réplicas dependem dele);
  recuperação = subir o Redis e aceitar a perda do estado (ver playbook no
  `docs/runbook.md`).
- Gatilho para reabrir: primeiro incidente real de perda de estado que incomode,
  ou aumento de tráfego que torne o host único inaceitável. Ao reabrir, **novo
  ADR** que substitui este.