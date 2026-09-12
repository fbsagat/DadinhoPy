"""
Tema oficial rotativo (Fase 12).

A cada 12h o tema de fundo muda sozinho. Para funcionar no alvo serverless
(Vercel), sem timers, threads de fundo ou estado persistente, a música não é
"trocada" por agendamento: ela é **derivada deterministicamente de uma janela
de tempo** de 12 horas (00:00 e 12:00 UTC). Qualquer instância que atenda o
pedido chega à mesma composição — mesmo `seed` gera o mesmo MIDI — então não
há nada para sincronizar entre instâncias.

O cliente busca o tema pela rota `GET /tema.mid` (ver `app.py`). Defina
`DADINHO_TEMA_SEED` para congelar uma música específica (ex.: a escolhida da
geração em lote) — nesse caso ela deixa de rotacionar, como esperado.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time

import gerar_musica

PERIODO_SEGUNDOS = 12 * 60 * 60  # troca de tema a cada 12h

_trava = threading.Lock()
_cache: dict[int, tuple[bytes, int, int]] = {}


def janela_atual(instante: float | None = None) -> int:
    """Índice da janela de 12h que contém o instante informado (padrão: agora)."""
    instante = time.time() if instante is None else instante
    return int(instante // PERIODO_SEGUNDOS)


def segundos_ate_virada(instante: float | None = None) -> int:
    """Segundos restantes até a próxima troca de tema (para o Cache-Control)."""
    instante = time.time() if instante is None else instante
    return int(PERIODO_SEGUNDOS - (instante % PERIODO_SEGUNDOS))


def _seed_da_janela(janela: int) -> int:
    """Seed da janela; usa `DADINHO_TEMA_SEED` se definida (congela o tema)."""
    fixo = os.environ.get('DADINHO_TEMA_SEED')
    if fixo:
        try:
            return int(fixo)
        except ValueError:
            pass
    resumo = hashlib.sha256(f'dadinho:tema:{janela}'.encode('utf-8')).hexdigest()
    return int(resumo[:8], 16)


def tema_atual(instante: float | None = None) -> tuple[bytes, int, int]:
    """(midi, bpm, seed) do tema vigente. Determinístico e cacheado por janela."""
    janela = janela_atual(instante)
    with _trava:
        if janela not in _cache:
            seed = _seed_da_janela(janela)
            midi, bpm = gerar_musica.gerar_variante(seed)
            _cache.clear()  # só a janela vigente interessa (serverless)
            _cache[janela] = (midi, bpm, seed)
        return _cache[janela]
