"""Modelo do Turno (Fase 45, M4)."""
from flask_socketio import emit

import narrador
from modelos.comum import somente_ias_na_partida


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

    def sala_room(self):
        """
        Nome da room no Socket.IO da sala onde o turno acontece.
        """
        return self.da_rodada.sala_room()

    def executar_turno(self):
        """Executa o turno no front end"""
        # Narração da jogada (vem antes do card para o cliente encaixar o
        # "tempo de pensamento" dos bots na fila de animação).
        pensou = (narrador.tempo_pensamento(self.do_jogador.ia_nivel, jogador=self.do_jogador,
                                            so_ias=somente_ias_na_partida(self.da_rodada.da_partida))
                  if self.do_jogador.is_ia else 0)
        anterior = self.obter_turno_anterior_na_partida()
        dados_mesa = sum(getattr(jogador, 'dados_qtd', 0) or 0 for jogador in self.da_rodada.jogadores)
        emit('narracao',
             narrador.narracao_aposta(self.do_jogador, self.dado_face, self.dado_qtd, pensou,
                                      anterior=anterior, dados_mesa=dados_mesa,
                                      primeira=(self.turno_num == 1), turno_num=self.turno_num),
             to=self.sala_room())
        # Mostrar sempre os 3 últimos.
        turnos = self.do_jogador.turnos[-3:][::-1]
        lista_turnos = [[turno.dado_face, turno.dado_qtd] for turno in turnos]
        emit('atualizar_turno', {'jogador': self.do_jogador.username, 'lista_turnos': lista_turnos,
                                 'is_ia': self.do_jogador.is_ia, 'ultimo': True},
             to=self.sala_room())

        if self.da_rodada.com_coringa is True:
            if lista_turnos[0][0] == 1:
                emit('atualizar_coringa', {
                    'coringa_atual': self.da_rodada.coringa_atual_qtd,
                    'ultimo_coringa': self.da_rodada.coringa_atual_jogador.username,
                    'coringa_cancelado': False}, to=self.sala_room())
        else:
            emit('atualizar_coringa', {'coringa_cancelado': True}, to=self.sala_room())

    def obter_turno_anterior_na_partida(self):
        if self.turno_num > 1:
            lista = self.da_rodada.turnos
            indice = lista.index(self)
            turno = lista[indice - 1]
            return turno

    def verificar_validade_da_jogada(self):
        """
        Valida a jogada do turno delegando para Rodada.jogada_valida (lógica pura).
        Mantém o efeito colateral do 1º turno: apostar face 1 cancela o coringa.
        """
        tur_ant = self.obter_turno_anterior_na_partida()
        valida = self.da_rodada.jogada_valida(self.dado_face, self.dado_qtd, tur_ant, self.turno_num)
        if valida and self.turno_num == 1 and self.dado_face == 1:
            self.da_rodada.com_coringa = False
        return valida