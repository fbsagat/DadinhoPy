from datetime import datetime

# Apagar jogador desta lista cuja chave client_id o valor corresponde ao pedido

dicionario = {0: {'client_id': 'X4PaLYD3kqQXxsu3AAAD', 'username': None, 'master': False},
        1: {'client_id': 'gfd0kR9nlzEEFCA3AAAF', 'username': None, 'master': False, 'pontos': 0},
        2: {'client_id': '4CLjWfFXVEkF9QlcAAAH', 'username': None, 'master': True, 'pontos': 0}}
print(dicionario)


def modificar_master(dicionario):
    # Verificar se nenhum item tem master = True
    nenhum_master_verdadeiro = all(not item['master'] for item in dicionario.values())

    if nenhum_master_verdadeiro:
        # Modificar a chave master do primeiro item para True
        primeiro_item_chave = list(dicionario.keys())[0]  # Pega a chave do primeiro item
        dicionario[primeiro_item_chave]['master'] = True
        return True  # Retorna True se a modificação foi feita
    return False  # Retorna False se não houve modificação


# Exemplo de uso da função
resultado = modificar_master(dicionario)

if resultado:
    print('A chave master do primeiro item foi modificada para True.')
else:
    print('Nenhuma modificação foi necessária.')

# Imprimir o dicionário após a modificação
print(dicionario)
