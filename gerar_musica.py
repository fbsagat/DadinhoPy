"""
Gera o tema musical do Dadinho em MIDI.

A composição é original e busca o clima **animado e orquestral** das trilhas
de Donkey Kong Country (SNES) e afins: andamento dançante, levada de percussão
com bongôs/congas, harmonia estendida (maj7/m9/sus/6), colchões de cordas e
coro, sinos e marimbas com eco e melodias de sopro cheias de síncope. Não há
cópia: o gerador apenas reproduz o *clima*, sempre com material novo.

Cada execução (ou `seed`) sorteia uma variante original dentro de regras
musicais: modo, tonalidade, progressão, timbres orquestrais (General MIDI),
motivo melódico, arpejos de sinos, baixo, contracanto e camadas opcionais —
coerente, mas nunca igual à anterior.

Uso:
    python gerar_musica.py                  # uma variante
    python gerar_musica.py -n 10            # 10 variantes para ouvir e escolher
    python gerar_musica.py -n 5 --seed 42   # lote reproduzível (mesmas músicas)

Saída: static/sons/dadinho_tema_01.mid, _02.mid, ...
Escolha a preferida e renomeie/copie para static/sons/dadinho_tema.mid.
"""

from __future__ import annotations

import argparse
import os
import random
import struct
from dataclasses import dataclass, field

# --- Parâmetros musicais ---------------------------------------------------
PPQ = 480                 # pulsos por semínima (ticks por batida)
COMPASSOS = 24            # duração do loop (compassos de 4/4)
TICKS_POR_BATIDA = PPQ
TICKS_POR_COMPASSO = PPQ * 4

# Clima animado: andamento dançante, cheio de energia.
BPM_MIN_PADRAO = 100
BPM_MAX_PADRAO = 128

# Canais General MIDI usados:
CANAL_MELODIA = 0
CANAL_SINOS = 1
CANAL_COLCHAO = 2
CANAL_BAIXO = 3
CANAL_CONTRACANTO = 4
CANAL_PERCLUSAO = 9       # o canal 10 do MIDI (índice 9) é sempre percussão

# Modos (graus da escala em semitons a partir da tônica). Dão o "sabor" modal
# típico das trilhas ambientais do SNES.
MODOS = {
    'ionico': [0, 2, 4, 5, 7, 9, 11],
    'dorico': [0, 2, 3, 5, 7, 9, 10],
    'eolio': [0, 2, 3, 5, 7, 8, 10],
    'mixolidio': [0, 2, 4, 5, 7, 9, 10],
    'lidio': [0, 2, 4, 6, 7, 9, 11],
}
PESO_MODOS = {'ionico': 3, 'dorico': 3, 'eolio': 3, 'mixolidio': 2, 'lidio': 1}

# Qualidades de acorde e seus intervalos em semitons (com extensões/9ª/6ª).
QUALIDADES_ACORDE = {
    'maj': [0, 4, 7],
    'maj7': [0, 4, 7, 11],
    'maj9': [0, 4, 7, 11, 14],
    'add9': [0, 4, 7, 14],
    '6': [0, 4, 7, 9],
    'm': [0, 3, 7],
    'm7': [0, 3, 7, 10],
    'm9': [0, 3, 7, 10, 14],
    'm6': [0, 3, 7, 9],
    '7': [0, 4, 7, 10],
    '9': [0, 4, 7, 10, 14],
    '7sus4': [0, 5, 7, 10],
    'sus2': [0, 2, 7],
    'sus4': [0, 5, 7],
    'm7b5': [0, 3, 6, 10],
    'dim7': [0, 3, 6, 9],
}

# Qualidade diatônica natural de cada grau em cada modo (acordes de 7ª).
GRAUS_DIATONICOS = {
    'ionico': ['maj7', 'm7', 'm7', 'maj7', '7', 'm7', 'm7b5'],
    'dorico': ['m7', 'm7', 'maj7', '7', 'm7', 'm7b5', 'maj7'],
    'eolio': ['m7', 'm7b5', 'maj7', 'm7', 'm7', 'maj7', '7'],
    'mixolidio': ['7', 'm7', 'm7b5', 'maj7', 'm7', 'm7', 'maj7'],
    'lidio': ['maj7', '7', 'm7', 'm7b5', 'maj7', 'm7', 'm7'],
}

# Como estender cada acorde-base, mantendo o mesmo centro tonal (clima suave).
EXTENSOES = {
    'maj7': [('maj7', 4), ('maj9', 3), ('6', 2), ('add9', 2)],
    'm7': [('m7', 4), ('m9', 3), ('m6', 1)],
    '7': [('7', 3), ('9', 2), ('7sus4', 2)],
    'm7b5': [('m7b5', 1)],
}

# Progressões de 8 compassos descritas por grau da escala (0 = tônica). São
# repetidas em passagens A-A'-A'' ao longo dos 24 compassos, com a qualidade
# de cada acorde sorteada — daí a variação sem quebrar a coerência.
PROGRESSOES: list[list[int]] = [
    [0, 5, 3, 4, 0, 5, 3, 4],   # I - vi - IV - V
    [0, 3, 5, 4, 0, 3, 5, 4],   # I - IV - vi - V
    [5, 3, 0, 4, 5, 3, 0, 4],   # vi - IV - I - V
    [0, 5, 1, 4, 0, 5, 1, 4],   # I - vi - ii - V
    [0, 2, 5, 4, 3, 4, 0, 0],   # I - iii - vi - V - IV - V - I - I
    [0, 4, 5, 3, 0, 4, 5, 3],   # I - V - vi - IV (contínuo)
    [0, 3, 1, 4, 0, 3, 5, 4],   # I - IV - ii - V
    [0, 6, 3, 4, 0, 6, 3, 4],   # I - VII - IV - V (modal)
    [0, 5, 6, 4, 0, 5, 6, 4],   # I - vi - VII - V
    [0, 1, 3, 4, 0, 1, 3, 4],   # ii - V prolongado (balada)
]

# Padrões de arpejo de sinos/marimba: índices num acorde expandido p/ 2 oitavas.
PADROES_SINOS = [
    [0, 1, 2, 3],
    [0, 2, 1, 3],
    [0, 1, 2, 3, 4, 3, 2, 1],
    [0, 2, 4, 2],
    [3, 2, 1, 0],
    [0, 1, 2, 3, 2, 3, 4, 5],
    [0, 4, 2, 5],
    [0, 1, 2, 3, 4, 5, 6, 7],
    [0, 2, 1, 3, 2, 4, 3, 5],
    [0, 3, 1, 4, 2, 5, 3, 6],
]

# Linhas de baixo animadas: (batida, duração, intervalo sobre a fundamental).
LINHAS_BAIXO = [
    [(0, 0.5, 0), (0.5, 0.5, 0), (1, 0.5, 0), (1.5, 0.5, 7),
     (2, 0.5, 0), (2.5, 0.5, 12), (3, 0.5, 7), (3.5, 0.5, 12)],
    [(0, 0.75, 0), (0.75, 0.25, 0), (1, 0.5, 0), (1.5, 0.5, 7),
     (2, 0.5, 0), (2.5, 0.5, 0), (3, 0.5, 7), (3.5, 0.5, 12)],
    [(0, 0.5, 0), (0.5, 0.25, 0), (0.75, 0.25, 7), (1, 0.5, 0),
     (1.5, 0.5, 0), (2, 0.5, 12), (2.5, 0.5, 7), (3, 0.5, 0), (3.5, 0.5, 12)],
    [(0, 1.0, 0), (1, 0.5, 0), (1.5, 0.5, 12), (2, 0.5, 7),
     (2.5, 0.5, 0), (3, 1.0, 7)],
    [(0, 0.5, 0), (0.5, 0.5, 0), (1, 1.0, 0), (2, 0.5, 7),
     (2.5, 0.5, 12), (3, 1.0, 7)],
]

# Levada de bateria/bongôs para o clima dançante (batidas dentro do compasso).
LEVADAS_BUMBO = [[0, 2], [0, 1.5, 2], [0, 2, 3.5], [0, 1, 2, 3], [0, 2.5], [0, 1.75, 2.5], [0, 1, 2.5, 3.5]]
LEVADAS_CAIXA = [[1, 3], [1, 3, 3.5], [1, 2.5, 3], [1, 3.25], [0.5, 1.5, 3]]
LEVADAS_CONGA = [
    [(1.0, 60), (1.5, 62), (2.0, 63), (2.5, 62), (3.0, 60), (3.5, 61)],
    [(0.5, 62), (1.0, 63), (2.0, 62), (2.5, 63), (3.0, 60), (3.5, 61)],
    [(1.0, 61), (1.5, 60), (2.0, 63), (3.0, 61), (3.5, 60)],
    [(0.5, 60), (1.0, 62), (1.5, 60), (2.0, 63), (2.5, 62), (3.0, 61)],
]

# Instrumentos General MIDI por papel (o cliente Web Audio aproxima os timbres).
INSTRUMENTOS = {
    'melodia': [73, 68, 71, 79, 75, 69, 78, 74, 64, 76],       # flautas/oboés/sax
    'sinos': [12, 11, 8, 10, 9, 13, 14, 46],                   # marimba/vibrafone/harpa
    'colchao': [48, 49, 50, 51, 52, 53, 88, 89, 90, 91, 94, 95],  # cordas/coro/pads
    'baixo': [32, 33, 35, 43, 42, 58],                         # baixo acústico/contrabaixo/tuba
    'contracanto': [60, 69, 57, 68, 42, 41, 56, 58],           # trompa/oboé/violoncelo
}


def varint(valor: int) -> bytes:
    """Codifica um inteiro em 'variable-length quantity' do formato MIDI."""
    if valor < 0:
        raise ValueError('varint negativo')
    partes = [valor & 0x7F]
    valor >>= 7
    while valor > 0:
        partes.append((valor & 0x7F) | 0x80)
        valor >>= 7
    return bytes(reversed(partes))


class Faixa:
    """Acumula eventos com tick absoluto e os serializa como uma MTrk."""

    def __init__(self, nome: str = ''):
        self.eventos: list[tuple[int, int, bytes]] = []
        if nome:
            self.meta(0x03, nome.encode('utf-8'))

    def adicionar(self, tick: float, dados: bytes, ordem: int = 0) -> None:
        self.eventos.append((int(round(tick)), ordem, dados))

    def meta(self, tipo: int, dados: bytes) -> None:
        self.adicionar(0, bytes([0xFF, tipo]) + varint(len(dados)) + dados, ordem=-3)

    def programa(self, canal: int, prog: int) -> None:
        self.adicionar(0, bytes([0xC0 | canal, prog]), ordem=-2)

    def nota(self, inicio: float, duracao: float, altura: int, velocidade: int, canal: int) -> None:
        if velocidade <= 0:
            return
        self.adicionar(inicio, bytes([0x90 | canal, altura, velocidade]), ordem=1)
        self.adicionar(inicio + duracao, bytes([0x80 | canal, altura, 0]), ordem=0)

    def compilar(self) -> bytes:
        self.eventos.sort(key=lambda e: (e[0], e[1]))
        dados = bytearray()
        anterior = 0
        for tick, _, evento in self.eventos:
            dados += varint(tick - anterior)
            dados += evento
            anterior = tick
        dados += varint(0) + b'\xFF\x2F\x00'  # Fim da trilha
        return b'MTrk' + struct.pack('>I', len(dados)) + bytes(dados)


@dataclass
class Contexto:
    """Material harmônico/tímbrico sorteado para uma variante."""
    modo: str
    transposicao: int
    progressao: list[tuple[int, str]] = field(default_factory=list)
    instrumentos: dict[str, int] = field(default_factory=dict)


def altura_escala(ctx: Contexto, grau: int, oitava: int = 4) -> int:
    """Número MIDI do grau do modo (aceita graus fora de 0-6, inclusive negativos)."""
    intervalos = MODOS[ctx.modo]
    return (oitava + grau // 7 + 1) * 12 + intervalos[grau % 7] + ctx.transposicao


def tons_do_acorde(ctx: Contexto, grau: int, qualidade: str, oitava: int = 4) -> list[int]:
    """Notas do acorde em MIDI, a partir do grau, da qualidade e da oitava."""
    raiz = altura_escala(ctx, grau, oitava)
    return [raiz + intervalo for intervalo in QUALIDADES_ACORDE[qualidade]]


def variar_qualidade(rng: random.Random, base: str) -> str:
    """Estende um acorde diatônico para maj9/m9/6/etc., sem sair do tom."""
    opcoes = EXTENSOES.get(base)
    if not opcoes:
        return base
    qualidades = [q for q, _ in opcoes]
    pesos = [p for _, p in opcoes]
    return rng.choices(qualidades, weights=pesos)[0]


def gerar_progressao(rng: random.Random, modo: str) -> list[tuple[int, str]]:
    """Progressão de COMPASSOS acordes: template de 8 graus repetido com variação."""
    template = rng.choice(PROGRESSOES)
    diatonico = GRAUS_DIATONICOS[modo]
    progressao: list[tuple[int, str]] = []
    for i in range(COMPASSOS):
        grau = template[i % len(template)]
        progressao.append((grau, variar_qualidade(rng, diatonico[grau])))
    return progressao


def gerar_motivo(rng: random.Random, extensao: float) -> list[tuple[float, float, int]]:
    """Motivo melódico: lista de (início, duração, grau da escala)."""
    eventos: list[tuple[float, float, int]] = []
    grau = rng.randint(0, 4)
    t = rng.choice([0.0, 0.0, 0.0, 0.5])  # às vezes entra em anacruse
    while t < extensao - 1e-9:
        duracao = rng.choices([0.25, 0.5, 0.75, 1.0, 1.5, 2.0], weights=[2, 5, 3, 4, 3, 1])[0]
        duracao = min(duracao, extensao - t)
        eventos.append((t, duracao, grau))
        grau += rng.choices([-2, -1, 0, 1, 2], weights=[1, 3, 2, 3, 1])[0]
        grau = max(-5, min(9, grau))
        t += duracao
        if t < extensao - 1e-9 and rng.random() < 0.18:  # respiro ocasional
            t += rng.choice([0.25, 0.5])
    return eventos


def adequar_ao_acorde(altura: int, tons: list[int]) -> int:
    """Atrai a nota para o tom do acorde mais próximo (mantém a consonância)."""
    if not tons or altura in tons:
        return altura
    proximos = [t for t in tons if abs(t - altura) <= 2]
    if not proximos:
        return altura
    return min(proximos, key=lambda t: abs(t - altura))


def gerar_melodia(rng: random.Random, ctx: Contexto) -> list[tuple[float, float, int, int]]:
    """Melodia de sopro: frases de 2 compassos com motivo repetido/variado."""
    eventos: list[tuple[float, float, int, int]] = []
    oitava = rng.choice([5, 5, 5, 4])
    centro = rng.randint(0, 4)
    extensao = 8.0
    motivo: list[tuple[float, float, int]] | None = None
    for frase in range(COMPASSOS // 2):
        base = frase * extensao
        if motivo is None or rng.random() < 0.4:
            motivo = gerar_motivo(rng, extensao)
        desloc = rng.choice([-1, 0, 0, 0, 1]) if rng.random() < 0.5 else 0
        for inicio, duracao, grau in motivo:
            if inicio >= extensao - 1e-9:
                continue
            dur = min(duracao, extensao - inicio)
            altura = min(max(altura_escala(ctx, grau + centro + desloc, oitava), 60), 91)
            if (base + inicio) % 1.0 < 1e-9:  # tempo forte: prefere nota do acorde
                compasso = int((base + inicio) // 4)
                grau_ac, qual = ctx.progressao[compasso]
                tons = [t for t in tons_do_acorde(ctx, grau_ac, qual, oitava=4)
                        if abs(t - altura) <= 4] or tons_do_acorde(ctx, grau_ac, qual, oitava=4)
                if rng.random() < 0.7:
                    altura = adequar_ao_acorde(altura, tons)
            eventos.append((base + inicio, dur, altura, rng.randint(74, 96)))
    return eventos


def gerar_sinos(rng: random.Random, ctx: Contexto) -> list[tuple[float, float, int, int]]:
    """Arpejos de sinos/marimba movimentados, com raros compassos de silêncio."""
    eventos: list[tuple[float, float, int, int]] = []
    for compasso in range(COMPASSOS):
        if rng.random() < 0.08:
            continue
        grau, qualidade = ctx.progressao[compasso]
        tons = tons_do_acorde(ctx, grau, qualidade, oitava=rng.choice([4, 5, 5]))
        expandidas = sorted({t for t in tons} | {t + 12 for t in tons if t + 12 <= 100})
        padrao = rng.choice(PADROES_SINOS)
        if rng.random() < 0.4:  # colcheias/semicolcheias velozes
            padrao = padrao + list(reversed(padrao))
        passo = rng.choice([0.25, 0.5, 0.5])
        base = compasso * 4
        for i, indice in enumerate(padrao):
            inicio = base + i * passo
            if inicio >= base + 4 - 1e-9:
                break
            eventos.append((inicio, passo * 0.9, expandidas[indice % len(expandidas)],
                            rng.randint(44, 70)))
    return eventos


def gerar_colchao(rng: random.Random, ctx: Contexto) -> list[tuple[float, float, int, int]]:
    """Colchão de cordas/coro: acorde sustentado, em notas longas e suaves."""
    eventos: list[tuple[float, float, int, int]] = []
    for compasso in range(COMPASSOS):
        grau, qualidade = ctx.progressao[compasso]
        tons = tons_do_acorde(ctx, grau, qualidade, oitava=4)[:4]
        vozes = sorted({min(max(t, 55), 79) for t in tons})
        base = compasso * 4
        for voz in vozes:
            eventos.append((base, 4.0, voz, rng.randint(44, 62)))
    return eventos


def gerar_baixo(rng: random.Random, ctx: Contexto) -> list[tuple[float, float, int, int]]:
    """Baixo acústico dançante: linhas em colcheias com síncopes e oitavas."""
    eventos: list[tuple[float, float, int, int]] = []
    for compasso in range(COMPASSOS):
        grau, _ = ctx.progressao[compasso]
        raiz = altura_escala(ctx, grau, oitava=2)
        base = compasso * 4
        for batida, duracao, intervalo in rng.choice(LINHAS_BAIXO):
            eventos.append((base + batida, duracao, raiz + intervalo, rng.randint(72, 92)))
    return eventos


def gerar_contracanto(rng: random.Random, ctx: Contexto) -> list[tuple[float, float, int, int]]:
    """Linha de resposta ocasional (trompa/oboé), só em parte das variantes."""
    if rng.random() < 0.5:
        return []
    eventos: list[tuple[float, float, int, int]] = []
    for compasso in sorted(rng.sample(range(COMPASSOS), k=rng.randint(2, 5))):
        grau, qualidade = ctx.progressao[compasso]
        tons = [t - 12 for t in tons_do_acorde(ctx, grau, qualidade, oitava=4)]
        base = compasso * 4
        pos = 0.0
        n_notas = rng.randint(2, 3)
        for i in range(n_notas):
            duracao = 2.0 if i == n_notas - 1 else 1.0
            duracao = min(duracao, 4 - pos)
            eventos.append((base + pos, duracao, rng.choice(tons), rng.randint(52, 70)))
            pos += duracao
    return eventos


def gerar_percussao(rng: random.Random) -> list[tuple[float, float, int, int]]:
    """Levada animada: bumbo, caixa e chimbais leves + bongôs/congas e tímpano."""
    eventos: list[tuple[float, float, int, int]] = []
    tem_kit = rng.random() < 0.85
    tem_congas = rng.random() < 0.65
    for compasso in range(COMPASSOS):
        base = compasso * 4
        if compasso % 4 == 0:
            eventos.append((base, 0.1, 49, rng.randint(92, 110)))  # prato de ataque
        if compasso % 8 == 0:
            eventos.append((base, 1.2, 47, rng.randint(58, 78)))   # tímpano de acento
        if tem_kit:
            for batida in rng.choice(LEVADAS_BUMBO):
                eventos.append((base + batida, 0.1, 36, rng.randint(92, 112)))
            for batida in rng.choice(LEVADAS_CAIXA):
                eventos.append((base + batida, 0.1, 38, rng.randint(84, 104)))
            i = 0.0
            while i < 4 - 1e-9:
                if abs(i - 3.5) < 1e-9 and rng.random() < 0.5:
                    altura = 46  # chimbal aberto
                else:
                    altura = 42 if int(round(i * 2)) % 2 == 0 else 44
                eventos.append((base + i, 0.1, altura, rng.choice([78, 60, 48, 68])))
                i += 0.5
        if tem_congas:
            for batida, altura in rng.choice(LEVADAS_CONGA):
                eventos.append((base + batida, 0.12, altura, rng.randint(64, 92)))
        if compasso % 4 == 3:  # virada no fim de cada bloco de 4 compassos
            for j, batida in enumerate((3.25, 3.5, 3.75)):
                eventos.append((base + batida, 0.1, 38, 76 + j * 12))
    return eventos


def escolher_instrumentos(rng: random.Random) -> dict[str, int]:
    return {papel: rng.choice(opcoes) for papel, opcoes in INSTRUMENTOS.items()}


def montar_tema(rng: random.Random) -> list[Faixa]:
    """Sorteia o material e devolve as trilhas MIDI (sem a trilha de tempo)."""
    modo = rng.choices(list(PESO_MODOS), weights=list(PESO_MODOS.values()))[0]
    instrumentos = escolher_instrumentos(rng)
    ctx = Contexto(
        modo=modo,
        transposicao=rng.randint(-6, 5),
        progressao=gerar_progressao(rng, modo),
        instrumentos=instrumentos,
    )

    faixas: list[Faixa] = []

    melodia = Faixa('Melodia')
    melodia.programa(CANAL_MELODIA, instrumentos['melodia'])
    for inicio, duracao, altura, velocidade in gerar_melodia(rng, ctx):
        melodia.nota(inicio * PPQ, duracao * PPQ, altura, velocidade, CANAL_MELODIA)
    faixas.append(melodia)

    sinos = Faixa('Sinos')
    sinos.programa(CANAL_SINOS, instrumentos['sinos'])
    for inicio, duracao, altura, velocidade in gerar_sinos(rng, ctx):
        sinos.nota(inicio * PPQ, duracao * PPQ, altura, velocidade, CANAL_SINOS)
    faixas.append(sinos)

    colchao = Faixa('Colchao')
    colchao.programa(CANAL_COLCHAO, instrumentos['colchao'])
    for inicio, duracao, altura, velocidade in gerar_colchao(rng, ctx):
        colchao.nota(inicio * PPQ, duracao * PPQ, altura, velocidade, CANAL_COLCHAO)
    faixas.append(colchao)

    baixo = Faixa('Baixo')
    baixo.programa(CANAL_BAIXO, instrumentos['baixo'])
    for inicio, duracao, altura, velocidade in gerar_baixo(rng, ctx):
        baixo.nota(inicio * PPQ, duracao * PPQ, altura, velocidade, CANAL_BAIXO)
    faixas.append(baixo)

    contracanto_eventos = gerar_contracanto(rng, ctx)
    if contracanto_eventos:
        contracanto = Faixa('Contracanto')
        contracanto.programa(CANAL_CONTRACANTO, instrumentos['contracanto'])
        for inicio, duracao, altura, velocidade in contracanto_eventos:
            contracanto.nota(inicio * PPQ, duracao * PPQ, altura, velocidade, CANAL_CONTRACANTO)
        faixas.append(contracanto)

    percussao_eventos = gerar_percussao(rng)
    if percussao_eventos:
        percussao = Faixa('Percussao')
        for inicio, duracao, altura, velocidade in percussao_eventos:
            percussao.nota(inicio * PPQ, duracao * PPQ, altura, velocidade, CANAL_PERCLUSAO)
        faixas.append(percussao)

    return faixas


def faixa_tempo(bpm: int) -> bytes:
    """Trilha 0: andamento e fórmula de compasso."""
    faixa = Faixa('Tempo')
    micros = int(round(60_000_000 / bpm))
    dados = bytearray()
    dados += varint(0) + bytes([0xFF, 0x51, 0x03]) + micros.to_bytes(3, 'big')
    dados += varint(0) + bytes([0xFF, 0x58, 0x04, 4, 2, 24, 8])  # 4/4
    dados += varint(0) + b'\xFF\x2F\x00'
    return b'MTrk' + struct.pack('>I', len(dados)) + bytes(dados)


def montar_midi_bytes(rng: random.Random, bpm: int) -> bytes:
    """Monta o arquivo MIDI completo (cabeçalho + trilhas) em memória."""
    faixas = montar_tema(rng)
    trilhas = [faixa_tempo(bpm)] + [f.compilar() for f in faixas]
    cabecalho = b'MThd' + struct.pack('>IHHH', 6, 1, len(trilhas), PPQ)
    return cabecalho + b''.join(trilhas)


def gerar_variante(seed: int, bpm_min: int = BPM_MIN_PADRAO, bpm_max: int = BPM_MAX_PADRAO) -> tuple[bytes, int]:
    """
    Gera uma variante determinística a partir da seed: devolve (midi, bpm).
    É o ponto de entrada usado pelo servidor para o tema rotativo (`tema.py`).
    """
    rng = random.Random(seed)
    bpm = rng.randint(bpm_min, bpm_max)
    return montar_midi_bytes(rng, bpm), bpm


def escrever_midi(caminho: str, rng: random.Random, bpm: int) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, 'wb') as arquivo:
        arquivo.write(montar_midi_bytes(rng, bpm))


def main() -> None:
    parser = argparse.ArgumentParser(description='Gera variantes do tema relaxante do Dadinho.')
    parser.add_argument('-n', '--quantidade', type=int, default=1,
                        help='quantas variantes gerar (padrão: 1)')
    parser.add_argument('--seed', type=int, default=None,
                        help='semente base, para reproduzir o mesmo lote')
    parser.add_argument('--bpm-min', type=int, default=BPM_MIN_PADRAO)
    parser.add_argument('--bpm-max', type=int, default=BPM_MAX_PADRAO)
    parser.add_argument('-d', '--diretorio', default=None,
                        help='diretório de saída (padrão: static/sons)')
    args = parser.parse_args()

    if args.quantidade < 1:
        parser.error('--quantidade precisa ser >= 1')
    if args.bpm_min > args.bpm_max:
        parser.error('--bpm-min não pode ser maior que --bpm-max')

    raiz = os.path.dirname(os.path.abspath(__file__))
    diretorio = args.diretorio or os.path.join(raiz, 'static', 'sons')
    base_seed = args.seed if args.seed is not None else random.randrange(1_000_000_000)
    print(f'Semente base: {base_seed} (use --seed {base_seed} para repetir)')

    for i in range(args.quantidade):
        seed = base_seed + i
        rng = random.Random(seed)
        bpm = rng.randint(args.bpm_min, args.bpm_max)
        nome = f'dadinho_tema_{i + 1:02d}.mid'
        escrever_midi(os.path.join(diretorio, nome), rng, bpm)
        print(f'  {nome}  seed={seed}  bpm={bpm}')

    print(f'Prontas em {diretorio}. Copie a preferida para dadinho_tema.mid.')


if __name__ == '__main__':
    main()
