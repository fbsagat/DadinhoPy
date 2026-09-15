"""
Jogadores controlados por IA (Fase 11).

Quatro responsabilidades:
- Motor de decisão puro (probabilidade binomial + perfis por nível), sem I/O;
- Leitura de oponentes (Fase 36): memória, só dentro da partida atual, de como
  cada adversário jogou nas rodadas já fechadas;
- Medo e coragem (Fase 37): instinto ligado a quantos dados restam — não é
  personalidade fixa, é o "estado de espírito" da rodada, e vale pra qualquer
  nível;
- Orquestrador `processar(lobby)`, que roda dentro do request que mudou o estado
  e faz as IAs agirem em sequência (rolagem, apostas, desconfiança, conferência
  e vitória). Nada de threads/timers: serverless-safe.

Regra de ouro: a IA só enxerga os PRÓPRIOS dados e a informação pública da
RODADA ATUAL (turnos, quantidade de dados restantes). É proibido ler
`rodada.todos_os_dados`/`rodada.dados_por_jogador` da rodada em andamento
(`partida.rodadas[-1]`), que contêm os dados reais de todos antes da hora.

Isso NÃO se estende às rodadas já fechadas (`partida.rodadas[:-1]`): o
resultado delas (quem blefou, quem desconfiou certo) já foi mostrado a todo
mundo na tela de conferência, então é informação tão pública quanto a memória
de um humano prestando atenção na mesa. É exatamente isso que a seção
"Leitura de oponentes" usa — nunca a rodada corrente. A quantidade de dados
de cada jogador (`jogador.dados_qtd`, usada pelo medo/coragem) também é
sempre pública — aparece na tela pra todo mundo o jogo inteiro.
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

# Leitura de oponentes (Fase 36): nº mínimo de observações desta partida antes
# de a IA "confiar" numa leitura sobre um adversário específico — com menos
# que isso, um humano também não teria formado opinião, então o ajuste fica
# neutro. PESO_* limita o quanto essa leitura pode mexer na conta pura (nunca
# substitui a matemática, só a inclina — mantém o range de personalidade).
AMOSTRA_MINIMA_LEITURA = 3
PESO_LEITURA_MESTRE = 0.35
PESO_LEITURA_PERITO = 0.18

# Medo/coragem (Fase 37): instinto de sobrevivência ligado à quantidade de
# dados na mesa — não é personalidade fixa (isso continua sendo
# ia_risco/ia_agressividade), é o "estado de espírito" da rodada, e vale para
# qualquer nível (até o Novato sente o aperto de jogar com um dado só). Medo é
# comum: todo bot carrega uma pitada natural de cautela. Coragem "do nada" é
# rara — um lampejo ocasional de audácia sem motivo. PESO_MEDO_CORAGEM limita
# o quanto isso desloca risco/agressividade só nesta decisão: nunca troca a
# personalidade do bot, só a inclina pro mais cauteloso ou pro mais ousado.
MEDO_NATURAL_BASE = 0.10
CHANCE_CORAGEM_NATURAL = 8       # % de chance por decisão
IMPULSO_CORAGEM_NATURAL = 0.35
PESO_MEDO_CORAGEM = 0.35
AJUSTE_PISO_MAXIMO = 0.15

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


# ---------------------------------------------------------------------------
# Leitura de oponentes (memória dentro da partida — Fase 36)
# ---------------------------------------------------------------------------
#
# Só entra aqui o desfecho de rodadas JÁ FECHADAS (`partida.rodadas[:-1]`): a
# última da lista é sempre a rodada em andamento e nunca é tocada por estas
# funções. Nada de estado novo pra persistir — é só reler o histórico que a
# própria Partida já guarda.

def _desfecho(rodada):
    """
    De uma rodada encerrada: quem fez a aposta que foi desconfiada, quem
    desconfiou dela, e se a aposta era verdadeira. Mesma informação exata que
    a tela de conferência já mostrou a todos os jogadores daquela rodada.
    None se a rodada (por algum estado defensivo) não chegou a fechar
    direito — não deveria acontecer para uma rodada que já ficou pra trás.
    """
    if not rodada.turnos or rodada.vencedor is None or rodada.perdedor is None:
        return None
    apostador = rodada.turnos[-1].do_jogador
    verdadeira = rodada.vencedor is apostador
    desafiante = rodada.perdedor if verdadeira else rodada.vencedor
    return {'apostador': apostador, 'desafiante': desafiante, 'verdadeira': verdadeira}


def perfil_oponente(partida, alvo):
    """
    Reconstrói, só a partir das rodadas já fechadas desta partida, como
    `alvo` jogou até agora: quantas vezes a aposta final dele era blefe, e
    quantas vezes ele acertou ao desconfiar. Recalculado a cada chamada (o
    histórico é curto — dezenas de rodadas no máximo) em vez de guardado à
    parte, então não há estado novo para migrar/serializar.
    """
    perfil = {'apostas_finais': 0, 'blefes': 0, 'desafios': 0, 'desafios_certos': 0}
    for rodada_passada in partida.rodadas[:-1]:
        desfecho = _desfecho(rodada_passada)
        if desfecho is None:
            continue
        if desfecho['apostador'] is alvo:
            perfil['apostas_finais'] += 1
            if not desfecho['verdadeira']:
                perfil['blefes'] += 1
        if desfecho['desafiante'] is alvo:
            perfil['desafios'] += 1
            if not desfecho['verdadeira']:
                perfil['desafios_certos'] += 1
    return perfil


def _taxa_confiavel(sucessos, total, minimo=AMOSTRA_MINIMA_LEITURA):
    """
    Converte uma contagem em taxa (0.0-1.0), ou None sem observações
    suficientes. Como um humano prestando atenção na mesa, a IA só forma
    opinião sobre alguém depois de vê-lo jogar algumas vezes — com pouca
    informação, o ajuste correspondente fica neutro (não mexe em nada).
    """
    if total < minimo:
        return None
    return sucessos / total


def leitura_blefe(partida, alvo):
    """Com que frequência a aposta final de `alvo` era blefe nesta partida
    (None sem histórico suficiente)."""
    perfil = perfil_oponente(partida, alvo)
    return _taxa_confiavel(perfil['blefes'], perfil['apostas_finais'])


def leitura_desafio(partida, alvo):
    """Com que frequência `alvo` acerta quando desconfia nesta partida
    (None sem histórico suficiente)."""
    perfil = perfil_oponente(partida, alvo)
    return _taxa_confiavel(perfil['desafios_certos'], perfil['desafios'])


# ---------------------------------------------------------------------------
# Medo e coragem (Fase 37)
# ---------------------------------------------------------------------------

def _pressao_situacional(rodada, jogador):
    """
    Medo/coragem que vem da SITUAÇÃO na mesa, não do temperamento: poucos
    dados assustam (perto de ser eliminado, joga mais brando), dados de
    sobra encorajam (a queda não dói tanto, dá pra arriscar mais). Compara
    com o máximo de dados permitido nesta partida e com os adversários ainda
    na mesa. Devolve algo entre ~-1 (medo máximo) e ~+1 (coragem máxima).
    """
    partida = rodada.da_partida
    meus = jogador.dados_qtd
    maximo = max(1, int(getattr(partida, 'dados_qtd', meus) or meus))
    outros = [j.dados_qtd for j in partida.jogadores if j is not jogador]

    escassez = 1.0 - (meus - 1) / max(1, maximo - 1)  # 0 (no máximo) .. 1 (só 1 dado)
    medo = escassez
    if outros and sum(1 for o in outros if o > meus) > len(outros) / 2:
        medo = min(1.0, medo + 0.25)  # a maioria da mesa já tem mais dados que eu

    coragem = 0.0
    if outros and sum(1 for o in outros if o < meus) > len(outros) / 2:
        coragem += 0.5  # tenho mais dados que a maioria
    if meus >= maximo:
        coragem += 0.5  # ainda no máximo permitido pela partida — não perdi nenhum
    coragem = min(1.0, coragem)

    return coragem - medo


def _fator_medo_coragem(rodada, jogador):
    """
    Combina o medo natural (sempre presente, em pouca dose — é o comum), um
    lampejo raro de coragem sem motivo situacional nenhum, e a leitura da
    mesa (quantos dados sobram, os meus e os dos outros). Quanto mais
    coragem no resultado, menor a barra de probabilidade que o bot topa
    aceitar como razoável (jogadas mais arriscadas); quanto mais medo, maior
    essa barra (jogadas mais brandas). Resultado aproximado entre -1 e +1.
    """
    medo = MEDO_NATURAL_BASE
    coragem = IMPULSO_CORAGEM_NATURAL if secrets.randbelow(100) < CHANCE_CORAGEM_NATURAL else 0.0
    situacional = _pressao_situacional(rodada, jogador)
    if situacional >= 0:
        coragem += situacional
    else:
        medo += -situacional
    return max(-1.0, min(1.0, coragem - medo))


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

    Níveis: 1 = aleatório (com intuição — não chuta jogada implausível);
    2 = heurístico; 3 = probabilístico (+ leitura leve do adversário);
    4 = estratégico (probabilístico + leitura do adversário mais confiante,
    inclusive de quem vai responder à própria aposta).
    Cada bot carrega uma personalidade (ia_risco/ia_agressividade, 0-1) que
    desloca desconfiança, altura das apostas e impulsividade — e um pouco de
    ruído mantém o mesmo bot imprevisível lance a lance. Por cima disso, todo
    nível sente medo/coragem conforme os dados que restam: com poucos dados
    joga mais brando, com dados de sobra (ou ainda no máximo da partida)
    arrisca mais — instinto, não cálculo, então vale até pro Novato.
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

    # Fase 37: medo/coragem é instinto de sobrevivência (quantos dados
    # restam), não personalidade — desloca risco/agressividade só para esta
    # decisão, pra qualquer nível.
    fator = _fator_medo_coragem(rodada, jogador)
    risco_efetivo = max(0.0, min(1.0, risco + fator * PESO_MEDO_CORAGEM))
    agressividade_efetiva = max(0.0, min(1.0, agressividade + fator * PESO_MEDO_CORAGEM))

    # Nível 1: sem raciocínio — aposta aleatória e desconfia por acaso.
    if nivel == 1:
        # Ousadia e agressividade mudam o apetite: cautelosos desconfiam mais,
        # agressivos preferem atacar a apostar na defensiva.
        chance_desconfiar = max(0, 6 + int(risco_efetivo * 20) - int(agressividade_efetiva * 8))
        if ultimo is not None and secrets.randbelow(100) < chance_desconfiar:
            return {'acao': 'desconfiar'}
        apostas = gerar_apostas_validas(rodada)
        if not apostas:
            return _sem_aposta(ultimo)
        if agressividade_efetiva > 0.7 and ultimo is not None and secrets.randbelow(100) < 30:
            face, quantidade = _aposta_mais_alta(apostas)
        else:
            face, quantidade = _aposta_por_intuicao(apostas, ultimo, risco_efetivo)
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
        # Fase 36: Perito/Mestre temperam a conta pura com o histórico deste
        # adversário específico nesta partida (rodadas já fechadas). Níveis 1
        # e 2 não fazem essa leitura — continuam só no cálculo/heurística de
        # sempre.
        probabilidade = _ler_probabilidade(rodada, ultimo, probabilidade, nivel)

    limiar = _limiar_desconfianca(rodada, nivel, ultimo, risco_efetivo, agressividade_efetiva)
    desconfia = probabilidade is not None and probabilidade < limiar
    # Nível 2 é imperfeito: mesmo achando a aposta ruim, às vezes deixa passar.
    if nivel == 2 and desconfia and secrets.randbelow(100) < 35:
        desconfia = False
    # Impulso de imprevisibilidade: às vezes desconfia sem ter a certeza do
    # cálculo (ou se furta a desconfiar quando deveria). É um tique da
    # personalidade fixa (ousados chamam mais por impulso) — usa o risco
    # original, não o efetivo: medo/coragem já atuou no limiar acima e na
    # aposta escolhida, não deveria também inflar esse impulso aleatório.
    if not desconfia and ultimo is not None and secrets.randbelow(100) < int(risco * 12):
        desconfia = True
    if desconfia:
        return {'acao': 'desconfiar'}

    aposta = _escolher_aposta(rodada, jogador, nivel, risco_efetivo, agressividade_efetiva)
    if aposta is None:
        return _sem_aposta(ultimo)
    face, quantidade = aposta
    return {'acao': 'apostar', 'dado': face, 'quantidade': quantidade}


def _sem_aposta(ultimo):
    if ultimo is not None:
        return {'acao': 'desconfiar'}
    return {'acao': 'apostar', 'dado': 1, 'quantidade': 1}


def _ler_probabilidade(rodada, ultimo, probabilidade, nivel):
    """
    Nível 3/4: sobre a probabilidade matemática pura, aplica um ajuste
    limitado conforme o quanto ESTE apostador específico já blefou nesta
    partida (rodadas já fechadas — nunca a atual). Quem já blefou muito
    ganha menos crédito do que a conta pura daria; quem raramente blefou
    ganha um pouco mais de benefício da dúvida — do jeito que um jogador
    atento também ajustaria a leitura pela pessoa, não só pelos números.
    Mestre (4) confia mais nessa leitura do que Perito (3); níveis 1 e 2
    não a fazem (devolvem a probabilidade sem alteração).
    """
    if probabilidade is None or nivel not in (3, 4):
        return probabilidade
    taxa = leitura_blefe(rodada.da_partida, ultimo.do_jogador)
    if taxa is None:
        return probabilidade
    peso = PESO_LEITURA_MESTRE if nivel == 4 else PESO_LEITURA_PERITO
    desvio = (taxa - 0.5) * 2 * peso  # -peso .. +peso
    ajustada = probabilidade * (1.0 - desvio)
    return max(0.0, min(1.0, ajustada))


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


def _escolher_aposta(rodada, jogador, nivel, risco=0.5, agressividade=0.5):
    apostas = gerar_apostas_validas(rodada)
    if not apostas:
        return None
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


def _aposta_por_intuicao(apostas, ultimo, risco):
    """
    Nível 1 não calcula probabilidade nenhuma, mas isso não é motivo pra
    chutar entre QUALQUER jogada legal — isso incluiria saltos de quantidade
    gigantescos e implausíveis que nem um novato de verdade tentaria (dá pra
    ser fraco sem ser insensato). Em vez de sortear uniforme, pesa cada
    jogada pela distância da quantidade até a última aposta: incrementos
    pequenos pesam mais, sem travar sempre no mínimo quando várias faces
    empatam na mesma quantidade (o decaimento é suave, não um corte seco —
    todo lance legal continua possível, só menos provável quanto mais
    longe). Ousados (risco alto) decaem mais devagar e toleram saltos
    maiores. A abertura da rodada (sem aposta anterior) continua livre, não
    há "exagero" ainda para comparar.
    """
    if ultimo is None:
        return secrets.choice(apostas)
    decaimento = 0.35 + 0.55 * risco  # 0.35 (cauteloso) .. 0.90 (ousado)
    pesos = [int(10000 * decaimento ** abs(qtd - ultimo.dado_qtd)) + 1 for _, qtd in apostas]
    alvo = secrets.randbelow(sum(pesos))
    acumulado = 0
    for aposta, peso in zip(apostas, pesos):
        acumulado += peso
        if alvo < acumulado:
            return aposta
    return apostas[-1]  # defensivo: a soma acima garante que não chega aqui


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
    Nível 4: entre as apostas ainda seguras (P >= piso), pressiona com uma das
    maiores quantidades — sem travar sempre na mesma escolha cravada, o que
    ficaria previsível/robótico rápido demais. O piso cai com a ousadia do bot
    (blefa mais) e ainda sobe ou desce um pouco conforme o quanto o PRÓXIMO
    jogador da rodada costuma acertar ao desconfiar nesta partida — evita
    empurrar demais contra quem tende a chamar, e relaxa contra quem quase
    nunca desconfia. Sem nenhuma segura, cai na mais defensável, já com a
    personalidade na conta.
    """
    piso = max(0.05, 0.60 - 0.30 * risco)
    piso = _ajustar_piso_pelo_proximo(piso, rodada, jogador)
    seguras = [aposta for aposta in apostas
               if _probabilidade_aposta(rodada, jogador, *aposta) >= piso]
    if seguras:
        ordenadas = sorted(seguras, key=lambda aposta: (-aposta[1], -aposta[0]))
        fatia = 1 + int(agressividade * 2)
        candidatas = ordenadas[:max(1, min(len(ordenadas), fatia))]
        return secrets.choice(candidatas)
    return _melhor_aposta(rodada, jogador, apostas, risco, agressividade)


def _ajustar_piso_pelo_proximo(piso, rodada, jogador):
    """
    Antes de decidir até onde empurrar a aposta, dá uma espiada em quem vai
    responder: contra quem desconfia muito e acerta (rodadas já fechadas
    desta partida), sobe um pouco o piso de segurança; contra quem quase não
    desconfia, relaxa um pouco. Ajuste pequeno e limitado — não troca a
    ousadia do bot, só a calibra pra mesa em jogo.
    """
    jogadores = rodada.da_partida.jogadores
    if jogador not in jogadores or len(jogadores) < 2:
        return piso
    proximo = rodada.selecionar_proximo_jogador_na_lista(jogador)
    taxa = leitura_desafio(rodada.da_partida, proximo)
    if taxa is None:
        return piso
    ajuste = (taxa - 0.5) * 2 * AJUSTE_PISO_MAXIMO
    return max(0.03, min(0.85, piso + ajuste))


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
