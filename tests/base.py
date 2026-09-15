"""Infraestrutura compartilhada da verificação (Fase 45, M5).

Estado global (modulo_store/modulo_app/funcoes_gerais/app/socketio), helpers
de conexão/reporte e constantes. `verificar.py` (runner) e
`tests/test_integracao.py` fazem `from tests.base import *` — como ambos
apontam para o MESMO módulo, não há o problema de `__main__` vs. nome de
módulo ao rodar `python verificar.py`.
"""
import os

# Estado local determinístico: nunca toca na Upstash mesmo com env vars no shell.
os.environ["DADINHO_STORE"] = "memoria"
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

import py_compile
import shutil
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULOS = [
    "app.py", "modelos/__init__.py", "modelos/comum.py", "modelos/migracao.py",
    "modelos/jogador.py", "modelos/turno.py", "modelos/rodada.py",
    "modelos/partida.py", "modelos/lobby.py",
    "funcoes_gerais.py", "store.py", "ia.py", "seed.py",
    "tema.py", "gerar_musica.py", "narrador.py", "simular_ia.py", "api/index.py",
]
SALA = "verificacao"

_falhas = []


def _ok(nome):
    print(f"  [OK] {nome}")


def _falhou(nome, detalhe=""):
    print(f"  [FALHOU] {nome} {detalhe}".rstrip())
    _falhas.append(nome)


def _checar(nome, condicao, detalhe=""):
    if condicao:
        _ok(nome)
    else:
        _falhou(nome, detalhe)

# Globals setados por `_preparar_integracao` (placeholders até lá).
modulo_store = None
modulo_app = None
funcoes_gerais = None
app = None
socketio = None

def _preparar_integracao():
    global modulo_store, modulo_app, funcoes_gerais, socketio, app
    import store as modulo_store
    import app as modulo_app
    import funcoes_gerais
    from app import app, socketio
    # Cooldown desligado no fluxo principal; o teste V2 religa o real.
    modulo_app.tem_cooldown = lambda *a, **k: False
    return modulo_store, modulo_app, funcoes_gerais


def _modulos_que_emitem():
    """Módulos que chamam `emit` do Socket.IO (Fase 45: modelos virou pacote)."""
    import modelos.comum
    import modelos.jogador
    import modelos.turno
    import modelos.rodada
    import modelos.partida
    import modelos.lobby
    return (modelos, modelos.comum, modelos.jogador, modelos.turno,
            modelos.rodada, modelos.partida, modelos.lobby, funcoes_gerais)


def _salvar_emit():
    return {modulo.__name__: getattr(modulo, 'emit', None)
            for modulo in _modulos_que_emitem()}


def _silenciar_emit():
    """Neutraliza `emit` fora de request (room/namespace inexistentes)."""
    for modulo in _modulos_que_emitem():
        if hasattr(modulo, 'emit'):
            modulo.emit = lambda *a, **k: None


def _restaurar_emit(salvo):
    for nome, original in salvo.items():
        modulo = sys.modules.get(nome)
        if modulo is None:
            continue
        if original is None:
            if hasattr(modulo, 'emit'):
                delattr(modulo, 'emit')
        else:
            modulo.emit = original


def _achar_evento(lista, nome):
    for evento in lista:
        if evento["name"] == nome:
            return evento["args"][0] if evento["args"] else True
    return None


def _contar_eventos(lista, nome):
    return sum(1 for evento in lista if evento["name"] == nome)


def _limpar():
    modulo_store.remover_sala(SALA)


def _conectar():
    c = socketio.test_client(app, query_string=f"sala={SALA}")
    eventos = c.get_received()
    cs = _achar_evento(eventos, "connect_start")
    assert cs is not None, "deve receber connect_start"
    return c, cs, eventos


def _conectar_trio(dados_qtd):
    clis = {}
    for nome in ("Ana", "Bia", "Caio"):
        c, cs, _ = _conectar()
        c.emit("apelido", {"apelido_msg": nome})
        clis[nome] = (c, cs["chave_secreta"])
    clis["Bia"][0].emit("ficar_pronto", {"chave": clis["Bia"][1]})
    clis["Caio"][0].emit("ficar_pronto", {"chave": clis["Caio"][1]})
    clis["Ana"][0].emit("iniciar_partida", {"chave": clis["Ana"][1], "dados_qtd": dados_qtd})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1
    for c, chave in clis.values():
        c.emit("jogar_dados", {"chave": chave})
    for c, chave in clis.values():
        c.emit("joguei_dados", {"chave_secreta": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2
    return clis, lobby


def _rodada_ate_conferencia(clis):
    """Da página de turnos à conferência: cada um aposta e o último desconfia."""
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    rodada = partida.rodadas[-1]
    ordem = list(partida.jogadores)
    while ordem[0] != rodada.vez_atual:
        ordem.append(ordem.pop(0))
    n = len(ordem)
    for i in range(n - 1):
        jogador = ordem[i]
        if i == 0:
            face = jogador.dados[0] if jogador.dados else 1
            qtd = 1
        else:
            face = 6
            qtd = i + 1
        clis[jogador.username][0].emit(
            "apostar",
            {"dados": {"chave": clis[jogador.username][1], "dado": face, "quantidade": qtd}},
        )
    desconfia = ordem[n - 1]
    clis[desconfia.username][0].emit(
        "desconfiar", {"dados": {"chave": clis[desconfia.username][1]}}
    )
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 3, f"deve estar na conferência, página={lobby.pagina}"
    return lobby


def _desconectar_todos(clis):
    for c, _ in clis.values():
        if c.is_connected():
            c.disconnect()


def _purgar_grace(clis):
    """Com a janela de graça em 0, um evento de qualquer ativo expurga os caídos."""
    ativo = next(c for c, _ in clis.values() if c.is_connected())
    ativo.emit("verificar_desconectados")


# --- Fase 6 -----------------------------------------------------------------

__all__ = [
    'os', 'py_compile', 'shutil', 'subprocess', 'sys', 'time',
    'RAIZ', 'MODULOS', 'SALA', '_falhas',
    '_ok', '_falhou', '_checar',
    '_preparar_integracao', '_modulos_que_emitem',
    '_salvar_emit', '_silenciar_emit', '_restaurar_emit',
    '_achar_evento', '_contar_eventos', '_limpar', '_conectar',
    '_conectar_trio', '_rodada_ate_conferencia',
    '_desconectar_todos', '_purgar_grace',
    'modulo_store', 'modulo_app', 'funcoes_gerais', 'app', 'socketio',
]
