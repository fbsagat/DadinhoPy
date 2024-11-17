from flask_socketio import emit
from modelos import Lobby
import re

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


def validar_input(texto, tamanho_minimo=1, tamanho_maximo=12, permitir_espacos=False, caracteres_permitidos=None):
    """
    Valida o texto recebido do front-end para evitar problemas comuns.

    Args:
        texto (str): O texto a ser validado.
        tamanho_minimo (int): Tamanho mínimo permitido do texto.
        tamanho_maximo (int): Tamanho máximo permitido do texto.
        permitir_espacos (bool): Se espaços são permitidos no texto.
        caracteres_permitidos (str): Regex de caracteres permitidos (None para permitir todos os caracteres comuns).

    Returns:
        str: Texto validado e limpo.
        ValueError: Se o texto não passar na validação.
    """
    if not isinstance(texto, str):
        raise ValueError("A entrada deve ser uma string.")

    # Remover espaços extras no início e no fim
    texto = texto.strip()

    # Verificar tamanho
    if not (tamanho_minimo <= len(texto) <= tamanho_maximo):
        raise ValueError(f"O texto deve ter entre {tamanho_minimo} e {tamanho_maximo} caracteres.")

    # Verificar se espaços são permitidos
    if not permitir_espacos and " " in texto:
        raise ValueError("Espaços não são permitidos.")

    # Verificar caracteres permitidos
    if caracteres_permitidos:
        if not re.fullmatch(caracteres_permitidos, texto):
            raise ValueError("O texto contém caracteres inválidos.")

    # Sanear texto (remover caracteres perigosos)
    texto = re.sub(r"[^\w\s\.,\-@]", "", texto)  # Exemplo de saneamento básico

    return texto


def validar_numero(numero):
    """
    Valida se o número está entre 1 e 6 e se é seguro para processamento.

    :param numero: O número a ser validado.
    :return: True se o número for válido, False caso contrário.
    """
    # Verifica se é um número inteiro
    if not isinstance(numero, int):
        print("Erro: O valor fornecido não é um número inteiro.")
        return False

    # Validação: Verifica se está no intervalo permitido
    if 1 <= numero <= 6:
        print(f"Número válido: {numero}")
        return True
    else:
        print("Erro: Número fora do intervalo permitido! Deve ser entre 1 e 6.")
        return False