"""observabilidade.py — logs estruturados em JSON (Fase 59).

O app não tem log próprio; os eventos suspeitos e os avisos de configuração
saem aqui como JSON em stdout (o `docker logs dadinho-api` os mostra).
Toda escrita passa por `_redigir`: campos sensíveis (`chave_secreta`,
`nonce_seed`, `compromisso_seed`, `dados`, etc.) NUNCA aparecem nos logs —
`log_redigido` é a porta de entrada para qualquer auditoria futura.

Serverless-safe: não há estado nem I/O além do print (flush), sem threads.
"""
import json
from datetime import datetime

# Campos cujo valor NÃO pode vazar para os logs (Fase 59, sanitização).
CAMPOS_SENSIVEIS = frozenset({
    'chave', 'chave_secreta', 'nonce', 'nonce_seed', 'seed', 'seed_final',
    'compromisso_seed', 'hcaptcha_response', 'hcaptcha_token', 'dados',
    'dado', 'token', 'senha', 'password', 'authorization',
})


def _redigir(valor):
    """Remove campos sensíveis recursivamente (auditoria de logs sem PII)."""
    if isinstance(valor, dict):
        return {k: _redigir(v) for k, v in valor.items() if k not in CAMPOS_SENSIVEIS}
    if isinstance(valor, (list, tuple)):
        return [_redigir(v) for v in valor]
    return valor


def _emitir(registro):
    """Imprime uma linha JSON em stdout (consumível por `docker logs`)."""
    try:
        print(json.dumps(
            {k: v for k, v in registro.items()},
            ensure_ascii=False, default=str,
        ), flush=True)
    except (TypeError, ValueError):  # pragma: no cover — JSON sempre serializável.
        print(json.dumps({'ts': datetime.utcnow().isoformat() + 'Z',
                          'tipo': 'log_nao_serializavel',
                          'mensagem': 'erro ao serializar log'}), flush=True)


def _base(tipo):
    return {'ts': datetime.utcnow().isoformat() + 'Z', 'tipo': tipo}


def log_evento_suspeito(tipo, client_id, ip, dados=None):
    """
    Evento de risco detectado (Fase 59).

    Tipos: `multiplas_contas`, `aposta_rapida_demais`,
    `desconfianca_em_rajada`, `padrao_horario`, `acuracia_binomial`,
    `captcha_falhou`. `client_id`/`ip` são aceitos (auditoria de segurança);
    qualquer `dados` sensível é redigido.
    """
    registro = _base(tipo)
    registro['nivel'] = 'SUSPEITO'
    registro['client_id'] = client_id
    registro['ip'] = ip
    if dados:
        registro['dados'] = _redigir(dados)
    _emitir(registro)


def log_advertencia(mensagem, **campos):
    """Aviso de configuração (ex.: CORS liberado em produção) em JSON."""
    registro = _base('configuracao')
    registro['nivel'] = 'WARNING'
    registro['mensagem'] = mensagem
    registro.update(_redigir(campos))
    _emitir(registro)


def log_redigido(**campos):
    """
    Auditoria genérica com garantia de sanitização: use quando um trecho
    novo precisar registrar contexto — os campos sensíveis nunca saem.
    """
    registro = _base('auditoria')
    registro['nivel'] = 'INFO'
    registro.update(_redigir(campos))
    _emitir(registro)