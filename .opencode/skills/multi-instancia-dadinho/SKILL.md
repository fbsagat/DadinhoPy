---
name: multi-instancia-dadinho
description: Use ao mexer em tempo real entre instâncias/réplicas ou estado distribuído do Dadinho — "cross-instance", "lock", "trancar_sala_distribuida", "message queue", "DADINHO_MESSAGE_QUEUE", "GerenciadorRedisSeguro", "réplica", "sticky", "gevent", "async_mode", "lost update", "ConflitoDeEstado", "broadcast". Aplica o checklist de invariantes e o mapa das peças.
---

# Skill: multi-instância / tempo real entre réplicas

O Dadinho roda com **múltiplas instâncias** (serverless na Vercel; 4 réplicas
gevent na VPS atrás de nginx sticky). Rooms/emits vivem na memória da instância —
este é o par de decisões: `docs/adr/002-lock-por-sala-e-message-queue.md` e
`docs/adr/006-gevent-4-replicas-sticky.md`. Plano original:
`docs/plano-cross-instance.md`.

## Invariantes (AGENTS.md) que esta área protege

1. Emit **escopo à sala**: `emit(..., to=sala_room())` ou `to=jogador.client_id` —
   **nunca** `broadcast=True` global.
2. Todo handler que muta **termina com `salvar_sala(lobby)`**, passa pelo lock e
   roda `ia.processar(lobby)` quando avança o jogo.
3. **Sem estado em memória entre requests** e **sem threads/timers** no servidor
   (`ia.processar` roda dentro do request) — vale para Vercel **e** VPS.
4. Painel de leitura tolerante (`carregar_sala_leve`, TTL 25s) só na partida; a
   **espera sempre lê fresco** do store.

## Peças (onde olhar)

- `store.trancar_sala` (lock local, LIFO) + `store.trancar_sala_distribuida`
  (SET NX EX / DELEX IFEQ, `TRAVA_TTL=120s`). `ConflitoDeEstado` = CAS de revisão.
- `store.ArmazenamentoRedis` / `ArmazenamentoUpstash` — agnósticos à URL
  (`DADINHO_REDIS_URL`); a message queue usa `DADINHO_MESSAGE_QUEUE`
  (`GerenciadorRedisSeguro` em `app.py`); sem a env, gerenciador local.
- `app.py`: `handle_connect`/`handle_disconnect`/`evento_mutavel` (é onde o
  `store.invalidar_cache_sala` é chamado no `except` — Fase 60 P2/P3).
- nginx sticky: `hash $ip_real consistent;` (o `sid` muda a cada reconexão; o IP
  real não) — ver `docs/adr/003` e `nginx/nginx.conf`.

## Checklist ao criar/alterar um handler ou emit

- [ ] O emit está escopado à sala/jogador (`to=...`), nunca global.
- [ ] A mutação passa pelo lock (`trancar_sala`/`trancar_sala_distribuida`) e
      termina em `salvar_sala`/`salvar_sala_com_resumo`.
- [ ] Se avança o jogo, chama `ia.processar(lobby)` **dentro** do handler.
- [ ] Nada de estado X em memória que precise ser visível em outra réplica sem
      tratar o re-sync (espera) ou a message queue (partida).
- [ ] Caches de leitura continuam sendo invalidados no caminho de erro (senão
      dedup/revisão trava a sala — Fase 60 P2).
- [ ] Teste novo em `tests/` (ver `tests/test_cross_instance.py`,
      `tests/test_performance.py`) + `python verificar.py` verde.

## Trade-off conhecido (não "corrigir" sem ADR)

`ia.processar` é CPU-bound e, sob gevent, **não preempta** outros greenlets da
mesma réplica; as 4 réplicas + LRU mitigam (ADR-006). Movê-la para thread/fila
viola o invariante nº 3 — exigiria novo ADR.
