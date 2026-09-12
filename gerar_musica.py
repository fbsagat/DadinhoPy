"""
Gera o tema musical do Dadinho em MIDI.

A composição é original, inspirada no clima alegre e saltitante dos jogos de
tabuleiro de Super Nintendo e Mega Drive: baixo caminhante, arpejo rápido de
sawtooth (típico do Mega Drive), melodia em onda quadrada (típica do SNES) e
bateria simples de 8 bits.

Cada execução sorteia uma variante dentro de regras musicais: tonalidade,
progressão de acordes, linha melódica, padrões de arpejo/baixo, contracanto,
bateria e andamento — sempre afinado, mas nunca igual ao anterior.

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

# --- Parâmetros musicais ---------------------------------------------------
PPQ = 480                 # pulsos por semínima (ticks por batida)
COMPASSOS = 16            # duração do loop
TICKS_POR_BATIDA = PPQ
TICKS_POR_COMPASSO = PPQ * 4   # 4/4

BPM_MIN_PADRAO = 112
BPM_MAX_PADRAO = 140

# Canais General MIDI usados:
CANAL_MELODIA = 0
CANAL_ARP = 1
CANAL_BAIXO = 2
CANAL_CONTRACANTO = 3
CANAL_BATERIA = 9         # o canal 10 do MIDI (índice 9) é sempre percussão

# Programas General MIDI (o cliente mapeia para timbres de chiptune):
PROG_MELODIA = 80         # Lead 1 (square)
PROG_ARP = 81             # Lead 2 (sawtooth)
PROG_BAIXO = 38           # Synth Bass 1
PROG_CONTRACANTO = 82     # Lead 3 (calliope)

# Escala maior e intervalos de cada qualidade de acorde.
ESCALA_MAIOR = [0, 2, 4, 5, 7, 9, 11]
QUALIDADES_ACORDE = {
    'maj7': [0, 4, 7, 11],
    'm7': [0, 3, 7, 10],
    '7': [0, 4, 7, 10],
    'maj': [0, 4, 7],
    'm': [0, 3, 7],
    'dim': [0, 3, 6],
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


# --- Material harmônico ----------------------------------------------------
# Progressões de 16 compassos descritas por grau da escala (0 = tônica) e
# qualidade do acorde. São transpostas para uma tonalidade sorteada.
PROGRESSOES: list[list[tuple[int, str]]] = [
    # I - vi - ii - V com turnarounds jazzísticos.
    [(0, 'maj7'), (5, 'm7'), (1, 'm7'), (4, '7'),
     (0, 'maj7'), (5, '7'), (1, 'm7'), (4, '7'),
     (0, 'maj7'), (5, 'm7'), (3, 'maj7'), (4, '7'),
     (2, 'm7'), (5, '7'), (1, 'm7'), (4, '7')],
    # I - V - vi - IV (pop).
    [(0, 'maj7'), (4, '7'), (5, 'm7'), (3, 'maj7')] * 4,
    # ii - V - I (rhythm changes).
    [(1, 'm7'), (4, '7'), (0, 'maj7'), (0, 'maj7'),
     (1, 'm7'), (4, '7'), (0, 'maj7'), (5, '7'),
     (1, 'm7'), (4, '7'), (0, 'maj7'), (3, 'maj7'),
     (1, 'm7'), (4, '7'), (0, 'maj7'), (4, '7')],
    # I - vi - IV - V (doo-wop).
    [(0, 'maj7'), (5, 'm7'), (3, 'maj7'), (4, '7')] * 4,
    # Blocos de tônica e subdominante (clima blues).
    [(0, 'maj7'), (0, 'maj7'), (0, 'maj7'), (0, 'maj7'),
     (3, 'maj7'), (3, 'maj7'), (0, 'maj7'), (0, 'maj7'),
     (1, 'm7'), (4, '7'), (0, 'maj7'), (5, '7'),
     (1, 'm7'), (4, '7'), (0, 'maj7'), (4, '7')],
    # I - vi - ii - V com o iii no meio (mais movimento).
    [(0, 'maj7'), (5, 'm7'), (1, 'm7'), (4, '7'),
     (2, 'm7'), (5, '7'), (1, 'm7'), (4, '7'),
     (0, 'maj7'), (3, 'maj7'), (1, 'm7'), (4, '7'),
     (0, 'maj7'), (5, '7'), (1, 'm7'), (4, '7')],
]

# Padrões de arpejo (índices em 4 notas do acorde expandidas para 2 oitavas).
PADROES_ARP = [
    [0, 1, 2, 3, 2, 1, 2, 3],
    [0, 2, 1, 3, 2, 0, 1, 3],
    [0, 1, 2, 3, 4, 5, 6, 7],
    [7, 6, 5, 4, 3, 2, 1, 0],
    [0, 4, 1, 5, 2, 6, 3, 7],
    [0, 2, 4, 6, 5, 3, 1, 0],
    [0, 3, 1, 4, 2, 5, 3, 7],
]

# Padrões de baixo: (batida, duração, intervalo sobre a fundamental).
PADROES_BAIXO = [
    [(0, 0.75, 0), (0.75, 0.25, 0), (1, 0.5, 0), (1.5, 0.5, 7),
     (2, 0.75, 0), (2.75, 0.25, 0), (3, 0.5, 7), (3.5, 0.5, 12)],
    [(0, 1.0, 0), (1, 0.5, 0), (1.5, 0.5, 12), (2, 1.0, 0), (3, 0.5, 7), (3.5, 0.5, 12)],
    [(0, 1.0, 0), (1, 1.0, 0), (2, 0.5, 7), (2.5, 0.5, 12), (3, 1.0, 7)],
    [(0, 0.5, 0), (0.5, 0.5, 12), (1, 0.5, 7), (1.5, 0.5, 0),
     (2, 0.5, 0), (2.5, 0.5, 12), (3, 0.5, 7), (3.5, 0.5, 12)],
    [(0, 1.5, 0), (1.5, 0.5, 7), (2, 1.5, 0), (3.5, 0.5, 12)],
]

PADROES_BUMBO = [[0, 2], [0, 1.5, 2], [0, 2, 3.5], [0, 2.5], [0, 1, 2, 3], [0, 2, 2.5]]
PADROES_CAIXA = [[1, 3], [1, 3, 3.5], [1, 2.5, 3], [1, 3.25]]


def altura_escala(grau: int, oitava: int = 4) -> int:
    """Número MIDI da nota do grau da escala (aceita graus fora de 0-6)."""
    return (oitava + grau // 7 + 1) * 12 + ESCALA_MAIOR[grau % 7]


def tons_do_acorde(grau: int, qualidade: str, oitava: int = 4) -> list[int]:
    """Notas do acorde em MIDI, a partir do grau e da qualidade."""
    raiz = altura_escala(grau, oitava)
    return [raiz + intervalo for intervalo in QUALIDADES_ACORDE[qualidade]]


def gerar_progressao(rng: random.Random) -> list[tuple[int, str]]:
    return rng.choice(PROGRESSOES)


def escolher_nota(rng: random.Random, anterior: int, tons_acorde: list[int], escala: list[int]) -> int:
    """Sorteia a próxima nota, preferindo graus do acorde e movimentos curtos."""
    candidatas = sorted(set(tons_acorde) | set(escala))
    pesos = []
    for c in candidatas:
        peso = 3.0 if c in tons_acorde else 1.0
        peso *= 0.6 ** abs(c - anterior)
        pesos.append(peso)
    return rng.choices(candidatas, weights=pesos)[0]


def gerar_melodia(rng: random.Random, progressao: list[tuple[int, str]]) -> list[tuple[float, float, int, int]]:
    eventos: list[tuple[float, float, int, int]] = []
    lo, hi = 55, 81  # G3..A5
    escala = [n for oitava in (3, 4, 5) for grau in range(7)
              if lo <= (n := altura_escala(grau, oitava)) <= hi]
    anterior = rng.choice([64, 67, 69, 72])
    for compasso in range(1, COMPASSOS + 1):
        grau, qualidade = progressao[compasso - 1]
        tons = [n for t in tons_do_acorde(grau, qualidade)
                for n in (t - 12, t, t + 12) if lo <= n <= hi]
        tons = sorted(set(tons))
        base = (compasso - 1) * 4
        t = 0.0
        while t < 4 - 1e-9:
            duracao = rng.choices([0.5, 1.0, 1.5, 2.0], weights=[5, 4, 2, 1])[0]
            duracao = min(duracao, 4 - t)
            if t > 0 and rng.random() < 0.12:  # respiro ocasional
                t += duracao
                continue
            nota = escolher_nota(rng, anterior, tons, escala)
            eventos.append((base + t, duracao, nota, rng.randint(88, 106)))
            anterior = nota
            t += duracao
    return eventos


def gerar_arpejo(rng: random.Random, progressao: list[tuple[int, str]]) -> list[tuple[float, float, int, int]]:
    eventos: list[tuple[float, float, int, int]] = []
    for compasso in range(1, COMPASSOS + 1):
        grau, qualidade = progressao[compasso - 1]
        tons = tons_do_acorde(grau, qualidade, oitava=3)
        expandidas = sorted(tons + [t + 12 for t in tons])
        padrao = rng.choice(PADROES_ARP)
        if rng.random() < 0.35:  # colcheias + semininas rápidas
            indices = padrao + list(reversed(padrao))
            duracao = 0.25
        else:
            indices = padrao
            duracao = 0.5
        base = (compasso - 1) * 4
        for i, indice in enumerate(indices):
            eventos.append((base + i * duracao, duracao * 0.9, expandidas[indice], rng.randint(38, 58)))
    return eventos


def gerar_baixo(rng: random.Random, progressao: list[tuple[int, str]]) -> list[tuple[float, float, int, int]]:
    eventos: list[tuple[float, float, int, int]] = []
    for compasso in range(1, COMPASSOS + 1):
        grau, _ = progressao[compasso - 1]
        raiz = altura_escala(grau, 2)
        base = (compasso - 1) * 4
        for batida, duracao, intervalo in rng.choice(PADROES_BAIXO):
            eventos.append((base + batida, duracao, raiz + intervalo, rng.randint(86, 98)))
    return eventos


def gerar_contracanto(rng: random.Random, progressao: list[tuple[int, str]]) -> list[tuple[float, float, int, int]]:
    eventos: list[tuple[float, float, int, int]] = []
    candidatos = [2, 4, 6, 8, 10, 12, 14, 16]
    for compasso in sorted(rng.sample(candidatos, rng.randint(2, 4))):
        grau, qualidade = progressao[compasso - 1]
        tons = [n - 12 for n in tons_do_acorde(grau, qualidade)]
        base = (compasso - 1) * 4
        pos = base
        n_notas = rng.randint(3, 5)
        for i in range(n_notas):
            duracao = 0.5 if i < n_notas - 1 else 2.0
            duracao = min(duracao, base + 4 - pos)
            eventos.append((pos, duracao, rng.choice(tons), rng.randint(62, 80)))
            pos += duracao
    return eventos


def gerar_bateria(rng: random.Random) -> list[tuple[float, float, int, int]]:
    eventos: list[tuple[float, float, int, int]] = []
    for compasso in range(1, COMPASSOS + 1):
        base = (compasso - 1) * 4
        if compasso in (1, 9):
            eventos.append((base, 0.1, 49, 100))  # prato de ataque
        for batida in rng.choice(PADROES_BUMBO):
            eventos.append((base + batida, 0.1, 36, 105))  # bumbo
        for batida in rng.choice(PADROES_CAIXA):
            eventos.append((base + batida, 0.1, 38, 92))   # caixa
        passo = rng.choice([0.5, 0.5, 0.5, 0.25])
        i = 0.0
        while i < 4 - 1e-9:
            if abs(i - 3.5) < 1e-9 and rng.random() < 0.5:
                altura = 46  # chimbal aberto
            else:
                altura = 42 if int(round(i * 2)) % 2 == 0 else 44
            eventos.append((base + i, 0.1, altura, rng.choice([70, 52, 44, 62])))
            i += passo
        if compasso % 4 == 0:  # virada no fim de cada bloco de 4 compassos
            for j, batida in enumerate((3.25, 3.5, 3.75)):
                eventos.append((base + batida, 0.1, 38, 70 + j * 12))
    return eventos


def montar_tema(rng: random.Random) -> list[Faixa]:
    progressao = gerar_progressao(rng)
    transposicao = rng.randint(-5, 6)  # mantém tudo numa região confortável

    melodia = Faixa('Tema')
    melodia.programa(CANAL_MELODIA, PROG_MELODIA)
    for batida, duracao, altura, velocidade in gerar_melodia(rng, progressao):
        melodia.nota(batida * PPQ, duracao * PPQ, altura + transposicao, velocidade, CANAL_MELODIA)

    arp = Faixa('Arpejo')
    arp.programa(CANAL_ARP, PROG_ARP)
    for batida, duracao, altura, velocidade in gerar_arpejo(rng, progressao):
        arp.nota(batida * PPQ, duracao * PPQ, altura + transposicao, velocidade, CANAL_ARP)

    baixo = Faixa('Baixo')
    baixo.programa(CANAL_BAIXO, PROG_BAIXO)
    for batida, duracao, altura, velocidade in gerar_baixo(rng, progressao):
        baixo.nota(batida * PPQ, duracao * PPQ, altura + transposicao, velocidade, CANAL_BAIXO)

    contracanto = Faixa('Contracanto')
    contracanto.programa(CANAL_CONTRACANTO, PROG_CONTRACANTO)
    for batida, duracao, altura, velocidade in gerar_contracanto(rng, progressao):
        contracanto.nota(batida * PPQ, duracao * PPQ, altura + transposicao, velocidade, CANAL_CONTRACANTO)

    bateria = Faixa('Bateria')
    for batida, duracao, altura, velocidade in gerar_bateria(rng):
        bateria.nota(batida * PPQ, duracao * PPQ, altura, velocidade, CANAL_BATERIA)

    return [melodia, arp, baixo, contracanto, bateria]


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
    parser = argparse.ArgumentParser(description='Gera variantes aleatórias do tema do Dadinho.')
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
