from datetime import datetime


class Jogador:
    def __init__(self, client_id, master=False):
        self.client_id = client_id
        self.username = None
        self.master = master
        self.pontos = 0
        self.dados = []
        self.entrou = datetime.now()

    def atualizar_pontos(self, pontos):
        self.pontos += pontos

    def __repr__(self):
        return (f"Jogador(client_id={self.client_id}, username={self.username}, "
                f"master={self.master}, pontos={self.pontos}, entrou={self.entrou})")


class Partida:
    def __init__(self):
        self.jogadores = []

    def adicionar_jogador(self, jogador):
        if isinstance(jogador, Jogador):
            self.jogadores.append(jogador)
        else:
            print("Somente objetos do tipo Jogador podem ser adicionados.")

    def jogadores_qtd(self):
        return len(self.jogadores)

    def listar_jogadores(self):
        for jogador in self.jogadores:
            print(jogador)
