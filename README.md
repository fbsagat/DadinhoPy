# Dadinho

Jogo de blefe de dados multiplayer em tempo real no navegador. Cada jogador rola seus dados e, em turnos, aposta quantas vezes um número aparece na mesa — ou desconfia da aposta do anterior. Quem erra perde um dado; o último com dados vence.

**Disponível em:** [dadinho.memetrigger.com](https://dadinho.memetrigger.com)

## Tecnologias

- **Backend:** Python + Flask + Flask-SocketIO (Socket.IO only, sem REST)
- **Frontend:** uma página HTML + um JS, com animação dos dados rolando
- **Estado distribuído:** Upstash Redis REST (serverless-safe na Vercel)
- **Deploy:** Vercel (serverless)

## Rodar localmente

```bash
python app.py
```

Sobe em http://localhost:5000. Crie uma sala pela URL (`?sala=<id>`) e abra em 2+ abas/navegadores para testar uma partida completa.

Para estado persistente entre instâncias (produção), configure as env vars `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` e `DADINHO_SECRET_KEY`. Sem Upstash, o app cai em armazenamento em memória (só para validar local).

## Verificação

```bash
python verificar.py                 # testes automatizados + boot
python simular_ia.py --partidas 20  # bots headless
```

Sempre complementar com o teste manual em dois browser tabs (criar sala, rodar partida até vitória).

## Documentação

- `Dadinho idéia.txt` — spec/design do jogo (telas, regras, fluxo)
- `docs/arquitetura.md` — arquitetura e camada de estado
- `docs/fluxo.md` — mapa de eventos Socket.IO
- `docs/verificacao.md` — verificação e deploy na Vercel