---
name: evento-dadinho
description: Use ao criar, alterar ou rastrear um evento Socket.IO do Dadinho — "novo evento", "novo socket.on", "handler", "emit", "mudar_pagina", "novo payload de evento". Aplica o checklist de handler e o mapa servidor↔cliente.
---

# Evento Socket.IO — Dadinho

Orienta alterações em qualquer evento do jogo, de ponta a ponta (servidor → cliente). O mapa completo de eventos está em `docs/fluxo.md`; arquitetura em `docs/arquitetura.md`.

## Antes de escrever

1. Leia a spec em `Dadinho idéia.txt` antes de mudar **comportamento** de jogo (telas/regras/fluxo).
2. Encontre o handler existente em `app.py` (`@socketio.on('...')`), o `emit` de origem (`modelos.py`/`funcoes_gerais.py`/`app.py`) e o `socket.on` correspondente em `static/script.js` — use `docs/fluxo.md` como índice, confira o código real.

## Checklist do handler no servidor (`app.py`)

- **Nome do evento em pt-BR, snake_case.**
- **Ordem dos decorators (regra que mais quebra):** `@socketio.on('...')` **por fora** de `@evento_mutavel`/`@evento_leitura`/`@autenticar` (o `@socketio.on` registra um wrapper interno e devolve a função original).
- **Tipo de wrapper:**
  - Mutação de estado → `@evento_mutavel` (rate limit + lock por sala + aborto silencioso).
  - Somente leitura (ex.: busca) → `@evento_leitura`.
  - Confirmações idempotentes e commit-reveal (`conferencia_final`, `vencedor_final`, `comprometer_seed`, `revelar_seed`) → `cooldown=None` (um drop silencioso pelo cooldown deixaria a sala presa).
- **Autenticação** → `@autenticar(exigir_master=..., extrair_chave=_chave_simples|_chave_aninhada)`; use `extrair_chave=None` para eventos sem chave (`apelido`, `verificar_desconectados`). O decorator injeta `(dados, lobby, jogador)`.
- **Finalização:** todo handler que **muta** termina com `salvar_sala(lobby)`; quando a mutação avança o jogo (início, rolagem, aposta, conferência, vitória, expurgo de graça), chame `ia.processar(lobby)`.
- **`emit` escopado:** `to=sala_room()` (room) ou `to=jogador.client_id` (individual). **Nunca** `broadcast=True` global.
- **Payload defensivo:** `dados = dados if isinstance(dados, dict) else {}`; nº não-numérico => fallback com `validar_numero`/`try/except`.
- **Servidor nunca escolhe idioma:** emita chave + parâmetros (`txtchave`/`txtparams`, `segmentos`, `motivo` {chave, params}) em vez de texto.

## Checkout do cliente (`static/script.js`)

- Adicione/atualize o `socket.on(evento, ...)` correspondente a cada `emit` novo do servidor.
- Strings montadas no JS passam por `t('chave', params)`; textos fixos via `data-i18n-*` em `templates/jogo.html`.
- Payloads novos com texto livre precisam de chave nova nos 5 dicionários de `static/i18n.js` → skill `i18n-dadinho`.

## Verificação

- Rodar `python verificar.py` (do repo root, `.venv`) ao final — cobre `py_compile`, `node --check` de `static/*.js`, cobertura i18n e a integração `flask_socketio.test_client`.
- Se o evento novo for de jogo, cobri-lo no `verificar.py` (teste de integração) ou no `simular_ia.py` quando aplicável.
- Teste manual em dois browser tabs para fluxos interativos.