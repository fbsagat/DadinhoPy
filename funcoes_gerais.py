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


def enviar_snapshot_sala(lobby, jogador):
    """
    Reconstrói o front-end de um jogador que acabou de conectar (tab novo, refresh
    ou reconexão), refletindo o estado persistido da sala (Fase 4).

    O estado autoritativo já é emitido por eventos; aqui apenas os repetimos para
    este cliente, na ordem certa, baseado em `lobby.pagina`.
    """
    pagina = lobby.pagina
    emit("mudar_pagina", {'pag_numero': pagina}, to=jogador.client_id)
    if pagina == 0:
        return

    # Um tab novo que chega no meio da partida não tem partida_atual: usa a última.
    partida = jogador.partida_atual
    if partida is None and lobby.partidas:
        partida = lobby.partidas[-1]
    if partida is None:
        return

    rodada = partida.rodadas[-1] if partida.rodadas else None
    espectador = jogador not in partida.jogadores

    if pagina == 1:
        if rodada is not None:
            emit('construtor_dados', {'quantidade': jogador.dados_qtd, 'espectador': espectador},
                 to=jogador.client_id)
            if not espectador and jogador.joguei_dados and jogador.dados:
                # Já rolou: repete o resultado pra reapresentar os dados na tela.
                emit('jogar_dados_resultado', {'jogador': jogador.client_id, 'dados_jogador': jogador.dados},
                     to=jogador.client_id)
        return

    if pagina == 2:
        if rodada is None:
            return
        turnos_lista = {
            j.username: [[t.dado_face, t.dado_qtd] for t in j.turnos[-3:][::-1]]
            for j in partida.jogadores
        }
        emit('construtor_html',
             {'rodada_n': rodada.rodada_num, 'turnos_lista': turnos_lista, 'coringa_atual': rodada.coringa_atual_qtd,
              'dados_tt': partida.dados_qtd}, to=jogador.client_id)
        emit('dados_mesa', {'total': sum(j.dados_qtd for j in partida.jogadores)}, to=jogador.client_id)
        if rodada.com_coringa is False:
            emit('atualizar_coringa', {'coringa_cancelado': True}, to=jogador.client_id)
        else:
            emit('atualizar_coringa', {
                'coringa_atual': rodada.coringa_atual_qtd,
                'ultimo_coringa': rodada.coringa_atual_jogador.username if rodada.coringa_atual_jogador else '',
            }, to=jogador.client_id)
        if not espectador:
            emit('meus_dados', {'dados': jogador.dados}, to=jogador.client_id)
        nomes = [j.username for j in partida.jogadores]
        vez_atual = rodada.vez_atual
        emit('formatador_coletivo', {'jogadores_nomes': nomes,
                                     'jogador_inicial_nome': vez_atual.username if vez_atual else ''},
             to=jogador.client_id)
        for j in partida.jogadores:
            if j.turnos:
                emit('atualizar_turno',
                     {'jogador': j.username, 'lista_turnos': [[t.dado_face, t.dado_qtd] for t in j.turnos[-3:][::-1]]},
                     to=jogador.client_id)
        if vez_atual is not None:
            if not espectador and vez_atual == jogador:
                emit('meu_turno', {'username': jogador.username, 'turno_num': len(rodada.turnos)},
                     to=jogador.client_id)
            else:
                emit('espera_turno', {'username': vez_atual.username}, to=jogador.client_id)
        return

    if pagina == 3:
        if rodada is not None and rodada.conferencia:
            emit('cards_conferencia', rodada.conferencia, to=jogador.client_id)
        return

    if pagina == 4:
        if partida.vencedor_final is not None:
            emit('vencedor_da_partida', {'nome': partida.vencedor_final.username}, to=jogador.client_id)
            nomes = [j.username for j in lobby.jogadores if j.username is not None]
            pontos = [j.pontos for j in lobby.jogadores if j.username is not None]
            emit('atualizar_pontos', {'nomes': nomes, 'pontos': pontos}, to=jogador.client_id)
            if not espectador and partida.vencedor_final == jogador:
                emit('botao_vencedor_ativ', to=jogador.client_id)
        return

    # Jogadores que não estão mais na partida (perderam os dados) entram como espectador:
    # esconde os painéis e mostra o selo ESPECTADOR por último, para não ser sobrescrito.
    if espectador:
        emit('espectador', {'nome': jogador.username}, to=jogador.client_id)


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
