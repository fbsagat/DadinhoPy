"""Modelo do Lobby (Fase 45, M4)."""
from datetime import datetime
from flask_socketio import emit

import narrador
import seed
from modelos.comum import sala_room
from modelos.jogador import Jogador
from modelos.migracao import MIGRACOES, VAGAS_RECENTES_SEGUNDOS, VERSAO_ATUAL
from modelos.partida import Partida
from modelos.rodada import Rodada
from modelos.turno import Turno


class Lobby:
    """
    Representa um conjunto de partidas.
    Representa o momento onde os jogadores se juntam para jogar dadinho, até o fim deste momento.
    """

    def __init__(self, sala_id, lobby_numero):
        self.sala_id = sala_id
        self.lobby_num = lobby_numero
        self.jogadores = []
        # Quem assiste a uma partida em andamento sem jogar. Fica fora de
        # `jogadores` para não contar em vitória, lotação ou limite de dados;
        # vira jogador quando o lobby reinicia (resetar_para_lobby).
        self.espectadores = []
        # Numeração monotônica das partidas (mesmo podando o histórico antigo,
        # o `partida_num` usado pela seed/auditoria nunca se repete).
        self.proxima_partida_num = 1
        # Revisão incrementada a cada `salvar_sala` (Fase 40, detector CAS):
        # alimenta o alerta de lost-update em `store.salvar_sala` para calibrar
        # o TTL do lock distribuído. Não confundir com `versao` (schema).
        self.revisao = 1
        self.partidas = []
        self.conferiram_vencedor = 0
        # Página atual da sala (0=lobby, 1=rolar dados, 2=turnos, 3=conferência, 4=vitória).
        # Persistida para permitir o snapshot no reconnect/novo tab (Fase 4).
        self.pagina = 0
        # Sala de espera / matchmaking (Fase 5).
        self.nome = f"Partida #{lobby_numero}"
        self.status = "espera"  # "espera" | "jogando"
        self.criado_em = datetime.now()
        # Última vez que a sala deu sinal de vida (evento ou heartbeat do
        # cliente). A busca usa isso para esconder resumos órfãos do serverless
        # (instância que morreu sem disconnect, deixando o resumo congelado).
        self.visto_em = self.criado_em
        self.config = Lobby.config_padrao()
        # Estado do commit-reveal enquanto a partida ainda não começou (ver seed.py).
        # None quando a verificação está desligada ou após a seed ser fixada na Partida.
        self.seed_info = None
        # Fase 30: chave_secreta -> {'nome', 'em'} de humanos removidos (janela de
        # graça expirada, início de partida, expulsão). Permite o retorno explicar
        # por que a vaga foi perdida (motivo do `retomar_negado`).
        self.vagas_recentes = {}

    @staticmethod
    def config_padrao():
        """
        Configuração padrão de uma partida (editável pelo master na sala de espera).
        É a fonte única dos defaults: o cliente só espelha estes valores enquanto
        não recebe o payload do servidor (`config_padrao` em `update_user_list`).
        O trio `dados_qtd`/`max_jogadores` casa com `simular_ia.montar_partida`,
        que sobrescreve os valores para os cenários headless.
        """
        return {
            'dados_qtd': 3,
            'max_jogadores': 4,
            'com_coringa': True,
            # Sala nasce privada (só entra por link); o master libera na busca.
            'publica': False,
            'substituir_desconectado_por_ia': True,
            'ia_nivel_padrao': 3,
            # Verificação de integridade dos dados (provably fair): ligada por
            # padrão; o master pode desligar. Exige o reveal da seed antes de iniciar.
            'verificacao_ativa': True,
            # Tempo máximo (segundos) por jogada; 0 desliga. Quando expira, o
            # jogo joga pelo jogador atrasado (jogada automática, Fase 21).
            'tempo_max_jogada': 60,
        }

    def sala_room(self):
        """
        Nome da room no Socket.IO correspondente a esta sala.
        """
        return sala_room(self.sala_id)

    def marcar_visto(self):
        """Registra o instante do último sinal de vida da sala (busca/heartbeat)."""
        self.visto_em = datetime.now()

    def registrar_vaga_perdida(self, jogador):
        """
        Fase 30: registra a vaga de um humano removido (chave_secreta -> nome e
        instante) para o `retomar_identidade` explicar o `retomar_negado`.
        Expurga entradas antigas (VAGAS_RECENTES_SEGUNDOS) ao gravar.
        """
        if jogador.is_ia or not jogador.chave_secreta:
            return
        agora = datetime.now()
        limite = (agora.timestamp() - VAGAS_RECENTES_SEGUNDOS)
        self.vagas_recentes = {c: v for c, v in self.vagas_recentes.items()
                               if isinstance(v, dict) and v.get('em') is not None
                               and v['em'].timestamp() > limite}
        self.vagas_recentes[jogador.chave_secreta] = {
            'nome': jogador.username,
            'em': agora,
        }

    def buscar_vaga_recente(self, chave_secreta):
        """
        Fase 30: retorna {'nome', 'em'} da vaga recente da chave, ou None se não
        houver registro vigente (sessão de outra sala / vaga antiga demais).
        """
        if not chave_secreta:
            return None
        vaga = self.vagas_recentes.get(chave_secreta)
        if not isinstance(vaga, dict) or vaga.get('em') is None:
            return None
        if (datetime.now() - vaga['em']).total_seconds() > VAGAS_RECENTES_SEGUNDOS:
            return None
        return vaga

    def status_vitoria_dict(self):
        """Quem já confirmou o "Ok" da vitória (página 4), por apelido (Fase 22)."""
        jogadores = [j for j in self.jogadores if j.username]
        return {
            'confirmados': [j.username for j in jogadores if j.confirmou_vencedor],
            'pendentes': [j.username for j in jogadores if not j.confirmou_vencedor],
            'total': len(jogadores),
        }

    def __repr__(self):
        return f"(LOBBY {self.lobby_num} com {len(self.jogadores)} jogadores)"

    @staticmethod
    def _partida_para_dict(partida):
        """Serializa uma partida (com rodadas e turnos) para ser persistida no store."""
        rodadas = []
        for rodada in partida.rodadas:
            rodadas.append({
                'rodada_num': rodada.rodada_num,
                'todos_os_dados': rodada.todos_os_dados,
                'dados_por_jogador': rodada.dados_por_jogador,
                'com_coringa': rodada.com_coringa,
                'coringa_atual_qtd': rodada.coringa_atual_qtd,
                'coringa_atual_jogador_id': rodada.coringa_atual_jogador.client_id
                if rodada.coringa_atual_jogador else None,
                'conferiram': rodada.conferiram,
                'conferencia': rodada.conferencia,
                'vez_atual_id': rodada.vez_atual.client_id if rodada.vez_atual else None,
                'vez_em': rodada.vez_em.isoformat() if rodada.vez_em else None,
                'inicio_rolagem_em': rodada.inicio_rolagem_em.isoformat() if rodada.inicio_rolagem_em else None,
                'conferencia_em': rodada.conferencia_em.isoformat() if rodada.conferencia_em else None,
                'perdedor_id': rodada.perdedor.client_id if rodada.perdedor else None,
                'vencedor_id': rodada.vencedor.client_id if rodada.vencedor else None,
                'turnos': [
                    {
                        'turno_num': turno.turno_num,
                        'do_jogador_id': turno.do_jogador.client_id if turno.do_jogador else None,
                        'dado_face': turno.dado_face,
                        'dado_qtd': turno.dado_qtd,
                    }
                    for turno in rodada.turnos
                ],
            })
        return {
            'partida_num': partida.partida_num,
            'dados_qtd': partida.dados_qtd,
            'com_coringa': partida.com_coringa,
            'jogadores_ids': [jogador.client_id for jogador in partida.jogadores],
            'jogador_sorteado_id': partida.jogador_sorteado.client_id if partida.jogador_sorteado else None,
            'vencedor_final_id': partida.vencedor_final.client_id if partida.vencedor_final else None,
            'vitoria_em': partida.vitoria_em.isoformat() if partida.vitoria_em else None,
            'seed_info': partida.seed_info,
            'seed_final': partida.seed_final,
            'rodadas': rodadas,
        }

    def para_dict(self):
        """Serializa toda a árvore do Lobby (jogadores + partidas) para o store distribuído."""
        return {
            'versao': VERSAO_ATUAL,
            'revisao': self.revisao,
            'sala_id': self.sala_id,
            'lobby_num': self.lobby_num,
            'pagina': self.pagina,
            'conferiram_vencedor': self.conferiram_vencedor,
            'nome': self.nome,
            'status': self.status,
            'criado_em': self.criado_em.isoformat() if self.criado_em else None,
            'visto_em': self.visto_em.isoformat() if self.visto_em else None,
            'config': self.config,
            'seed_info': self.seed_info,
            'proxima_partida_num': self.proxima_partida_num,
            'vagas_recentes': {chave: {'nome': vaga.get('nome'), 'em': vaga['em'].isoformat()}
                               for chave, vaga in self.vagas_recentes.items()
                               if isinstance(vaga, dict) and vaga.get('em') is not None},
            'jogadores': [jogador.para_dict(self) for jogador in self.jogadores],
            'espectadores': [jogador.para_dict(self) for jogador in self.espectadores],
            'partidas': [self._partida_para_dict(partida) for partida in self.partidas],
        }

    @staticmethod
    def _migrar(dados):
        """
        Aplica as migrações de formato (Fase 10, S3): lê a versão gravada e sobe
        passo a passo até VERSAO_ATUAL. Dados sem versão são tratados como v1.
        Um formato mais novo que o atual é mantido como está (os defaults cobrem
        campos ausentes), evitando rebaixar uma gravação futura.
        """
        if not isinstance(dados, dict):
            return dados
        try:
            versao = int(dados.get('versao') or 1)
        except (ValueError, TypeError):
            versao = 1
        while versao in MIGRACOES:
            dados = MIGRACOES[versao](dados)
            versao += 1
        if versao <= VERSAO_ATUAL:
            dados['versao'] = VERSAO_ATUAL
        return dados

    @staticmethod
    def _jogador_de_dict(dados_jogador):
        """Reconstrói um Jogador a partir do dict serializado (sem vínculos de árvore)."""
        jogador = Jogador(client_id=dados_jogador['client_id'],
                          master=dados_jogador.get('master', False))
        jogador.username = dados_jogador.get('username')
        jogador.chave_secreta = dados_jogador.get('chave_secreta', '')
        jogador.pontos = dados_jogador.get('pontos', 0)
        jogador.dados = list(dados_jogador.get('dados') or [])
        jogador.dados_qtd = dados_jogador.get('dados_qtd', 0)
        jogador.joguei_dados = bool(dados_jogador.get('joguei_dados', False))
        entrou = dados_jogador.get('entrou')
        jogador.entrou = datetime.fromisoformat(entrou) if entrou else datetime.now()
        jogador.confirmou_rodada = bool(dados_jogador.get('confirmou_rodada', False))
        jogador.confirmou_vencedor = bool(dados_jogador.get('confirmou_vencedor', False))
        jogador.pronto = bool(dados_jogador.get('pronto', False))
        desconectado_em = dados_jogador.get('desconectado_em')
        jogador.desconectado_em = datetime.fromisoformat(desconectado_em) if desconectado_em else None
        jogador.is_ia = bool(dados_jogador.get('is_ia', False))
        jogador.ia_nivel = dados_jogador.get('ia_nivel')
        jogador.ia_risco = float(dados_jogador.get('ia_risco', 0.5) or 0.5)
        jogador.ia_agressividade = float(dados_jogador.get('ia_agressividade', 0.5) or 0.5)
        jogador.compromisso_seed = dados_jogador.get('compromisso_seed')
        jogador.nonce_seed = dados_jogador.get('nonce_seed')
        jogador.revelado_seed = bool(dados_jogador.get('revelado_seed', False))
        return jogador

    @staticmethod
    def _religar_jogador(dados_jogador, jogador, lobby):
        """Religa as referências vivas (partida/rodada/turno atuais e históricos)."""
        partida_idx = dados_jogador.get('partida_atual_idx')
        if partida_idx is not None and 0 <= partida_idx < len(lobby.partidas):
            partida = lobby.partidas[partida_idx]
            jogador.partida_atual = partida
            rodada_idx = dados_jogador.get('rodada_atual_idx')
            if rodada_idx is not None and 0 <= rodada_idx < len(partida.rodadas):
                rodada = partida.rodadas[rodada_idx]
                jogador.rodada_atual = rodada
                turno_idx = dados_jogador.get('turno_atual_idx')
                if turno_idx is not None and 0 <= turno_idx < len(rodada.turnos):
                    jogador.turno_atual = rodada.turnos[turno_idx]
        jogador.partidas = [p for p in lobby.partidas if jogador in p.jogadores]
        jogador.rodadas = []
        for partida in jogador.partidas:
            jogador.rodadas.extend(r for r in partida.rodadas if jogador in r.jogadores)

    @classmethod
    def de_dict(cls, dados):
        """
        Reconstrói a árvore completa do Lobby a partir do dicionário serializado.
        Referências são religadas por client_id / índices (ver Jogador.para_dict).
        Antes de tudo, migra o formato pela `versao` gravada (Fase 10, S3).
        """
        dados = cls._migrar(dados)
        sala_id = dados.get('sala_id', 'padrao')
        lobby = cls(sala_id=sala_id, lobby_numero=dados.get('lobby_num', 1))
        lobby.revisao = int(dados.get('revisao') or 1)
        lobby.conferiram_vencedor = dados.get('conferiram_vencedor', 0)
        lobby.pagina = dados.get('pagina', 0)
        lobby.nome = dados.get('nome') or f"Partida #{lobby.lobby_num}"
        lobby.status = dados.get('status', 'espera')
        criado_em = dados.get('criado_em')
        lobby.criado_em = datetime.fromisoformat(criado_em) if criado_em else datetime.now()
        visto_em = dados.get('visto_em')
        lobby.visto_em = datetime.fromisoformat(visto_em) if visto_em else lobby.criado_em
        lobby.config = dict(cls.config_padrao())
        lobby.config.update(dados.get('config') or {})
        lobby.seed_info = dados.get('seed_info')
        ultimo_num = max((p.get('partida_num', 0) for p in dados.get('partidas', []) or []), default=0)
        lobby.proxima_partida_num = dados.get('proxima_partida_num') or (int(ultimo_num) + 1)
        lobby.vagas_recentes = {}
        for chave, vaga in (dados.get('vagas_recentes') or {}).items():
            if not isinstance(vaga, dict) or not vaga.get('em'):
                continue
            try:
                lobby.vagas_recentes[str(chave)] = {
                    'nome': vaga.get('nome'),
                    'em': datetime.fromisoformat(vaga['em']),
                }
            except (ValueError, TypeError):
                continue

        jogadores = {}
        for dados_jogador in dados.get('jogadores', []):
            jogador = cls._jogador_de_dict(dados_jogador)
            jogador.lobby_atual = lobby
            jogadores[jogador.client_id] = jogador
        lobby.jogadores = list(jogadores.values())

        # Espectadores ficam fora do registro de jogadores (não participam das
        # partidas), mas precisam existir como Jogador para auth/snapshot.
        lobby.espectadores = []
        for dados_jogador in dados.get('espectadores', []):
            espectador = cls._jogador_de_dict(dados_jogador)
            espectador.lobby_atual = lobby
            lobby.espectadores.append(espectador)

        for dados_partida in dados.get('partidas', []):
            jogadores_partida = [jogadores[cid] for cid in dados_partida.get('jogadores_ids', [])
                                 if cid in jogadores]
            partida = Partida(do_lobby=lobby, jogadores=jogadores_partida,
                              partida_numero=dados_partida.get('partida_num', 1),
                              dados_qtd=dados_partida.get('dados_qtd', 1),
                              com_coringa=dados_partida.get('com_coringa', True),
                              seed_info=dados_partida.get('seed_info'))
            partida.seed_final = dados_partida.get('seed_final')
            partida.jogador_sorteado = jogadores.get(dados_partida.get('jogador_sorteado_id'))
            partida.vencedor_final = jogadores.get(dados_partida.get('vencedor_final_id'))
            vitoria_em = dados_partida.get('vitoria_em')
            partida.vitoria_em = datetime.fromisoformat(vitoria_em) if vitoria_em else None
            for dados_rodada in dados_partida.get('rodadas', []):
                rodada = Rodada(partida=partida, jogadores=partida.jogadores,
                                rodada_numero=dados_rodada.get('rodada_num', 1),
                                vez_atual=jogadores.get(dados_rodada.get('vez_atual_id')))
                rodada.todos_os_dados = list(dados_rodada.get('todos_os_dados') or [])
                rodada.dados_por_jogador = dados_rodada.get('dados_por_jogador') or {}
                rodada.com_coringa = bool(dados_rodada.get('com_coringa', True))
                rodada.coringa_atual_qtd = dados_rodada.get('coringa_atual_qtd', 0)
                rodada.coringa_atual_jogador = jogadores.get(dados_rodada.get('coringa_atual_jogador_id'))
                rodada.conferiram = dados_rodada.get('conferiram', 0)
                rodada.conferencia = dados_rodada.get('conferencia')
                vez_em = dados_rodada.get('vez_em')
                rodada.vez_em = datetime.fromisoformat(vez_em) if vez_em else None
                inicio_rolagem = dados_rodada.get('inicio_rolagem_em')
                rodada.inicio_rolagem_em = datetime.fromisoformat(inicio_rolagem) if inicio_rolagem else None
                conferencia_em = dados_rodada.get('conferencia_em')
                rodada.conferencia_em = datetime.fromisoformat(conferencia_em) if conferencia_em else None
                rodada.perdedor = jogadores.get(dados_rodada.get('perdedor_id'))
                rodada.vencedor = jogadores.get(dados_rodada.get('vencedor_id'))
                for dados_turno in dados_rodada.get('turnos', []):
                    turno = Turno(da_rodada=rodada, dado=dados_turno.get('dado_face', 1),
                                  jogador=jogadores.get(dados_turno.get('do_jogador_id')),
                                  dado_qtd=dados_turno.get('dado_qtd', 1),
                                  turno_numero=dados_turno.get('turno_num', 1))
                    rodada.turnos.append(turno)
                partida.rodadas.append(rodada)
            # Histórico de turnos por jogador: a rodada atual (última) é a que está em jogo.
            for jogador in partida.jogadores:
                jogador.turnos = []
            if partida.rodadas:
                for turno in partida.rodadas[-1].turnos:
                    if turno.do_jogador is not None:
                        turno.do_jogador.turnos.append(turno)
            lobby.partidas.append(partida)

        for dados_jogador, jogador in zip(dados.get('jogadores', []), lobby.jogadores):
            cls._religar_jogador(dados_jogador, jogador, lobby)
        for dados_jogador, espectador in zip(dados.get('espectadores', []), lobby.espectadores):
            cls._religar_jogador(dados_jogador, espectador, lobby)

        return lobby

    def construir_partida(self, dados_qtd, seed_info=None):
        """
        Constrói uma partida em um lobby.
        :param dados_qtd: A quantidade de dados para cada jogador nesta partida.
        :param seed_info: Dados do commit-reveal (seed.py) quando a verificação
        está ativa; None no fluxo legado.
        """
        emit('reset_partida', to=self.sala_room())  # Arruma algumas coisas da partida anterior no front-end
        partida_numero = self.proxima_partida_num
        self.proxima_partida_num += 1
        partida = Partida(do_lobby=self, jogadores=self.jogadores.copy(), partida_numero=partida_numero,
                          dados_qtd=dados_qtd, com_coringa=bool(self.config.get('com_coringa', True)),
                          seed_info=seed_info)
        # A seed já foi fixada na Partida; o estado pendente do lobby não é mais necessário.
        self.seed_info = None
        self.partidas.append(partida)
        self.status = 'jogando'
        for jogador in self.jogadores:
            jogador.partida_atual = partida
            jogador.partidas.append(partida)
            jogador.pronto = False
            emit('desativar_username_edit', to=jogador.client_id)
        return partida

    def definir_config(self, dados):
        """
        Atualiza a configuração da partida (sala de espera), com validações.
        Aceita um subconjunto das chaves; o restante permanece como estava.
        :param dados: Dicionário com as configurações a aplicar.
        :return: True se algo foi aplicado.
        """
        if not isinstance(dados, dict):
            return False
        config = dict(self.config)
        aplicado = False
        if 'nome' in dados and isinstance(dados['nome'], str):
            nome = dados['nome'].strip()[:30]
            if nome:
                self.nome = nome
                aplicado = True
        try:
            if 'dados_qtd' in dados:
                valor = int(dados['dados_qtd'])
                if 1 <= valor <= 6:
                    config['dados_qtd'] = valor
                    aplicado = True
        except (ValueError, TypeError):
            pass
        try:
            if 'max_jogadores' in dados:
                valor = int(dados['max_jogadores'])
                if 2 <= valor <= 10:
                    config['max_jogadores'] = valor
                    aplicado = True
        except (ValueError, TypeError):
            pass
        # Fase 6 (B6): só aceita bool de verdade (bool("false") é True e "falsa" a config).
        if 'com_coringa' in dados and isinstance(dados['com_coringa'], bool):
            config['com_coringa'] = dados['com_coringa']
            aplicado = True
        if 'publica' in dados and isinstance(dados['publica'], bool):
            config['publica'] = dados['publica']
            aplicado = True
        if 'substituir_desconectado_por_ia' in dados and isinstance(dados['substituir_desconectado_por_ia'], bool):
            config['substituir_desconectado_por_ia'] = dados['substituir_desconectado_por_ia']
            aplicado = True
        if 'verificacao_ativa' in dados and isinstance(dados['verificacao_ativa'], bool):
            config['verificacao_ativa'] = dados['verificacao_ativa']
            aplicado = True
        try:
            if 'ia_nivel_padrao' in dados:
                valor = int(dados['ia_nivel_padrao'])
                if 1 <= valor <= 4:
                    config['ia_nivel_padrao'] = valor
                    aplicado = True
        except (ValueError, TypeError):
            pass
        # Fase 21: tempo máximo de jogada em segundos (0 = desligado).
        try:
            if 'tempo_max_jogada' in dados:
                valor = int(dados['tempo_max_jogada'])
                if 0 <= valor <= 300:
                    config['tempo_max_jogada'] = valor
                    aplicado = True
        except (ValueError, TypeError):
            pass
        self.config = config
        return aplicado

    # ------------------------------------------------------------------
    # Verificação de integridade (provably fair) — ver seed.py
    # ------------------------------------------------------------------

    def preparar_seed(self):
        """
        Garante que o servidor já tem uma entropia comprometida ANTES de aceitar
        nonces de jogadores. A entropia é o nonce secreto do servidor (só
        revelado na auditoria), o que mantém os dados imprevisíveis mesmo com as
        revelações públicas dos nonces dos jogadores. Idempotente.
        """
        if self.seed_info is not None:
            return self.seed_info
        nonce_servidor = seed.gerar_nonce()
        self.seed_info = {
            'versao': seed.VERSAO_ATUAL,
            'fonte': 'servidor',
            'entropia_externa': nonce_servidor,
            'nonce_servidor': nonce_servidor,
            'compromisso_servidor': seed.compromisso(nonce_servidor),
            'compromissos': {},
            'seed_final': None,
        }
        return self.seed_info

    def sincronizar_compromissos(self):
        """Copia para o seed_info os compromissos de todos os jogadores (inclusive bots)."""
        if self.seed_info is None:
            return
        # Reconstrói a partir dos jogadores atuais: remove compromissos de quem saiu.
        self.seed_info['compromissos'] = {
            jogador.client_id: jogador.compromisso_seed
            for jogador in self.jogadores
            if jogador.compromisso_seed
        }

    def registrar_compromisso(self, jogador, compromisso_valor):
        """
        Fase de compromisso (provably fair): aceita apenas o hash do nonce do
        jogador, sem receber o nonce. O primeiro compromisso é imutável (impede
        o jogador de "escolher" o nonce depois). Devolve True se aceito.
        """
        if not seed.valido_nonce(compromisso_valor):
            return False
        if jogador.compromisso_seed:
            # Já comprometeu: ignora tentativas de troca.
            return False
        # Garante que a entropia do servidor foi comprometida ANTES deste nonce.
        self.preparar_seed()
        if self.seed_info is None:
            return False
        jogador.compromisso_seed = compromisso_valor
        jogador.nonce_seed = None
        jogador.revelado_seed = False
        self.seed_info.setdefault('compromissos', {})[jogador.client_id] = compromisso_valor
        return True

    def registrar_revelacao(self, jogador, nonce):
        """
        Fase de revelação: valida o nonce contra o compromisso já publicado e o
        guarda para derivar a seed. Devolve True se aceito.
        """
        if not jogador.compromisso_seed:
            return False
        if not seed.valido_nonce(nonce):
            return False
        if seed.compromisso(nonce) != jogador.compromisso_seed:
            return False
        jogador.nonce_seed = nonce
        jogador.revelado_seed = True
        return True

    def compromissos_completos(self):
        """True se todos os jogadores (inclusive bots) já publicaram o compromisso."""
        return all(jogador.compromisso_seed for jogador in self.jogadores)

    def revelacoes_pendentes(self):
        """
        True se algum humano comprometeu-se mas ainda não revelou o nonce (a
        partida não deve começar antes da revelação, senão o nonce cairia no
        fallback H(compromisso)).
        """
        return any(jogador.compromisso_seed and not jogador.revelado_seed and not jogador.is_ia
                   for jogador in self.jogadores)

    def info_publica_seed(self):
        """Payload público do estado do commit-reveal (sem revelar nonces)."""
        if self.seed_info is None:
            return None
        self.sincronizar_compromissos()
        return {
            'versao': self.seed_info.get('versao'),
            'fonte': self.seed_info.get('fonte'),
            'compromisso_servidor': self.seed_info.get('compromisso_servidor'),
            'beacon': self.seed_info.get('beacon'),
            'compromissos': dict(self.seed_info.get('compromissos') or {}),
        }

    def finalizar_seed(self):
        """
        Fixa a seed_final usando o nonce secreto do servidor como entropia e os
        nonces revelados pelos participantes (revelação pública). Devolve o dict
        de auditoria (também guardado no seed_info) ou None se a verificação off.
        """
        if not self.config.get('verificacao_ativa'):
            return None
        info = self.preparar_seed()

        info['fonte'] = 'servidor'
        info['entropia_externa'] = info['nonce_servidor']

        nonces = {}
        participantes = []
        for jogador in self.jogadores:
            compromisso_valor = jogador.compromisso_seed
            nonce = jogador.nonce_seed
            sem_reveal = False
            if nonce and compromisso_valor and seed.compromisso(nonce) == compromisso_valor:
                nonce_final = nonce
            elif compromisso_valor:
                nonce_final = seed.nonce_fallback(compromisso_valor)
                sem_reveal = True
            else:
                nonce_final = None
            if nonce_final is not None:
                nonces[jogador.client_id] = nonce_final
            participantes.append({
                'client_id': jogador.client_id,
                'nome': jogador.username,
                'compromisso': compromisso_valor,
                'nonce': nonce_final,
                'sem_reveal': sem_reveal,
            })

        info['participantes'] = participantes
        info['seed_final'] = seed.derivar_seed(info['fonte'], info['entropia_externa'], nonces)
        return info

    def contar_prontos(self):
        """Quantidade de jogadores prontos (o master conta como pronto por padrão)."""
        return sum(1 for jogador in self.jogadores if jogador.master or jogador.pronto)

    def pode_iniciar(self):
        """
        Verifica as regras da sala de espera para liberar o início da partida.
        Retorna (bool, motivo) onde motivo é None quando liberado ou um dict
        {'chave', 'params'} com a chave i18n do impedimento (o cliente traduz).
        """
        if self.status != 'espera':
            return False, {'chave': 'msg.motivo.status_andamento'}
        if len(self.jogadores) < 2:
            return False, {'chave': 'msg.motivo.min_jogadores'}
        if self.contar_jogadores(nome=True) != len(self.jogadores):
            return False, {'chave': 'msg.motivo.sem_apelido'}
        if len(self.jogadores) > int(self.config.get('max_jogadores', 6)):
            return False, {'chave': 'msg.motivo.limite'}
        for jogador in self.jogadores:
            if not jogador.master and not jogador.pronto:
                nome = jogador.username or 'Jogador'
                return False, {'chave': 'msg.motivo.nao_pronto', 'params': {'nome': nome}}
        # Verificação ativa: a partida só começa quando todos revelaram o nonce
        # (senão a seed usaria H(compromisso) para alguém e a auditoria do
        # jogador acusaria "sem revelação").
        if self.config.get('verificacao_ativa') and self.revelacoes_pendentes():
            return False, {'chave': 'msg.motivo.aguardando_revelacao'}
        return True, {'chave': 'msg.motivo.tudo_pronto'}

    def resumo_partida(self):
        """
        Resumo público da partida para a listagem/busca de partidas.
        """
        master = self.retornar_master()
        pode_iniciar, motivo = self.pode_iniciar()
        return {
            'sala': self.sala_id,
            'nome': self.nome,
            'status': self.status,
            'jogadores': len(self.jogadores),
            'humanos': self.humanos_conectados(),
            'prontos': self.contar_prontos(),
            'max_jogadores': int(self.config.get('max_jogadores', 6)),
            'dados_qtd': int(self.config.get('dados_qtd', 1)),
            'com_coringa': bool(self.config.get('com_coringa', True)),
            'publica': bool(self.config.get('publica', True)),
            'verificacao_ativa': bool(self.config.get('verificacao_ativa', False)),
            'master': master.username if master else None,
            'criada_em': self.criado_em.isoformat() if self.criado_em else None,
            'visto_em': self.visto_em.isoformat() if self.visto_em else None,
            'pode_entrar': self.status == 'espera'
                           and len(self.jogadores) < int(self.config.get('max_jogadores', 6)),
            'pode_iniciar': pode_iniciar,
            'motivo': motivo,
        }

    def resetar_para_lobby(self):
        """
        Volta todos os jogadores ao estado inicial do lobby, após o fim de uma partida.
        Mantém apelido, pontos, status de master e configurações; zera somente o estado da partida.
        """
        self.conferiram_vencedor = 0
        self.pagina = 0
        self.status = 'espera'
        # Nonces são de uso único por partida: zera os antigos (já revelados na
        # auditoria) e gera novos para os bots da próxima partida.
        self.seed_info = None
        for jogador in self.jogadores:
            self._resetar_estado_jogador(jogador)
        # Espectadores viram jogadores na próxima partida (precisam de apelido e
        # de ficar prontos como qualquer humano).
        for espectador in self.espectadores:
            self._resetar_estado_jogador(espectador)
            self.jogadores.append(espectador)
        self.espectadores = []
        # Poda o histórico: a árvore antiga (rodadas/turnos/dados) não é mais
        # usada e faria o blob persistido crescer a cada partida. Mantém só a
        # última (snapshot/auditoria imediatos) e a numeração continua pela
        # `proxima_partida_num`.
        if len(self.partidas) > 1:
            self.partidas = self.partidas[-1:]

    @staticmethod
    def _resetar_estado_jogador(jogador):
        """
        Zera o estado de partida/rodada de um jogador, preservando apelido,
        pontos e master. Bots seguem prontos; humanos recomeçam não prontos.
        """
        jogador.compromisso_seed = None
        jogador.nonce_seed = None
        jogador.revelado_seed = False
        if jogador.is_ia:
            jogador.nonce_seed = seed.gerar_nonce()
            jogador.compromisso_seed = seed.compromisso(jogador.nonce_seed)
            jogador.revelado_seed = True
        jogador.partida_atual = None
        jogador.rodada_atual = None
        jogador.turno_atual = None
        jogador.dados = []
        jogador.dados_qtd = 0
        jogador.joguei_dados = False
        jogador.confirmou_rodada = False
        jogador.confirmou_vencedor = False
        jogador.pronto = jogador.is_ia
        jogador.partidas = []
        jogador.rodadas = []
        jogador.turnos = []

    def verificar_apelido(self, nome, atual=None):
        """
        Faz umas validações de nomes.
        :param nome: Nome que vem do front-end.
        :param atual: Apelido atual do próprio jogador (exclui a si mesmo da
            checagem de unicidade — reenviar o próprio apelido não vira "_1").
        """
        nomes = [jogador.username for jogador in self.jogadores if jogador.username != atual]
        nomes += [espectador.username for espectador in self.espectadores if espectador.username != atual]
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
        Verifica se algum jogador HUMANO é master. Bots não contam: um humano
        substituído pela IA pode ter ficado com a flag `master` e, se contasse,
        bloquearia para sempre a promoção de outro humano (sala sem master).
        """
        for jogador in self.jogadores:
            if jogador.master and not jogador.is_ia:
                return True
        return False

    def definir_master(self):
        """
        Define um novo master caso precise. Bots nunca assumem o master (e um
        bot que herdou a flag de um humano substituído é limpo aqui).
        """
        if self.verificar_jogador_master():
            return
        for jogador in self.jogadores:
            if jogador.is_ia:
                jogador.master = False
        humanos = [jogador for jogador in self.jogadores if not jogador.is_ia]
        humanos.sort(key=lambda jogador: jogador.entrou)
        if humanos:
            humanos[0].master = True

    def tem_humano(self):
        """True se ainda há ao menos um humano (jogador ou espectador) na sala."""
        return (any(not j.is_ia for j in self.jogadores)
                or any(not j.is_ia for j in self.espectadores))

    def humanos_conectados(self):
        """
        Quantidade de humanos conectados: jogadores fora da janela de reconexão
        (desconectado_em) mais espectadores (que saem na hora). Bots não contam.
        """
        return (sum(1 for j in self.jogadores if not j.is_ia and j.desconectado_em is None)
                + sum(1 for e in self.espectadores if not e.is_ia))

    def tem_humano_conectado(self):
        """True se resta ao menos um humano conectado (base do GC de sala órfã)."""
        return self.humanos_conectados() > 0

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
        for espectador in self.espectadores:
            if espectador.client_id == client_id:
                return espectador
        return None

    def buscar_jogador_pela_chave(self, chave_secreta):
        """
        Procura um jogador pela chave secreta de sessão (usado para retomar
        identidade em um refresh/reconexão sem depender do sid antigo).
        :param chave_secreta: A chave do jogador (vinda de sessionStorage).
        """
        if not chave_secreta:
            return None
        for jogador in self.jogadores:
            if jogador.chave_secreta == chave_secreta:
                return jogador
        for espectador in self.espectadores:
            if espectador.chave_secreta == chave_secreta:
                return espectador
        return None

    def contar_jogadores(self, nome=False):
        if nome:
            quantidade = sum(1 for jogador in self.jogadores if jogador.username is not None)
            return quantidade
        else:
            return len(self.jogadores)

    def retornar_master(self):
        """Master humano da sala (bots nunca contam), ou False se não houver."""
        for jogador in self.jogadores:
            if jogador.master and not jogador.is_ia:
                return jogador
        return False