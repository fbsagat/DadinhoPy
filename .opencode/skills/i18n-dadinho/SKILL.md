---
name: i18n-dadinho
description: Use ao adicionar ou traduzir qualquer texto do Dadinho — "chave nova", "novo texto", "tradução", "falta idioma", "i18n", "data-i18n", "txtchave". Cobre os 5 dicionários, os canais estático/JS/servidor e a validação de cobertura.
---

# i18n — Dadinho

O servidor **nunca escolhe o idioma**. Toda string chega ao cliente como chave + parâmetros e é resolvida no idioma do jogador.

## Canais

| Canal | Onde | Como |
|---|---|---|
| Estático (HTML) | `templates/jogo.html` | atributos `data-i18n` / `data-i18n-html` / `data-i18n-title` / `data-i18n-placeholder` / `data-i18n-value` / `data-i18n-aria-label` |
| Dinâmico (JS) | `static/script.js` | `t('chave', params)`; narração via `traduzirSegmentos(segmentos, ...)` |
| Servidor (chaves nunca texto) | `modelos.py`/`app.py`/`narrador.py` | `txtchave`+`txtparams` (jogada inválida), `segmentos` (narração), `motivo` `{chave, params}` (`pode_iniciar`/`iniciar_negado`), `dado_qtd`/`quantidade_real`/`verdadeira` da conferência |
| Chave de interface | `static/i18n.js` | dicionário único com 5 idiomas: EN (base/fallback), pt-BR, es, fr, zh-CN |

## Procedimento

1. **Defina a chave** seguindo o namespace existente: `ui.*` (interface/fixos), `js.*` (strings dinâmicas do JS), `msg.*` (mensagens/erros), `alerta.*`, `narracao.*` (segmentos do narrador). Use parâmetros `{nome}`, `{n}` etc. em vez de concatenar.
2. **Adicione a chave aos 5 dicionários** de `static/i18n.js` na mesma posição da versão inglesa — o inglês é a base e o fallback; os outros 4 devem ter a mesma cobertura.
3. **Mexeu no servidor?** Emita `txtchave`/`txtparams`/`segmentos`/`motivo` (chaves + params), nunca texto resolvido. Se a narração mudar, ajuste `narrador.py` (segmentos estruturados) e o remonte no cliente.
4. **Mexeu no frontend?** Strings fixas via `data-i18n-*`; strings montadas via `t()`. Texto com HTML use `data-i18n-html`/`t` com cuidado (escape).
5. **Valide a cobertura:** `python verificar.py` falha se alguma chave faltar nos 4 idiomas em relação ao inglês. Rode sempre ao final.
6. **Teste:** pelo `#seletor_idioma`, mude para os 5 idiomas e confira os fluxos alterados.

## Regras

- Não usar `navigator.language` do servidor; não mandar o idioma na URL.
- Chave ausente cai no inglês (fallback) — mas `verificar.py` deve pegar antes de subir.
- `msg.jogada.*` usa códigos (`msg.jogada.dados_ausentes`, `msg.jogada.nao_inteiros`, `msg.jogada.fora_intervalo`, `msg.jogada.tente_outra`) — siga o padrão ao criar mensagens de validação.