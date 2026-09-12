"""
Narrador da partida e tempo de pensamento dos bots.

Centraliza os textos em pt-BR de cada lance (com variações de fala) e o cálculo
do "tempo de pensamento" das IAs. O atraso é só um número em milissegundos: quem
o aplica é o cliente, através da fila de animação — nada de sleep/thread no
servidor (serverless-safe).
"""

import secrets


# Faixa de tempo (ms) que um bot "pensa" antes de agir. Quanto mais inteligente
# o nível, maior a pausa (dá a sensação de raciocínio mais elaborado).
FAIXAS_PENSAMENTO = {
    1: (250, 600),
    2: (450, 1000),
    3: (700, 1500),
    4: (1000, 2100),
}

NOMES_FACES = {
    1: ('ás', 'ases'),
    2: ('duque', 'duques'),
    3: ('terno', 'ternos'),
    4: ('quadra', 'quadras'),
    5: ('quina', 'quinas'),
    6: ('sena', 'senas'),
}


def tempo_pensamento(nivel):
    """Atraso (ms) de pensamento do bot; maior nos níveis mais inteligentes."""
    try:
        nivel = int(nivel)
    except (TypeError, ValueError):
        nivel = 1
    faixa = FAIXAS_PENSAMENTO.get(nivel, FAIXAS_PENSAMENTO[1])
    return secrets.randbelow(faixa[1] - faixa[0] + 1) + faixa[0]


def nome_face(face, quantidade):
    """Nome da face no singular/plural (ex.: 2 quadras, 1 ás)."""
    singular, plural = NOMES_FACES.get(int(face), ('dado', 'dados'))
    return plural if quantidade > 1 else singular


def _pick(opcoes):
    return secrets.choice(opcoes)


def _nome_exibicao(jogador):
    """Nome para o narrador; garante um único 🤖 nos bots (inclusive substituídos)."""
    nome = jogador.username or 'Jogador'
    if jogador.is_ia and not nome.startswith('🤖'):
        return f"🤖 {nome}"
    return nome


def narracao_aposta(jogador, face, quantidade, pensou=0):
    """Payload de narração de uma aposta (humano ou bot)."""
    nome = _nome_exibicao(jogador)
    face_nome = nome_face(face, quantidade)
    is_ia = bool(jogador.is_ia)
    if is_ia:
        texto = _pick([
            f"{nome} pensou um pouco e apostou {quantidade} {face_nome}.",
            f"{nome} arrisca {quantidade} {face_nome}.",
            f"{nome} calculou direitinho e soltou {quantidade} {face_nome}.",
            f"{nome} sobe a aposta para {quantidade} {face_nome}.",
        ])
    else:
        texto = _pick([
            f"{nome} aposta {quantidade} {face_nome}.",
            f"{nome} anuncia {quantidade} {face_nome}.",
            f"{nome} sobe a aposta para {quantidade} {face_nome}.",
            f"Fala, {nome}! {quantidade} {face_nome}.",
        ])
    return {
        'texto': texto,
        'tipo': 'aposta',
        'jogador': nome,
        'is_ia': is_ia,
        'nivel': jogador.ia_nivel,
        'atraso': int(pensou),
    }


def narracao_desconfianca(jogador, alvo, pensou=0):
    """Payload de narração de uma desconfiança (humano ou bot)."""
    nome = _nome_exibicao(jogador)
    if alvo is None:
        alvo_nome = 'o último lance'
    else:
        alvo_nome = _nome_exibicao(alvo)
    is_ia = bool(jogador.is_ia)
    if is_ia:
        texto = _pick([
            f"{nome} parou para pensar... e desconfiou de {alvo_nome}!",
            f"{nome} não acreditou e apontou: {alvo_nome}!",
            f"{nome} desconfia da aposta de {alvo_nome}!",
        ])
    else:
        texto = _pick([
            f"{nome} desconfia da aposta de {alvo_nome}!",
            f"{nome} bate na mesa: não acredita em {alvo_nome}!",
            f"{nome} pede para ver: desconfiança em {alvo_nome}!",
        ])
    return {
        'texto': texto,
        'tipo': 'desconfianca',
        'jogador': nome,
        'is_ia': is_ia,
        'nivel': jogador.ia_nivel,
        'atraso': int(pensou),
    }


def narracao_rodada(numero, total_dados):
    """Payload de narração do começo de uma rodada."""
    texto = _pick([
        f"🎲 Rodada {numero} começou — {total_dados} dados na mesa.",
        f"🎲 Nova rodada! São {total_dados} dados em jogo nesta rodada.",
        f"🎲 Rodada {numero}: todos rolaram, são {total_dados} dados na mesa.",
    ])
    return {'texto': texto, 'tipo': 'rodada', 'is_ia': False, 'atraso': 0}


def narracao_vitoria(jogador):
    """Payload de narração do fim da partida."""
    nome = _nome_exibicao(jogador)
    texto = _pick([
        f"🏆 {nome} venceu a partida! Palmas!",
        f"🏆 É campeão! {nome} levou a melhor.",
        f"🏆 {nome} é o último de pé e vence a partida!",
    ])
    return {'texto': texto, 'tipo': 'vitoria', 'is_ia': bool(jogador.is_ia), 'atraso': 0}
