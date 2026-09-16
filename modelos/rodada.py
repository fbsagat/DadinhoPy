"""Modelo da Rodada (Fase 45, M4)."""
from datetime import datetime
from flask_socketio import emit

import narrador
import seed
import anti_fraude
from modelos.comum import somente_ias_na_partida
from modelos.turno import Turno


class Rodada:
    """
    Representa um conjunto de turnos.
    Represento o momento em que os jogadores atuais da partida jogam seus dados até o momento em que alguém desconfia e
    ele mesmo ou outro jogador perde.
    """

    def __init__(self, partida, jogadores, rodada_numero, vez_atual, perdedor=None, vencedor=None,
                 com_coringa=True):
        self.rodada_num = rodada_numero
        self.da_partida = partida
        self.turnos = []
        self.todos_os_dados = []
        self.dados_por_jogador = {}
        self.jogadores = jogadores
        self.com_coringa = com_coringa
        self.coringa_atual_qtd = 0
        self.coringa_atual_jogador = None
        self.conferiram = 0
        self.conferencia = None  # Payload da tela de conferência, persistido p/ snapshot (Fase 4).
        self.vez_atual = vez_atual
        self.perdedor = perdedor
        self.vencedor = vencedor
        # Marcas de tempo da jogada automática (Fase 21): quando a vez atual
        # começou (`vez_em`) e quando a rolagem da rodada começou
        # (`inicio_rolagem_em`). O servidor confere o tempo decorrido antes de
        # aceitar um `autojogar`; o cliente usa para o contador regressivo.
        self.vez_em = None
        self.inicio_rolagem_em = None
        # Quando a tela de conferência (3) foi aberta (Fase 22): o `autojogar`
        # usa como referência de tempo para auto-confirmar um humano atrasado.
        self.conferencia_em = None

    def __repr__(self):
        jogadores_nomes = [jogador.username for jogador in self.da_partida.jogadores]
        txt = (f"(RODADA {self.rodada_num} da partida {self.da_partida} com os jogadores: {jogadores_nomes}, "
               f"perdedor: {self.perdedor}, vencedor: {self.vencedor})")
        return txt

    def sala_room(self):
        """
        Nome da room no Socket.IO da sala onde a rodada acontece.
        """
        return self.da_partida.sala_room()

    def status_rolagem_dict(self):
        """Quem já rolou os dados na rolagem (página 1), por apelido (Fase 22)."""
        jogadores = [j for j in self.jogadores if j.username]
        return {
            'confirmados': [j.username for j in jogadores if j.joguei_dados],
            'pendentes': [j.username for j in jogadores if not j.joguei_dados],
            'total': len(jogadores),
        }

    def status_conferencia_dict(self):
        """Quem já confirmou o "Ok" da conferência (página 3), por apelido (Fase 22)."""
        jogadores = [j for j in self.jogadores if j.username]
        return {
            'confirmados': [j.username for j in jogadores if j.confirmou_rodada],
            'pendentes': [j.username for j in jogadores if not j.confirmou_rodada],
            'total': len(jogadores),
        }

    def construir_turno(self, jogador, dados):
        """
        Constrói um turno na rodada para o jogador da vez.
        """
        turno_numero = len(self.turnos) + 1
        # Fase 6 (B3): valida o payload da aposta antes de criar o turno — dado
        # em 1-6 e quantidade >= 1; payload malformado é rejeitado com
        # jogada_invalida em vez de estourar exceção no handler. Fase 13: os
        # alertas explicam ao jogador o motivo exato da recusa.
        if not isinstance(dados, dict):
            emit('jogada_invalida', {'txtchave': 'msg.jogada.dados_ausentes'},
                 to=jogador.client_id)
            return
        try:
            dado = int(dados['dado'])
            dado_qtd = int(dados['quantidade'])
        except (ValueError, TypeError, KeyError):
            emit('jogada_invalida', {'txtchave': 'msg.jogada.nao_inteiros'},
                 to=jogador.client_id)
            return
        if not (1 <= dado <= 6) or dado_qtd < 1:
            emit('jogada_invalida', {'txtchave': 'msg.jogada.fora_intervalo'},
                 to=jogador.client_id)
            return
        # Fase 29 (H2): aposta acima do total teórico de dados na mesa é impossível
        # de responder (o desafiado não consegue subir) — clampeia no máximo. A
        # regra do coringa (dobro para sair dos ases) fica "à parte" e segue sendo
        # validada no turno normalmente.
        total_dados = len(self.todos_os_dados) or sum(j.dados_qtd for j in self.jogadores)
        if total_dados and dado_qtd > total_dados:
            dado_qtd = total_dados
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
            turno_ant = turno.obter_turno_anterior_na_partida()
            motivo = self.explicar_jogada(dado, dado_qtd, turno_ant, turno_numero)
            self.turnos.remove(turno)
            jogador.turnos.remove(turno)
            del turno
            if motivo:
                emit('jogada_invalida',
                     {'txtchave': motivo['chave'], 'txtparams': motivo.get('params', {})},
                     to=jogador.client_id)
            else:
                emit('jogada_invalida', {'txtchave': 'msg.jogada.tente_outra'},
                     to=jogador.client_id)

    def jogar_dados(self):
        partida = self.da_partida
        seed_final = getattr(partida, 'seed_final', None)
        self.dados_por_jogador = {}
        for jogador in partida.jogadores:
            if seed_final:
                # Derivação determinística (auditável) em vez de sorteio.
                dados = [
                    seed.valor(seed_final, partida.do_lobby.sala_id, partida.partida_num,
                               self.rodada_num, jogador.client_id, indice)
                    for indice in range(jogador.dados_qtd)
                ]
                jogador.dados = dados
            else:
                dados = jogador.jogar_dados()
            self.dados_por_jogador[jogador.client_id] = list(dados)
            for dado in dados:
                self.todos_os_dados.append(dado)

    def verificar_se_todos_ja_jogaram_seus_dados(self):
        jogadores_tt = len(self.da_partida.jogadores)
        count = 0
        for jogador in self.da_partida.jogadores:
            if jogador.joguei_dados is True:
                count += 1
        return True if jogadores_tt == count else False

    def jogada_valida(self, face, qtd, turno_ant=None, turno_num=None):
        """
        Validação pura de uma jogada, sem efeitos colaterais (Fase 11) — usada pela
        IA para gerar apenas apostas legais. Espelha a regra de
        Turno.verificar_validade_da_jogada, que delega para cá.
        """
        return self.explicar_jogada(face, qtd, turno_ant, turno_num) is None

    def explicar_jogada(self, face, qtd, turno_ant=None, turno_num=None):
        """
        Mesma regra de jogada_valida, mas devolve None quando a jogada é válida ou
        um dict {'chave', 'params'} com a chave i18n do motivo da invalidade
        (Fase 13/i18n). Fonte única da regra de aposta, consumida pela validação e
        pela IA. Os parâmetros trazem faces/quantidades numéricas; o cliente
        resolve o nome da face no idioma do jogador.
        """
        if turno_num is None:
            turno_num = len(self.turnos) + 1
        if turno_num == 1 or turno_ant is None:
            return None
        face_ant = turno_ant.dado_face
        qtd_ant = turno_ant.dado_qtd
        base = {'face': face, 'face_num': face, 'face_ant': face_ant, 'face_ant_num': face_ant}

        def _motivo(chave, **extra):
            params = dict(base)
            params.update(extra)
            return {'chave': chave, 'params': params}

        if self.com_coringa:
            if face_ant > 1 and face > 1:
                if qtd > qtd_ant:
                    return None
                if face_ant < face and qtd_ant == qtd:
                    return None
                if face_ant == face:
                    return _motivo('msg.jogada.repetir_face', qtd_ant=qtd_ant, qtd=qtd)
                if qtd < qtd_ant:
                    return _motivo('msg.jogada.diminuir', qtd=qtd, qtd_ant=qtd_ant)
                return _motivo('msg.jogada.face_menor', qtd=qtd, qtd_ant=qtd_ant)
            if face_ant > 1 and face == 1:
                if qtd > self.coringa_atual_qtd:
                    return None
                return _motivo('msg.jogada.coringa_superar', coringa=self.coringa_atual_qtd, qtd=qtd)
            if face_ant == 1 and face > 1:
                minimo = self.coringa_atual_qtd * 2
                if qtd >= minimo:
                    return None
                return _motivo('msg.jogada.coringa_dobro', coringa=self.coringa_atual_qtd,
                               minimo=minimo, qtd=qtd)
            if face_ant == face:
                if qtd > qtd_ant:
                    return None
                return _motivo('msg.jogada.coringa_repetir', qtd_ant=qtd_ant)
            return _motivo('msg.jogada.nao_supera', qtd=qtd, qtd_ant=qtd_ant)
        if face_ant > 0 and face > 0:
            if qtd > qtd_ant:
                return None
            if face_ant < face and qtd_ant == qtd:
                return None
            if face_ant == face:
                return _motivo('msg.jogada.repetir_face', qtd_ant=qtd_ant, qtd=qtd)
            if qtd < qtd_ant:
                return _motivo('msg.jogada.diminuir', qtd=qtd, qtd_ant=qtd_ant)
            return _motivo('msg.jogada.face_menor', qtd=qtd, qtd_ant=qtd_ant)
        return _motivo('msg.jogada.nao_supera', qtd=qtd, qtd_ant=qtd_ant)

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
            # Contagem com coringa: os 1 valem como a face apostada. Trabalha
            # sobre uma cópia para não corromper o registro dos dados da rodada
            # (`todos_os_dados` é persistido e representa os dados reais).
            todos_dados = [
                ultimo_turno.dado_face if dado == 1 else dado
                for dado in todos_dados
            ]
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
        self.conferencia_em = datetime.now()
        self.conferencia = {
            'nomes': nomes, 'ganhador': vencedor, 'perdedor': perdedor, 'saiu_da_partida': saiu, 'dados': dados,
            'dado_apostado_face': ultimo_turno.dado_face,
            'dado_qtd': ultimo_turno.dado_qtd,
            'quantidade_real': quantidade,
            'verdadeira': quantidade >= ultimo_turno.dado_qtd,
            'com_coringa': self.com_coringa, 'texto': txt,
            # Fase 22: tempo máximo de confirmação (jogada automática) desta tela.
            'tempo_max': int(self.da_partida.do_lobby.config.get('tempo_max_jogada', 0) or 0),
        }
        self.da_partida.do_lobby.pagina = 3
        pensou = max(
            (narrador.tempo_pensamento(jogador.ia_nivel, jogador=jogador,
                                       so_ias=somente_ias_na_partida(self.da_partida))
             if jogador.is_ia else 0),
            anti_fraude.delay_adicional(jogador))
        emit('narracao', narrador.narracao_desconfianca(jogador, ultimo_turno.do_jogador, pensou,
                                                        aposta=ultimo_turno),
             to=self.sala_room())
        emit('cards_conferencia', self.conferencia, to=self.sala_room())
        emit("mudar_pagina", {'pag_numero': 3}, to=self.sala_room())
        # Fase 22: status inicial da conferência (ninguém confirmou ainda).
        emit('conferencia_status', self.status_conferencia_dict(), to=self.sala_room())

    def contexto_aposta(self):
        """
        Estado da aposta usado pelo cliente para calibrar o mínimo do input de
        quantidade (mesma regra de `explicar_jogada`, resolvida no navegador).
        """
        ultima = self.turnos[-1] if self.turnos else None
        return {
            'turno_num': len(self.turnos),
            'com_coringa': self.com_coringa,
            'coringa_atual_qtd': self.coringa_atual_qtd,
            'ultima_aposta': ({'face': ultima.dado_face, 'qtd': ultima.dado_qtd} if ultima else None),
        }

    def atualizar_front_pro_da_vez(self, jogador_atual):
        """
        Modifica o front-end para todos os jogadores, o da vez joga, os outros observam a mensagem: aguarde a sua vez.
        Esta função não faz nenhuma validação de jogador da vez, deve ser feita em 'app.py'.
        """
        self.vez_em = datetime.now()
        nomes = [jogador.username for jogador in self.da_partida.jogadores]
        emit('formatador_coletivo', {'jogadores_nomes': nomes, 'jogador_inicial_nome': jogador_atual.username},
             to=self.sala_room())
        payload = {'username': jogador_atual.username,
                   'tempo_max': int(self.da_partida.do_lobby.config.get('tempo_max_jogada', 0) or 0)}
        payload.update(self.contexto_aposta())
        emit('meu_turno', payload, to=jogador_atual.client_id)
        for jogador in self.da_partida.jogadores:
            if jogador != jogador_atual:
                # O username é o da VEZ (jogador_atual), não o do receptor: o
                # cliente (Fase D2) e o snapshot (`emitir_dispatcher_turno`)
                # dependem desse campo para saber quem é o da vez.
                emit('espera_turno', {'username': jogador_atual.username}, to=jogador.client_id)

    def selecionar_proximo_jogador_na_lista(self, jogador_atual):
        lista_jogadores = self.da_partida.jogadores
        indice_atual = lista_jogadores.index(jogador_atual)
        indice_proximo = (indice_atual + 1) % len(lista_jogadores)
        return lista_jogadores[indice_proximo]