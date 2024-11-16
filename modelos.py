from datetime import datetime
import secrets
import random
from flask_socketio import emit


class Jogador:
    def __init__(self, client_id, master=False, partida_atual=None, rodada_atual=None, turno_atual=None):
        self.client_id = client_id
        self.username = None
        self.master = master
        self.chave_secreta = secrets.token_hex(16)
        self.pontos = 0
        self.dados = []
        self.dados_qtd = 0
        self.joguei_dados = False
        self.partidas = []
        self.rodadas = []
        self.turnos = []
        self.partida_atual = partida_atual
        self.rodada_atual = rodada_atual
        self.turno_atual = turno_atual
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

    def jogar_dados(self):
        """Rola os seus dados e retorna o resultado como uma lista de valores."""
        dados = []
        for dado in range(0, self.dados_qtd):
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

        emit("construtor_html",
             {'rodada_n': 0, 'turnos_lista': turnos_lista, 'coringa_atual': 0,
              'dados_tt': partida.dados_qtd},
             broadcast=True)
        emit('dados_mesa', {'total': partida.dados_qtd * len(partida.jogadores)}, broadcast=True)
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
        self.dados_qtd = 1
        self.jogadores = jogadores
        self.jogador_sorteado = random.choice(self.jogadores)
        self.do_lobby = do_lobby
        self.rodadas = []

    def __repr__(self):
        jogadores_nomes = [jogador.username for jogador in self.jogadores]
        txt = f"(PARTIDA do lobby {self.do_lobby} com jogadores: {jogadores_nomes})"
        return txt

    def construir_rodada(self):
        verificar = self.verificar_partida_anterior()
        vez_atual = verificar['vez_atual']
        rodada_numero = verificar['rodada_numero']
        if 'final' in verificar and verificar['final']:
            self.declarar_vencedor(verificar['vez_atual'])
        else:
            rodada = Rodada(partida=self, jogadores=self.jogadores, rodada_numero=rodada_numero,
                            vez_atual=vez_atual)
            self.rodadas.append(rodada)
            rodada.construir_front_pro_da_vez(jogador_atual=vez_atual)
            nomes = []
            jogadores_dados_qtd = []
            for jogador in self.jogadores:
                jogador.rodada_atual = rodada
                jogador.rodadas.append(rodada)
                jogador.dados_qtd = self.dados_qtd if rodada_numero == 1 else jogador.dados_qtd
                nomes.append(jogador.username)
                jogadores_dados_qtd.append(jogador.dados_qtd)
            rodada.jogar_dados()
            dados_mesa = 0
            for jogador in self.jogadores:
                emit('construtor_dados', {'quantidade': jogador.dados_qtd}, to=jogador.client_id)
                dados_mesa += jogador.dados_qtd
            if rodada_numero > 1:
                emit('reset_rodada', {'jogadores_nomes': nomes, 'jogadores_dados_qtd': jogadores_dados_qtd},
                     broadcast=True)
                emit('atualizar_coringa', {'coringa_atual': 0}, broadcast=True)
                emit('dados_mesa', {'total': dados_mesa}, broadcast=True)
            emit("mudar_pagina", {'pag_numero': 1}, broadcast=True)
            return rodada

    def contar_jogadores(self):
        return len(self.jogadores)

    def verificar_partida_anterior(self):
        """
        Esta funçào toma as decisões de quem será o próximo jogador a jogar na rodada criada baseado nas informações
        da rodada anterior, ou caso não exista, ou sej, é a primeira rodada.
        """
        rodada_numero = len(self.rodadas) + 1
        if rodada_numero > 1:
            print('rodada numero', rodada_numero, "> 1")

            # Pegar o perdedor e o vencedor da última partida
            perdedor = self.rodadas[-1].perdedor if hasattr(self.rodadas[-1], 'perdedor') else None
            vencedor = self.rodadas[-1].vencedor if hasattr(self.rodadas[-1], 'vencedor') else None

            print('PERDEDOR da ultima rodada joga nessa: ', perdedor.username)
            print('VENCEDOR da ultima rodada joga nessa: ', vencedor.username)

            # Tirar um dado do perdedor e tirar ele da partida se não restar nenhum dado pra ele
            perdedor.dados_qtd -= 1
            if perdedor.dados_qtd == 0:
                perdedor.joguei_dados = False
                perdedor.rodadas = []
                perdedor.turnos = []
                perdedor.rodada_atual = None
                perdedor.turno_atual = None
                self.jogadores.remove(perdedor)
            if len(self.jogadores) < 2:
                return {'vez_atual': vencedor, 'rodada_numero': rodada_numero, 'final': True}
            else:
                if perdedor in self.jogadores:
                    print(perdedor.usernme, 'perdeu um dado')
                    return {'vez_atual': perdedor, 'rodada_numero': rodada_numero}
                else:
                    print(vencedor.username, 'inicia a rodada por ter tirado ', perdedor.username)
                    return {'vez_atual': vencedor, 'rodada_numero': rodada_numero}
        else:
            print('SORTEADO joga nessa rodada pois é a primeira: ', self.jogador_sorteado.username)
            return {'vez_atual': self.jogador_sorteado, 'rodada_numero': rodada_numero}

    def buscar_jogador_pelo_client_id(self, client_id):
        for jogador in self.jogadores:
            if jogador.client_id == client_id:
                return jogador
        return None

    def declarar_vencedor(self, jogador):
        print(jogador.username, 'Venceu a partida!')
        # AGORA ARRUMAR AS RODADAS A PARTIR DO MOMENTO QUE SAI UM JOGADOR
        # CRIAR UM MODO DE ESPECTADOR PARA O JOGADOR QUE SAIU


class Rodada:
    """
    Representa um conjunto de turnos.
    Represento o momento em que os jogadores atuais da partida jogam seus dados até o momento em que alguém desconfia e
    ele mesmo ou outro jogador perde.
    """

    def __init__(self, partida, jogadores, rodada_numero, vez_atual, perdedor=None, vencedor=None):
        self.rodada_num = rodada_numero
        self.da_partida = partida
        self.jogaram_dados = False
        self.turnos = []
        self.todos_os_dados = []
        self.jogadores = jogadores
        self.com_coringa = True
        self.coringa_atual_qtd = 0
        self.coringa_atual_jogador = None
        self.conferiram = 0
        self.vez_atual = vez_atual  # Para checagem de requisição web apenas
        self.perdedor = perdedor
        self.vencedor = vencedor

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
            print('É o turno de: ', turno.do_jogador.username)
            o_da_vez = self.selecionar_proximo_jogador_na_lista(turno.do_jogador)
            print('Próximo da vez: ', o_da_vez.username)
            self.construir_front_pro_da_vez(o_da_vez)
            self.vez_atual = o_da_vez
        else:
            # print('TURNO INVÁLIDO, DELETAR')
            txt = 'tente outra jogada.'
            self.turnos.remove(turno)
            jogador.turnos.remove(turno)
            del turno
            emit('jogada_invalida', {'txtadd': txt}, to=jogador.client_id)

    def jogar_dados(self):
        for jogador in self.da_partida.jogadores:
            dados = jogador.jogar_dados()
            for dado in dados:
                self.todos_os_dados.append(dado)
        self.jogaram_dados = True

    def verificar_se_todos_ja_jogaram_seus_dados(self):
        jogadores_tt = len(self.da_partida.jogadores)
        count = 0
        for jogador in self.da_partida.jogadores:
            if jogador.joguei_dados is True:
                count += 1
        return True if jogadores_tt == count else False

    def desconfiar(self, jogador):
        """
        Pegar todos os dados
        Pegar jogada anterior
        Verificar se o que foi apostado em jogada anterior é igual ou maior que a contagem nos dados totais da 
        rodada(contar os coringas também), se sim, jogador anterior vence partida, se não jogador que desconfiou 
        vence a partida.
        """
        # print(f'{jogador} desconfiou')
        todos_dados = self.todos_os_dados
        # print(todos_dados)
        ultimo_turno = self.turnos[-1]
        # print(ultimo_turno)
        if self.com_coringa:
            for i, dado in enumerate(todos_dados):
                if dado == 1:
                    todos_dados[i] = ultimo_turno.dado_face
        # print(todos_dados)
        quantidade = todos_dados.count(ultimo_turno.dado_face)
        faces_dado_nomes = {
            1: "ases" if ultimo_turno.dado_qtd > 1 else "ás",
            2: "duques" if ultimo_turno.dado_qtd > 1 else "duque",
            3: "ternos" if ultimo_turno.dado_qtd > 1 else "terno",
            4: "quadras" if ultimo_turno.dado_qtd > 1 else "quadra",
            5: "quinas" if ultimo_turno.dado_qtd > 1 else "quina",
            6: "senas" if ultimo_turno.dado_qtd > 1 else "sena"
        }

        saiu = ''
        if quantidade >= ultimo_turno.dado_qtd:
            # print(f'{ultimo_turno.do_jogador.username} ganhou!')
            vencedor = ultimo_turno.do_jogador.username
            perdedor = jogador.username
            perdedor = jogador.username
            self.vencedor = ultimo_turno.do_jogador
            self.perdedor = jogador
            txt_add_1 = ''
            if jogador.dados_qtd == 1:
                saiu = perdedor
                txt_add_1 = f' {perdedor} não tem mais dados e saiu da partida 🤣🤣🤣'

            txt = (
                f'{vencedor} apostou {ultimo_turno.dado_qtd} {faces_dado_nomes[ultimo_turno.dado_face]} e '
                f'realmente havia{"m" if ultimo_turno.dado_qtd > 1 else ""}, {vencedor} ganhou! {perdedor} desconfiou '
                f'errado e perdeu um dado.{txt_add_1}')
        else:
            # print(f'{jogador.username} ganhou!')
            vencedor = jogador.username
            perdedor = ultimo_turno.do_jogador.username
            self.vencedor = jogador
            self.perdedor = ultimo_turno.do_jogador
            txt_add_1 = ''
            if ultimo_turno.do_jogador.dados_qtd == 1:
                saiu = perdedor
                txt_add_1 = f' {perdedor} não tem mais dados e saiu da partida 🤣🤣🤣'

            quantidades = {
                0: f"não havia nenhum",
                1: f"havia {quantidade}",
                2: f"haviam {quantidade}"
            }
            qtd_txt = 0 if quantidade == 0 else 1 if quantidade == 1 else 2 if quantidade > 1 else None
            txt = (f'{perdedor} apostou {ultimo_turno.dado_qtd} {faces_dado_nomes[ultimo_turno.dado_face]}, '
                   f'mas {quantidades[qtd_txt]}. {perdedor} perdeu um dado! {vencedor} desconfiou certo!{txt_add_1}')

        # Mudar para a tela de conferência destacando o vencedor e o perdedor e descrevendo o acontecimento:
        nomes = [jogador.username for jogador in self.da_partida.jogadores]
        dados = [jogador.dados for jogador in self.da_partida.jogadores]
        emit('cards_conferencia',
             {'nomes': nomes, 'ganhador': vencedor, 'perdedor': perdedor, 'saiu_da_partida': saiu, 'dados': dados,
              'dado_apostado_face': ultimo_turno.dado_face,
              'com_coringa': self.com_coringa, 'texto': txt}, broadcast=True)
        emit("mudar_pagina", {'pag_numero': 3}, broadcast=True)

    def construir_front_pro_da_vez(self, jogador_atual):
        """
        Modifica o front-end para todos os jogadores, o da vez joga, os outros observam a mensagem: aguarde a sua vez.
        Esta função não faz nenhuma validação de jogador da vez, deve ser feita em outro lugar.
        """
        print('Construindo front para: ', jogador_atual.username)
        nomes = [jogador.username for jogador in self.da_partida.jogadores]
        emit('formatador_coletivo', {'jogadores_nomes': nomes, 'jogador_inicial_nome': jogador_atual.username},
             broadcast=True)
        emit('meu_turno', {'username': jogador_atual.username, 'turno_num': len(self.turnos)},
             to=jogador_atual.client_id)

        for jogador in self.da_partida.jogadores:
            if jogador != jogador_atual:
                emit('espera_turno', {'username': jogador.username}, to=jogador.client_id)

    def selecionar_proximo_jogador_na_lista(self, jogador_atual):
        lista_jogadores = self.da_partida.jogadores
        # Obter o índice do item atual na lista
        indice_atual = lista_jogadores.index(jogador_atual)
        # Calcular o índice do próximo item de forma circular
        indice_proximo = (indice_atual + 1) % len(lista_jogadores)
        # Retornar o próximo item
        return lista_jogadores[indice_proximo]


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
                    'coringa_cancelado': False}, broadcast=True)
        else:
            # print('atualizar_coringa cancelado True')
            emit('atualizar_coringa', {'coringa_cancelado': True}, broadcast=True)

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
            # print(
            #     f'turno anterior: Face: {turno_ant_dado_face}, Qtd: {turno_ant_dado_qtd}, valor'
            #     f' {turno_ant_jogada_valor}')

        turno_atual_dado_face = self.dado_face
        turno_atual_dado_qtd = self.dado_qtd
        # print(
        #     f'turno atual: Face: {turno_atual_dado_face}, Qtd: {turno_atual_dado_qtd}, valor'
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
                # 3. Se anterior for coringa com atual sendo número: aumentar a aposta: deve ser o dobro ou mais, mas
                # sendo qualquer número.
                if turno_atual_dado_qtd >= (coringa_atual_qtd * 2):
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
