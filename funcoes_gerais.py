from flask_socketio import emit
from modelos import Lobby
import re
import store

SALA_PADRAO = "padrao"


def sala_room(sala_id):
    """
    Retorna o nome da room no Socket.IO para um id de sala.
    """
    return f"sala_{sala_id}"


def normalizar_sala(sala_id):
    """
    Normaliza e valida o id de sala vindo da URL/front-end. Inválidos caem na sala padrão.
    """
    if not isinstance(sala_id, str):
        return SALA_PADRAO
    sala = sala_id.strip().lower()
    if re.fullmatch(r"[a-z0-9\-_]{1,24}", sala):
        return sala
    return SALA_PADRAO


def obter_sala(sala_id):
    """
    Retorna o Lobby da sala, carregando-o do store distribuído ou criando caso ainda não exista.
    """
    sala_id = normalizar_sala(sala_id)
    lobby = store.carregar_sala(sala_id)
    if lobby is None:
        lobby = Lobby(sala_id=sala_id, lobby_numero=store.contar_salas() + 1)
        store.salvar_sala(lobby)
    return lobby


def salvar_sala(lobby):
    """
    Persiste o estado atual da sala no store distribuído.
    """
    if lobby is not None:
        store.salvar_sala(lobby)


def buscar_lobby_pelo_client_id(client_id):
    """
    Procura em todas as salas o Lobby que contém o jogador com o client_id informado.
    """
    for lobby in store.listar_lobbys():
        if lobby.buscar_jogador_pelo_client_id(client_id) is not None:
            return lobby
    return None


def remover_sala(sala_id):
    """
    Remove uma sala vazia do store (GC de salas sem ninguém).
    """
    store.remover_sala(sala_id)


def mudar_pagina(num, sala):
    """
    Envia a mudança de página escopada à room da sala.
    """
    emit("mudar_pagina", {'pag_numero': num}, to=sala_room(sala))


def atualizar_lista_usuarios(lobby):
    """
    Atualiza a lista de usuários na tela de entrada de jogadores da sala.
    """
    lista = lobby.listar_jogadores()
    usernames = [jogador.username for jogador in lista if jogador.username is not None]
    pontos = [jogador.pontos for jogador in lista if jogador.username is not None]
    masters = [jogador.master for jogador in lista if jogador.username is not None]
    o_master = lobby.retornar_master()
    if o_master:
        emit("master_def", {"is_master": True}, to=o_master.client_id)
    emit("update_user_list", {"users": usernames, "pontos": pontos, "masters": masters}, to=lobby.sala_room())
    salvar_sala(lobby)


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
