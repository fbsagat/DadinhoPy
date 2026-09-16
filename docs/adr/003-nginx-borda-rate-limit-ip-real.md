# ADR-003 — Nginx como borda na VPS com rate limit por IP real

- **Status:** Aceito
- **Contexto:** Fase 59 do `todo.md` (VPS da Fase 46 já exposta pelo Cloudflare Tunnel)
- **Decisores:** mantenedor

## Contexto

O firewall/rate limit da Vercel protege o caminho serverless, mas o Cloudflare
Tunnel da VPS **expõe a API diretamente** em `dadinho-api.memetrigger.com`. Um
atacante que descubra o hostname pode spammar o handshake do Socket.IO sem passar
por nenhuma proteção da Vercel. A API também não pode ser exposta direto no UFW.

Complicação central: atrás do tunnel, `$remote_addr` é **127.0.0.1 para todos**
(o cloudflared roda com `network_mode: host`). Limitar por `$remote_addr` agruparia
o mundo inteiro sob um único balde — qualquer rate limit por ele derrubaria gente
legítima e ainda não conteria o ataque.

## Decisão

Um container **nginx** (`nginx:1.27-alpine`) como **borda** da VPS, publicado só em
loopback (`127.0.0.1:8090`) e alvo do tunnel. O IP real do cliente é reconstruído
por `map` em cascata: `Cf-Connecting-Ip` (cloudflared) → `X-Forwarded-For` →
`remote_addr`, na variável `$ip_real`. Sobre `$ip_real`:

- `limit_req_zone ... rate=60r/s` no `/socket.io/` (handshake + polling + upgrade);
- `limit_req_zone ... rate=10r/s` no resto, com `burst` configurado;
- `client_max_body_size 100k`, alinhado ao `max_http_buffer_size` do Socket.IO;
- `proxy_read_timeout 60s` (a sessão Engine.IO ociosa faz ping a cada 15s);
- logs em **JSON no stdout** (`log_format dadinho_json`) com IP real e status.

O nginx faz proxy para as réplicas da API (Fase 61 → ADR-006).

## Consequências

- Positivas: a API nunca recebe tráfego direto do tunnel; rate limit efetivo por
  cliente real; auditoria em log estruturado; UFW segue sem abrir porta.
- Positivas: alinhamento com o `verificar.py` (boot/borda) e smoke tests locais
  (8000/8090) e público.
- Negativas: um componente a mais para operar (ver `docs/runbook.md`); as regras
  de rate limit precisam ser ajustadas quando o padrão de uso mudar (falsos
  positivos são a falha mais provável).
- Nota de operação: o `nginx.conf` é um arquivo de configuração **completo**
  (precisa de `events {}` e `http {}`; `map`/`upstream`/`server` não valem no nível
  `main`). Uma cópia editada à mão na VPS que divirja do repo é sobrescrita no
  próximo deploy.
- Proíbe: apontar o tunnel direto para `api:8000`; expor a porta da API fora do
  loopback; limitar por `$remote_addr` (é sempre 127.0.0.1 atrás do tunnel).