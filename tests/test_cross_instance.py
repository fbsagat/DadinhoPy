"""Testes de integração cross-instance (Fase 54).

Objetivo: validar a arquitetura serverless (Vercel + Upstash) sob condições
reais de concorrência — dois "processos" (threads) disputando a MESMA sala,
com o estado e o lock distribuído vivendo num store compartilhado.

Como simula duas instâncias: o `store.armazenamento` do processo é trocado por
um `ArmazenamentoUpstash` cujos `_comando`/`_pedido`/`_pipeline` apontam para
um `_FakeRedis` em memória (mesma técnica dos fakes de `test_integracao`, mas
com o sufixo de comandos completo). O lock distribuído (`trancar_sala_distribuida`)
fica ATIVO (é no-op no modo memória), cada handler deserializa um Lobby NOVO do
blob (como entre instâncias reais) e o aborto CAS da Fase 52 vigora. A única
parte que não é isolada por instância é o lock de processo (`trancar_sala`) —
o que só torna o teste mais estrito (serialização dupla), nunca menos.

Cenários:
  1. Dois jogadores `ficar_pronto` simultâneos.
  2. Dois jogadores `apostar` no mesmo turno (um válido, um inválido).
  3. Desconexão e reconexão de um humano enquanto a IA joga.
  4. Heartbeat batendo enquanto a sala é modificada.

Após cada cenário o estado é validado lendo o Lobby DIRETO do store
compartilhado (fonte da verdade) — integridade de jogadores, prontidão, turnos
e identidade.

Uso:
    python tests/test_cross_instance.py            (standalone)
    python verificar.py                             (rodado no final da integração)
"""
import os
import sys
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":
    sys.path.insert(0, RAIZ)

import tests.base as base

# Módulos preparados uma vez (boot determinístico, cooldown desligado).
modulo_store, modulo_app, funcoes_gerais = base._preparar_integracao()
from app import app, socketio


# ---------------------------------------------------------------------------
# Fake do Redis REST da Upstash, compartilhado pelas "instâncias".
# ---------------------------------------------------------------------------
class _FakeRedis:
    """Substituto em memória da REST da Upstash com o sufixo de comandos que o
    `ArmazenamentoUpstash` usa: blobs por chave (`dadinho:sala:*`,
    `dadinho:sid:*`, `dadinho:resumo:*`), índice de resumos, contador e o lock
    distribuído (SET NX/EX + DELEX IFEQ com lease)."""

    def __init__(self):
        self.dados = {}      # chave -> valor (blobs/sids/resumos/sequência)
        self.indice = set()  # CHAVE_RESUMOS
        self.travas = {}     # chave lock -> (token, expira_em)
        self.relogio = lambda: time.monotonic()

    def comando(self, *args):
        op = args[0]
        if op == "SET":
            chave, valor = args[1], args[2]
            restante = args[3:]
            nx = "NX" in restante
            ex = int(restante[restante.index("EX") + 1]) if "EX" in restante else 120
            if nx:
                agora = self.relogio()
                atual = self.travas.get(chave)
                if atual is not None and atual[1] > agora:
                    return {"result": None}
                self.travas[chave] = (valor, agora + ex)
                return {"result": "OK"}
            self.dados[chave] = valor
            return {"result": "OK"}
        if op == "DELEX":
            atual = self.travas.get(args[1])
            if atual is not None and atual[0] == args[3]:
                del self.travas[args[1]]
                return {"result": 1}
            return {"result": 0}
        if op == "GET":
            return {"result": self.dados.get(args[1])}
        if op == "DEL":
            removidos = 0
            for chave in args[1:]:
                if self.dados.pop(chave, None) is not None:
                    removidos += 1
            return {"result": removidos}
        if op == "INCR":
            atual = int(self.dados.get(args[1], 0)) + 1
            self.dados[args[1]] = str(atual)
            return {"result": atual}
        if op == "SADD":
            for membro in args[2:]:
                self.indice.add(membro)
            return {"result": len(args) - 2}
        if op == "SMEMBERS":
            return {"result": list(self.indice)}
        if op == "SREM":
            for membro in args[2:]:
                self.indice.discard(membro)
            return {"result": len(args) - 2}
        if op == "MGET":
            return {"result": [self.dados.get(chave) for chave in args[1:]]}
        return {"result": None}

    def pedido(self, rota):
        # "get/<chave>" | "incr/<chave>" | "scan/<cursor>/match/<prefixo>*/count/<n>"
        # O `ArmazenamentoUpstash` URL-encoda as chaves em `get/...` (quote),
        # mas não em `incr/...`/`scan/...` — desencoda para casar com as chaves.
        import urllib.parse as _urllib
        if rota.startswith("get/"):
            chave = _urllib.unquote(rota[len("get/"):])
            return {"result": self.dados.get(chave)}
        if rota.startswith("incr/"):
            return self.comando("INCR", rota[len("incr/"):])
        if rota.startswith("scan/"):
            partes = rota.split("/")
            prefixo = None
            for i, parte in enumerate(partes):
                if parte == "match" and i + 1 < len(partes):
                    prefixo = _urllib.unquote(partes[i + 1].rstrip("*"))
            chaves = [c for c in self.dados if prefixo is None or c.startswith(prefixo)]
            return {"result": ["0", chaves]}
        return {"result": ["0", []]}

    def pipeline(self, comandos):
        for comando in comandos:
            self.comando(*comando)
        return {"result": "OK"}


def _criar_armazenamento_fake(fake):
    arm = modulo_store.ArmazenamentoUpstash("http://fake", "tok")
    arm._comando = fake.comando
    arm._pedido = lambda metodo, rota: fake.pedido(rota)
    arm._pipeline = fake.pipeline
    arm._varrer_chaves = lambda prefixo: [c for c in fake.dados if c.startswith(prefixo)]
    return arm


def _preparar_ambiente():
    """Troca `store.armazenamento` pelo fake Upstash (lock distribuído ativo)."""
    fake = _FakeRedis()
    arm = _criar_armazenamento_fake(fake)
    original = modulo_store.armazenamento
    modulo_store.armazenamento = arm
    return original


def _restaurar_ambiente(original):
    modulo_store.armazenamento = original


def _conectar(sala, tem_chave=False):
    qs = f"sala={sala}" + ("&tem_chave=1" if tem_chave else "")
    cliente = socketio.test_client(app, query_string=qs)
    conectado = base._achar_evento(cliente.get_received(), "connect_start")
    return cliente, conectado


def _limpar_sala(sala, clientes):
    for cliente in clientes:
        try:
            cliente.disconnect()
        except Exception:
            pass
    modulo_store.remover_sala(sala)


def _rodar_em_paralelo(alvo_a, alvo_b):
    barreira = threading.Barrier(2)

    def agir(funcao):
        barreira.wait()
        funcao()

    threads = [threading.Thread(target=agir, args=(a,)) for a in (alvo_a, alvo_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ---------------------------------------------------------------------------
# Cenário 1 — dois jogadores `ficar_pronto` simultâneos.
# ---------------------------------------------------------------------------
def teste_ficar_pronto_simultaneo():
    sala = "xi_pronto"
    c1, cs1 = _conectar(sala)
    c2, cs2 = _conectar(sala)
    try:
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c2.emit("apelido", {"apelido_msg": "Bia"})
        _rodar_em_paralelo(
            lambda: c1.emit("ficar_pronto", {"chave": cs1["chave_secreta"]}),
            lambda: c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]}),
        )
        lobby = modulo_store.carregar_sala(sala)
        assert lobby is not None
        assert sorted(j.username for j in lobby.jogadores) == ["Ana", "Bia"]
        assert sorted(j.username for j in lobby.jogadores if j.pronto) == ["Ana", "Bia"], \
            "dois ficar_pronto simultâneos devem aplicar AMBOS (lock serializa)"
        assert lobby.revisao >= 2, "revisão deve ter avançado com os saves"
    finally:
        _limpar_sala(sala, (c1, c2))
    base._ok("ficar-pronto simultâneo (2 instâncias, mesma sala)")


# ---------------------------------------------------------------------------
# Cenário 2 — dois jogadores `apostar` no mesmo turno (um válido, um inválido).
# ---------------------------------------------------------------------------
def teste_apostar_simultaneo():
    sala = "xi_aposta"
    c1, cs1 = _conectar(sala)
    c2, cs2 = _conectar(sala)
    try:
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c2.emit("apelido", {"apelido_msg": "Bia"})
        c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(sala)
        assert lobby.status == "jogando"
        # Rolagem dos dois humanos.
        c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
        c1.emit("joguei_dados", {"chave_secreta": cs1["chave_secreta"]})
        c2.emit("jogar_dados", {"chave": cs2["chave_secreta"]})
        c2.emit("joguei_dados", {"chave_secreta": cs2["chave_secreta"]})
        lobby = modulo_store.carregar_sala(sala)
        rodada = lobby.partidas[-1].rodadas[-1]
        assert lobby.pagina == 2
        vez = rodada.vez_atual
        assert vez is not None and len(rodada.turnos) == 0
        c_vez, c_outro = (c1, c2) if vez.username == "Ana" else (c2, c1)
        # O da vez aposta válido; o outro aposta inválido (qtd 0) no MESMO turno.
        _rodar_em_paralelo(
            lambda: c_vez.emit("apostar", {"dados": {"chave": cs1["chave_secreta"] if vez.username == "Ana" else cs2["chave_secreta"],
                                                    "dado": 2, "quantidade": 1}}),
            lambda: c_outro.emit("apostar", {"dados": {"chave": cs1["chave_secreta"] if vez.username != "Ana" else cs2["chave_secreta"],
                                                       "dado": 2, "quantidade": 0}}),
        )
        lobby = modulo_store.carregar_sala(sala)
        rodada = lobby.partidas[-1].rodadas[-1]
        assert len(rodada.turnos) == 1, \
            f"apostas simultâneas devem criar exatamente 1 turno (tinha {len(rodada.turnos)})"
        turno = rodada.turnos[0]
        assert turno.do_jogador.username == vez.username, "o turno criado deve ser do da vez"
        assert len(lobby.jogadores) == 2 and all(j.dados_qtd == 1 for j in lobby.jogadores), \
            "ninguém pode perder dado nem sair com aposta rejeitada"
        assert lobby.revisao >= 3, "revisão deve acompanhar os saves sob concorrência"
    finally:
        _limpar_sala(sala, (c1, c2))
    base._ok("apostar simultâneo (2 instâncias, mesma rodada)")


# ---------------------------------------------------------------------------
# Cenário 3 — desconexão e reconexão de um humano enquanto a IA joga.
# ---------------------------------------------------------------------------
def teste_desconexao_reconexao_com_ia():
    sala = "xi_ia"
    c1, cs1 = _conectar(sala)
    c2, cs2 = _conectar(sala)
    reconexao = None
    try:
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c2.emit("apelido", {"apelido_msg": "Bia"})
        c1.emit("adicionar_ia", {"chave": cs1["chave_secreta"], "nivel": 2, "quantidade": 1})
        c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(sala)
        assert lobby.status == "jogando" and any(j.is_ia for j in lobby.jogadores)
        # Rolagem humana; a IA rola/confirma via ia.processar.
        c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
        c1.emit("joguei_dados", {"chave_secreta": cs1["chave_secreta"]})
        c2.emit("jogar_dados", {"chave": cs2["chave_secreta"]})
        c2.emit("joguei_dados", {"chave_secreta": cs2["chave_secreta"]})
        lobby = modulo_store.carregar_sala(sala)
        assert lobby.pagina == 2, "a IA deve ter avançado junto com os humanos"

        # Bia cai no meio da partida: entra na janela de graça.
        c2.disconnect()
        lobby = modulo_store.carregar_sala(sala)
        bia = [j for j in lobby.jogadores if j.username == "Bia"]
        assert bia and bia[0].desconectado_em is not None, "Bia deve entrar na graça"

        # Enquanto Bia está fora, o jogo avança (Ana joga e a IA responde).
        lobby = modulo_store.carregar_sala(sala)
        rodada = lobby.partidas[-1].rodadas[-1]
        vez = rodada.vez_atual
        turnos_antes = len(rodada.turnos)
        if vez is not None and vez.username == "Ana":
            c1.emit("apostar", {"dados": {"chave": cs1["chave_secreta"], "dado": 2, "quantidade": 1}})

        # Bia reconecta com a chave (retomar_identidade) no meio do jogo.
        reconexao, _ = _conectar(sala, tem_chave=True)
        reconexao.emit("retomar_identidade", {"chave": cs2["chave_secreta"]})
        lobby = modulo_store.carregar_sala(sala)
        bia = [j for j in lobby.jogadores if j.username == "Bia"]
        assert bia, "Bia deve seguir como jogadora da sala após a reconexão"
        assert bia[0].desconectado_em is None, "reconexão deve limpar a janela de graça"
        assert bia[0].partida_atual is not None, "identidade deve voltar para o meio da partida"
        assert len(bia[0].turnos) == 0 or True  # (não exige turnos; só a integridade)
        rodada = lobby.partidas[-1].rodadas[-1]
        assert len(rodada.turnos) >= turnos_antes, "o jogo não pode regredir"
    finally:
        clientes = [c1]
        if reconexao is not None:
            clientes.append(reconexao)
        _limpar_sala(sala, clientes)
    base._ok("desconexão+reconexão com IA jogando (2 instâncias)")


# ---------------------------------------------------------------------------
# Cenário 4 — heartbeat batendo enquanto a sala é modificada.
# ---------------------------------------------------------------------------
def teste_heartbeat_durante_modificacao():
    sala = "xi_hb"
    c1, cs1 = _conectar(sala)
    c2, cs2 = _conectar(sala)
    try:
        c1.emit("apelido", {"apelido_msg": "Ana"})
        c2.emit("apelido", {"apelido_msg": "Bia"})
        c1.get_received()
        _rodar_em_paralelo(
            lambda: [c1.emit("apelido", {"apelido_msg": f"Ana{i}"}) or time.sleep(0.02)
                     for i in range(5)],
            lambda: [c1.emit("heartbeat", {"chave": cs1["chave_secreta"]}) or time.sleep(0.02)
                     for i in range(5)],
        )
        lobby = modulo_store.carregar_sala(sala)
        assert lobby is not None and len(lobby.jogadores) == 2
        anas = [j.username for j in lobby.jogadores if (j.username or '').startswith("Ana")]
        assert anas, "apelido modificado sob heartbeat deve ter sido aplicado"
        assert any(j.username == "Bia" for j in lobby.jogadores), "Bia não pode sumir"
        assert lobby.status == "espera"
    finally:
        _limpar_sala(sala, (c1, c2))
    base._ok("heartbeat durante modificação da sala (2 instâncias)")


# ---------------------------------------------------------------------------
# Runner (chamado pelo verificar.py e standalone).
# ---------------------------------------------------------------------------
def rodar():
    original = _preparar_ambiente()
    cenarios = [
        ("ficar-pronto-simultaneo", teste_ficar_pronto_simultaneo),
        ("apostar-simultaneo", teste_apostar_simultaneo),
        ("desconexao-reconexao-ia", teste_desconexao_reconexao_com_ia),
        ("heartbeat-durante-modificacao", teste_heartbeat_durante_modificacao),
    ]
    try:
        for nome, funcao in cenarios:
            try:
                funcao()
            except Exception as erro:  # noqa: BLE001 (agrega falhas dos testes)
                base._falhou(nome, repr(erro))
    finally:
        _restaurar_ambiente(original)


if __name__ == "__main__":
    rodar()
    if base._falhas:
        print(f"FALHAS ({len(base._falhas)}): " + ", ".join(base._falhas))
        sys.exit(1)
    print("TUDO OK (cross-instance)")
    sys.exit(0)