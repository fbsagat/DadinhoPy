# Dadinho

[![CI](https://github.com/fbsagat/DadinhoPy/actions/workflows/ci.yml/badge.svg)](https://github.com/fbsagat/DadinhoPy/actions/workflows/ci.yml)

Jogo de blefe de dados multiplayer em tempo real no navegador. Cada jogador rola seus dados e, em turnos, aposta quantas vezes um número aparece na mesa — ou desconfia da aposta do anterior. Quem erra perde um dado; o último com dados vence.

**Disponível em:** [dadinho.memetrigger.com](https://dadinho.memetrigger.com)

## Tecnologias

- **Backend:** Python + Flask + Flask-SocketIO (Socket.IO only, sem REST)
- **Frontend:** uma página HTML + um JS, com animação dos dados rolando
- **Estado distribuído:** Redis — **local na VPS** em produção (`DADINHO_REDIS_URL`, TCP) ou **Upstash Redis REST** no caminho 100% Vercel (`UPSTASH_REDIS_REST_URL`/`TOKEN`)
- **Deploy (produção):** frontend na **Vercel** + **API em 4 réplicas Docker na VPS** (Socket.IO, gevent) atrás de nginx e Cloudflare Tunnel — o estado e a message queue vivem no Redis da VPS
- **Deploy alternativo:** tudo na Vercel (serverless), estado no Upstash — mesmo código, sem operação de servidor (`docs/adr/001-serverless-vercel-e-api-vps.md`)

## Rodar localmente

```bash
python app.py
```

Sobe em http://localhost:5000. Crie uma sala pela URL (`?sala=<id>`) e abra em 2+ abas/navegadores para testar uma partida completa.

Para estado persistente entre instâncias, configure o store (sem ele o app cai em memória, que só serve para validar local):

- **Produção (API na VPS):** `DADINHO_REDIS_URL=redis://redis:6379/0` e `DADINHO_MESSAGE_QUEUE` apontando para o mesmo Redis.
- **Caminho 100% Vercel:** `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` (Redis REST). Obrigatórias também na função da Vercel em produção: sem store configurado, o boot com `VERCEL=1` **falha de propósito** (`store.py:1106-1127`) em vez de zerar o estado a cada cold start.

Em ambos os casos, `DADINHO_SECRET_KEY` é obrigatório. Procedimentos em `docs/verificacao.md`.

## Verificação

```bash
python verificar.py                 # testes automatizados + boot (entrada única do CI)
python simular_ia.py --partidas 20  # bots headless
```

Sempre complementar com o teste manual em dois browser tabs (criar sala, rodar partida até vitória).

### Testes

`verificar.py` é o runner único: ele orquestra todos os módulos de teste em `tests/` e é o que o CI executa. Os testes não seguem a convenção pytest padrão — são chamados explicitamente pelo runner e usam nomes em pt-BR:

| Módulo | Execução | Escopo |
|---|---|---|
| `tests/test_integracao.py` | via `verificar.py` | Integração full-stack (lobby → partida → conferência → vitória → reconexão) |
| `tests/test_cross_instance.py` | `python tests/test_cross_instance.py` **ou** via `verificar.py` | Concorrência cross-instance (lock distribuído + CAS) |
| `tests/test_anti_fraude.py` | via `verificar.py` | Rate limit por IP, limite de conexões, redaction de logs |
| `tests/test_performance.py` | via `verificar.py` | Cache de resumo, LRU da IA, fast-path de heartbeat, compressão |

`tests/base.py` é a infraestrutura compartilhada (setup de store em memória, helpers de conexão, helpers de assertiva).

## Documentação

- `Dadinho idéia.txt` — spec/design do jogo (telas, regras, fluxo)
- `docs/arquitetura.md` — arquitetura e camada de estado
- `docs/fluxo.md` — mapa de eventos Socket.IO
- `docs/verificacao.md` — verificação e deploy (frontend na Vercel + API na VPS)