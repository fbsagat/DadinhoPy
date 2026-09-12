# store.py
"""
Camada de armazenamento distribuído do estado das salas.

Abstrai o estado do jogo (Lobby e toda a árvore Partida/Rodada/Turno/Jogador)
atrás de uma interface comum, com duas implementações:

- ArmazenamentoMemoria: dicionário em processo (dev local / comportamento anterior);
- ArmazenamentoUpstash: Redis REST da Upstash, recomendado para a Vercel.

A implementação é escolhida na importação pelas variáveis de ambiente
UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN (se presentes) ou
DADINHO_STORE=memoria para forçar o modo local.

Layout no Redis (Fase 8): cada dado é uma chave própria com TTL (expira sozinha
se a função serverless morrer sem disparar o GC do disconnect — antes a sala
órfã ficava para sempre). Nada de hash de campo único:

- dadinho:sala:<id>      -> JSON do Lobby (TTL renovado a cada salvar_sala)
- dadinho:resumo:<id>    -> resumo leve p/ a busca de partidas (TTL)
- dadinho:sid:<client_id> -> sala_id do jogador (TTL; índice p/ achar_jogador
                             sem varrer o store)
- dadinho:lobby_seq      -> contador INCR p/ numerar lobbies novos (B8)
"""

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request

from modelos import Lobby


_travas_salas = {}
_travas_guard = threading.Lock()


def trancar_sala(sala_id):
    """
    Context manager que serializa eventos mutáveis da mesma sala dentro do processo
    (Fase 7, A4 — mitigação imediata de lost-update).

    Handlers fazem read-modify-write no Upstash sem atomicidade; dois eventos
    concorrentes da mesma sala podem sobrescrever estado entre si. Este lock garante
    exclusão mútua por sala num único processo (dev e a instância "quente" da Vercel).

    Entre instâncias serverless o risco continua — documentado em AGENTS.md; a evolução
    é check-and-set (version token) no Redis ou message queue.
    """
    with _travas_guard:
        trava = _travas_salas.setdefault(sala_id, threading.RLock())
    return trava


def esquecer_sala(sala_id):
    """
    Remove a trava de uma sala do registro do processo (chamado quando a sala esvazia
    e é removida do store), evitando acúmulo de locks de salas mortas.
    """
    with _travas_guard:
        _travas_salas.pop(sala_id, None)


class ArmazenamentoMemoria:
    """Mantém os Lobby em memória no processo (mesmo comportamento de antes)."""

    def __init__(self):
        self._salas = {}
        self._resumos = {}
        self._sids = {}
        self._contador = 0

    def carregar_sala(self, sala_id):
        return self._salas.get(sala_id)

    def salvar_sala(self, lobby):
        self._salas[lobby.sala_id] = lobby

    def remover_sala(self, sala_id):
        self._salas.pop(sala_id, None)

    def listar_lobbys(self):
        return list(self._salas.values())

    def proximo_numero(self):
        self._contador += 1
        return self._contador

    def salvar_resumo(self, sala_id, resumo):
        self._resumos[sala_id] = resumo

    def remover_resumo(self, sala_id):
        self._resumos.pop(sala_id, None)

    def listar_resumos(self):
        return list(self._resumos.values())

    def registrar_sid(self, client_id, sala_id):
        self._sids[client_id] = sala_id

    def sala_do_sid(self, client_id):
        return self._sids.get(client_id)

    def desregistrar_sid(self, client_id):
        self._sids.pop(client_id, None)


class ArmazenamentoUpstash:
    """
    Persiste o estado com chaves próprias por sala, com TTL renovado a cada gravação
    (salas órfãs expiram sozinhas). Leitura pontual via GET; varreduras só em fallback.
    """

    PREFIXO_SALA = "dadinho:sala:"
    PREFIXO_RESUMO = "dadinho:resumo:"
    PREFIXO_SID = "dadinho:sid:"
    CHAVE_SEQUENCIA = "dadinho:lobby_seq"
    # TTL (segundos): janela generosa; como é renovado a cada salvar_sala, salas
    # ativas nunca expiram — só as órfãs (instância morreu sem disconnect).
    TTL_SALA = 7 * 24 * 3600
    TTL_RESUMO = 7 * 24 * 3600
    TTL_SID = 24 * 3600

    def __init__(self, url_rest, token):
        self._base = url_rest.rstrip("/")
        self._token = token

    def _pedido(self, metodo, rota, corpo=None):
        url = f"{self._base}/{rota}"
        dados = None
        if corpo is not None:
            dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        pedido = urllib.request.Request(url, data=dados, method=metodo)
        pedido.add_header("Authorization", "Bearer " + self._token)
        if dados is not None:
            pedido.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(pedido, timeout=10) as resposta:
            texto = resposta.read().decode("utf-8")
        return json.loads(texto) if texto else None

    def _comando(self, *args):
        """
        Body-style da REST da Upstash: POST com o array JSON da linha de comando
        (recomendado para valores complexos — evita URL-encode de JSONs).
        """
        dados = json.dumps(list(args), ensure_ascii=False).encode("utf-8")
        pedido = urllib.request.Request(self._base, data=dados, method="POST")
        pedido.add_header("Authorization", "Bearer " + self._token)
        pedido.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(pedido, timeout=10) as resposta:
            texto = resposta.read().decode("utf-8")
        return json.loads(texto) if texto else None

    @classmethod
    def _chave_sala(cls, sala_id):
        return f"{cls.PREFIXO_SALA}{sala_id}"

    @classmethod
    def _chave_resumo(cls, sala_id):
        return f"{cls.PREFIXO_RESUMO}{sala_id}"

    @classmethod
    def _chave_sid(cls, client_id):
        return f"{cls.PREFIXO_SID}{client_id}"

    def carregar_sala(self, sala_id):
        resposta = self._pedido(
            "GET", f"get/{urllib.parse.quote(self._chave_sala(sala_id))}"
        )
        bloco = (resposta or {}).get("result")
        if not bloco:
            return None
        return Lobby.de_dict(json.loads(bloco))

    def salvar_sala(self, lobby):
        bloco = json.dumps(lobby.para_dict(), ensure_ascii=False)
        self._comando("SET", self._chave_sala(lobby.sala_id), bloco, "EX", self.TTL_SALA)

    def remover_sala(self, sala_id):
        self._comando("DEL", self._chave_sala(sala_id))

    def _varrer_chaves(self, prefixo):
        """
        SCAN por chaves com o prefixo informado (fallback de varredura; na prática
        a leitura pontual pelo índice de SIDs elimina a varredura por sala).
        """
        chaves = []
        cursor = "0"
        while True:
            resposta = self._pedido(
                "GET", f"scan/{cursor}/match/{prefixo}*/count/100"
            )
            resultado = (resposta or {}).get("result") or []
            if not isinstance(resultado, list) or len(resultado) < 2:
                break
            cursor = str(resultado[0])
            itens = resultado[1] or []
            chaves.extend(itens)
            if cursor == "0":
                break
        return chaves

    def listar_lobbys(self):
        lobbys = []
        for chave in self._varrer_chaves(self.PREFIXO_SALA):
            resposta = self._pedido("GET", f"get/{urllib.parse.quote(chave)}")
            bloco = (resposta or {}).get("result")
            if not bloco:
                continue
            try:
                lobbys.append(Lobby.de_dict(json.loads(bloco)))
            except (ValueError, TypeError, KeyError):
                continue
        return lobbys

    def proximo_numero(self):
        resposta = self._pedido("GET", f"incr/{self.CHAVE_SEQUENCIA}")
        return (resposta or {}).get("result") or 1

    def salvar_resumo(self, sala_id, resumo):
        bloco = json.dumps(resumo, ensure_ascii=False)
        self._comando("SET", self._chave_resumo(sala_id), bloco, "EX", self.TTL_RESUMO)

    def remover_resumo(self, sala_id):
        self._comando("DEL", self._chave_resumo(sala_id))

    def listar_resumos(self):
        resumos = []
        for chave in self._varrer_chaves(self.PREFIXO_RESUMO):
            resposta = self._pedido("GET", f"get/{urllib.parse.quote(chave)}")
            bloco = (resposta or {}).get("result")
            if not bloco:
                continue
            try:
                resumos.append(json.loads(bloco))
            except (ValueError, TypeError):
                continue
        return resumos

    def registrar_sid(self, client_id, sala_id):
        self._comando(
            "SET", self._chave_sid(client_id), sala_id, "EX", self.TTL_SID
        )

    def sala_do_sid(self, client_id):
        resposta = self._pedido(
            "GET", f"get/{urllib.parse.quote(self._chave_sid(client_id))}"
        )
        return (resposta or {}).get("result")

    def desregistrar_sid(self, client_id):
        self._comando("DEL", self._chave_sid(client_id))


def _selecionar_armazenamento():
    if os.environ.get("DADINHO_STORE", "").strip().lower() == "memoria":
        return ArmazenamentoMemoria()
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip()
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if url and token:
        return ArmazenamentoUpstash(url, token)
    return ArmazenamentoMemoria()


armazenamento = _selecionar_armazenamento()


def carregar_sala(sala_id):
    return armazenamento.carregar_sala(sala_id)


def salvar_sala(lobby):
    if lobby is not None:
        armazenamento.salvar_sala(lobby)


def remover_sala(sala_id):
    armazenamento.remover_sala(sala_id)


def listar_lobbys():
    return armazenamento.listar_lobbys()


def proximo_numero():
    return armazenamento.proximo_numero()


def salvar_resumo(sala_id, resumo):
    armazenamento.salvar_resumo(sala_id, resumo)


def remover_resumo(sala_id):
    armazenamento.remover_resumo(sala_id)


def listar_resumos():
    return armazenamento.listar_resumos()


def registrar_sid(client_id, sala_id):
    armazenamento.registrar_sid(client_id, sala_id)


def sala_do_sid(client_id):
    return armazenamento.sala_do_sid(client_id)


def desregistrar_sid(client_id):
    armazenamento.desregistrar_sid(client_id)