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
        self.entrou = datetime.now()

    @classmethod
    def criar_jogador(cls, client_id, master=False):
        """Cria e retorna uma nova instância de Jogador."""
        return cls(client_id=client_id, master=master)

    def atualizar_pontos(self, pontos):
        self.pontos += pontos

    def __repr__(self):
        return (f"Jogador(client_id={self.client_id}, username={self.username}, "
                f"master={self.master}, pontos={self.pontos}, entrou={self.entrou})")

    def jogar_dados(self):
        """Rola os três dados e retorna o resultado como uma lista de valores."""
        dados_qtd = 3
        dados = []
        for dado in range(0, dados_qtd):
            dados.append(secrets.randbelow(6) + 1)
        self.dados = dados


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
        self.dados_qtd = 3
        self.jogadores = []
        self.lobby = lobby
        self.todos_os_dados = []
        self.coringa_atual = 0
        self.jogaram_dados = False
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
            jogador.jogar_dados()
        self.jogaram_dados = True

    def contar_jogadores(self):
        return len(self.jogadores)

    def iniciar_partida(self):
        if self.prepara_turno:
            turnos_lista = {}
            for jogador in self.jogadores:
                turnos_lista[jogador.username] = [[0, 0], [0, 0], [0, 0]]
            jog_inicial = self.sortear_jogador()
            nomes = [jogador.username for jogador in self.jogadores]

            emit('dados_mesa', {'total': len(self.todos_os_dados)}, broadcast=True)
            emit("construtor_html", {'rodada_n': 0, 'turnos_lista': turnos_lista, 'coringa_atual': 0},
                 broadcast=True)
            emit('meu_turno', {'username': jog_inicial.username}, to=jog_inicial.client_id)
            for jogador in self.jogadores:
                if jogador != jog_inicial:
                    emit('espera_turno', {'username': jogador.username}, to=jogador.client_id)
            emit('formatador_coletivo', {'jogadores_nomes': nomes, 'jogador_inicial_nome': jog_inicial.username},
                 broadcast=True)
        else:
            desconfiou = False
            while not desconfiou:
                self.jogar_turno()

    def jogar_turno(self):
        """Inicia o ciclo de turnos até que alguém desconfie."""
        turno = Turno()
        self.turnos.append(turno)
        pass


class Turno:
    """Representa o turno de um jogador na partida."""

    def executar(self):
        """Executa o turno, onde o jogador pode aumentar a aposta ou desconfiar."""
        pass
