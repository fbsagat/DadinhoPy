from flask_socketio import emit
from modelos import Lobby
import re

lobby_unico = Lobby(lobby_numero=1)


def mudar_pagina(num, broadcast=False):
    emit("mudar_pagina", {'pag_numero': num}, broadcast=broadcast)


def atualizar_lista_usuarios():
    """
    Atualiza a lista de usuários na tela de entrada de jogadores.
    """
    lista = lobby_unico.listar_jogadores()
    usernames = [jogador.username for jogador in lista if jogador.username is not None]
    pontos = [jogador.pontos for jogador in lista if jogador.username is not None]
    masters = [jogador.master for jogador in lista if jogador.username is not None]
    o_master = lobby_unico.retornar_master()
    if o_master:
        emit("master_def", {"is_master": True}, to=o_master.client_id)
    emit("update_user_list", {"users": usernames, "pontos": pontos, "masters": masters}, broadcast=True)


def validar_input(texto, tamanho_minimo=1, tamanho_maximo=12, permitir_espacos=True,
                  caracteres_permitidos=r"^[a-zA-Z0-9\s\-\_\.\@\#\!\$\%\&\*\(\)\+\=\,\;\:\'\"\?\[\]\{\}\\\/áéíóúâêîôûãõçÁÉÍÓÚÂÊÎÔÛÃÕÇ]*$"):
    """
    Valida o texto recebido do front-end para verificar se é válido ou inválido.
    Args:
        texto (str): O texto a ser validado.
        tamanho_minimo (int): Tamanho mínimo permitido do texto.
        tamanho_maximo (int): Tamanho máximo permitido do texto.
        permitir_espacos (bool): Se espaços são permitidos no texto.
        caracteres_permitidos (str): Regex de caracteres permitidos (None para permitir todos os caracteres comuns).
    Returns:
        bool: True se o texto for válido, False caso contrário.
    """
    if not isinstance(texto, str):
        return False

    # Remover espaços extras no início e no fim
    texto = texto.strip()

    # Verificar tamanho
    if not (tamanho_minimo <= len(texto) <= tamanho_maximo):
        return False

    # Verificar se espaços são permitidos
    if not permitir_espacos and " " in texto:
        return False

    # Verificar caracteres permitidos
    if caracteres_permitidos and not re.fullmatch(caracteres_permitidos, texto):
        return False

    return True


def validar_numero(numero):
    """
    Valida se o número está entre 1 e 6 e se é seguro para processamento.
    :param numero: O número a ser validado.
    :return: True se o número for válido, False caso contrário.
    """
    # Verifica se é um número inteiro
    if not isinstance(numero, int):
        # print("Erro: O valor fornecido não é um número inteiro.")
        return False
    # Validação: Verifica se está no intervalo permitido
    if 1 <= numero <= 6:
        # print(f"Número válido: {numero}")
        return True
    else:
        # print("Erro: Número fora do intervalo permitido! Deve ser entre 1 e 6.")
        return False
