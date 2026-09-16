"""anti_fraude.py — detecção de automação/bots por padrão de jogo (Fase 59).

Heurísticas em processo (mesmo caráter do rate limit `tem_cooldown`): detectam
comportamento de script e flagam o `Jogador` como `suspeito`, o que força um
delay adicional nas ações dele (~1,5s por jogada). Nunca bloqueiam e nunca
olham dados alheios — só timestamps e o resultado público da conferência.

Padrões:
- `tempo_entre_acoes`: humano raramente age em <200ms consistentemente.
- `desconfianca_em_rajada`: 3+ desconfianças do mesmo jogador em 5s.
- `padrao_horario`: atividade espalhada por quase todo o dia é suspeita.
- `acuracia_binomial`: acerto das próprias apostas muito acima do acaso numa
  amostra razoável sugere cálculo exato de bot (humano erra).

Serverless-safe: sem threads/timers de servidor; a curva fica por instância
(heurística defensiva, não fonte da verdade).
"""
import time

# Tempo mínimo realista entre ações humanas (segundos).
APOSTA_RAPIDA_LIMITE_S = 0.2
# Rajada de desconfianças: N em JANELA segundos.
RAJADA_JANELA_S = 5.0
RAJADA_MINIMO = 3
# Análise binomial: taxa de acerto das apostas confirmadas.
BINOMIAL_MINIMO_AMOSTRA = 20
BINOMIAL_TAXA_SUSPEITA = 0.85
# Horário: nº de horas distintas do dia com atividade.
HORAS_MINIMO_SUSPEITO = 20
# Delay extra (ms) aplicado às ações de um jogador marcado como suspeito.
DELAY_SUSPEITO_MS = 1500
# Tamanho do ring buffer de ações por jogador.
MAX_ACOES = 24
# Teto de client_ids rastreados ao mesmo tempo (processo persistente da VPS):
# sem isso, cada socket novo (sid único) deixaria uma entrada permanente.
MAX_CLIENTES = 8192

# Registro em processo (compartilhado pelas instâncias via heartbeat NÃO —
# heurística local, tolerante à perda por cold start).
_acoes = {}            # client_id -> [{'tipo': str, 'ts': float}]
_acertos = {}          # client_id -> {'verdadeiras': int, 'total': int}
_horas_ativas = {}     # client_id -> set de horas do dia com atividade (0-23)


def _podar():
    """
    Limita o nº de client_ids rastreados: o `client_id` é o `sid` (único por
    socket), então um processo que vive semanas acumularia uma entrada por
    conexão. Expulsa os mais antigos (ordem de inserção do dict) para manter a
    heurística viva sem crescer sem teto.
    """
    if len(_acoes) <= MAX_CLIENTES:
        return
    for _ in range(len(_acoes) - MAX_CLIENTES):
        antigo = next(iter(_acoes), None)
        if antigo is None:
            break
        limpar(antigo)


def _ultimas_acoes(client_id):
    return _acoes.get(client_id, [])


def registrar_acao(client_id, tipo_acao):
    """
    Registra uma ação do jogador e devolve a lista de detecões que ela
    disparou (`[]` = normal). Tipos: 'aposta', 'desconfiar', ...
    """
    agora = time.time()
    lista = _acoes.setdefault(client_id, [])
    lista.append({'tipo': tipo_acao, 'ts': agora})
    if len(lista) > MAX_ACOES:
        lista.pop(0)
    _horas_ativas.setdefault(client_id, set()).add(
        time.localtime(agora).tm_hour)
    _podar()

    detecoes = []
    if _aposta_rapida_demais(client_id):
        detecoes.append('aposta_rapida_demais')
    if tipo_acao == 'desconfiar' and _desconfianca_em_rajada(client_id):
        detecoes.append('desconfianca_em_rajada')
    if len(_horas_ativas[client_id]) >= HORAS_MINIMO_SUSPEITO:
        detecoes.append('padrao_horario')
    return detecoes


def _aposta_rapida_demais(client_id):
    """Duas ações do mesmo jogador com <200ms de intervalo."""
    lista = _ultimas_acoes(client_id)
    if len(lista) < 2:
        return False
    return (lista[-1]['ts'] - lista[-2]['ts']) < APOSTA_RAPIDA_LIMITE_S


def _desconfianca_em_rajada(client_id):
    """3+ desconfianças do mesmo jogador dentro de uma janela de 5s."""
    agora = time.time()
    contador = 0
    for acao in reversed(_ultimas_acoes(client_id)):
        if acao['tipo'] != 'desconfiar':
            continue
        if agora - acao['ts'] <= RAJADA_JANELA_S:
            contador += 1
        else:
            break
    return contador >= RAJADA_MINIMO


def marcar_resultado_aposta(client_id, e_verdadeira):
    """
    Alimenta a análise binomial com o desfecho público da conferência
    (`rodada.conferencia['verdadeira']`). Devolve True quando o jogador cruza
    a taxa suspeita de acerto (bot calcula a aposta, humano erra).
    """
    _podar()
    reg = _acertos.setdefault(client_id, {'verdadeiras': 0, 'total': 0})
    reg['total'] += 1
    if e_verdadeira:
        reg['verdadeiras'] += 1
    if reg['total'] < BINOMIAL_MINIMO_AMOSTRA:
        return False
    return reg['verdadeiras'] / reg['total'] >= BINOMIAL_TAXA_SUSPEITA


def taxa_acerto(client_id):
    """Acurácia das apostas confirmadas do jogador (para métricas)."""
    reg = _acertos.get(client_id)
    if not reg or reg['total'] == 0:
        return None
    return reg['verdadeiras'] / reg['total']


def marcar_suspeito(jogador, motivo):
    """Marca o `Jogador` como suspeito com o motivo codificado (Fase 59)."""
    jogador.suspeito = motivo


def delay_adicional(jogador):
    """
    Delay extra (ms) aplicado às ações de um jogador suspeito — desacelera a
    automação sem travar o jogo (humano continua jogando, só com pausa).
    """
    if getattr(jogador, 'suspeito', None):
        return DELAY_SUSPEITO_MS
    return 0


def limpar(client_id):
    """Zera os registros de um jogador (uso em testes/expurgo)."""
    _acoes.pop(client_id, None)
    _acertos.pop(client_id, None)
    _horas_ativas.pop(client_id, None)