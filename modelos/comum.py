"""Funções compartilhadas dos modelos (Fase 45, M4)."""
from flask_socketio import emit


def sala_room(sala_id):
    """Nome da room do Socket.IO a partir do id de uma sala (fonte única do prefixo)."""
    return f"sala_{sala_id}"


def somente_ias_na_partida(partida):
    """True quando todos os jogadores ainda com dados na partida são bots."""
    return bool(partida is not None and partida.jogadores) and all(j.is_ia for j in partida.jogadores)