def obter_chave_por_client_id(dicionario, client_id):
    for chave, dados in dicionario.items():
        if dados.get('client_id') == client_id:
            return chave
    return None  # Retorna None se o client_id não for encontrado

# Exemplo de uso:
dicionario = {
    0: {'client_id': 'X4PaLYD3kqQXxsu3AAAD', 'username': None, 'master': False},
    1: {'client_id': 'gfd0kR9nlzEEFCA3AAAF', 'username': None, 'master': False, 'pontos': 0},
    2: {'client_id': '4CLjWfFXVEkF9QlcAAAH', 'username': None, 'master': True, 'pontos': 0}
}

# Teste com um client_id existente
chave = obter_chave_por_client_id(dicionario, 'X4PaLYD3kqQXxsu3AAADzr')
print(chave)  # Saída: 1

# Teste com um client_id inexistente
chave = obter_chave_por_client_id(dicionario, 'invalido')
print(chave)  # Saída: None
