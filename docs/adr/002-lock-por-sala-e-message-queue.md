# ADR-002 — Lock distribuído por sala + message queue entre instâncias

- **Status:** Aceito
- **Contexto:** Fases 24–26 do `plano-cross-instance.md`; retomada/otimização na Fase 40
- **Decisores:** mantenedor

## Contexto

Com múltiplas instâncias (Vercel serverless e/ou as 4 réplicas da VPS), dois
problemas aparecem:

1. **Lost update:** duas instâncias leem a mesma sala, mutam e gravam por cima uma
   da outra (read-modify-write concorrente). Salas podem até "voltar no tempo".
2. **Emits não chegam:** as rooms do Socket.IO vivem na memória de cada instância.
   Um `emit(..., to=sala_room())` só alcança quem está conectado àquela instância.

Forças: sem estado em memória entre requests; a plataforma não oferece lock nem
pub/sub prontos; custo de cada comando extra conta no orçamento (Upstash/Vercel).

## Decisão

**Lock distribuído por sala** (`store.trancar_sala_distribuida`) + **message queue**
(`DADINHO_MESSAGE_QUEUE`).

- Lock: `SET dadinho:lock:<sala_id> <token> NX EX <ttl>` para adquirir; liberar com
  `DELEX ... IFEQ <token>` (compare-and-del atômico, evita liberar o lock de outra
  instância). Combinado com o lock local (`trancar_sala`) em LIFO, sem inversão →
  sem deadlock. TTL de lease curto (`TRAVA_TTL`); ao estourar, degrada com erro
  visível, nunca com escrita parcial silenciosa.
- Message queue: com `DADINHO_MESSAGE_QUEUE` definida, o `GerenciadorRedisSeguro`
  (pub/sub Redis) propaga os emits entre instâncias; sem a env, o gerenciador
  local (instância única) é usado.
- Revisão/CAS: cada sala carrega um watermark de revisão; gravações concorrentes
  que não baterem com a revisão viram `ConflitoDeEstado` (não sobrescrevem). Fase
  60 corrigiu o caso em que o watermark avançava antes da escrita abortada
  (ver ADR-005).

## Consequências

- Positivas: estado consistente entre instâncias; emits chegam a jogadores em
  réplicas diferentes; base para as 4 réplicas da Fase 61 (ADR-006).
- Positivas: `cooldown=None` para confirmações idempotentes/commit-reveal — só
  mutação real paga o custo do lock.
- Negativas: cada mutação ganha round-trips (lock + leitura + gravação + unlock);
  mitigado pelo cache/batch/compressão da Fase 60 (ADR-005).
- Negativas: a espera (lobby) ainda depende do **re-sync do heartbeat** porque
  rooms/emits são por instância — o partial da Fase 26 durante a partida foi
  resolvido pela message queue, mas o caminho quente da espera segue no re-sync.
- Proíbe: `emit(..., broadcast=True)` global (invariante nº 1 do `AGENTS.md`);
  mutar sala sem `salvar_sala` sob o lock; handler mutável sem `chave_secreta`.