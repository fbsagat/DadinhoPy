"""Modelo da Partida (Fase 45, M4)."""
from datetime import datetime
import secrets
from flask_socketio import emit

import narrador
import seed
from modelos.rodada import Rodada


class Partida:
    """
    Representa um conjunto de rodadas.
    Representa o momento em que todos os jogadores estão no jogo, até o momento em que sobra um ganhador.
    """

    def __init__(self, do_lobby, jogadores, partida_numero, dados_qtd, com_coringa=True, seed_info=None):
        self.partida_num = partida_numero
        self.dados_qtd = dados_qtd
        self.com_coringa = com_coringa
        self.jogadores = jogadores
        self.do_lobby = do_lobby
        self.seed_info = seed_info
        self.seed_final = seed_info.get('seed_final') if seed_info else None
        # Com verificação ativa, o jogador inicial também é derivado da seed
        # (auditável); sem ela, mantém o sorteio legado.
        if self.seed_final and jogadores:
            indice = seed.indice_inicial(self.seed_final, do_lobby.sala_id, partida_numero, len(jogadores))
            self.jogador_sorteado = jogadores[indice]
        elif jogadores:
            self.jogador_sorteado = secrets.choice(self.jogadores)
        else:
            # Fase 28 (H1b): partida construída sem jogadores (estado corrompido
            # vindo do store) não pode estourar IndexError/ZeroDivisionError no
            # sorteio — fica sem jogador sorteado até alguém entrar na mesa.
            self.jogador_sorteado = None
        self.rodadas = []
        self.vencedor_final = None
        # Quando a tela de vitória (4) foi aberta (Fase 22): referência de tempo
        # do `autojogar` para auto-confirmar um humano atrasado no reset.
        self.vitoria_em = None
        # Fase 69 (espectador): relógio do próximo lance dos bots. Cobre as
        # páginas 3 (conferência) e 4 (vitória), que a `Rodada` não guarda com
        # folga — ver `Rodada.proximo_lance_em`. Lido/gravado por qualquer
        # instância via o store; nenhum timer/thread no servidor.
        self.proximo_lance_em = None

    def __repr__(self):
        jogadores_nomes = [jogador.username for jogador in self.jogadores]
        txt = f"(PARTIDA do lobby {self.do_lobby} com jogadores: {jogadores_nomes})"
        return txt

    def sala_room(self):
        """
        Nome da room no Socket.IO da sala onde a partida acontece.
        """
        return self.do_lobby.sala_room()

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
            # Fase 21: tempo máximo de jogada da sala (0 = sem jogada automática).
            tempo_max_jogada = int(self.do_lobby.config.get('tempo_max_jogada', 0) or 0)
            # Prepara o front-end
            for jogador in self.jogadores:
                turnos_lista[jogador.username] = [[0, 0]]
            emit("construtor_html",
                 {'rodada_n': rodada_numero, 'turnos_lista': turnos_lista,
                  'dados_tt': self.dados_qtd}, to=self.sala_room())
            emit('dados_mesa', {'total': self.dados_qtd * len(self.jogadores)}, to=self.sala_room())
            emit('atualizar_coringa', {'coringa_atual': 0, 'ultimo_coringa': ''}, to=self.sala_room())

            # cria a rodada.
            rodada = Rodada(partida=self, jogadores=self.jogadores, rodada_numero=rodada_numero,
                            vez_atual=vez_atual, com_coringa=self.com_coringa)
            rodada.inicio_rolagem_em = datetime.now()
            self.rodadas.append(rodada)
            # Arruma o front pro jogador da vez na rodada.
            rodada.atualizar_front_pro_da_vez(jogador_atual=vez_atual)
            nomes = []
            jogadores_dados_qtd = []
            for jogador in self.jogadores:
                jogador.rodada_atual = rodada
                jogador.joguei_dados = False
                jogador.confirmou_rodada = False
                jogador.turnos = []
                jogador.rodadas.append(rodada)
                jogador.dados_qtd = self.dados_qtd if rodada_numero == 1 else jogador.dados_qtd
                nomes.append(jogador.username)
                jogadores_dados_qtd.append(jogador.dados_qtd)
            # Jogando os dados da galera
            rodada.jogar_dados()
            dados_mesa = 0

            for jogador in self.jogadores:
                emit('construtor_dados', {'quantidade': jogador.dados_qtd, 'espectador': False,
                                          'tempo_max': tempo_max_jogada},
                     to=jogador.client_id)
                dados_mesa += jogador.dados_qtd
            if rodada_numero > 1:
                emit('reset_rodada', {'jogadores_nomes': nomes, 'jogadores_dados_qtd': jogadores_dados_qtd},
                     to=self.sala_room())
                emit('atualizar_coringa', {'coringa_atual': 0}, to=self.sala_room())
                emit('dados_mesa', {'total': dados_mesa}, to=self.sala_room())
            emit('narracao',
                 narrador.narracao_rodada(rodada_numero, dados_mesa, iniciante=vez_atual,
                                          primeira=(rodada_numero == 1)),
                 to=self.sala_room())
            emit("mudar_pagina", {'pag_numero': 1}, to=self.sala_room())
            # Fase 22: status inicial da rolagem (todos pendentes) para o
            # front acompanhar quem já rolou em tempo real.
            emit('rolagem_status', rodada.status_rolagem_dict(), to=self.sala_room())
            self.do_lobby.pagina = 1
            return rodada

    def verificar_partida_anterior(self):
        """
        Esta função toma as decisões de quem será o próximo jogador a jogar na rodada criada baseado nas informações
        da rodada anterior, ou caso não exista, ou seja, é a primeira rodada, sortear um jogador.
        """
        rodada_numero = len(self.rodadas) + 1
        # Se não for a primeira rodada, escolher alguém para iniciar.
        if rodada_numero > 1:
            ultima_rodada = self.rodadas[-1]
            perdedor = getattr(ultima_rodada, 'perdedor', None)
            vencedor = getattr(ultima_rodada, 'vencedor', None)
            # O perdedor pode já ter saído da partida (desconexão na conferência):
            # nesse caso não perde outro dado nem precisa ser removido de novo.
            if perdedor is not None and perdedor in self.jogadores:
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
                    return {'vez_atual': self.iniciante_valido(vencedor),
                            'rodada_numero': rodada_numero, 'final': True}
                if perdedor in self.jogadores:
                    return {'vez_atual': perdedor, 'rodada_numero': rodada_numero}
                return {'vez_atual': self.iniciante_valido(vencedor), 'rodada_numero': rodada_numero}
            # Sem perdedor em jogo (não houve, ou ele caiu na conferência): segue
            # com o vencedor ou com um sorteado que ainda esteja na mesa.
            proximo = self.iniciante_valido(vencedor if vencedor in self.jogadores else self.jogador_sorteado)
            if len(self.jogadores) < 2:
                return {'vez_atual': proximo, 'rodada_numero': rodada_numero, 'final': True}
            return {'vez_atual': proximo, 'rodada_numero': rodada_numero}
        # Se for a primeira rodada, sortear.
        else:
            return {'vez_atual': self.jogador_sorteado, 'rodada_numero': rodada_numero}

    def iniciante_valido(self, preferido):
        """
        Garante que o jogador escolhido para abrir a rodada ainda está na partida.
        Um perdedor/vencedor que desconectou na conferência não pode voltar como
        `vez_atual`; cai para o primeiro jogador ainda na mesa.
        """
        if preferido in self.jogadores:
            return preferido
        return self.jogadores[0] if self.jogadores else preferido

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
        self.vencedor_final = jogador
        self.vitoria_em = datetime.now()
        self.do_lobby.pagina = 4
        emit('narracao', narrador.narracao_vitoria(jogador), to=self.sala_room())
        emit('vencedor_da_partida',
             {'nome': jogador.username,
              # Fase 22: tempo máximo de confirmação (jogada automática) da vitória.
              'tempo_max': int(self.do_lobby.config.get('tempo_max_jogada', 0) or 0)},
             to=self.sala_room())
        emit('botao_vencedor_ativ', to=jogador.client_id)
        emit("mudar_pagina", {'pag_numero': 4}, to=self.sala_room())
        # Fase 22: status inicial da vitória (ninguém confirmou o reset ainda).
        emit('vitoria_status', self.do_lobby.status_vitoria_dict(), to=self.sala_room())
        nomes = [jogador.username for jogador in self.do_lobby.jogadores if jogador.username is not None]
        pontos = [jogador.pontos for jogador in self.do_lobby.jogadores if jogador.username is not None]

        # Atualizar pontos na tela inicial.
        emit('atualizar_pontos', {'nomes': nomes, 'pontos': pontos}, to=self.sala_room())

        # Verificação de integridade: revela seed, nonces e dados para auditoria.
        if self.seed_info:
            emit('auditoria_partida', self.montar_auditoria(), to=self.sala_room())

    def montar_auditoria(self):
        """
        Payload da auditoria (fim da partida): seed revelada, compromissos,
        nonces dos participantes e os dados por rodada, para o cliente recomputar
        tudo com a fórmula pública (seed.py) sem confiar no servidor.
        """
        info = self.seed_info or {}
        return {
            'versao': info.get('versao', seed.VERSAO_ATUAL),
            'sala': self.do_lobby.sala_id,
            'partida_num': self.partida_num,
            'fonte': info.get('fonte'),
            'entropia_externa': info.get('entropia_externa'),
            'nonce_servidor': info.get('nonce_servidor'),
            'compromisso_servidor': info.get('compromisso_servidor'),
            'beacon': info.get('beacon'),
            'participantes': info.get('participantes', []),
            'seed_final': self.seed_final,
            'rodadas': [
                {'rodada_num': rodada.rodada_num, 'dados_por_jogador': rodada.dados_por_jogador}
                for rodada in self.rodadas
            ],
        }