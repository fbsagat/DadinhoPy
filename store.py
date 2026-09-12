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
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from modelos import Lobby


class ArmazenamentoMemoria:
    """Mantém os Lobby em memória no processo (mesmo comportamento de antes)."""

    def __init__(self):
        self._salas = {}

    def carregar_sala(self, sala_id):
        return self._salas.get(sala_id)

    def salvar_sala(self, lobby):
        self._salas[lobby.sala_id] = lobby

    def remover_sala(self, sala_id):
        self._salas.pop(sala_id, None)

    def listar_lobbys(self):
        return list(self._salas.values())

    def contar_salas(self):
        return len(self._salas)


class ArmazenamentoUpstash:
    """
    Persiste cada sala como um campo de um hash no Redis REST da Upstash.
    O estado é gravado/relido como JSON (ver Lobby.para_dict/de_dict).
    """

    CHAVE = "dadinho:salas"

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

    def carregar_sala(self, sala_id):
        resposta = self._pedido(
            "GET", f"hget/{self.CHAVE}/{urllib.parse.quote(sala_id)}"
        )
        bloco = (resposta or {}).get("result")
        if not bloco:
            return None
        return Lobby.de_dict(json.loads(bloco))

    def salvar_sala(self, lobby):
        bloco = json.dumps(lobby.para_dict(), ensure_ascii=False)
        self._pedido("POST", f"hset/{self.CHAVE}", corpo={lobby.sala_id: bloco})

    def remover_sala(self, sala_id):
        self._pedido(
            "DELETE", f"hdel/{self.CHAVE}/{urllib.parse.quote(sala_id)}"
        )

    def listar_lobbys(self):
        resposta = self._pedido("GET", f"hgetall/{self.CHAVE}")
        itens = (resposta or {}).get("result") or []
        lobbys = []
        for i in range(0, len(itens), 2):
            bloco = itens[i + 1]
            if not bloco:
                continue
            try:
                lobbys.append(Lobby.de_dict(json.loads(bloco)))
            except (ValueError, TypeError, KeyError):
                continue
        return lobbys

    def contar_salas(self):
        return len(self.listar_lobbys())


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


def contar_salas():
    return armazenamento.contar_salas()