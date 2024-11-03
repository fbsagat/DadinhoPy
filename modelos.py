from datetime import datetime


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

    def listar_jogadores_por_ordem(self):
        # Ordena os jogadores pela data de entrada
        jogadores_ordenados = sorted(self.jogadores, key=lambda x: x.entrou)
        # Lista com o índice de entrada
        lista = []
        for indice, jogador in enumerate(jogadores_ordenados, start=1):
            lista.append(jogador)
        return lista


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
    def __init__(self, jogador, lobby):
        self.jogador = jogador  # Referência à instância de Jogador
        self.lobby = lobby  # Referência à instância de Lobby

    def __repr__(self):
        pass


class Dado:
    def __init__(self):
        self.lados = 6
