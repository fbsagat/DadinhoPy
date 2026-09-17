"""
Narrador da partida e tempo de pensamento dos bots.

Centraliza os textos em pt-BR de cada lance (com muitas variações de fala) e o
cálculo do "tempo de pensamento" das IAs. O narrador é "inteligente": além das
falas genéricas, ele lê apenas informação **pública** (quantos dados cada um tem,
total de dados na mesa, coringa ativo, se é a abertura da rodada, se a aposta
saltou...) e comenta a situação — nunca revela os dados escondidos de ninguém.

i18n: cada payload de narração carrega, além do `texto` em pt-BR (fallback), uma
lista `segmentos` de `{'chave', 'params'}`. O narrador não sabe o idioma do
jogador: o cliente resolve as chaves no idioma dele (static/i18n.js). Assim a
narração continua sendo emitida uma única vez para a room, sem timers.

O atraso é só um número em milissegundos: quem o aplica é o cliente, através da
fila de animação — nada de sleep/thread no servidor (serverless-safe).
"""

import secrets


# Faixa de tempo (ms) que um bot "pensa" antes de agir. Quanto mais inteligente
# o nível, maior a pausa (dá a sensação de raciocínio mais elaborado). O range
# é propositalmente largo: a personalidade do bot e a situação da mesa
# (só bots com dados) encolhem ou esticam esse tempo a cada lance.
FAIXAS_PENSAMENTO = {
    1: (800, 1350),
    2: (1050, 1985),
    3: (1400, 2720),
    4: (1800, 3560),
}

NOMES_FACES = {
    1: ('ás', 'ases'),
    2: ('duque', 'duques'),
    3: ('terno', 'ternos'),
    4: ('quadra', 'quadras'),
    5: ('quina', 'quinas'),
    6: ('sena', 'senas'),
}


def tempo_pensamento(nivel, jogador=None, so_ias=False):
    """
    Atraso (ms) de pensamento do bot; maior nos níveis mais inteligentes.
    A personalidade modula o ritmo: bots ousados/agressivos decidem mais rápido
    (impulso), ponderados/cautelosos demoram mais — mais imprevisibilidade.
    Quando só restam IAs com dados na partida (`so_ias`), o jogo acelera.
    """
    try:
        nivel = int(nivel)
    except (TypeError, ValueError):
        nivel = 1
    faixa = FAIXAS_PENSAMENTO.get(nivel, FAIXAS_PENSAMENTO[1])
    atraso = secrets.randbelow(faixa[1] - faixa[0] + 1) + faixa[0]
    if jogador is not None and getattr(jogador, 'is_ia', False):
        risco = float(getattr(jogador, 'ia_risco', 0.5) or 0.5)
        agressividade = float(getattr(jogador, 'ia_agressividade', 0.5) or 0.5)
        atraso = int(atraso * (1.0 - 0.18 * risco - 0.12 * agressividade))
    if so_ias:
        atraso = int(atraso * 0.70)
    return max(120, atraso)


def nome_face(face, quantidade):
    """Nome da face no singular/plural (ex.: 2 quadras, 1 ás)."""
    singular, plural = NOMES_FACES.get(int(face), ('dado', 'dados'))
    return plural if quantidade > 1 else singular


def _pick(opcoes):
    return secrets.choice(opcoes)


def _item(chave, texto, **params):
    """Fala traduzível: chave i18n, texto pt-BR e parâmetros de interpolação."""
    return {'chave': chave, 'texto': texto, 'params': params}


def _seg(item, **extras):
    """Segmento do payload: a chave + os parâmetros (mesclados com extras)."""
    params = dict(item.get('params') or {})
    params.update(extras)
    return {'chave': item['chave'], 'params': params}


def _comentar(especiais, genericas, chance=72):
    """
    Prefere uma fala contextual (quando existe contexto relevante), mas de vez em
    quando volta às falas genéricas para não repetir sempre o mesmo bordão.
    """
    if especiais and (not genericas or secrets.randbelow(100) < chance):
        return _pick(especiais)
    return _pick(genericas or especiais)


def _nome_exibicao(jogador):
    """Nome para o narrador; garante um único 🤖 nos bots (inclusive substituídos)."""
    nome = jogador.username or 'Jogador'
    if jogador.is_ia and not nome.startswith('🤖'):
        return f"🤖 {nome}"
    return nome


# --- Falas de aposta (o {nome}/{qtd}/{face} são preenchidos na hora) ---
_ACOES_APOSTA_IA = [
    _item('narr.aposta.ia.0', "{nome} pensou um pouco e apostou {qtd} {face}."),
    _item('narr.aposta.ia.1', "{nome} arrisca {qtd} {face}."),
    _item('narr.aposta.ia.2', "{nome} calculou direitinho e soltou {qtd} {face}."),
    _item('narr.aposta.ia.3', "{nome} sobe a aposta para {qtd} {face}."),
    _item('narr.aposta.ia.4', "{nome} processa a mesa e anuncia {qtd} {face}."),
    _item('narr.aposta.ia.5', "{nome} roda os circuitos e crava {qtd} {face}."),
    _item('narr.aposta.ia.6', "{nome} faz as contas e lança {qtd} {face}."),
    _item('narr.aposta.ia.7', "{nome} não hesita: {qtd} {face}."),
    _item('narr.aposta.ia.8', "{nome} cruza os dados e responde {qtd} {face}."),
]

_ACOES_APOSTA_HUMANO = [
    _item('narr.aposta.humano.0', "{nome} aposta {qtd} {face}."),
    _item('narr.aposta.humano.1', "{nome} anuncia {qtd} {face}."),
    _item('narr.aposta.humano.2', "{nome} sobe a aposta para {qtd} {face}."),
    _item('narr.aposta.humano.3', "Fala, {nome}! {qtd} {face}."),
    _item('narr.aposta.humano.4', "{nome} joga {qtd} {face} na mesa."),
    _item('narr.aposta.humano.5', "{nome} confia no instinto e diz {qtd} {face}."),
    _item('narr.aposta.humano.6', "{nome} bate a mão na mesa: {qtd} {face}."),
    _item('narr.aposta.humano.7', "{nome} ousa e aposta {qtd} {face}."),
    _item('narr.aposta.humano.8', "{nome} encara a galera e solta {qtd} {face}."),
]

_ABERTURAS = [
    _item('narr.prefixo.abertura.0', "Aberta a rodada: "),
    _item('narr.prefixo.abertura.1', "Primeira palavra da rodada: "),
    _item('narr.prefixo.abertura.2', "Para abrir os trabalhos, "),
    _item('narr.prefixo.abertura.3', "Sem rodeios, "),
    _item('narr.prefixo.abertura.4', "Quem começa é: "),
]

_TOQUE_CORDA = [
    _item('narr.prefixo.corda.0', "Na corda bamba, "),
    _item('narr.prefixo.corda.1', "Com o último dado em jogo, "),
    _item('narr.prefixo.corda.2', "Sem margem para erro, "),
    _item('narr.prefixo.corda.3', "Pressionado, "),
    _item('narr.prefixo.corda.4', "Jogando a vida, "),
]

_SALTO = [
    _item('narr.prefixo.salto.0', "Salto ousado: "),
    _item('narr.prefixo.salto.1', "Aposta salgada: "),
    _item('narr.prefixo.salto.2', "De uma vez só: "),
    _item('narr.prefixo.salto.3', "Escalada agressiva: "),
    _item('narr.prefixo.salto.4', "Sem medo de ser feliz: "),
]

_ACIMA_DA_MESA = [
    _item('narr.prefixo.acima.0', "Mais dados do que existem na mesa: "),
    _item('narr.prefixo.acima.1', "Aposta astronômica: "),
    _item('narr.prefixo.acima.2', "Isso é mais do que a mesa inteira: "),
    _item('narr.prefixo.acima.3', "Ousadia total: "),
]

_CORINGA = [
    _item('narr.prefixo.coringa.0', "Chamando o coringa: "),
    _item('narr.prefixo.coringa.1', "Aposta no coringa: "),
    _item('narr.prefixo.coringa.2', "O 1 entrou na conversa: "),
    _item('narr.prefixo.coringa.3', "Apostando no curinga: "),
]

_QUEBRA_CORINGA = [
    _item('narr.prefixo.quebra.0', "Quebrando o coringa: "),
    _item('narr.prefixo.quebra.1', "Voltando ao número: "),
    _item('narr.prefixo.quebra.2', "Encerrando o curinga: "),
    _item('narr.prefixo.quebra.3', "Deixando o 1 de lado: "),
]

_ARREMATES_IA = [
    _item('narr.arremate.ia.0', " Confiança de máquina."),
    _item('narr.arremate.ia.1', " Os humanos que se cuidem."),
    _item('narr.arremate.ia.2', " A mesa gelou."),
    _item('narr.arremate.ia.3', " Será que dá?"),
    _item('narr.arremate.ia.4', " O clima esquentou."),
]

_ARREMATES_HUMANO = [
    _item('narr.arremate.humano.0', " A mesa prendeu a respiração."),
    _item('narr.arremate.humano.1', " Será que cola?"),
    _item('narr.arremate.humano.2', " O clima esquentou."),
    _item('narr.arremate.humano.3', " Coragem!"),
    _item('narr.arremate.humano.4', " A pressão subiu."),
]


def narracao_aposta(jogador, face, quantidade, pensou=0, anterior=None, dados_mesa=0,
                    primeira=False, turno_num=0):
    """
    Payload de narração de uma aposta (humano ou bot), com comentário contextual
    baseado só em informação pública:
    - `anterior`: turno imediatamente anterior (para medir saltos de aposta);
    - `dados_mesa`: total de dados da partida (para detectar aposta acima do possível);
    - `primeira`: True se abre a rodada.
    """
    nome = _nome_exibicao(jogador)
    face_nome = nome_face(face, quantidade)
    is_ia = bool(jogador.is_ia)
    dados_jogador = getattr(jogador, 'dados_qtd', 0) or 0

    acoes = _ACOES_APOSTA_IA if is_ia else _ACOES_APOSTA_HUMANO
    acao = _pick(acoes)
    frase = acao['texto'].format(nome=nome, qtd=quantidade, face=face_nome)

    especiais = []
    if primeira or turno_num == 1:
        especiais += _ABERTURAS
    if dados_jogador == 1:
        especiais += _TOQUE_CORDA
    if anterior is not None:
        qtd_ant = getattr(anterior, 'dado_qtd', 0) or 0
        face_ant = getattr(anterior, 'dado_face', 0) or 0
        if quantidade - qtd_ant >= 2 or (quantidade == qtd_ant and face - face_ant >= 2):
            especiais += _SALTO
        if face_ant == 1 and face > 1:
            especiais += _QUEBRA_CORINGA
    if face == 1:
        especiais += _CORINGA
    if dados_mesa and quantidade > dados_mesa:
        especiais += _ACIMA_DA_MESA

    prefixo = _comentar(especiais, []) if especiais else None
    arremates = _ARREMATES_IA if is_ia else _ARREMATES_HUMANO
    arremate = _pick(arremates) if secrets.randbelow(100) < 28 else None

    segmentos = []
    if prefixo:
        segmentos.append(_seg(prefixo))
    segmentos.append(_seg(acao, nome=nome, qtd=quantidade, face=int(face)))
    if arremate:
        segmentos.append(_seg(arremate))

    texto = (prefixo['texto'] if prefixo else '') + frase + (arremate['texto'] if arremate else '')

    return {
        'texto': texto,
        'segmentos': segmentos,
        'tipo': 'aposta',
        'jogador': nome,
        'is_ia': is_ia,
        'nivel': jogador.ia_nivel,
        'atraso': int(pensou),
    }


_ACOES_DESCONFIANCA_IA = [
    'narr.desconfianca.ia.0',
    'narr.desconfianca.ia.1',
    'narr.desconfianca.ia.2',
    'narr.desconfianca.ia.3',
    'narr.desconfianca.ia.4',
    'narr.desconfianca.ia.5',
]

_ACOES_DESCONFIANCA_HUMANO = [
    'narr.desconfianca.humano.0',
    'narr.desconfianca.humano.1',
    'narr.desconfianca.humano.2',
    'narr.desconfianca.humano.3',
    'narr.desconfianca.humano.4',
    'narr.desconfianca.humano.5',
]

_TEXTO_DESCONFIANCA_IA = [
    "{nome} parou para pensar... e desconfiou de {alvo}!",
    "{nome} não acreditou e apontou: {alvo}!",
    "{nome} desconfia da aposta de {alvo}!",
    "{nome} recalcula tudo e bate o pé: não é possível!",
    "{nome} analisou a mesa e desconfiou de {alvo}.",
    "{nome} rodou as probabilidades e disse: duvido, {alvo}!",
]

_TEXTO_DESCONFIANCA_HUMANO = [
    "{nome} desconfia da aposta de {alvo}!",
    "{nome} bate na mesa: não acredita em {alvo}!",
    "{nome} pede para ver: desconfiança em {alvo}!",
    "{nome} não engoliu a aposta e desconfia de {alvo}.",
    "{nome} aponta o dedo: duvido, {alvo}!",
    "{nome} sente o cheiro de blefe e desconfia de {alvo}.",
]


def narracao_desconfianca(jogador, alvo, pensou=0, aposta=None):
    """Payload de narração de uma desconfiança (humano ou bot)."""
    nome = _nome_exibicao(jogador)
    if alvo is None:
        alvo_nome = 'o último lance'
    else:
        alvo_nome = _nome_exibicao(alvo)
    is_ia = bool(jogador.is_ia)

    chaves = _ACOES_DESCONFIANCA_IA if is_ia else _ACOES_DESCONFIANCA_HUMANO
    textos = _TEXTO_DESCONFIANCA_IA if is_ia else _TEXTO_DESCONFIANCA_HUMANO
    indice = secrets.randbelow(len(chaves))
    generica = _item(chaves[indice], textos[indice], nome=nome, alvo=alvo_nome)
    frase = generica['texto'].format(nome=nome, alvo=alvo_nome)

    especiais = []
    if aposta is not None:
        face_nome = nome_face(aposta.dado_face, aposta.dado_qtd)
        especiais += [
            _item('narr.desconfianca.olha.0',
                  f"{nome} olha para os {aposta.dado_qtd} {face_nome} e desconfia de {alvo_nome}!",
                  nome=nome, alvo=alvo_nome, qtd=aposta.dado_qtd, face=int(aposta.dado_face)),
            _item('narr.desconfianca.duvido.0',
                  f"Duvido que existam {aposta.dado_qtd} {face_nome}! {nome} desconfia de {alvo_nome}.",
                  nome=nome, alvo=alvo_nome, qtd=aposta.dado_qtd, face=int(aposta.dado_face)),
        ]
    if getattr(alvo, 'dados_qtd', 0) == 1:
        especiais += [
            _item('narr.desconfianca.alvo_corda.0',
                  f"{nome} sente o blefe na corda bamba de {alvo_nome}!", nome=nome, alvo=alvo_nome),
            _item('narr.desconfianca.alvo_corda.1',
                  f"Tem tudo a ver: {alvo_nome} está por um fio e {nome} desconfia!", nome=nome, alvo=alvo_nome),
        ]
    if getattr(jogador, 'dados_qtd', 0) == 1:
        especiais += [
            _item('narr.desconfianca.eu_corda.0',
                  f"É tudo ou nada: {nome}, com um só dado, desconfia de {alvo_nome}!", nome=nome, alvo=alvo_nome),
            _item('narr.desconfianca.eu_corda.1',
                  f"Sem margem para erro, {nome} aposta contra {alvo_nome}!", nome=nome, alvo=alvo_nome),
        ]

    escolhido = _comentar(especiais, [generica])
    texto = escolhido['texto']
    return {
        'texto': texto,
        'segmentos': [_seg(escolhido)],
        'tipo': 'desconfianca',
        'jogador': nome,
        'is_ia': is_ia,
        'nivel': jogador.ia_nivel,
        'atraso': int(pensou),
    }


def narracao_rodada(numero, total_dados, iniciante=None, primeira=False):
    """Payload de narração do começo de uma rodada."""
    if primeira:
        inicio = _pick([
            _item('narr.rodada.primeira.0', "🎲 A partida começou! {total} dados na mesa.", total=total_dados),
            _item('narr.rodada.primeira.1', "🎲 Lá vamos nós: {total} dados em jogo na primeira rodada!",
                  total=total_dados),
            _item('narr.rodada.primeira.2', "🎲 Rodada 1 no ar — {total} dados rolaram.", total=total_dados),
        ])
    else:
        inicio = _pick([
            _item('narr.rodada.nova.0', "🎲 Rodada {numero} começou — {total} dados na mesa.",
                  numero=numero, total=total_dados),
            _item('narr.rodada.nova.1', "🎲 Nova rodada! São {total} dados em jogo nesta rodada.", total=total_dados),
            _item('narr.rodada.nova.2', "🎲 Rodada {numero}: todos rolaram, são {total} dados na mesa.",
                  numero=numero, total=total_dados),
            _item('narr.rodada.nova.3', "🎲 Rodada {numero} valendo — {total} dados na mesa.",
                  numero=numero, total=total_dados),
        ])
    segmentos = [_seg(inicio)]
    texto = inicio['texto'].format(numero=numero, total=total_dados)
    if iniciante is not None:
        nome = _nome_exibicao(iniciante)
        abertura = _pick([
            _item('narr.rodada.iniciante.0', " {nome} abre as apostas.", nome=nome),
            _item('narr.rodada.iniciante.1', " A vez é de {nome}.", nome=nome),
            _item('narr.rodada.iniciante.2', " {nome} tem a palavra.", nome=nome),
            _item('narr.rodada.iniciante.3', " Começa com {nome}.", nome=nome),
        ])
        segmentos.append(_seg(abertura))
        texto += abertura['texto'].format(nome=nome)
    return {'texto': texto, 'segmentos': segmentos, 'tipo': 'rodada', 'is_ia': False, 'atraso': 0}


def narracao_vitoria(jogador):
    """Payload de narração do fim da partida."""
    nome = _nome_exibicao(jogador)
    pontos = getattr(jogador, 'pontos', 0) or 0
    is_ia = bool(jogador.is_ia)
    if is_ia:
        vitoria = _pick([
            _item('narr.vitoria.ia.0', "🏆 A máquina venceu! {nome} deixa os humanos comendo poeira.", nome=nome),
            _item('narr.vitoria.ia.1', "🏆 {nome} calculou melhor e venceu a partida!", nome=nome),
            _item('narr.vitoria.ia.2', "🏆 Fim de jogo: {nome} desbancou a mesa!", nome=nome),
        ])
    else:
        vitoria = _pick([
            _item('narr.vitoria.humano.0', "🏆 {nome} venceu a partida! Palmas!", nome=nome),
            _item('narr.vitoria.humano.1', "🏆 É campeão! {nome} levou a melhor.", nome=nome),
            _item('narr.vitoria.humano.2', "🏆 {nome} é o último de pé e vence a partida!", nome=nome),
            _item('narr.vitoria.humano.3', "🏆 {nome} enganou todo mundo e venceu!", nome=nome),
        ])
    segmentos = [_seg(vitoria)]
    texto = vitoria['texto'].format(nome=nome)
    if pontos > 1:
        pontos_item = _pick([
            _item('narr.vitoria.pontos.0', " Já são {pontos} vitórias na sala!", pontos=pontos),
            _item('narr.vitoria.pontos.1', " Que sequência: {pontos} vitórias!", pontos=pontos),
            _item('narr.vitoria.pontos.2', " {pontos} vitórias e contando!", pontos=pontos),
        ])
        segmentos.append(_seg(pontos_item))
        texto += pontos_item['texto'].format(pontos=pontos)
    return {'texto': texto, 'segmentos': segmentos, 'tipo': 'vitoria', 'is_ia': is_ia, 'atraso': 0}


def narracao_substituicao(jogador, motivo='timeout'):
    """
    Narração quando um humano desconectado é substituído por uma IA (Fase 11/30).
    `motivo` distingue a queda durante a partida ('timeout': a janela de
    reconexão expirou) de quem já estava fora quando a partida começou
    ('ausente'). Usa o apelido puro — o jogador ainda não é um bot "de verdade".
    """
    nome = jogador.username or 'Jogador'
    if motivo == 'ausente':
        fala = _item('narr.substituicao.ausente',
                     "📴 {nome} estava desconectado quando a partida começou — uma IA assume o lugar.",
                     nome=nome)
    else:
        fala = _item('narr.substituicao.timeout',
                     "📴 {nome} caiu e não voltou a tempo — uma IA assume o lugar.", nome=nome)
    return {'texto': fala['texto'].format(nome=nome), 'segmentos': [_seg(fala)],
            'tipo': 'substituicao', 'is_ia': False, 'atraso': 0}


def narracao_retorno(jogador):
    """Narração quando o humano retoma a própria identidade após virar bot (Fase 11/30)."""
    nome = jogador.username or 'Jogador'
    fala = _item('narr.retorno', "🔌 {nome} voltou e reassumiu o próprio controle.", nome=nome)
    return {'texto': fala['texto'].format(nome=nome), 'segmentos': [_seg(fala)],
            'tipo': 'retorno', 'is_ia': False, 'atraso': 0}
