# ADRs — Decisões de Arquitetura do Dadinho

Registros curtos das decisões que moldaram o jogo (Fase 62 do `todo.md`). Um ADR
explica **por que** uma escolha foi feita (contexto), **o que** ficou decidido e
**o que** isso custa — para que a próxima pessoa (ou IA) não reverte uma decisão
sem conhecer o motivo original.

## Como ler/usar

- Um ADR **não é documentação de uso** — é o registro da decisão. O como-fazer
  fica em `docs/arquitetura.md`, `docs/verificacao.md` e `docs/runbook.md`.
- Status possíveis: `Aceito`, `Aceito (revisado por ADR-xxx)`, `Substituído por
  ADR-xxx`, `Adiado`.
- Decisão que estoura o escopo de um ADR existente → **novo ADR** que o
  referencia (não reescrever o antigo; ADR é imutável, exceto status).
- Toda decisão que toca o jogo deve ter ADR **ou** estar coberta por um dos
  invariantes do `AGENTS.md`.

## Índice

| ADR | Título | Status |
| --- | --- | --- |
| [001](001-serverless-vercel-e-api-vps.md) | Serverless na Vercel com store distribuído e API persistente opcional na VPS | Aceito |
| [002](002-lock-por-sala-e-message-queue.md) | Lock distribuído por sala + message queue entre instâncias | Aceito |
| [003](003-nginx-borda-rate-limit-ip-real.md) | Nginx como borda na VPS com rate limit por IP real | Aceito |
| [004](004-anti-fraude-e-captcha-opt-in.md) | Anti-fraude heurístico + observabilidade; captcha opt-in | Aceito |
| [005](005-performance-store-e-rejeicao-pool-ia.md) | Performance do store (cache/batch/compressão/LRU) e rejeição do pool de threads da IA | Aceito |
| [006](006-gevent-4-replicas-sticky.md) | Múltiplos workers cooperativos: gevent + 4 réplicas + sticky por IP | Aceito |
| [007](007-redis-local-spof-adiado.md) | Redis local é SPOF documentado; HA adiado | Adiado |

## Template

```markdown
# ADR-NNN — Título

- **Status:** Aceito | Adiado | Substituído por ADR-xxx
- **Contexto:** (fase do `todo.md`, data)
- **Decisores:** mantenedor

## Contexto
O problema e as forças em jogo (restrições reais: serverless, custo, casual).

## Decisão
O que ficou decidido, em uma frase, e os detalhes que importam.

## Consequências
- Positivas.
- Negativas / trade-offs aceitos.
- O que isso proíbe (o que um contribuidor não pode fazer sem reabrir a decisão).
```