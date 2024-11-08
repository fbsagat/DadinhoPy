from datetime import datetime
import secrets, random
from flask_socketio import emit


class Jogador:
    def __init__(self, client_id, master=False):
        self.client_id = client_id
        self.chave_secreta = secrets.token_hex(16)
        self.username = None
        self.master = master
        self.pontos = 0
        self.dados = []
        self.turnos = []
        self.entrou = datetime.now()

    @classmethod
    def criar_jogador(cls, client_id, master=False):
        """Cria e retorna uma nova instância de Jogador."""
        return cls(client_id=client_id, master=master)

    def atualizar_pontos(self, pontos):
        self.pontos += pontos

    def __repr__(self):
        return (f"Jogador {self.username} (client_id={self.client_id}, "
                f"master={self.master}, pontos={self.pontos}, entrou={self.entrou})")

    def jogar_dados(self, partida):
        """Rola os três dados e retorna o resultado como uma lista de valores."""
        dados_qtd = partida.dados_qtd
        dados = []
        for dado in range(0, dados_qtd):
            dados.append(secrets.randbelow(6) + 1)
        self.dados = dados

    def adicionar_turno(self, turno):
        self.turnos.append(turno)


class Lobby:
    def __init__(self):
        self.jogadores = []

    def __repr__(self):
        return f"Lobby({len(self.jogadores)} jogadores)"

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
    def __init__(self, lobby):
        self.dados_qtd = 6
        self.jogadores = []
        self.lobby = lobby
        self.todos_os_dados = []
        self.coringa_atual_qtd = 0
        self.coringa_atual_jogador = None
        self.jogaram_dados = False
        self.sem_coringa = False
        self.prepara_turno = True  # Diferencia o turno onde não pode desconfiar(primeiro turno apenas)
        self.turnos = []

    def __repr__(self):
        txt = f"Partida do lobby {self.lobby} com os jogadores: {self.jogadores}"
        return txt

    def sortear_jogador(self):
        if self.jogadores:  # Verifica se a lista não está vazia
            jogador_aleatorio = random.choice(self.jogadores)  # Seleciona um jogador aleatório
            return jogador_aleatorio
        else:
            return None  # Retorna None se a lista estiver vazia

    def verificar_se_todos_ja_jogaram_seus_dados(self):
        return True if self.contar_jogadores() == (len(self.todos_os_dados) / self.dados_qtd) else False

    def jogar_dados(self):
        self.todos_os_dados = []  # limpar dados (temporário)
        for jogador in self.jogadores:
            jogador.jogar_dados(self)
        self.jogaram_dados = True

    def contar_jogadores(self):
        return len(self.jogadores)

    def buscar_jogador_pelo_client_id(self, client_id):
        for jogador in self.jogadores:
            if jogador.client_id == client_id:
                return jogador
        return None

    def iniciar_partida(self):
        if self.prepara_turno:
            turnos_lista = {}
            for jogador in self.jogadores:
                turnos_lista[jogador.username] = [[0, 0]]
            jog_inicial = self.sortear_jogador()
            nomes = [jogador.username for jogador in self.jogadores]

            emit('dados_mesa', {'total': len(self.todos_os_dados)}, broadcast=True)
            emit("construtor_html",
                 {'rodada_n': 0, 'turnos_lista': turnos_lista, 'coringa_atual': 0, 'dados_tt': self.dados_qtd},
                 broadcast=True)
            emit('atualizar_coringa', {'coringa_atual': 0, 'ultimo_coringa': ''}, broadcast=True)
            emit('meu_turno', {'username': jog_inicial.username}, to=jog_inicial.client_id)
            for jogador in self.jogadores:
                if jogador != jog_inicial:
                    emit('espera_turno', {'username': jogador.username}, to=jogador.client_id)
            emit('formatador_coletivo', {'jogadores_nomes': nomes, 'jogador_inicial_nome': jog_inicial.username},
                 broadcast=True)

    def registrar_turno(self, jogador, dados):
        turno_numero = len(self.turnos) + 1
        dado = int(dados['dado'])
        dado_qtd = int(dados['quantidade'])
        turno = Turno(partida=self, jogador=jogador, dado=dado, dado_qtd=dado_qtd, turno_numero=turno_numero)
        self.turnos.append(turno)
        jogador.adicionar_turno(turno)

        if turno.verificar_validade_da_jogada():
            print('TURNO VÁLIDO, EXECUTAR')
            if dado == 1:
                self.coringa_atual_qtd = dado_qtd
                self.coringa_atual_jogador = jogador
            turno.executar_turno()
        else:
            print('TURNO INVÁLIDO, DELETAR')
            txt = 'tente outra jogada.'
            self.turnos.remove(turno)
            jogador.turnos.remove(turno)
            del turno
            emit('jogada_invalida', {'txtadd': txt}, to=jogador.client_id)


class Turno:
    """Representa o turno de um jogador na partida."""

    def __init__(self, partida, dado, jogador, dado_qtd, turno_numero):
        self.turno_num = turno_numero
        self.do_jogador = jogador
        self.da_partida = partida
        self.dado = dado
        self.dado_qtd = dado_qtd

    def __repr__(self):
        txt = f"Turno {self.turno_num} de {self.do_jogador.username}, (Face: {self.dado}, Qtd: {self.dado_qtd})"
        return txt

    def proximo_jogador(self, item_atual):
        lista = self.da_partida.jogadores
        # Obter o índice do item atual na lista
        indice_atual = lista.index(item_atual)
        # Calcular o índice do próximo item de forma circular
        indice_proximo = (indice_atual + 1) % len(lista)
        # Retornar o próximo item
        return lista[indice_proximo]

    def obter_turno_anterior_na_partida(self):
        if self.turno_num > 1:
            lista = self.da_partida.turnos
            indice = lista.index(self)
            turno = lista[indice - 1]
            return turno

    def verificar_validade_da_jogada(self):
        """ Validar jogada aqui, retorna True se válida ou False de inválida"""
        print('')
        print('VERIFICANDO VALIDADE DA JOGADA')
        turno_anterior = self.obter_turno_anterior_na_partida()
        print('Turno anterior: ', turno_anterior)
        print('Turno atual: ', self)
        if self.turno_num > 1:
            # Se for o primeiro turno pode passar = True
            # MEXER NA ATIVAÇÃO DO PARTIDA SEM CORINGA
            if self.dado == 1:
                # Se for coringa, verificar se é maior que o coringa anterior
                print(self.do_jogador.username, 'Atual jogou coringa')
                cori_anterior = turno_anterior.dado_qtd
                cori_jogada = self.dado_qtd
                if cori_jogada > cori_anterior:
                    return True
                else:
                    return False
            else:
                if turno_anterior.dado == 1:  # Anterior é coringa
                    print('Turno anterior é coringa')
                    # turno anterior é coringa
                    # Sem atual ser coringa, mas anterior sendo coringa: verificar se é uma aposta dobrada em relação
                    # à quantidade de coringas jogados na rodada anterior.
                    if self.dado_qtd >= (turno_anterior.dado_qtd * self.dado_qtd):
                        return True
                    else:
                        return False
                else:
                    print('Turno anterior não é coringa')
                    if self.dado == turno_anterior.dado:  # Mesma face e quantidade atual igual
                        print('Mesma face')
                        # Sem ser coringa e sem coringa anterior: verificar se é uma aposta maior que a anterior, ou
                        # seja, (uma quantidade de dados maior se for a mesma face do dado)
                        if self.dado_qtd > turno_anterior.dado_qtd:
                            print('quantidade atual maior que qtd anterior = True')
                            return True
                        else:
                            print('Quantidade atual não é maior que qtd anterior = False')
                            return False
                    elif self.dado > turno_anterior.dado:  # Faces diferentes e quantidade atual maior
                        print('Faces diferentes')
                        # Sem ser coringa e sem coringa anterior: verificar se é uma quantidade igual o maior de
                        # uma face maior que a anterior.
                        if self.dado_qtd >= turno_anterior.dado_qtd:
                            print('Qtd atual maior que a anterior = True')
                            return True
                        else:
                            print('Quantidade menor não passa na regra = False')
                            # Quantidade menor não passa na regra.
                            return False
                    elif self.dado < turno_anterior.dado and self.dado_qtd > turno_anterior.dado_qtd:
                        # Face atual menor não passa na regra, exceto se a quantidade seja maior.
                        print('Face atual menor que a anterior mas quantidade maior = True')
                        return True
                    else:
                        print('Outra possibilidade aqui')
                        return False
        print('primeiro turno')
        return True

    def executar_turno(self):
        """Executa o turno no front end"""
        turnos = self.do_jogador.turnos[-3:][::-1]
        lista_turnos = [[turno.dado, turno.dado_qtd] for turno in turnos]
        emit('atualizar_turno', {'jogador': self.do_jogador.username, 'lista_turnos': lista_turnos},
             broadcast=True)
        if lista_turnos[0][0] == 1:
            emit('atualizar_coringa',
                 {'coringa_atual': self.da_partida.coringa_atual_qtd,
                  'ultimo_coringa': self.da_partida.coringa_atual_jogador.username},
                 broadcast=True)

        nomes = [jogador.username for jogador in self.da_partida.jogadores]
        proximo = self.proximo_jogador(self.do_jogador)  # Aqui o próximo jogador a jogar

        emit('formatador_coletivo', {'jogadores_nomes': nomes, 'jogador_inicial_nome': proximo.username},
             broadcast=True)
        emit('meu_turno', {'username': proximo.username}, to=proximo.client_id)

        for jogador in self.da_partida.jogadores:
            if jogador != proximo:
                emit('espera_turno', {'username': jogador.username}, to=jogador.client_id)
