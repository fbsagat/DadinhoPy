from datetime import datetime
import secrets
import random
from flask_socketio import emit


class Jogador:
    def __init__(self, client_id, master=False, lobby=None, partida_atual=None, rodada_atual=None, turno_atual=None):
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
        self.lobby_atual = lobby
        self.partida_atual = partida_atual
        self.rodada_atual = rodada_atual
        self.turno_atual = turno_atual
        self.entrou = datetime.now()

    def __repr__(self):
        return (f"(JOGADOR {self.username}, client_id={self.client_id}, "
                f"master={self.master}, pontos={self.pontos}, entrou={self.entrou})")

    @classmethod
    def criar_jogador(cls, client_id, master=False):
        """Cria e retorna uma nova instância de Jogador."""
        return cls(client_id=client_id, master=master)

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
        self.conferiram_vencedor = 0

    def __repr__(self):
        return f"(LOBBY {self.lobby_num} com {len(self.jogadores)} jogadores)"

    def construir_partida(self, dados_qtd):
        """
        Constrói uma partida em um lobby.
        :param dados_qtd: A quantidade de dados para cada jogador nesta partida.
        """
        emit('reset_partida', broadcast=True)  # Arruma algumas coisas da partida anterior no front-end
        partida_numero = len(self.partidas) + 1
        partida = Partida(do_lobby=self, jogadores=self.jogadores.copy(), partida_numero=partida_numero,
                          dados_qtd=dados_qtd)
        self.partidas.append(partida)
        for jogador in self.jogadores:
            jogador.partida_atual = partida
            jogador.partidas.append(partida)
            emit('desativar_username_edit', to=jogador.client_id)
        return partida

    def verificar_apelido(self, nome):
        """
        Faz umas validações de nomes.
        :param nome: Nome que vem do front-end.
        """
        nomes = [jogador.username for jogador in self.jogadores]
        if nome not in nomes:  # Verifica se o nome é único
            return nome  # Se for único, retorna o nome original
            # Se o nome já existe, adiciona um índice até que o nome se torne único
        indice = 1
        novo_nome = f"{nome}_{indice}"
        while novo_nome in nomes:
            indice += 1
            novo_nome = f"{nome}_{indice}"
        return novo_nome  # Retorna o novo nome único

    def verificar_jogador_master(self):
        """
        Verifica se algum jogador é master.
        """
        for jogador in self.jogadores:
            if jogador.master:
                return True
        return False

    def definir_master(self):
        """
        Define um novo master caso precise.
        """
        if self.verificar_jogador_master():
            return
        else:
            self.jogadores.sort(key=lambda jogador: jogador.entrou)
            if self.jogadores:
                self.jogadores[0].master = True

    def adicionar_jogador(self, jogador):
        """
        Adiciona um jogador novo no lobby.
        """
        if isinstance(jogador, Jogador):
            self.jogadores.append(jogador)
            jogador.lobby_atual = self

    def remover_jogador(self, client_id):
        """
        Remove um jogador do lobby.
        """
        if not isinstance(client_id, str):
            return
        else:
            for jogador in self.jogadores:
                if jogador.client_id == client_id:
                    self.jogadores.remove(jogador)
                    return

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

    def __init__(self, do_lobby, jogadores, partida_numero, dados_qtd):
        self.partida_num = partida_numero
        self.dados_qtd = dados_qtd
        self.jogadores = jogadores
        self.jogador_sorteado = random.choice(self.jogadores)
        self.do_lobby = do_lobby
        self.rodadas = []

    def __repr__(self):
        jogadores_nomes = [jogador.username for jogador in self.jogadores]
        txt = f"(PARTIDA do lobby {self.do_lobby} com jogadores: {jogadores_nomes})"
        return txt

    def construir_rodada(self):
        """
        Constrói uma nova rodada numa partida.
        """
        # verifica a partida anterior, caso exista, para tomar decisões para a partida nova sendo criada.
        verificar = self.verificar_partida_anterior()

        # ESPECTADOR \/
        # transforma(muda algumas coisas no front-end), o jogador em espectador quando ele perde todos os dados.
        for lobby_jogador in self.do_lobby.jogadores:
            if lobby_jogador.client_id not in [jogador.client_id for jogador in self.jogadores]:
                emit('espectador', {'nome': lobby_jogador.username}, to=lobby_jogador.client_id)
                emit('construtor_dados', {'quantidade': lobby_jogador.dados_qtd, 'espectador': True},
                     to=lobby_jogador.client_id)
        # ESPECTADOR /\

        # Terminar a rodada caso só tenha um jogador com dado(s) sobrando.
        vez_atual = verificar['vez_atual']
        rodada_numero = verificar['rodada_numero']
        if 'final' in verificar and verificar['final']:
            # Declara este jogador o vencedor da partida.
            self.declarar_vencedor(verificar['vez_atual'])
        else:
            # Caso ainda tenhas dois ou mais, continua tudo:
            turnos_lista = {}
            # Prepara o front-end
            for jogador in self.jogadores:
                turnos_lista[jogador.username] = [[0, 0]]
            emit("construtor_html",
                 {'rodada_n': 0, 'turnos_lista': turnos_lista, 'coringa_atual': 0,
                  'dados_tt': self.dados_qtd}, broadcast=True)
            emit('dados_mesa', {'total': self.dados_qtd * len(self.jogadores)}, broadcast=True)
            emit('atualizar_coringa', {'coringa_atual': 0, 'ultimo_coringa': ''}, broadcast=True)

            # cria a rodada.
            rodada = Rodada(partida=self, jogadores=self.jogadores, rodada_numero=rodada_numero,
                            vez_atual=vez_atual)
            self.rodadas.append(rodada)
            # Arruma o front pro jogador da vez na rodada.
            rodada.atualizar_front_pro_da_vez(jogador_atual=vez_atual)
            nomes = []
            jogadores_dados_qtd = []
            for jogador in self.jogadores:
                jogador.rodada_atual = rodada
                jogador.turnos = []
                jogador.rodadas.append(rodada)
                jogador.dados_qtd = self.dados_qtd if rodada_numero == 1 else jogador.dados_qtd
                nomes.append(jogador.username)
                jogadores_dados_qtd.append(jogador.dados_qtd)
            # Jogando os dados da galera
            rodada.jogar_dados()
            dados_mesa = 0

            for jogador in self.jogadores:
                emit('construtor_dados', {'quantidade': jogador.dados_qtd, 'espectador': False},
                     to=jogador.client_id)
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
        Esta função toma as decisões de quem será o próximo jogador a jogar na rodada criada baseado nas informações
        da rodada anterior, ou caso não exista, ou seja, é a primeira rodada, sortear um jogador.
        """
        rodada_numero = len(self.rodadas) + 1
        # Se não for a primeira rodada, escolher alguém para iniciar.
        if rodada_numero > 1:
            perdedor = self.rodadas[-1].perdedor if hasattr(self.rodadas[-1], 'perdedor') else None
            vencedor = self.rodadas[-1].vencedor if hasattr(self.rodadas[-1], 'vencedor') else None
            # Tirar um dado do perdedor e tirar ele da partida se não restar nenhum dado para ele
            perdedor.dados_qtd -= 1
            if perdedor.dados_qtd == 0:
                # Fazer tudo isso com o perdedor da partida, ou seja, com nenhum dado.
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
                    return {'vez_atual': perdedor, 'rodada_numero': rodada_numero}
                else:
                    return {'vez_atual': vencedor, 'rodada_numero': rodada_numero}
        # Se for a primeira rodada, sortear.
        else:
            return {'vez_atual': self.jogador_sorteado, 'rodada_numero': rodada_numero}

    def buscar_jogador_pelo_client_id(self, client_id):
        for jogador in self.jogadores:
            if jogador.client_id == client_id:
                return jogador
        return None

    def declarar_vencedor(self, jogador):
        """
        Jogar todos para a tela do vencedor e fazer uma farofa pro vencedor lá kkk.
        Dar um ponto pro vencedor.
        """
        jogador.pontos += 1
        emit('vencedor_da_partida', {'nome': jogador.username}, broadcast=True)
        emit('botao_vencedor_ativ', to=jogador.client_id)
        emit("mudar_pagina", {'pag_numero': 4}, broadcast=True)
        nomes = [jogador.username for jogador in self.do_lobby.jogadores if jogador.username is not None]
        pontos = [jogador.pontos for jogador in self.do_lobby.jogadores if jogador.username is not None]

        # Atualizar pontos na tela inicial.
        emit('atualizar_pontos', {'nomes': nomes, 'pontos': pontos}, broadcast=True)


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
        self.vez_atual = vez_atual
        self.perdedor = perdedor
        self.vencedor = vencedor

    def __repr__(self):
        jogadores_nomes = [jogador.username for jogador in self.da_partida.jogadores]
        txt = (f"(RODADA {self.rodada_num} da partida {self.da_partida} com os jogadores: {jogadores_nomes}, "
               f"perdedor: {self.perdedor}, vencedor: {self.vencedor})")
        return txt

    def construir_turno(self, jogador, dados):
        """
        Constrói um turno na rodada para o jogador da vez.
        """
        turno_numero = len(self.turnos) + 1
        dado = int(dados['dado'])
        dado_qtd = int(dados['quantidade'])
        turno = Turno(da_rodada=self, jogador=jogador, dado=dado, dado_qtd=dado_qtd, turno_numero=turno_numero)
        self.turnos.append(turno)
        jogador.turno_atual = turno
        jogador.turnos.append(turno)

        if turno.verificar_validade_da_jogada():
            if dado == 1:
                self.coringa_atual_qtd = dado_qtd
                self.coringa_atual_jogador = jogador
            turno.executar_turno()
            o_da_vez = self.selecionar_proximo_jogador_na_lista(turno.do_jogador)
            self.atualizar_front_pro_da_vez(o_da_vez)
            self.vez_atual = o_da_vez
        else:
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
        todos_dados = self.todos_os_dados
        ultimo_turno = self.turnos[-1]
        if self.com_coringa:
            for i, dado in enumerate(todos_dados):
                if dado == 1:
                    todos_dados[i] = ultimo_turno.dado_face
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
            vencedor = ultimo_turno.do_jogador.username
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

    def atualizar_front_pro_da_vez(self, jogador_atual):
        """
        Modifica o front-end para todos os jogadores, o da vez joga, os outros observam a mensagem: aguarde a sua vez.
        Esta função não faz nenhuma validação de jogador da vez, deve ser feita em 'app.py'.
        """
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
        indice_atual = lista_jogadores.index(jogador_atual)
        indice_proximo = (indice_atual + 1) % len(lista_jogadores)
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
        # Mostrar sempre os 3 últimos.
        turnos = self.do_jogador.turnos[-3:][::-1]
        lista_turnos = [[turno.dado_face, turno.dado_qtd] for turno in turnos]
        emit('atualizar_turno', {'jogador': self.do_jogador.username, 'lista_turnos': lista_turnos},
             broadcast=True)

        if self.da_rodada.com_coringa is True:
            if lista_turnos[0][0] == 1:
                emit('atualizar_coringa', {
                    'coringa_atual': self.da_rodada.coringa_atual_qtd,
                    'ultimo_coringa': self.da_rodada.coringa_atual_jogador.username,
                    'coringa_cancelado': False}, broadcast=True)
        else:
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

        # VERIFICANDO VALIDADE DA JOGADA
        tur_ant = self.obter_turno_anterior_na_partida()  # Recebe o turno anterior

        coringa_true = self.da_rodada.com_coringa
        coringa_atual_qtd = self.da_rodada.coringa_atual_qtd

        if tur_ant:
            turno_ant_dado_face = tur_ant.dado_face
            turno_ant_dado_qtd = tur_ant.dado_qtd

        turno_atual_dado_face = self.dado_face
        turno_atual_dado_qtd = self.dado_qtd

        # Validações de primeiro turno
        if self.turno_num == 1 and self.dado_face == 1:
            # PRIMEIRO TURNO
            # Se for o primeiro turno e o dado atual for 1, a partida não tem coringa e turno válida.
            self.da_rodada.com_coringa = False
            # Partida sem coringa
            return True
        if self.turno_num == 1:
            # PRIMEIRO TURNO
            # Partida com coringa
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
