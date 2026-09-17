"""Migrações de formato serializado do Lobby (Fase 45, M4)."""

# Versão do formato serializado do Lobby (store distribuído). Sempre que a
# serialização mudar de forma incompatível, incremente e registre a migração
# correspondente em MIGRACOES (Fase 10, S3).
VERSAO_ATUAL = 9

# Janela (segundos) em que a vaga de um humano removido fica registrada no
# lobby (Fase 30): permite o `retomar_identidade` dizer por que a retomada foi
# negada (vaga expirada por inatividade vs. sessão de outra sala).
VAGAS_RECENTES_SEGUNDOS = 300


def _migrar_v1_para_v2(dados):
    """v1 -> v2 (Fase 5): sala de espera ganha nome/status/página/config/prontidão."""
    dados.setdefault('nome', None)
    dados.setdefault('status', 'espera')
    dados.setdefault('pagina', 0)
    dados.setdefault('config', {})
    for jogador in dados.get('jogadores', []) or []:
        jogador.setdefault('pronto', False)
    return dados


def _migrar_v2_para_v3(dados):
    """v2 -> v3 (Fase 11): jogadores IA e configs de substituição/nível dos bots."""
    for jogador in dados.get('jogadores', []) or []:
        jogador.setdefault('is_ia', False)
        jogador.setdefault('ia_nivel', None)
    config = dados.setdefault('config', {})
    config.setdefault('substituir_desconectado_por_ia', False)
    config.setdefault('ia_nivel_padrao', 2)
    return dados


def _migrar_v3_para_v4(dados):
    """v3 -> v4 (Fase 15): espectadores deixam de ser jogadores do lobby."""
    dados.setdefault('espectadores', [])
    return dados


def _migrar_v4_para_v5(dados):
    """v4 -> v5 (Fase 15): numeração de partida própria, p/ podar histórico."""
    if 'proxima_partida_num' not in dados:
        ultimo = max((p.get('partida_num', 0) for p in dados.get('partidas', []) or []), default=0)
        dados['proxima_partida_num'] = int(ultimo) + 1
    return dados


def _migrar_v5_para_v6(dados):
    """v5 -> v6 (Fase 20): personalidade dos bots (risco/agressividade)."""
    for jogador in list(dados.get('jogadores', []) or []) + list(dados.get('espectadores', []) or []):
        jogador.setdefault('ia_risco', 0.5)
        jogador.setdefault('ia_agressividade', 0.5)
    return dados


def _migrar_v6_para_v7(dados):
    """v6 -> v7 (Fase 21): tempo máximo de jogada configurável (jogada automática)."""
    dados.setdefault('config', {}).setdefault('tempo_max_jogada', 30)
    return dados


def _migrar_v7_para_v8(dados):
    """v7 -> v8 (Fase 30): registro de vagas recentes (motivo do retomar_negado)."""
    dados.setdefault('vagas_recentes', {})
    return dados


def _migrar_v8_para_v9(dados):
    """
    v8 -> v9 (Fase 69): relógio do próximo lance dos bots (partida só de IAs
    assistida). A leitura usa `get` com default None, então o campo ausente já
    é tratado — a migração existe só para registrar o formato.
    """
    for partida in dados.get('partidas', []) or []:
        partida.setdefault('proximo_lance_em', None)
        for rodada in partida.get('rodadas', []) or []:
            rodada.setdefault('proximo_lance_em', None)
    return dados


MIGRACOES = {
    1: _migrar_v1_para_v2,
    2: _migrar_v2_para_v3,
    3: _migrar_v3_para_v4,
    4: _migrar_v4_para_v5,
    5: _migrar_v5_para_v6,
    6: _migrar_v6_para_v7,
    7: _migrar_v7_para_v8,
    8: _migrar_v8_para_v9,
}