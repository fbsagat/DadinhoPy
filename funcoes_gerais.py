from flask_socketio import emit
from modelos import Lobby

lobby_unico = Lobby(lobby_numero=1)


def mudar_pagina(num, broadcast=False):
    emit("mudar_pagina", {'pag_numero': num}, broadcast=broadcast)


def atualizar_lista_usuarios():
    lista = lobby_unico.listar_jogadores()
    usernames = [jogador.username for jogador in lista if jogador.username is not None]
    pontos = [jogador.pontos for jogador in lista if jogador.username is not None]
    masters = [jogador.master for jogador in lista if jogador.username is not None]
    o_master = lobby_unico.retornar_master()
    if o_master:
        emit("master_def", {"is_master": True}, to=o_master.client_id)
    emit("update_user_list", {"users": usernames, "pontos": pontos, "masters": masters}, broadcast=True)

