from modelos import *

jogador1 = Jogador.criar_jogador(client_id='Felipe', master=True)
jogador2 = Jogador.criar_jogador(client_id='Felipe', master=True)

lobby = Lobby()
jogador1.username = 'Fabio'
jogador2.username = 'Felipe'
print('Criado jogador:', jogador1)
print('Criado jogador:', jogador2)

partida = Partida(lobby=lobby)
partida.jogadores = [jogador1, jogador2]
print(partida)
partida.iniciar_partida()
