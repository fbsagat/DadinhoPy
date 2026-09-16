# ADR-005 — Performance do store (cache/batch/compressão/LRU) e rejeição do pool de threads da IA

- **Status:** Aceito
- **Contexto:** Fase 60 do `todo.md` (pós-métricas)
- **Decisores:** mantenedor

## Contexto

O jogo ficou mais lento e mais caro do que deveria sob carga: o handler
`heartbeat` adquiria o lock distribuído mesmo sendo 95% leitura; `carregar_resumo`
batia no Redis a cada listagem/OG; `atualizar_lista_usuarios` fazia 2–3 comandos
em sequência; blobs grandes trafegavam inteiros; e o cálculo probabilístico da IA
se repetia com os mesmos argumentos.

A tentação óbvia era tirar a IA do caminho do request com um **pool de threads
dedicado** — o que colide de frente com a invariante serverless (ver ADR-001).

## Decisão

Otimizar **dentro do request**, sem quebrar a invariante, com cinco mudanças
(`store.py`, `ia.py`, `funcoes_gerais.py`, `app.py`):

1. **Heartbeat com fast path** — `@evento_mutavel(lock_distribuido=False)`:
   espera faz re-sync fresco sem lock (leitura pura); partida quieta é servida do
   cache; só adquire o lock quando há mutação possível, re-lendo fresco dentro do
   lock antes de `ia.processar`.
2. **Cache de resumo** — `_cache_resumos` (TTL 5s, max 2048) com guarda; `None`
   nunca é cacheado; populado no save e invalidado em `remover_resumo` e em
   `invalidar_cache_sala`.
3. **LRU do cálculo probabilístico** — `functools.lru_cache(maxsize=1024)` na
   função **pura** `probabilidade_verdade(...)` (args numéricos hasháveis). Não no
   `_probabilidade_aposta`, que receberia objetos vivos e vazaria memória.
4. **Batch de escrita** — `salvar_sala_com_resumo` faz sala + resumo + índice num
   único pipeline (Upstash `/pipeline`; `redis.pipeline()` no TCP).
5. **Compressão de blobs** — `_comprimir`/`_descomprimir` (zlib→base64, marcador
   `gz1:`, limiar 512 B) com **compat retroativa** (blob antigo sem marcador passa
   intacto). Só no `ArmazenamentoRedis` (TCP).

**Rejeitada:** pool de threads para `ia.processar` (viola "sem threads/timers no
servidor"; em serverless a thread morre com a resposta e a fila reintroduz estado
em memória). O caminho serverless-safe é rodar a IA dentro do handler que mutou —
os caches barateiam cada processamento sem quebrar a invariante.

## Consequências

- Positivas: menos aquisições de lock (~70%+ em salas ociosas), menos comandos por
  gravação, menos bytes no Redis, menos CPU repetida na IA.
- Positivas: benchmark determinístico em `tests/test_performance.py` (sem
  depender de timing) garante as propriedades no CI.
- Negativas: mais superfície de cache/invalidação — um erro de invalidação serve
  dado velho ou marca como salvo o que não foi. Foi exatamente o que o revisor
  pegou (P1/P2/P3) e a correção: `invalidar_cache_sala` limpa as **quatro**
  estruturas (`_cache_salas`, `_cache_resumos`, `_resumos_assinatura`,
  `_revisoes_salvas`) e é chamado nos `except` de `evento_mutavel`,
  `handle_connect` e `handle_disconnect`; `listar_lobbys` passou a descomprimir.
- Positivas de custo: menos comandos Upstash (orçamento do free tier) e menos
  banda.
- Negativas: no fast path, `_renovar_sinal` grava **só o resumo** (derivado,
  dedup por assinatura) sem o lock distribuído — uma listagem pode ficar
  defasada por segundos entre réplicas. O estado autoritativo (Lobby) só é salvo
  sob lock; o resumo é regenerado a cada transição de estado e o heartbeat
  re-sincroniza. Aceito.
- Proíbe: cachear `None`; cachear em função que recebe objetos vivos; mover a IA
  para thread/fila; esquecer a compat retroativa ao mexer em `_comprimir`.