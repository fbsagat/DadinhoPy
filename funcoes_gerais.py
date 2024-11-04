from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from modelos import Lobby, Partida

lobby_unico = Lobby()
partida = Partida(lobby=lobby_unico)


def mudar_pagina(num, args=None, broadcast=False):
    if args is None:
        args = {}  # Inicializa args como um dicionário vazio se não for fornecido

    args_ini = {'numero': num}  # Cria um dicionário inicial com 'numero'
    args_ini.update(args)  # Atualiza args_ini com o conteúdo de args
    emit("mudar_pagina", args_ini, broadcast=broadcast)  # Emite o evento com args_ini


def atualizar_lista_usuarios():
    lista = lobby_unico.listar_jogadores()
    usernames = [jogador.username for jogador in lista if jogador.username is not None]
    pontos = [jogador.pontos for jogador in lista if jogador.username is not None]
    masters = [jogador.master for jogador in lista if jogador.username is not None]
    o_master = lobby_unico.retornar_master()
    if o_master:
        emit("master_def", {"is_master": True}, to=o_master.client_id)
    emit("update_user_list", {"users": usernames, "pontos": pontos, "masters": masters}, broadcast=True)
