"""
Jogadores controlados por IA (Fase 11).

Duas responsabilidades:
- Motor de decisão puro (probabilidade binomial + perfis por nível), sem I/O;
- Orquestrador `processar(lobby)`, que roda dentro do request que mudou o estado
  e faz as IAs agirem em sequência (rolagem, apostas, desconfiança, conferência
  e vitória). Nada de threads/timers: serverless-safe.

Regra de ouro: a IA só enxerga os PRÓPRIOS dados e a informação pública da
rodada (turnos, quantidade de dados restantes). É proibido ler
`rodada.todos_os_dados`, que contém os dados de todos.
"""

import math
import secrets

import funcoes_gerais
from modelos import Jogador


NOMES_NIVEIS = {
    1: 'Novato',
    2: 'Regular',
    3: 'Perito',
    4: 'Mestre',
}


def nome_base(nivel):
    """Apelido base de um bot do nível informado (o lobby garante a unicidade)."""
    return f"🤖 {NOMES_NIVEIS.get(int(nivel), 'Bot')}"


# ---------------------------------------------------------------------------
# Criação/remoção de bots na sala
# ---------------------------------------------------------------------------

def adicionar_bots(lobby, nivel, quantidade):
    """Adiciona até `quantidade` bots do nível informado, respeitando max_jogadores."""
    if lobby is None:
        return []
    try:
        quantidade = max(0, int(quantidade or 0))
    except (TypeError, ValueError):
        return []
    limite = int(lobby.config.get('max_jogadores', 6))
    criados = []
    for _ in range(quantidade):
        if len(lobby.jogadores) >= limite:
            break
        username = lobby.verificar_apelido(nome_base(nivel))
        jogador = Jogador.criar_ia(nivel, username)
        lobby.adicionar_jogador(jogador)
        criados.append(jogador)
    return criados


def completar_bots(lobby, nivel):
    """Preenche as vagas restantes da sala com bots do nível informado."""
    if lobby is None:
        return []
    limite = int(lobby.config.get('max_jogadores', 6))
    faltam = max(0, limite - len(lobby.jogadores))
    return adicionar_bots(lobby, nivel, faltam)


def remover_bots(lobby, nivel=None):
    """Remove os bots que ainda não entraram numa partida (seguro só na espera)."""
    if lobby is None:
        return 0
    removidos = 0
    for jogador in list(lobby.jogadores):
        if not jogador.is_ia or jogador.partida_atual is not None:
            continue
        if nivel is not None and int(jogador.ia_nivel or 0) != int(nivel):
            continue
        lobby.remover_jogador(jogador.client_id)
        removidos += 1
    return removidos


# ---------------------------------------------------------------------------
# Motor de decisão (funções puras)
# ---------------------------------------------------------------------------

def total_dados_ativos(rodada):
    """Soma dos dados na mesa (somente jogadores ainda na partida)."""
    return sum(jogador.dados_qtd for jogador in rodada.da_partida.jogadores)


def contar_suporte(dados, face, coringa):
    """Quantos dos dados informados apoiam a face (o 1 conta quando o coringa está ativo)."""
    total = 0
    for dado in dados:
        if dado == face or (coringa and face != 1 and dado == 1):
            total += 1
    return total


def probabilidade_verdade(face, quantidade, suporte, desconhecidos, coringa):
    """
    P(total de dados que apoiam `face` >= `quantidade`), tratando os dados
    desconhecidos como independentes. Face 1 ou sem coringa: p = 1/6; face != 1
    com coringa: p = 2/6 (o 1 vale como a face).
    """
    if desconhecidos <= 0:
        return 1.0 if suporte >= quantidade else 0.0
    p = (1.0 / 6.0) if (face == 1 or not coringa) else (2.0 / 6.0)
    precisam = max(0, quantidade - suporte)
    if precisam > desconhecidos:
        return 0.0
    prob = 0.0
    for k in range(precisam, desconhecidos + 1):
        prob += math.comb(desconhecidos, k) * (p ** k) * ((1.0 - p) ** (desconhecidos - k))
    return prob


def gerar_apostas_validas(rodada):
    """Todas as apostas (face, quantidade) legais para o próximo turno da rodada."""
    turno_ant = rodada.turnos[-1] if rodada.turnos else None
    turno_num = len(rodada.turnos) + 1
    total = total_dados_ativos(rodada)
    apostas = []
    for face in range(1, 7):
        for quantidade in range(1, total + 1):
            if rodada.jogada_valida(face, quantidade, turno_ant, turno_num):
                apostas.append((face, quantidade))
    return apostas


def decidir(jogador, rodada, nivel):
    """
    Decide a ação da IA no seu turno. Devolve:
    - {'acao': 'apostar', 'dado': face, 'quantidade': qtd}
    - {'acao': 'desconfiar'}

    Níveis: 1 = aleatório; 2 = heurístico; 3 = probabilístico; 4 = estratégico.
    """
    try:
        nivel = int(nivel)
    except (TypeError, ValueError):
        nivel = 1
    if nivel not in NOMES_NIVEIS:
        nivel = 1

    ultimo = rodada.turnos[-1] if rodada.turnos else None

    # Nível 1: sem raciocínio — aposta aleatória e desconfia por acaso.
    if nivel == 1:
        if ultimo is not None and secrets.randbelow(100) < 10:
            return {'acao': 'desconfiar'}
        apostas = gerar_apostas_validas(rodada)
        if not apostas:
            return _sem_aposta(ultimo)
        face, quantidade = secrets.choice(apostas)
        return {'acao': 'apostar', 'dado': face, 'quantidade': quantidade}

    coringa = rodada.com_coringa
    meus = list(jogador.dados)
    desconhecidos = max(0, total_dados_ativos(rodada) - len(meus))
    probabilidade = None
    if ultimo is not None:
        suporte = contar_suporte(meus, ultimo.dado_face, coringa)
        probabilidade = probabilidade_verdade(
            ultimo.dado_face, ultimo.dado_qtd, suporte, desconhecidos, coringa
        )

    limiar = _limiar_desconfianca(rodada, nivel, ultimo)
    desconfia = probabilidade is not None and probabilidade < limiar
    # Nível 2 é imperfeito: mesmo achando a aposta ruim, às vezes deixa passar.
    if nivel == 2 and desconfia and secrets.randbelow(100) < 35:
        desconfia = False
    if desconfia:
        return {'acao': 'desconfiar'}

    aposta = _escolher_aposta(rodada, jogador, nivel)
    if aposta is None:
        return _sem_aposta(ultimo)
    face, quantidade = aposta
    return {'acao': 'apostar', 'dado': face, 'quantidade': quantidade}


def _sem_aposta(ultimo):
    if ultimo is not None:
        return {'acao': 'desconfiar'}
    return {'acao': 'apostar', 'dado': 1, 'quantidade': 1}


def _limiar_desconfianca(rodada, nivel, ultimo):
    """Probabilidade abaixo da qual a IA desconfia da última aposta."""
    if ultimo is None:
        return 0.0
    if nivel == 2:
        return 0.30
    if nivel == 3:
        return 0.40
    # Nível 4: mais seletivo para desconfiar; sobe um pouco em disputas longas,
    # quando as apostas costumam ficar exageradas.
    return min(0.55, 0.30 + min(0.10, len(rodada.turnos) * 0.02))


def _escolher_aposta(rodada, jogador, nivel):
    apostas = gerar_apostas_validas(rodada)
    if not apostas:
        return None
    if nivel == 2:
        return _menor_aposta(apostas)
    if nivel == 3:
        return _melhor_aposta(rodada, jogador, apostas)
    return _aposta_de_pressao(rodada, jogador, apostas)


def _menor_aposta(apostas):
    """Aposta de menor quantidade (e menor face no empate)."""
    return min(apostas, key=lambda aposta: (aposta[1], aposta[0]))


def _probabilidade_aposta(rodada, jogador, face, quantidade):
    """Probabilidade de uma aposta ser verdadeira, dado o que a IA conhece."""
    coringa = rodada.com_coringa
    meus = list(jogador.dados)
    desconhecidos = max(0, total_dados_ativos(rodada) - len(meus))
    suporte = contar_suporte(meus, face, coringa)
    return probabilidade_verdade(face, quantidade, suporte, desconhecidos, coringa)


def _melhor_aposta(rodada, jogador, apostas):
    """Aposta mais defensável (maior P), desempatando pela menor."""
    return min(apostas, key=lambda aposta: (-_probabilidade_aposta(rodada, jogador, *aposta),
                                            aposta[1], aposta[0]))


def _aposta_de_pressao(rodada, jogador, apostas):
    """
    Nível 4: entre as apostas ainda seguras (P >= 0.60), escolhe a de maior
    quantidade — pressiona o próximo sem apostar algo provavelmente falso.
    Sem nenhuma segura, cai na mais defensável.
    """
    seguras = [aposta for aposta in apostas
               if _probabilidade_aposta(rodada, jogador, *aposta) >= 0.60]
    if seguras:
        return max(seguras, key=lambda aposta: (aposta[1], aposta[0]))
    return _melhor_aposta(rodada, jogador, apostas)


def executar_acao(jogador, rodada, acao):
    """Aplica a ação decidida ao modelo, pelos mesmos caminhos do fluxo humano."""
    if not isinstance(acao, dict):
        return
    if acao.get('acao') == 'desconfiar' and rodada.turnos:
        rodada.desconfiar(jogador=jogador)
        return
    if acao.get('acao') == 'apostar':
        try:
            face = int(acao.get('dado'))
            quantidade = int(acao.get('quantidade'))
        except (TypeError, ValueError):
            return
        rodada.construir_turno(jogador=jogador, dados={'dado': face, 'quantidade': quantidade})


# ---------------------------------------------------------------------------
# Orquestrador
# ---------------------------------------------------------------------------

def processar(lobby):
    """
    Faz as IAs agirem até o jogo precisar de um humano (ou acabar). Chamado ao
    fim de cada handler mutável, sob o lock da sala. Devolve True se algo mudou.
    """
    if lobby is None:
        return False
    limite = max(50, len(lobby.jogadores) * 8)
    mudou = False
    for _ in range(limite):
        pagina = lobby.pagina
        if pagina == 1:
            avancou = _processar_rolagem(lobby)
        elif pagina == 2:
            avancou = _processar_turno(lobby)
        elif pagina == 3:
            avancou = _processar_conferencia(lobby)
        elif pagina == 4:
            avancou = _processar_vitoria(lobby)
        else:
            break
        if not avancou:
            break
        mudou = True
    return mudou


def _partida_atual(lobby):
    if not lobby.partidas:
        return None
    return lobby.partidas[-1]


def _processar_rolagem(lobby):
    """Marca as IAs como prontas na rolagem e destrava a ida para a página 2."""
    partida = _partida_atual(lobby)
    if partida is None or not partida.rodadas:
        return False
    rodada = partida.rodadas[-1]
    for jogador in partida.jogadores:
        if jogador.is_ia:
            jogador.joguei_dados = True
    if rodada.verificar_se_todos_ja_jogaram_seus_dados():
        lobby.pagina = 2
        funcoes_gerais.mudar_pagina(2, sala=lobby.sala_id)
        return True
    return False


def _processar_turno(lobby):
    """Se a vez é de uma IA, decide e executa (o turno continua até chegar num humano)."""
    partida = _partida_atual(lobby)
    if partida is None or not partida.rodadas:
        return False
    rodada = partida.rodadas[-1]
    vez = rodada.vez_atual
    if vez is None or not vez.is_ia or vez not in partida.jogadores:
        return False
    turnos_antes = len(rodada.turnos)
    pagina_antes = lobby.pagina
    acao = decidir(vez, rodada, vez.ia_nivel)
    executar_acao(vez, rodada, acao)
    # Sem progresso (jogada rejeitada): para para não girar em falso.
    if lobby.pagina == pagina_antes and len(rodada.turnos) == turnos_antes and rodada.vez_atual is vez:
        return False
    return True


def _processar_conferencia(lobby):
    """Confirma a conferência das IAs e engatilha a próxima rodada quando fecha."""
    partida = _partida_atual(lobby)
    if partida is None or not partida.rodadas:
        return False
    rodada = partida.rodadas[-1]
    houve = False
    for jogador in list(rodada.jogadores):
        if jogador.is_ia and not jogador.confirmou_rodada:
            jogador.confirmou_rodada = True
            rodada.conferiram += 1
            houve = True
    if not houve:
        return False
    if rodada.conferiram >= len(rodada.jogadores):
        partida.construir_rodada()
        return True
    return False


def _processar_vitoria(lobby):
    """Confirma a vitória das IAs e volta ao lobby quando todos confirmam."""
    houve = False
    for jogador in list(lobby.jogadores):
        if jogador.is_ia and not jogador.confirmou_vencedor:
            jogador.confirmou_vencedor = True
            lobby.conferiram_vencedor += 1
            houve = True
    if not houve:
        return False
    if lobby.conferiram_vencedor >= len(lobby.jogadores):
        lobby.resetar_para_lobby()
        funcoes_gerais.atualizar_lista_usuarios(lobby)
        funcoes_gerais.mudar_pagina(0, sala=lobby.sala_id)
        return True
    return False
