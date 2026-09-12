from datetime import datetime
import secrets
from flask_socketio import emit

import narrador
import seed


def sala_room(sala_id):
    """Nome da room do Socket.IO a partir do id de uma sala (fonte única do prefixo)."""
    return f"sala_{sala_id}"


# Versão do formato serializado do Lobby (store distribuído). Sempre que a
# serialização mudar de forma incompatível, incremente e registre a migração
# correspondente em MIGRACOES (Fase 10, S3).
VERSAO_ATUAL = 3


def _migrar_v1_para_v2(dados):
    """v1 -> v2 (Fase 5): sala de espera ganha nome/status/página/config/prontidão."""
    dados.setdefault('nome', None)
    dados.setdefault('status', 'espera')
    dados.setdefault('pagina', 0)
    dados.setdefault('config', {})
    for jogador in dados.get('jogadores', []) or []:
        jogador.setdefault('pronto', False)
    return dados


def _migrar_v2_para_v3(dados):
    """v2 -> v3 (Fase 11): jogadores IA e configs de substituição/nível dos bots."""
    for jogador in dados.get('jogadores', []) or []:
        jogador.setdefault('is_ia', False)
        jogador.setdefault('ia_nivel', None)
    config = dados.setdefault('config', {})
    config.setdefault('substituir_desconectado_por_ia', False)
    config.setdefault('ia_nivel_padrao', 2)
    return dados


MIGRACOES = {
    1: _migrar_v1_para_v2,
    2: _migrar_v2_para_v3,
}


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
        # Dedup de confirmação (evita clique duplo/refresh contar 2x e travar o jogo).
        self.confirmou_rodada = False
        self.confirmou_vencedor = False
        # Sala de espera: só inicia quando todos os não-master estiverem prontos.
        self.pronto = False
        # Janela de reconexão (Fase 9): marca o momento da desconexão durante uma
        # partida; enquanto não expira, o jogador pode voltar via chave_secreta.
        self.desconectado_em = None
        # Jogador controlado por IA (Fase 11): is_ia + nível de inteligência (1-4).
        # Bots não têm socket e nunca viram master.
        self.is_ia = False
        self.ia_nivel = None
        # Verificação de integridade (provably fair): compromisso público e o
        # nonce secreto do jogador (revelado na auditoria). Bots têm o nonce
        # gerado pelo servidor; humanos geram no cliente.
        self.compromisso_seed = None
        self.nonce_seed = None

    def __repr__(self):
        return (f"(JOGADOR {self.username}, client_id={self.client_id}, "
                f"master={self.master}, pontos={self.pontos}, entrou={self.entrou})")

    @classmethod
    def criar_ia(cls, nivel, username):
        """
        Cria um jogador controlado por IA (Fase 11). Ganha um client_id próprio
        (não é um sid do Socket.IO), já entra pronto e nunca é master.
        """
        jogador = cls(client_id=f"ia:{secrets.token_hex(8)}")
        jogador.username = username
        jogador.is_ia = True
        jogador.ia_nivel = int(nivel)
        jogador.pronto = True
        # Bots também contribuem com nonce (gerado pelo servidor) para a seed.
        jogador.nonce_seed = seed.gerar_nonce()
        jogador.compromisso_seed = seed.compromisso(jogador.nonce_seed)
        return jogador

    def para_dict(self, lobby):
        """
        Serializa o jogador para ser persistido no store distribuído.
        Referências vivas (partida/rodada/turno atuais) viram índices dentro da árvore do Lobby.
        """
        partida_atual_idx = None
        rodada_atual_idx = None
        turno_atual_idx = None
        if self.partida_atual in lobby.partidas:
            partida_atual_idx = lobby.partidas.index(self.partida_atual)
            if self.rodada_atual in self.partida_atual.rodadas:
                rodada_atual_idx = self.partida_atual.rodadas.index(self.rodada_atual)
                if self.turno_atual in self.rodada_atual.turnos:
                    turno_atual_idx = self.rodada_atual.turnos.index(self.turno_atual)
        return {
            'client_id': self.client_id,
            'username': self.username,
            'master': self.master,
            'chave_secreta': self.chave_secreta,
            'pontos': self.pontos,
            'dados': self.dados,
            'dados_qtd': self.dados_qtd,
            'joguei_dados': self.joguei_dados,
            'entrou': self.entrou.isoformat() if self.entrou else None,
            'confirmou_rodada': self.confirmou_rodada,
            'confirmou_vencedor': self.confirmou_vencedor,
            'pronto': self.pronto,
            'desconectado_em': self.desconectado_em.isoformat() if self.desconectado_em else None,
            'is_ia': self.is_ia,
            'ia_nivel': self.ia_nivel,
            'compromisso_seed': self.compromisso_seed,
            'nonce_seed': self.nonce_seed,
            'partida_atual_idx': partida_atual_idx,
            'rodada_atual_idx': rodada_atual_idx,
            'turno_atual_idx': turno_atual_idx,
        }

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

    def __init__(self, sala_id, lobby_numero):
        self.sala_id = sala_id
        self.lobby_num = lobby_numero
        self.jogadores = []
        self.partidas = []
        self.conferiram_vencedor = 0
        # Página atual da sala (0=lobby, 1=rolar dados, 2=turnos, 3=conferência, 4=vitória).
        # Persistida para permitir o snapshot no reconnect/novo tab (Fase 4).
        self.pagina = 0
        # Sala de espera / matchmaking (Fase 5).
        self.nome = f"Partida #{lobby_numero}"
        self.status = "espera"  # "espera" | "jogando"
        self.criado_em = datetime.now()
        self.config = Lobby.config_padrao()
        # Estado do commit-reveal enquanto a partida ainda não começou (ver seed.py).
        # None quando a verificação está desligada ou após a seed ser fixada na Partida.
        self.seed_info = None

    @staticmethod
    def config_padrao():
        """Configuração padrão de uma partida (editável pelo master na sala de espera)."""
        return {
            'dados_qtd': 1,
            'max_jogadores': 6,
            'com_coringa': True,
            'publica': True,
            'substituir_desconectado_por_ia': False,
            'ia_nivel_padrao': 2,
            # Verificação de integridade dos dados (provably fair): opt-in do master.
            'verificacao_ativa': False,
        }

    def sala_room(self):
        """
        Nome da room no Socket.IO correspondente a esta sala.
        """
        return sala_room(self.sala_id)

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
            'seed_info': partida.seed_info,
            'seed_final': partida.seed_final,
            'rodadas': rodadas,
        }

    def para_dict(self):
        """Serializa toda a árvore do Lobby (jogadores + partidas) para o store distribuído."""
        return {
            'versao': VERSAO_ATUAL,
            'sala_id': self.sala_id,
            'lobby_num': self.lobby_num,
            'pagina': self.pagina,
            'conferiram_vencedor': self.conferiram_vencedor,
            'nome': self.nome,
            'status': self.status,
            'criado_em': self.criado_em.isoformat() if self.criado_em else None,
            'config': self.config,
            'seed_info': self.seed_info,
            'jogadores': [jogador.para_dict(self) for jogador in self.jogadores],
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
        lobby.conferiram_vencedor = dados.get('conferiram_vencedor', 0)
        lobby.pagina = dados.get('pagina', 0)
        lobby.nome = dados.get('nome') or f"Partida #{lobby.lobby_num}"
        lobby.status = dados.get('status', 'espera')
        criado_em = dados.get('criado_em')
        lobby.criado_em = datetime.fromisoformat(criado_em) if criado_em else datetime.now()
        lobby.config = dict(cls.config_padrao())
        lobby.config.update(dados.get('config') or {})
        lobby.seed_info = dados.get('seed_info')

        jogadores = {}
        for dados_jogador in dados.get('jogadores', []):
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
            jogador.compromisso_seed = dados_jogador.get('compromisso_seed')
            jogador.nonce_seed = dados_jogador.get('nonce_seed')
            jogador.lobby_atual = lobby
            jogadores[jogador.client_id] = jogador
        lobby.jogadores = list(jogadores.values())

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

        return lobby

    def construir_partida(self, dados_qtd, seed_info=None):
        """
        Constrói uma partida em um lobby.
        :param dados_qtd: A quantidade de dados para cada jogador nesta partida.
        :param seed_info: Dados do commit-reveal (seed.py) quando a verificação
        está ativa; None no fluxo legado.
        """
        emit('reset_partida', to=self.sala_room())  # Arruma algumas coisas da partida anterior no front-end
        partida_numero = len(self.partidas) + 1
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
        self.config = config
        return aplicado

    # ------------------------------------------------------------------
    # Verificação de integridade (provably fair) — ver seed.py
    # ------------------------------------------------------------------

    def preparar_seed(self):
        """
        Garante que o servidor já tem uma entropia comprometida ANTES de aceitar
        nonces de jogadores: gera o nonce do servidor e, se possível, fixa um
        round futuro do beacon drand (a entropia externa). Idempotente.
        """
        if self.seed_info is not None:
            return self.seed_info
        nonce_servidor = seed.gerar_nonce()
        info = {
            'versao': seed.VERSAO_ATUAL,
            'fonte': 'servidor',
            'entropia_externa': nonce_servidor,
            'nonce_servidor': nonce_servidor,
            'compromisso_servidor': seed.compromisso(nonce_servidor),
            'beacon': None,
            'compromissos': {},
            'seed_final': None,
        }
        plano = seed.beacon_planejar()
        if plano:
            info['fonte'] = 'beacon'
            info['beacon'] = plano
        self.seed_info = info
        return info

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

    def registrar_compromisso(self, jogador, nonce, compromisso_valor):
        """
        Valida e guarda o nonce/compromisso de um jogador. Devolve True se aceito.
        """
        if not seed.valido_nonce(nonce):
            return False
        if seed.compromisso(nonce) != compromisso_valor:
            return False
        jogador.nonce_seed = nonce
        jogador.compromisso_seed = compromisso_valor
        self.preparar_seed()
        self.seed_info.setdefault('compromissos', {})[jogador.client_id] = compromisso_valor
        return True

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
        Resolve a entropia externa (beacon, com fallback para o nonce do servidor),
        coleta os nonces dos participantes e fixa a seed_final. Devolve o dict de
        auditoria (também guardado no seed_info) ou None se a verificação está off.
        """
        if not self.config.get('verificacao_ativa'):
            return None
        info = self.preparar_seed()

        entropia = None
        if info.get('beacon'):
            beacon = info['beacon']
            entropia = seed.beacon_buscar(beacon.get('chain'), beacon.get('round'))
            if entropia:
                info['fonte'] = 'beacon'
                info['beacon'] = dict(beacon, randomness=entropia)
        if not entropia:
            info['fonte'] = 'servidor'
            info['beacon'] = None
            entropia = info['nonce_servidor']
        info['entropia_externa'] = entropia

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
        info['seed_final'] = seed.derivar_seed(info['fonte'], entropia, nonces)
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
            'prontos': self.contar_prontos(),
            'max_jogadores': int(self.config.get('max_jogadores', 6)),
            'dados_qtd': int(self.config.get('dados_qtd', 1)),
            'com_coringa': bool(self.config.get('com_coringa', True)),
            'publica': bool(self.config.get('publica', True)),
            'master': master.username if master else None,
            'criada_em': self.criado_em.isoformat() if self.criado_em else None,
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
            jogador.compromisso_seed = None
            jogador.nonce_seed = None
            if jogador.is_ia:
                jogador.nonce_seed = seed.gerar_nonce()
                jogador.compromisso_seed = seed.compromisso(jogador.nonce_seed)
            jogador.partida_atual = None
            jogador.rodada_atual = None
            jogador.turno_atual = None
            jogador.dados = []
            jogador.dados_qtd = 0
            jogador.joguei_dados = False
            jogador.confirmou_rodada = False
            jogador.confirmou_vencedor = False
            # Bots continuam prontos para a próxima partida; humanos recomeçam.
            jogador.pronto = jogador.is_ia
            jogador.partidas = []
            jogador.rodadas = []
            jogador.turnos = []

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
        Define um novo master caso precise. Bots nunca assumem o master.
        """
        if self.verificar_jogador_master():
            return
        else:
            humanos = [jogador for jogador in self.jogadores if not jogador.is_ia]
            humanos.sort(key=lambda jogador: jogador.entrou)
            if humanos:
                humanos[0].master = True

    def tem_humano(self):
        """True se ainda há ao menos um jogador humano na sala (ativo ou na janela de graça)."""
        return any(not j.is_ia for j in self.jogadores)

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
        return None

    def contar_jogadores(self, nome=False):
        if nome:
            quantidade = sum(1 for jogador in self.jogadores if jogador.username is not None)
            return quantidade
        else:
            return len(self.jogadores)

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
        else:
            self.jogador_sorteado = secrets.choice(self.jogadores)
        self.rodadas = []
        self.vencedor_final = None

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
                emit('construtor_dados', {'quantidade': jogador.dados_qtd, 'espectador': False},
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
            if perdedor is not None:
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
                if perdedor in self.jogadores:
                    return {'vez_atual': perdedor, 'rodada_numero': rodada_numero}
                return {'vez_atual': vencedor, 'rodada_numero': rodada_numero}
            # Sem registro de perdedor na rodada anterior: segue com o vencedor ou com um sorteado.
            proximo = vencedor or self.jogador_sorteado
            if len(self.jogadores) < 2:
                return {'vez_atual': proximo, 'rodada_numero': rodada_numero, 'final': True}
            return {'vez_atual': proximo, 'rodada_numero': rodada_numero}
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
        self.vencedor_final = jogador
        self.do_lobby.pagina = 4
        emit('narracao', narrador.narracao_vitoria(jogador), to=self.sala_room())
        emit('vencedor_da_partida', {'nome': jogador.username}, to=self.sala_room())
        emit('botao_vencedor_ativ', to=jogador.client_id)
        emit("mudar_pagina", {'pag_numero': 4}, to=self.sala_room())
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
        self.conferencia = {
            'nomes': nomes, 'ganhador': vencedor, 'perdedor': perdedor, 'saiu_da_partida': saiu, 'dados': dados,
            'dado_apostado_face': ultimo_turno.dado_face,
            'dado_qtd': ultimo_turno.dado_qtd,
            'quantidade_real': quantidade,
            'verdadeira': quantidade >= ultimo_turno.dado_qtd,
            'com_coringa': self.com_coringa, 'texto': txt,
        }
        self.da_partida.do_lobby.pagina = 3
        pensou = narrador.tempo_pensamento(jogador.ia_nivel) if jogador.is_ia else 0
        emit('narracao', narrador.narracao_desconfianca(jogador, ultimo_turno.do_jogador, pensou,
                                                        aposta=ultimo_turno),
             to=self.sala_room())
        emit('cards_conferencia', self.conferencia, to=self.sala_room())
        emit("mudar_pagina", {'pag_numero': 3}, to=self.sala_room())

    def atualizar_front_pro_da_vez(self, jogador_atual):
        """
        Modifica o front-end para todos os jogadores, o da vez joga, os outros observam a mensagem: aguarde a sua vez.
        Esta função não faz nenhuma validação de jogador da vez, deve ser feita em 'app.py'.
        """
        nomes = [jogador.username for jogador in self.da_partida.jogadores]
        emit('formatador_coletivo', {'jogadores_nomes': nomes, 'jogador_inicial_nome': jogador_atual.username},
             to=self.sala_room())
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

    def sala_room(self):
        """
        Nome da room no Socket.IO da sala onde o turno acontece.
        """
        return self.da_rodada.sala_room()

    def executar_turno(self):
        """Executa o turno no front end"""
        # Narração da jogada (vem antes do card para o cliente encaixar o
        # "tempo de pensamento" dos bots na fila de animação).
        pensou = narrador.tempo_pensamento(self.do_jogador.ia_nivel) if self.do_jogador.is_ia else 0
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
