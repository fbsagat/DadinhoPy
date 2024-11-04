from datetime import datetime
import random


class Jogador:
    def __init__(self, client_id, master=False):
        self.client_id = client_id
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
            dados.append(random.randint(0, 6))
        self.dados = dados


class Lobby:
    def __init__(self):
        self.jogadores = []

    def __repr__(self):
        return f"Lobby({len(self.jogadores)} jogadores)"

    def definir_master(self):
        # Verifica se já existe um jogador master
        if self.verificar_jogador_master():
            # print("Já existe um jogador master.")
            return

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

    def contar_jogadores(self):
        return len(self.jogadores)

    def listar_jogadores(self):
        lista = []
        for jogador in self.jogadores:
            lista.append(jogador)
        return lista

    def verificar_jogador_master(self):
        # Verifica se algum jogador é master
        for jogador in self.jogadores:
            if jogador.master:
                return True
        return False

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
        self.primeiro_turno = True

    def __repr__(self):
        txt = f"Partida do lobby {self.lobby} com os jogadores: {self.jogadores}"
        return txt

    def iniciar_partida(self):
        if self.primeiro_turno is True:
            self.jogar_dados()

    def jogar_dados(self):
        for jogador in self.jogadores:
            jogador.jogar_dados()

    def jogar_turnos(self):
        """Inicia o ciclo de turnos até que alguém desconfie."""
        primeira_rodada = True
        pass

    def contar_jogadores(self):
        return len(self.jogadores)


class Turno:
    """Representa o turno de um jogador na partida."""

    def executar(self):
        """Executa o turno, onde o jogador pode aumentar a aposta ou desconfiar."""
        pass


class Dado:
    """Representa um dado de seis lados."""

    def rolar(self):
        """Rola o dado e retorna um valor entre 1 e 6."""
        return random.randint(1, 6)
