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

# Teto de segurança por chamada de `processar`: um jogo inteiro só entre bots
# pode exigir centenas de ações (rolagens, apostas, conferências e vitórias), e
# como `avancou` só é True quando há progresso real, o laço termina sozinho
# quando o jogo acaba. O teto antigo (50) era baixo demais e estacionava jogos
# longos quando o último humano já tinha sido eliminado.
LIMITE_ACOES_PROCESSAR = 10000

# Apelidos dos bots: sorteados a cada criação, misturando designações
# robóticas puras com nomes humanos "robotizados" (prefixo/sufixo/leet).
# A unicidade fica a cargo de Lobby.verificar_apelido.
NOMES_ROBOTICOS = [
    'Chip', 'Bolt', 'Neo', 'Zeta', 'Vex', 'Kilo', 'Orb', 'Pino', 'Byte',
    'Hex', 'Volt', 'Nix', 'Zen', 'Dado', 'Asimo', 'Teco', 'Bino',
]

PREFIXOS_ROBO = ['XJ', 'R2', 'C3', 'TK', 'ZX', 'QB', 'MK', 'AX', 'NV', 'IO',
                 'BOT', 'UNIT', 'NULL']

NOMES_HUMANOS = [
    'Ana', 'Bia', 'Bruno', 'Carla', 'Davi', 'Elisa', 'Fábio', 'Gabi',
    'Heitor', 'Igor', 'Joana', 'Kelly', 'Lucas', 'Marina', 'Nando',
    'Olívia', 'Pedro', 'Rafa', 'Sofia', 'Tati', 'Vitor', 'Zeca',
]

PREFIXOS_HIBRIDOS = ['Robô', 'Cyber', 'Mega', 'Nano', 'Proto', 'Auto']

SUFIXOS_HIBRIDOS = ['Bot', '-9000', '.exe', ' Tron', '-X', ' 2.0', 'Tech', '-Byte']

_TABELA_LEET = str.maketrans('aAeEiIoOsS', '4433110055')


def _nome_robotico():
    """Nome puramente robótico: designação (ex.: 'BOT-42') ou apelido avulso."""
    if secrets.randbelow(2):
        prefixo = secrets.choice(PREFIXOS_ROBO)
        return f"{prefixo}-{secrets.randbelow(99) + 1:02d}"
    return secrets.choice(NOMES_ROBOTICOS)


def _nome_hibrido():
    """Nome humano robotizado (ex.: 'Robô Ana', 'Lucas.exe', 'C4rl4')."""
    nome = secrets.choice(NOMES_HUMANOS)
    estilo = secrets.randbelow(3)
    if estilo == 0:
        return f"{secrets.choice(PREFIXOS_HIBRIDOS)} {nome}"
    if estilo == 1:
        return f"{nome}{secrets.choice(SUFIXOS_HIBRIDOS)}"
    return nome.translate(_TABELA_LEET)


def gerar_nome():
    """Apelido aleatório de bot (robótico ou híbrido), já com o marcador 🤖."""
    apelido = _nome_robotico() if secrets.randbelow(2) else _nome_hibrido()
    return f"🤖 {apelido}"


def sorteiar_personalidade(jogador):
    """
    Sorteia a personalidade de um bot (0-1 em cada eixo): predisposição a risco
    e agressividade nas apostas. Usado também quando um humano desconectado é
    substituído por IA (Fase 20).
    """
    jogador.ia_risco = round(secrets.randbelow(101) / 100, 2)
    jogador.ia_agressividade = round(secrets.randbelow(101) / 100, 2)
    return jogador


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
        username = lobby.verificar_apelido(gerar_nome())
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
    Cada bot carrega uma personalidade (ia_risco/ia_agressividade, 0-1) que
    desloca desconfiança, altura das apostas e impulsividade — e um pouco de
    ruído mantém o mesmo bot imprevisível lance a lance.
    """
    try:
        nivel = int(nivel)
    except (TypeError, ValueError):
        nivel = 1
    if nivel not in NOMES_NIVEIS:
        nivel = 1

    risco = float(getattr(jogador, 'ia_risco', 0.5) or 0.5)
    agressividade = float(getattr(jogador, 'ia_agressividade', 0.5) or 0.5)
    ultimo = rodada.turnos[-1] if rodada.turnos else None

    # Nível 1: sem raciocínio — aposta aleatória e desconfia por acaso.
    if nivel == 1:
        # Ousadia e agressividade mudam o apetite: cautelosos desconfiam mais,
        # agressivos preferem atacar a apostar na defensiva.
        chance_desconfiar = max(0, 6 + int(risco * 20) - int(agressividade * 8))
        if ultimo is not None and secrets.randbelow(100) < chance_desconfiar:
            return {'acao': 'desconfiar'}
        apostas = gerar_apostas_validas(rodada)
        if not apostas:
            return _sem_aposta(ultimo)
        if agressividade > 0.7 and ultimo is not None and secrets.randbelow(100) < 30:
            face, quantidade = _aposta_mais_alta(apostas)
        else:
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

    limiar = _limiar_desconfianca(rodada, nivel, ultimo, risco, agressividade)
    desconfia = probabilidade is not None and probabilidade < limiar
    # Nível 2 é imperfeito: mesmo achando a aposta ruim, às vezes deixa passar.
    if nivel == 2 and desconfia and secrets.randbelow(100) < 35:
        desconfia = False
    # Impulso de imprevisibilidade: às vezes desconfia sem ter a certeza do
    # cálculo (ou se furta a desconfiar quando deveria). Ousados chamam mais.
    if not desconfia and ultimo is not None and secrets.randbelow(100) < int(risco * 12):
        desconfia = True
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


def _limiar_desconfianca(rodada, nivel, ultimo, risco=0.5, agressividade=0.5):
    """Probabilidade abaixo da qual a IA desconfia da última aposta."""
    if ultimo is None:
        return 0.0
    if nivel == 2:
        base = 0.30
    elif nivel == 3:
        base = 0.40
    # Nível 4: mais seletivo para desconfiar; sobe um pouco em disputas longas,
    # quando as apostas costumam ficar exageradas.
    else:
        base = min(0.55, 0.30 + min(0.10, len(rodada.turnos) * 0.02))
    # Ousados/agressivos seguram a desconfiança e empurram o jogo; cautelosos
    # puxam o freio cedo.
    base *= max(0.05, 1.0 - 0.30 * risco - 0.15 * agressividade)
    # Ruído: o mesmo bot não desconfia sempre na mesma probabilidade.
    base *= 0.85 + 0.30 * (secrets.randbelow(101) / 100)
    return base


def _escolher_aposta(rodada, jogador, nivel):
    apostas = gerar_apostas_validas(rodada)
    if not apostas:
        return None
    risco = float(getattr(jogador, 'ia_risco', 0.5) or 0.5)
    agressividade = float(getattr(jogador, 'ia_agressividade', 0.5) or 0.5)
    if nivel == 2:
        return _aposta_heuristica(apostas, agressividade)
    if nivel == 3:
        return _melhor_aposta(rodada, jogador, apostas, risco, agressividade)
    return _aposta_de_pressao(rodada, jogador, apostas, risco, agressividade)


def _aposta_heuristica(apostas, agressividade):
    """
    Nível 2: aposta baixa, mas agressivos sobem degraus na escala (quantidade
    primeiro, face no empate) de vez em quando — e sempre com um toque de sorte.
    """
    ordenadas = sorted(apostas, key=lambda aposta: (aposta[1], aposta[0]))
    if len(ordenadas) <= 1:
        return ordenadas[0] if ordenadas else None
    max_degraus = min(len(ordenadas) - 1, 1 + int(agressividade * 3))
    degraus = secrets.randbelow(max_degraus + 1)
    return ordenadas[degraus]


def _aposta_mais_alta(apostas):
    """Aposta de maior quantidade (e maior face no empate)."""
    return max(apostas, key=lambda aposta: (aposta[1], aposta[0]))


def _probabilidade_aposta(rodada, jogador, face, quantidade):
    """Probabilidade de uma aposta ser verdadeira, dado o que a IA conhece."""
    coringa = rodada.com_coringa
    meus = list(jogador.dados)
    desconhecidos = max(0, total_dados_ativos(rodada) - len(meus))
    suporte = contar_suporte(meus, face, coringa)
    return probabilidade_verdade(face, quantidade, suporte, desconhecidos, coringa)


def _melhor_aposta(rodada, jogador, apostas, risco=0.5, agressividade=0.5):
    """
    Entre as apostas mais defensáveis (maior P), escolhe uma com inclinação pela
    quantidade conforme a personalidade: ousados/agressivos encaram candidatas
    menos prováveis (maiores quantidades), cautelosos ficam no topo da certeza.
    """
    ordenadas = sorted(apostas, key=lambda aposta: (-_probabilidade_aposta(rodada, jogador, *aposta),
                                                    aposta[1], aposta[0]))
    if not ordenadas:
        return None
    # Quantas candidatas entram na disputa: cresce com ousadia e agressividade.
    fatia = 1 + int((agressividade * 4 + risco * 3) * (0.5 + secrets.randbelow(101) / 100))
    candidatas = ordenadas[:max(1, min(len(ordenadas), fatia))]
    # Puxa para a maior quantidade dentro da fatia (mais ainda se agressivo).
    return max(candidatas, key=lambda aposta: (aposta[1] * (0.5 + agressividade), aposta[0]))


def _aposta_de_pressao(rodada, jogador, apostas, risco=0.5, agressividade=0.5):
    """
    Nível 4: entre as apostas ainda seguras (P >= piso), escolhe a de maior
    quantidade — pressiona o próximo sem apostar algo provavelmente falso. O piso
    cai com a ousadia do bot (blefa mais); sem nenhuma segura, cai na mais
    defensável, já com a personalidade na conta.
    """
    piso = max(0.05, 0.60 - 0.30 * risco)
    seguras = [aposta for aposta in apostas
               if _probabilidade_aposta(rodada, jogador, *aposta) >= piso]
    if seguras:
        return max(seguras, key=lambda aposta: (aposta[1], aposta[0]))
    return _melhor_aposta(rodada, jogador, apostas, risco, agressividade)


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
    limite = max(LIMITE_ACOES_PROCESSAR, len(lobby.jogadores) * 8)
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
    # Fase 22: humanos acompanham em tempo real quem já rolou.
    funcoes_gerais.emitir_status_rolagem(lobby)
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
    for jogador in list(rodada.jogadores):
        if jogador.is_ia and not jogador.confirmou_rodada:
            jogador.confirmou_rodada = True
            rodada.conferiram += 1
    # Fase 22: humanos acompanham em tempo real quem já confirmou (as IAs
    # confirmam na hora; sem isto o status ficaria desatualizado).
    funcoes_gerais.emitir_status_conferencia(lobby)
    # Fecha mesmo sem nova confirmação agora: o contador já pode estar completo
    # (ex.: um humano caiu na conferência depois de as IAs confirmarem) e, sem
    # isto, a rodada ficaria presa para sempre na tela de conferência.
    if rodada.conferiram >= len(rodada.jogadores):
        partida.construir_rodada()
        return True
    return False


def _processar_vitoria(lobby):
    """Confirma a vitória das IAs e volta ao lobby quando todos confirmam."""
    for jogador in list(lobby.jogadores):
        if jogador.is_ia and not jogador.confirmou_vencedor:
            jogador.confirmou_vencedor = True
            lobby.conferiram_vencedor += 1
    # Fase 22: idem `_processar_conferencia` — status em tempo real.
    funcoes_gerais.emitir_status_vitoria(lobby)
    # Idem `_processar_conferencia`: fecha mesmo sem nova confirmação, senão a
    # tela de vitória fica presa quando o contador já está completo.
    if lobby.conferiram_vencedor >= len(lobby.jogadores):
        lobby.resetar_para_lobby()
        funcoes_gerais.atualizar_lista_usuarios(lobby)
        funcoes_gerais.mudar_pagina(0, sala=lobby.sala_id)
        return True
    return False
