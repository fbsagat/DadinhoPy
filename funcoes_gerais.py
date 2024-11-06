from flask_socketio import emit
from modelos import Lobby, Partida

lobby_unico = Lobby()
partida = Partida(lobby=lobby_unico)


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


# def construir_primeira_rodada(partida, jogadores):
#     turnos_lista = {}
#     for jogador in jogadores:
#         turnos_lista[jogador.username] = [[0, 0], [0, 0], [0, 0]]
#     jog_inicial = partida.sortear_jogador()
#     jogadores.remove(jog_inicial)
#     nomes = [jogador.username for jogador in jogadores]
#
#     emit('dados_mesa', {'total': len(partida.todos_os_dados)}, broadcast=True)
#     emit("construtor_html", {'rodada_n': 0, 'turnos_lista': turnos_lista, 'coringa_atual': 0}, broadcast=True)
#     emit('meu_turno', {'username': jog_inicial.username}, to=jog_inicial.client_id)
#     for jogador in jogadores:
#         emit('espera_turno', {'username': jogador.username}, to=jogador.client_id)
#     emit('formatador_coletivo', {'jogadores_nomes': nomes, 'jogador_inicial_nome': jog_inicial.username},
#          broadcast=True)
#     # time.sleep(random.randint(3, 4))
#     mudar_pagina(2, broadcast=True)
