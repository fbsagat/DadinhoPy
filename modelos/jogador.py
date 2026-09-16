"""Modelo do Jogador (Fase 45, M4)."""
from datetime import datetime
import secrets

import seed


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
        # Sinalização de automação suspeita (Fase 59): preenchido pelo
        # `anti_fraude` com um motivo em PT-BR quando a heurística detecta
        # padrão de bot; aciona um delay extra nas ações do jogador.
        self.suspeito = None
        # Personalidade do bot (Fase 20): predisposição a risco e agressividade
        # nas apostas, ambas em 0-1. Sorteadas por bot na criação; nulas para
        # humanos. Mexem na desconfiança, na altura das apostas e no ritmo.
        self.ia_risco = 0.5
        self.ia_agressividade = 0.5
        # Verificação de integridade (provably fair): o jogador publica só o
        # compromisso (hash) na sala de espera; o nonce é revelado depois, na
        # fase de revelação, e nunca fica com o servidor antes disso.
        self.compromisso_seed = None
        self.nonce_seed = None
        self.revelado_seed = False

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
        # Cada bot ganha uma personalidade própria (0-1): ousadia e agressividade
        # mudam desconfiança, altura das apostas e tempo de pensamento.
        jogador.ia_risco = round(secrets.randbelow(101) / 100, 2)
        jogador.ia_agressividade = round(secrets.randbelow(101) / 100, 2)
        jogador.pronto = True
        # Bots também contribuem com nonce (gerado pelo servidor) para a seed e
        # já vêm revelados (o servidor não precisa de fase de revelação p/ eles).
        jogador.nonce_seed = seed.gerar_nonce()
        jogador.compromisso_seed = seed.compromisso(jogador.nonce_seed)
        jogador.revelado_seed = True
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
            'ia_risco': self.ia_risco,
            'ia_agressividade': self.ia_agressividade,
            'suspeito': self.suspeito,
            'compromisso_seed': self.compromisso_seed,
            'nonce_seed': self.nonce_seed,
            'revelado_seed': self.revelado_seed,
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