from datetime import datetime
import secrets
import random
from flask_socketio import emit


class Jogador:
    def __init__(self, client_id, master=False):
        self.client_id = client_id
        self.username = None
        self.master = master
        self.chave_secreta = secrets.token_hex(16)
        self.pontos = 0
        self.dados = []
        self.joguei_dados = False
        self.partidas = []
        self.rodadas = []
        self.turnos = []
        self.partida_atual = Partida
        self.rodada_atual = Rodada
        self.turno_atual = Turno
        self.entrou = datetime.now()

    @classmethod
    def criar_jogador(cls, client_id, master=False):
        """Cria e retorna uma nova instância de Jogador."""
        return cls(client_id=client_id, master=master)

    def atualizar_pontos(self, pontos):
        self.pontos += pontos

    def __repr__(self):
        return (f"(JOGADOR {self.username}, client_id={self.client_id}, "
                f"master={self.master}, pontos={self.pontos}, entrou={self.entrou})")

    def jogar_dados(self, partida):
        """Rola os três dados e retorna o resultado como uma lista de valores."""
        dados_qtd = partida.dados_qtd
        dados = []
        for dado in range(0, dados_qtd):
            dados.append(secrets.randbelow(6) + 1)
        self.dados = dados
        return dados


class Lobby:
    """
    Representa um conjunto de partidas.
    Representa o momento onde os jogadores se juntam para jogar dadinho, até o fim deste momento.
    """

    def __init__(self, lobby_numero):
        self.lobby_num = lobby_numero
        self.jogadores = []
        self.partidas = []

    def __repr__(self):
        return f"(LOBBY {self.lobby_num} com {len(self.jogadores)} jogadores)"

    def construir_partida(self):
        # print('Lobby: Construindo partida')
        partida_numero = len(self.partidas) + 1
        partida = Partida(do_lobby=self, jogadores=self.jogadores, partida_numero=partida_numero)
        self.partidas.append(partida)
        for jogador in self.jogadores:
            jogador.partida_atual = partida
            jogador.partidas.append(partida)

        turnos_lista = {}
        for jogador in partida.jogadores:
            turnos_lista[jogador.username] = [[0, 0]]
        jog_inicial = partida.jogador_sorteado
        nomes = [jogador.username for jogador in partida.jogadores]

        emit('dados_mesa', {'total': partida.dados_qtd * len(partida.jogadores)}, broadcast=True)
        emit("construtor_html",
             {'rodada_n': 0, 'turnos_lista': turnos_lista, 'coringa_atual': 0,
              'dados_tt': partida.dados_qtd},
             broadcast=True)
        emit('atualizar_coringa', {'coringa_atual': 0, 'ultimo_coringa': ''}, broadcast=True)
        emit('meu_turno', {'username': jog_inicial.username}, to=jog_inicial.client_id)
        for jogador in partida.jogadores:
            if jogador != jog_inicial:
                emit('espera_turno', {'username': jogador.username}, to=jogador.client_id)
        emit('formatador_coletivo', {'jogadores_nomes': nomes, 'jogador_inicial_nome': jog_inicial.username},
             broadcast=True)
        return partida

    def verificar_apelido(self, nome):
        nomes = [jogador.username for jogador in self.jogadores]
        if nome not in nomes:  # Verifica se o nome é único
            return nome  # Se for único, retorna o nome original
            # Se o nome já existe, adiciona um índice até que o nome se torne único
        indice = 1
        novo_nome = f"{nome}{indice}"
        while novo_nome in nomes:
            indice += 1
            novo_nome = f"{nome}{indice}"
        return novo_nome  # Retorna o novo nome único

    def verificar_jogador_master(self):
        # Verifica se algum jogador é master
        for jogador in self.jogadores:
            if jogador.master:
                return True
        return False

    def definir_master(self):
        # Verifica se já existe um jogador master
        if self.verificar_jogador_master():
            # print("Já existe um jogador master.")
            return
        else:
            # Ordena os jogadores por ordem de entrada e define o primeiro como master
            self.jogadores.sort(key=lambda jogador: jogador.entrou)
            if self.jogadores:
                self.jogadores[0].master = True
                # print(f"O jogador {self.jogadores[0].username} foi definido como master.")

    def adicionar_jogador(self, jogador):
        if isinstance(jogador, Jogador):
            self.jogadores.append(jogador)
        # else:
        #     print("Somente objetos do tipo Jogador podem ser adicionados.")

    def remover_jogador(self, client_id):
        if not isinstance(client_id, str):
            # print("Erro: client_id deve ser uma string.")
            return
        else:
            for jogador in self.jogadores:
                if jogador.client_id == client_id:
                    self.jogadores.remove(jogador)
                    # print(f"Jogador com client_id {client_id} removido.")
                    return
            # print(f"Jogador com client_id {client_id} não encontrado.")

    def buscar_jogador_pelo_client_id(self, client_id):
        for jogador in self.jogadores:
            if jogador.client_id == client_id:
                return jogador
        return None

    def contar_jogadores(self, nome=False):
        if nome:
            quantidade = sum(1 for jogador in self.jogadores if jogador.username is not None)
            return quantidade
        else:
            return len(self.jogadores)

    def listar_jogadores(self):
        lista = []
        for jogador in self.jogadores:
            lista.append(jogador)
        return lista

    def retornar_master(self):
        for jogador in self.jogadores:
            if jogador.master:
                return jogador
        return False


class Partida:
    """
    Representa um conjunto de rodadas.
    Representa o momento em que todos os jogadores estão no jogo, até o momento em que sobra um ganhador.
    """

    def __init__(self, do_lobby, jogadores, partida_numero):
        self.partida_num = partida_numero
        self.dados_qtd = 3
        self.jogadores = jogadores
        self.jogador_sorteado = random.choice(self.jogadores)
        self.do_lobby = do_lobby
        self.rodadas = []

    def __repr__(self):
        jogadores_nomes = [jogador.username for jogador in self.jogadores]
        txt = f"(PARTIDA do lobby {self.do_lobby} com jogadores: {jogadores_nomes})"
        return txt

    def construir_rodada(self):
        # print('Partida: Construindo rodada')
        rodada_numero = len(self.rodadas) + 1
        rodada = Rodada(partida=self, rodada_numero=rodada_numero)
        self.rodadas.append(rodada)
        for jogador in self.jogadores:
            jogador.rodada_atual = rodada
            jogador.rodadas.append(rodada)

        rodada.jogar_dados()
        emit('construtor_dados', {'quantidade': self.dados_qtd}, broadcast=True)
        emit("mudar_pagina", {'pag_numero': 1}, broadcast=True)
        return rodada

    def contar_jogadores(self):
        return len(self.jogadores)

    def buscar_jogador_pelo_client_id(self, client_id):
        for jogador in self.jogadores:
            if jogador.client_id == client_id:
                return jogador
        return None


class Rodada:
    """
    Representa um conjunto de turnos.
    Represento o momento em que os jogadores atuais da partida jogam seus dados até o momento em que alguém desconfia e
    ele mesmo ou outro jogador perde.
    """

    def __init__(self, partida, rodada_numero):
        self.rodada_num = rodada_numero
        self.da_partida = partida
        self.jogaram_dados = False
        self.turnos = []
        self.todos_os_dados = []
        self.com_coringa = True
        self.coringa_atual_qtd = 0
        self.coringa_atual_jogador = None
        self.prepara_turno = True  # Diferencia o turno onde não pode desconfiar(primeiro turno apenas)

    def __repr__(self):
        jogadores_nomes = [jogador.username for jogador in self.da_partida.jogadores]
        txt = f"(RODADA {self.rodada_num} da partida {self.da_partida} com os jogadores: {jogadores_nomes})"
        return txt

    def construir_turno(self, jogador, dados):
        # print('Rodada: Construindo turno')
        turno_numero = len(self.turnos) + 1
        dado = int(dados['dado'])
        dado_qtd = int(dados['quantidade'])
        turno = Turno(da_rodada=self, jogador=jogador, dado=dado, dado_qtd=dado_qtd, turno_numero=turno_numero)
        self.turnos.append(turno)
        jogador.turno_atual = turno
        jogador.turnos.append(turno)

        if turno.verificar_validade_da_jogada():
            # print('TURNO VÁLIDO, EXECUTAR')
            if dado == 1:
                self.coringa_atual_qtd = dado_qtd
                self.coringa_atual_jogador = jogador
            turno.executar_turno()
        else:
            # print('TURNO INVÁLIDO, DELETAR')
            txt = 'tente outra jogada.'
            self.turnos.remove(turno)
            jogador.turnos.remove(turno)
            del turno
            emit('jogada_invalida', {'txtadd': txt}, to=jogador.client_id)

    def jogar_dados(self):
        for jogador in self.da_partida.jogadores:
            dados = jogador.jogar_dados(self.da_partida)
            self.todos_os_dados.append(dados)
        self.jogaram_dados = True

    def verificar_se_todos_ja_jogaram_seus_dados(self):
        jogadores_tt = len(self.da_partida.jogadores)
        count = 0
        for jogador in self.da_partida.jogadores:
            if jogador.joguei_dados is True:
                count += 1
        return True if jogadores_tt == count else False


class Turno:
    """
    Representa o turno de um jogador na partida.
    Representa o momento de um jogador, onde ele aumenta aposta ou desconfia da aposta do jogador anterior.
    """

    def __init__(self, da_rodada, dado, jogador, dado_qtd, turno_numero):
        self.turno_num = turno_numero
        self.do_jogador = jogador
        self.da_rodada = da_rodada
        self.dado_face = dado
        self.dado_qtd = dado_qtd

    def __repr__(self):
        txt = f"(TURNO {self.turno_num} de {self.do_jogador.username}, (Face: {self.dado_face}, Qtd: {self.dado_qtd}))"
        return txt

    def executar_turno(self):
        """Executa o turno no front end"""
        turnos = self.do_jogador.turnos[-3:][::-1]
        lista_turnos = [[turno.dado_face, turno.dado_qtd] for turno in turnos]
        emit('atualizar_turno', {'jogador': self.do_jogador.username, 'lista_turnos': lista_turnos},
             broadcast=True)

        if self.da_rodada.com_coringa is True:
            if lista_turnos[0][0] == 1:
                # print('atualizar_coringa cancelado False')
                emit('atualizar_coringa', {
                    'coringa_atual': self.da_rodada.coringa_atual_qtd,
                    'ultimo_coringa': self.da_rodada.coringa_atual_jogador.username,
                    'coringa_cancelado': False},
                     broadcast=True)
        else:
            # print('atualizar_coringa cancelado True')
            emit('atualizar_coringa', {'coringa_cancelado': True}, broadcast=True)

        nomes = [jogador.username for jogador in self.da_rodada.da_partida.jogadores]
        proximo = self.proximo_jogador(self.do_jogador)  # Aqui o próximo jogador a jogar

        emit('formatador_coletivo', {'jogadores_nomes': nomes, 'jogador_inicial_nome': proximo.username},
             broadcast=True)
        emit('meu_turno', {'username': proximo.username, 'turno_num': self.turno_num}, to=proximo.client_id)

        for jogador in self.da_rodada.da_partida.jogadores:
            if jogador != proximo:
                emit('espera_turno', {'username': jogador.username}, to=jogador.client_id)

    def proximo_jogador(self, item_atual):
        lista = self.da_rodada.da_partida.jogadores
        # Obter o índice do item atual na lista
        indice_atual = lista.index(item_atual)
        # Calcular o índice do próximo item de forma circular
        indice_proximo = (indice_atual + 1) % len(lista)
        # Retornar o próximo item
        return lista[indice_proximo]

    def obter_turno_anterior_na_partida(self):
        if self.turno_num > 1:
            lista = self.da_rodada.turnos
            indice = lista.index(self)
            turno = lista[indice - 1]
            return turno

    def verificar_validade_da_jogada(self):
        """ Validar jogada aqui, retorna True se válida ou False de inválida:
        1. Se for o primeiro turno(self.turno_num == 1): self.da_partida.sem_coringa = False caso o
        turno_atual_dado_face == 1, depois disso feito retorna false prontamente.

        A partir do segundo turno:
        Se coringa True (coringa_true_false): Usar variáveis 'coringa_atual_qtd', 'turno_ant_coringa' e
        'turno_atual_coringa' aqui:
            1. Se atual jogar coringa, pode ser a qualquer momento, desde que qtd seja maior que qtd do coringa
            anterior.
            2. Se jogar num, qtd deve ser maior que qtd do número anterior ou a mesma qtd se a face do dado for maior,
            se anterior for um coringa, dobrar a quantidade.
            ...
        Se coringa False (coringa_true_false), não usar variáveis 'turno_ant_coringa' e 'turno_atual_coringa' e
        'coringa_atual_qtd' aqui:
            1. Se jogar 1, pode ser a qualquer momento, desde que qtd seja maior que qtd do número anterior.
            2. Se jogar num, qtd deve ser maior que qtd do número anterior ou a mesma qtd se a face do dado for maior.

        UTILIZAR AS VARIÁVEIS ABAIXO NA DESCRIÇÃO E NA CRIAÇÃO DO CÓDIGO
        """
        turno_ant_dado_qtd = 0
        turno_ant_dado_face = 0

        # print('\nVERIFICANDO VALIDADE DA JOGADA')
        tur_ant = self.obter_turno_anterior_na_partida()  # Recebe o turno anterior

        coringa_true = self.da_rodada.com_coringa
        coringa_atual_qtd = self.da_rodada.coringa_atual_qtd

        if tur_ant:
            turno_ant_dado_face = tur_ant.dado_face
            turno_ant_dado_qtd = tur_ant.dado_qtd
            turno_ant_jogada_valor = turno_ant_dado_face * turno_ant_dado_qtd
            # print(
            #     f'turno anterior: Face: {turno_ant_dado_face}, Qtd:  {turno_ant_dado_qtd}, valor'
            #     f' {turno_ant_jogada_valor}')

        turno_atual_dado_face = self.dado_face
        turno_atual_dado_qtd = self.dado_qtd
        turno_atul_jogada_valor = turno_atual_dado_face * turno_atual_dado_qtd
        # print(
        #     f'turno atual: Face: {turno_atual_dado_face}, Qtd:  {turno_atual_dado_qtd}, valor'
        #     f' {turno_atul_jogada_valor}')

        # Validações de primeiro turno
        if self.turno_num == 1 and self.dado_face == 1:
            # print('PRIMEIRO TURNO')
            # Se for o primeiro turno e o dado atual for 1, a partida não tem coringa e turno válida.
            self.da_rodada.com_coringa = False
            # print('Partida sem coringa')
            return True
        if self.turno_num == 1:
            # print('PRIMEIRO TURNO')
            # print('Partida com coringa')
            # Se for o primeiro turno, turno válido.
            return True

        # Validações de segundo+ turnos
        if coringa_true:  # SE CORINGA ATIVADO -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
            if turno_ant_dado_face > 1 and turno_atual_dado_face > 1:
                # 1. Ambos números: Aumentar a aposta: A quantidade deve ser maior, mas se o número de face for maior,
                # a quantidade pode ser igual.
                if turno_atual_dado_qtd > turno_ant_dado_qtd:
                    return True
                if turno_ant_dado_face < turno_atual_dado_face and turno_ant_dado_qtd == turno_atual_dado_qtd:
                    return True
            if turno_ant_dado_face > 1 and turno_atual_dado_face == 1:
                # 2. Se anterior for número, mas atual sendo coringa: Qtd deve ser maior que coringa_atual_qtd.
                if turno_atual_dado_qtd > coringa_atual_qtd:
                    return True
            if turno_ant_dado_face == 1 and turno_atual_dado_face > 1:
                # 3. Se anterior for coringa com atual sendo número: aumentar a aposta: deve ser o dobro, mas sendo
                # qualquer número.
                if turno_atual_dado_qtd == (coringa_atual_qtd * 2):
                    return True
            if turno_ant_dado_face == turno_atual_dado_face:
                # 4. Ambos coringas: Qtd deve ser maior que coringa_atual_qtd.
                if turno_atual_dado_qtd > turno_ant_dado_qtd:
                    return True
            return False
        else:  # SE CORINGA DESATIVADO -=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-
            if turno_ant_dado_face > 0 and turno_atual_dado_face > 0:
                # 1. Ambos números(incluindo 1): Aumentar a aposta: A quantidade deve ser maior, mas se o número de
                # face for maior, a quantidade pode ser igual.
                # 2. Se anterior for número, mas atual sendo 1: dentro da regra 1.
                # 3. Se anterior for 1 com atual sendo número: dentro da regra 1.
                # 4. Ambos 1: Dentro da regra 1.
                if turno_atual_dado_qtd > turno_ant_dado_qtd:
                    return True
                if turno_ant_dado_face < turno_atual_dado_face and turno_ant_dado_qtd == turno_atual_dado_qtd:
                    return True
            return False
