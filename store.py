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
- dadinho:resumos        -> SET com os ids que têm resumo (evita SCAN na busca)
- dadinho:sid:<client_id> -> sala_id do jogador (TTL; índice p/ achar_jogador
                             sem varrer o store)
- dadinho:ip:<ip>        -> SET de client_ids ativos por IP (Fase 59; usado
                             no limite de sockets por IP — SADD+EXPIRE,
                             SREM no disconnect)
- dadinho:lobby_seq      -> contador INCR p/ numerar lobbies novos (B8)
- dadinho:lock:<id>      -> token de um lock distribuído por sala (Fase 24;
                             SET NX EX no adquirir + DELEX IFEQ no liberar,
                             TTL curto de lease)
"""

import base64
import contextlib
import http.client
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
import zlib

from modelos import Lobby

# Fase 46: as falhas do redis-py (ConnectionError, TimeoutError, ResponseError)
# herdam de RedisError, não de OSError — o `evento_mutavel` do app.py aborta
# silenciosamente num blip do Redis local da VPS (mesma política da Fase B
# aplicada à REST da Upstash).
#
# Fase 60: o pacote `redis` deixou de ser importado no boot do módulo — a
# Vercel (Upstash/memória) nunca usa o Redis TCP e pagava o custo de carregar
# o pacote sem usá-lo. `erros_de_rede()` importa o pacote LAZY (só quando o
# `ArmazenamentoRedis`, modo VPS, entra em cena) e devolve a classe real de
# erro na tupla de exceções; `RedisError` abaixo é só um placeholder que nunca
# casa nada quando o pacote não chegou a carregar.
class RedisError(Exception):
    """Fallback para quando o pacote redis não está instalado (dev parcial)."""


_log = logging.getLogger(__name__)


# Fase 51: falhas de rede do store distribuído (Upstash REST ou Redis TCP da
# VPS) que as leituras NÃO devem deixar estourar o worker — um blip de rede
# num GET não pode virar 500 (ex.: rota do OG) nem traceback num handler.
# `evento_mutavel` já aborta silenciosamente nas ESCRITAS; aqui as leituras
# são convertidas em None/[] (política de aborto silencioso da Fase B).
# Fase 60: a tupla é montada LAZY (ver `erros_de_rede`) para o `redis` não ser
# importado no boot da Vercel.
_REDIS_ERRO_LAZY = None


def erros_de_rede():
    """
    Exceções de rede/latência que leituras e handlers não devem deixar estourar.
    Inclui a classe REAL de erro do redis-py só quando o pacote precisa existir
    (modo VPS — `ArmazenamentoRedis`); antes disso devolve o placeholder
    `RedisError`, que nunca casa nada (na Vercel o pacote não é usado). A
    importação lazy acontece aqui ou no `ArmazenamentoRedis.__init__` quando o
    Redis TCP é selecionado.
    """
    global _REDIS_ERRO_LAZY
    if _REDIS_ERRO_LAZY is None:
        try:
            import redis as _pacote_redis
            _REDIS_ERRO_LAZY = _pacote_redis.exceptions.RedisError
        except ImportError:  # pragma: no cover — redis é dep pinada em requirements.
            _REDIS_ERRO_LAZY = RedisError
    return (OSError, http.client.HTTPException, TimeoutError, _REDIS_ERRO_LAZY)


def _leitura_segura(funcao, fallback):
    """Executa uma leitura do store; falha de rede vira `fallback` com log."""
    try:
        return funcao()
    except erros_de_rede() as erro:
        _log.warning("Fase 51: leitura do store falhou (aborto silencioso): %r", erro)
        return fallback


_travas_salas = {}
_travas_guard = threading.Lock()


class _TravaSala:
    """
    Trava de sala com ref-count (Fase 28, H4).

    Cada `trancar_sala` devolve um objeto novo, mas todos apontam para a MESMA
    entrada em `_travas_salas` (mesmo RLock). `esquecer_sala` durante uma seção
    crítica só marca a entrada para remoção; o registro só é limpo quando o
    último holder solta a trava. Assim um request que chega enquanto a sala
    esvazia continua vendo o MESMO lock — não reconfigura a trava e não muta o
    mesmo Lobby em paralelo com quem ainda está dentro do `with`.
    """

    def __init__(self, sala_id):
        with _travas_guard:
            entrada = _travas_salas.setdefault(
                sala_id, {"trava": threading.RLock(), "em_uso": 0})
            entrada["em_uso"] += 1
            self._sala_id = sala_id
            self._entrada = entrada

    def __enter__(self):
        self._entrada["trava"].acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._entrada["trava"].release()
        with _travas_guard:
            self._entrada["em_uso"] -= 1
            if self._entrada["em_uso"] <= 0 and self._entrada.get("esquecida"):
                _travas_salas.pop(self._sala_id, None)
        return False


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
    return _TravaSala(sala_id)


def esquecer_sala(sala_id):
    """
    Remove a trava de uma sala do registro do processo (chamado quando a sala esvazia
    e é removida do store), evitando acúmulo de locks de salas mortas.

    Fase 28 (H4): se a sala ainda está dentro de uma seção crítica (em_uso > 0),
    a remoção é adiada para o último holder soltar a trava — senão o próximo
    request adquiriria um RLock NOVO e mutaria o mesmo Lobby em paralelo.
    """
    with _travas_guard:
        entrada = _travas_salas.get(sala_id)
        if entrada is None:
            return
        if entrada["em_uso"] > 0:
            entrada["esquecida"] = True
            return
        _travas_salas.pop(sala_id, None)


# ---------------------------------------------------------------------------
# Lock distribuído por sala (Fase 24).
#
# O `trancar_sala` acima é por processo; entre instâncias serverless duas
# mutações concorrentes do mesmo Lobby podem se sobrescrever no Upstash.
# Este lock fecha essa janela: SET NX EX adquire (lease) e DELEX IFEQ libera
# (só apaga se o valor ainda for o nosso token — nunca derruba a trava de
# outra instância cujo lease expirou e foi re-adquirido). No-op em memória:
# dev local e os testes de verificar.py não mudam e não pagam comandos.
# ---------------------------------------------------------------------------
PREFIXO_TRAVA = "dadinho:lock:"
TRAVA_TTL = 120          # lease: handlers são de segundos; degrade documentado se estourar.
TRAVA_TENTATIVAS = 10
TRAVA_ESPERA_BASE = 0.05


class TravaIndisponivel(Exception):
    """Lock distribuído não adquirido (contenda ou falha de rede) — aborto silencioso."""


class ConflitoDeEstado(Exception):
    """
    Save de um lobby STALE (revisão menor que a última salva na instância) —
    possível lost-update. O handler deve abortar a operação (Fase 52); o estado
    NÃO é sobrescrito (era corrupção silenciosa na Fase 40, que só logava).
    """


@contextlib.contextmanager
def trancar_sala_distribuida(sala_id):
    """
    Serializa o read-modify-write do Lobby ENTRE instâncias (a `trancar_sala`
    local só cobre o processo). Aninhado por fora da mutação e por dentro do
    lock de processo; o `with` libera em LIFO, sem inversão → sem deadlock.

    Adquirir: SET dadinho:lock:<sala_id> <token> NX EX <ttl> → {"result": "OK"}
    Liberar: DELEX dadinho:lock:<sala_id> IFEQ <token> (compare-and-del, único
    comando REST). Na memória, vira um yield puro.
    """
    if not isinstance(armazenamento, (ArmazenamentoUpstash, ArmazenamentoRedis)):
        yield
        return
    token = secrets.token_hex(8)
    chave = _chave_trava(sala_id)
    adquiriu = False
    for tentativa in range(TRAVA_TENTATIVAS):
        if tentativa:
            time.sleep(min(TRAVA_ESPERA_BASE * (2 ** (tentativa - 1)), 0.2))
        resposta = armazenamento._comando("SET", chave, token, "NX", "EX", TRAVA_TTL)
        if (resposta or {}).get("result") == "OK":
            adquiriu = True
            break
    if not adquiriu:
        raise TravaIndisponivel(sala_id)
    try:
        yield
    finally:
        # Compara-e-apaga: se o lease expirou no meio e outra instância
        # re-adquiriu, este DELEX IFEQ não derruba a trava dela.
        armazenamento._comando("DELEX", chave, "IFEQ", token)


def _chave_trava(sala_id):
    return f"{PREFIXO_TRAVA}{sala_id}"


# ---------------------------------------------------------------------------
# Cache de leitura tolerante a defasagem (Fase C).
#
# O heartbeat da sala de espera re-lê o Lobby a cada batida para re-sincronizar
# o estado entre instâncias; a cada 5s isso custa um GET + deserialização na
# Upstash por cliente (estoura o free tier de 500k comandos/mês com poucos
# jogadores ociosos). Este cache em processo (por instância, como as rooms do
# Socket.IO) serve a leitura re-sincronizada com um TTL generoso e é atualizado
# a cada `salvar_sala` e descartado a cada `remover_sala`.
#
# Só o caminho do heartbeat usa este cache (defasagem de até TTL é aceitável
# para re-sync); os handlers continuam lendo SEMPRE frescos do store (TTL 0),
# preservando o comportamento atual de consistência entre instâncias.
# ---------------------------------------------------------------------------
CACHE_SALA_TTL_RESYNC = 25.0
CACHE_SALA_TTL_PADRAO = 0.0  # 0 = cache desligado (leitura sempre fresca)
# Fase 51: teto de entradas do cache por processo — num deploy VPS (gunicorn
# persistente, Fase 46) o processo vive dias e salas distintas se acumulariam;
# acima do teto, evicta a entrada mais antiga (defasagem de 1 entrada é
# irrelevante para o re-sync — a próxima batida recarrega do store).
CACHE_SALA_MAX = 4096

# Fase 60: cache do RESUMO leve (OG dinâmico da home e eventuais listagens leem
# o mesmo resumo a cada request; ele só muda em transições de estado). TTL curto
# (5s) — uma leitura defasada em até 5s é irrelevante. Válido por instância;
# `salvar_resumo`/`remover_resumo`/`salvar_sala_com_resumo` mantêm a entrada.
CACHE_RESUMO_TTL = 5.0
CACHE_RESUMO_MAX = 2048

_cache_salas = {}
_cache_salas_guard = threading.Lock()


def _armazenar_cache_sala(sala_id, lobby):
    with _cache_salas_guard:
        if len(_cache_salas) >= CACHE_SALA_MAX:
            _cache_salas.pop(min(_cache_salas, key=lambda s: _cache_salas[s][1]), None)
        _cache_salas[sala_id] = (lobby, time.monotonic())


def invalidar_cache_sala(sala_id):
    """Descarta o estado EM PROCESSO de uma sala após uma mutação abortar no
    meio (ex.: `evento_mutavel` captura falha de rede/lock). Fase 60 (P2/P3):
    além do cache de leitura do Lobby, limpa o cache do resumo (um resumo de
    mutação revertida não pode ser servido ao OG por até 5s), a assinatura de
    dedup (conteúdo que NUNCA foi gravado não pode ser marcado como gravado —
    senão o save seguinte, igual, seria ignorado deixando o store antigo) e o
    watermark de revisão do CAS (sem isso todo save posterior da sala abortaria
    como ConflitoDeEstado até `remover_sala` — sala presa)."""
    with _cache_salas_guard:
        _cache_salas.pop(sala_id, None)
    with _cache_resumos_guard:
        _cache_resumos.pop(sala_id, None)
    with _resumos_assinatura_guard:
        _resumos_assinatura.pop(sala_id, None)
    with _revisoes_guard:
        _revisoes_salvas.pop(sala_id, None)


def carregar_sala_leve(sala_id):
    """
    Leitura re-sincronizada do heartbeat: usa o cache tolerante a defasagem.
    Devolve (lobby, veio_do_cache). Com `veio_do_cache=True` o estado pode ter
    até CACHE_SALA_TTL_RESYNC segundos — suficiente para re-sync, mas o chamador
    não deve mutar a sala (ia.processar) com base nele.
    """
    with _cache_salas_guard:
        entrada = _cache_salas.get(sala_id)
        if entrada is not None and (time.monotonic() - entrada[1]) < CACHE_SALA_TTL_RESYNC:
            return entrada[0], True
    lobby = _leitura_segura(lambda: armazenamento.carregar_sala(sala_id), None)
    if lobby is not None:
        _armazenar_cache_sala(sala_id, lobby)
    return lobby, False


# ---------------------------------------------------------------------------
# Cache do resumo da busca (Fase 60).
# ---------------------------------------------------------------------------
_cache_resumos = {}
_cache_resumos_guard = threading.Lock()


def _armazenar_cache_resumo(sala_id, resumo):
    with _cache_resumos_guard:
        if len(_cache_resumos) >= CACHE_RESUMO_MAX:
            _cache_resumos.pop(min(_cache_resumos, key=lambda s: _cache_resumos[s][1]), None)
        _cache_resumos[sala_id] = (resumo, time.monotonic())


class ArmazenamentoMemoria:
    """Mantém os Lobby em memória no processo (mesmo comportamento de antes)."""

    def __init__(self):
        self._salas = {}
        self._resumos = {}
        self._sids = {}
        self._ips = {}
        self._contador = 0
        self._contador_trava = threading.Lock()

    def carregar_sala(self, sala_id):
        return self._salas.get(sala_id)

    def salvar_sala(self, lobby):
        self._salas[lobby.sala_id] = lobby

    def remover_sala(self, sala_id):
        self._salas.pop(sala_id, None)

    def listar_lobbys(self):
        return list(self._salas.values())

    def proximo_numero(self):
        # INCR local precisa ser atômico: com async_mode 'threading' várias
        # requisições da instância quente chamam isto em paralelo (Fase 15).
        with self._contador_trava:
            self._contador += 1
            return self._contador

    def salvar_resumo(self, sala_id, resumo):
        self._resumos[sala_id] = resumo

    def salvar_sala_com_resumo(self, lobby, resumo, resumo_mudou=True):
        """Fase 60: grava Lobby + resumo numa chamada (interface comum; memória é trivial)."""
        self._salas[lobby.sala_id] = lobby
        if resumo_mudou:
            self._resumos[lobby.sala_id] = resumo

    def carregar_resumo(self, sala_id):
        return self._resumos.get(sala_id)

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

    def registrar_ip(self, ip, client_id):
        ativos = self._ips.setdefault(ip, set())
        ativos.add(client_id)
        return len(ativos)

    def remover_ip(self, ip, client_id):
        ativos = self._ips.get(ip)
        if ativos is not None:
            ativos.discard(client_id)
            if not ativos:
                self._ips.pop(ip, None)

    def sids_do_ip(self, ip):
        return list(self._ips.get(ip, set()))


# ---------------------------------------------------------------------------
# Transporte HTTPS com keep-alive para a Upstash (Fase 41, C8/C9).
#
# O `urllib.request` abre um handshake TLS do zero a cada chamada; cada evento
# mutável encadeia 2-4 chamadas (lock, leitura, gravação, unlock) — isso somava
# latência real por jogada. Este pool reutiliza conexões `http.client` (keep-
# alive) dentro da instância quente, com uma trava para ser seguro no
# `async_mode='threading'` (uma conexão por thread por vez). `_enviar` soma 1
# retry rápido com backoff para blips transitórios de rede/5xx (C9) — após
# isso, levanta OSError/HTTPException, mesma política de aborto silencioso de
# hoje (`evento_mutavel`).
# ---------------------------------------------------------------------------
_CAPACIDADE_POOL = 8
_RETRY_TENTATIVAS = 2           # 1 tentativa inicial + 1 retry rápido
_RETRY_ESPERA_BASE = 0.05


class _PoolHTTPS:
    """Pool de conexões HTTP(S) com keep-alive (uma por thread por vez)."""

    def __init__(self, host, porta, timeout=10, conexao_cls=None):
        self._host = host
        self._porta = porta
        self._timeout = timeout
        self._conexao_cls = conexao_cls or http.client.HTTPSConnection
        self._livres = []
        self._trava = threading.Lock()

    def obter(self):
        with self._trava:
            if self._livres:
                return self._livres.pop()
        return self._conexao_cls(self._host, self._porta, timeout=self._timeout)

    def devolver(self, conexao):
        with self._trava:
            if len(self._livres) < _CAPACIDADE_POOL:
                self._livres.append(conexao)
                return
        conexao.close()

    def fechar(self):
        with self._trava:
            for conexao in self._livres:
                conexao.close()
            self._livres = []


class ArmazenamentoUpstash:
    """
    Persiste o estado com chaves próprias por sala, com TTL renovado a cada gravação
    (salas órfãs expiram sozinhas). Leitura pontual via GET; varreduras só em fallback.
    """

    PREFIXO_SALA = "dadinho:sala:"
    PREFIXO_RESUMO = "dadinho:resumo:"
    PREFIXO_SID = "dadinho:sid:"
    PREFIXO_IP = "dadinho:ip:"
    CHAVE_SEQUENCIA = "dadinho:lobby_seq"
    # Índice (SET) com os ids das salas que têm resumo, para a busca não varrer
    # o keyspace com SCAN a cada listagem.
    CHAVE_RESUMOS = "dadinho:resumos"
    # TTL (segundos): janela generosa; como é renovado a cada salvar_sala, salas
    # ativas nunca expiram — só as órfãs (instância morreu sem disconnect).
    TTL_SALA = 7 * 24 * 3600
    TTL_RESUMO = 7 * 24 * 3600
    TTL_SID = 24 * 3600
    # Renovado a cada connect: o SET de um IP que parou de conectar some depois
    # de TTL_IP (evita bloquear um IP por uma instância que morreu sem disconnect).
    TTL_IP = 6 * 3600

    def __init__(self, url_rest, token):
        self._base = url_rest.rstrip("/")
        self._token = token
        partes = urllib.parse.urlsplit(self._base)
        self._caminho_base = partes.path.rstrip("/")
        conexao_cls = http.client.HTTPSConnection if partes.scheme == "https" \
            else http.client.HTTPConnection
        self._pool = _PoolHTTPS(partes.hostname,
                                partes.port or (443 if partes.scheme == "https" else 80),
                                conexao_cls=conexao_cls)

    def _enviar(self, metodo, caminho, corpo=None):
        """
        Envia uma requisição ao host da Upstash com keep-alive (pool) e 1 retry
        rápido em erro transitório (timeout, reset, 5xx). Devolve o JSON do
        corpo; em falha persistente levanta OSError/http.client.HTTPException —
        a mesma política de aborto silencioso dos handlers.
        """
        ultimo_erro = None
        for tentativa in range(_RETRY_TENTATIVAS):
            conexao = self._pool.obter()
            try:
                cabecalhos = {"Authorization": "Bearer " + self._token}
                if corpo is not None:
                    cabecalhos["Content-Type"] = "application/json"
                conexao.request(metodo, caminho, body=corpo, headers=cabecalhos)
                resposta = conexao.getresponse()
                texto = resposta.read().decode("utf-8")
                if not (200 <= resposta.status < 300):
                    ultimo_erro = OSError(f"Upstash HTTP {resposta.status}")
                else:
                    self._pool.devolver(conexao)
                    conexao = None
                    return json.loads(texto) if texto else None
            except (http.client.HTTPException, OSError) as erro:
                ultimo_erro = erro
            finally:
                if conexao is not None:
                    conexao.close()
            if ultimo_erro is not None and tentativa + 1 < _RETRY_TENTATIVAS:
                time.sleep(_RETRY_ESPERA_BASE * (2 ** tentativa))
        raise ultimo_erro

    def _pedido(self, metodo, rota, corpo=None):
        dados = None
        if corpo is not None:
            dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        caminho = f"{self._caminho_base}/{rota}"
        return self._enviar(metodo, caminho, dados)

    def _comando(self, *args):
        """
        Body-style da REST da Upstash: POST com o array JSON da linha de comando
        (recomendado para valores complexos — evita URL-encode de JSONs).
        """
        dados = json.dumps(list(args), ensure_ascii=False).encode("utf-8")
        return self._enviar("POST", self._caminho_base or "/", dados)

    def _pipeline(self, comandos):
        """
        Executa vários comandos num único request (endpoint /pipeline da Upstash):
        reduz round-trips em operações que gravam mais de uma chave (sala+resumo).
        """
        dados = json.dumps(comandos, ensure_ascii=False).encode("utf-8")
        return self._enviar("POST", f"{self._caminho_base}/pipeline", dados)

    @classmethod
    def _chave_sala(cls, sala_id):
        return f"{cls.PREFIXO_SALA}{sala_id}"

    @classmethod
    def _chave_resumo(cls, sala_id):
        return f"{cls.PREFIXO_RESUMO}{sala_id}"

    @classmethod
    def _chave_sid(cls, client_id):
        return f"{cls.PREFIXO_SID}{client_id}"

    @classmethod
    def _chave_ip(cls, ip):
        return f"{cls.PREFIXO_IP}{ip}"

    def carregar_sala(self, sala_id):
        resposta = self._pedido(
            "GET", f"get/{urllib.parse.quote(self._chave_sala(sala_id))}"
        )
        bloco = (resposta or {}).get("result")
        if not bloco:
            return None
        try:
            return Lobby.de_dict(json.loads(bloco))
        except (ValueError, TypeError, KeyError):
            # Fase 28 (H1): bloco corrompido no Upstash não pode derrubar o
            # handler com 500 — a sala é tratada como inexistente e recriada na
            # próxima escrita (fluxo do GC).
            return None

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
        # Grava o resumo e inscreve a sala no índice de busca num só request.
        self._pipeline([
            ["SET", self._chave_resumo(sala_id), bloco, "EX", self.TTL_RESUMO],
            ["SADD", self.CHAVE_RESUMOS, sala_id],
        ])

    def salvar_sala_com_resumo(self, lobby, resumo, resumo_mudou=True):
        """
        Fase 60: persistir o Lobby e o resumo da busca num único request
        (pipeline) no caminho quente do `atualizar_lista_usuarios` — a chamada
        separada fazia 2 requests (SET do Lobby + pipeline do resumo). Com o
        resumo inalterado (dedup da assinatura), cai no SET único do Lobby,
        como a `salvar_sala`.
        """
        bloco = json.dumps(lobby.para_dict(), ensure_ascii=False)
        comandos = [["SET", self._chave_sala(lobby.sala_id), bloco, "EX", self.TTL_SALA]]
        if resumo_mudou:
            rbloco = json.dumps(resumo, ensure_ascii=False)
            comandos.append(["SET", self._chave_resumo(lobby.sala_id), rbloco, "EX", self.TTL_RESUMO])
            comandos.append(["SADD", self.CHAVE_RESUMOS, lobby.sala_id])
        if len(comandos) == 1:
            self._comando(*comandos[0])
        else:
            self._pipeline(comandos)

    def remover_resumo(self, sala_id):
        self._pipeline([
            ["DEL", self._chave_resumo(sala_id)],
            ["SREM", self.CHAVE_RESUMOS, sala_id],
        ])

    def carregar_resumo(self, sala_id):
        """Resumo leve de uma sala (para o OG dinâmico da home, Fase 42/N1)."""
        resposta = self._pedido("GET", f"get/{urllib.parse.quote(self._chave_resumo(sala_id))}")
        bloco = (resposta or {}).get("result")
        if not bloco:
            return None
        try:
            return json.loads(bloco)
        except (ValueError, TypeError):
            return None

    def listar_resumos(self):
        # Caminho rápido: SMEMBERS no índice + MGET nos resumos (2 comandos),
        # em vez de SCAN + um GET por sala.
        resposta = self._comando("SMEMBERS", self.CHAVE_RESUMOS)
        ids = (resposta or {}).get("result") or []
        if not ids:
            # Índice vazio (deploy antigo): reconstrói a partir do keyspace.
            ids = [chave[len(self.PREFIXO_RESUMO):] for chave in self._varrer_chaves(self.PREFIXO_RESUMO)]
            for lote in self._lotes(ids, 100):
                self._comando("SADD", self.CHAVE_RESUMOS, *lote)
            if not ids:
                return []

        resumos = []
        mortos = []
        for lote in self._lotes(ids, 100):
            resposta = self._comando("MGET", *[self._chave_resumo(i) for i in lote])
            valores = (resposta or {}).get("result") or []
            for sala_id, bloco in zip(lote, valores):
                if not bloco:
                    mortos.append(sala_id)
                    continue
                try:
                    resumos.append(json.loads(bloco))
                except (ValueError, TypeError):
                    continue
        if mortos:
            # Resumos expirados (TTL) saem do índice na próxima listagem.
            self._comando("SREM", self.CHAVE_RESUMOS, *mortos)
        return resumos

    @staticmethod
    def _lotes(lista, tamanho):
        for inicio in range(0, len(lista), tamanho):
            yield lista[inicio:inicio + tamanho]

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

    def registrar_ip(self, ip, client_id):
        chave = self._chave_ip(ip)
        self._pipeline([
            ["SADD", chave, client_id],
            ["EXPIRE", chave, self.TTL_IP],
        ])
        resposta = self._comando("SCARD", chave)
        return (resposta or {}).get("result")

    def remover_ip(self, ip, client_id):
        self._comando("SREM", self._chave_ip(ip), client_id)

    def sids_do_ip(self, ip):
        resposta = self._comando("SMEMBERS", self._chave_ip(ip))
        return list((resposta or {}).get("result") or [])


class ArmazenamentoRedis:
    """
    Persiste o estado num Redis TCP local (deploy na VPS, Fase 46). Mesma
    interface e mesmo layout de chaves do `ArmazenamentoUpstash`, mas falando
    com um Redis acessível por TCP (`DADINHO_REDIS_URL`, ex. `redis://redis:6379/0`)
    via redis-py — sem depender da REST da Upstash.

    Usa TTL idêntico aos do Upstash (sala/resumo 7 dias, sid 1 dia) e, como o
    host Redis também é usado como message queue (`DADINHO_MESSAGE_QUEUE`
    apontando para a mesma URL), o lock distribuído (`trancar_sala_distribuida`)
    funciona nativamente: SET NX/EX adquire e um script Lua DELEX-IFEQ libera
    com compare-and-del atômico.
    """

    PREFIXO_SALA = "dadinho:sala:"
    PREFIXO_RESUMO = "dadinho:resumo:"
    PREFIXO_SID = "dadinho:sid:"
    PREFIXO_IP = "dadinho:ip:"
    CHAVE_SEQUENCIA = "dadinho:lobby_seq"
    CHAVE_RESUMOS = "dadinho:resumos"
    TTL_SALA = 7 * 24 * 3600
    TTL_RESUMO = 7 * 24 * 3600
    TTL_SID = 24 * 3600
    TTL_IP = 6 * 3600

    # Fase 60: compressão dos blobs do Lobby no Redis TCP da VPS. O JSON de uma
    # partida longa passa de 100KB; `zlib` (nível 6) + base64 reduz banda e tempo
    # de serialização. Textos abaixo do limiar e blobs que não encolhem seguem
    # sem compressão — e blobs ANTIGOS (sem o marcador) continuam legíveis.
    PREFIXO_COMPRESSAO = "gz1:"
    LIMIAR_COMPRESSAO = 512

    _LUA_DELEX = (
        "if redis.call('GET', KEYS[1]) == ARGV[1] then "
        "return redis.call('DEL', KEYS[1]) else return 0 end"
    )

    def __init__(self, url):
        import redis as pacote_redis
        # Timeouts curtos (Fase 46): um Redis que aceita TCP mas não responde
        # não pode segurar uma thread do gunicorn/request para sempre — falha
        # rápido e vira `redis.exceptions.RedisError`, aborto silencioso
        # (mesma política da Fase B aplicada ao Upstash).
        self._redis = pacote_redis.Redis.from_url(
            url, decode_responses=True,
            socket_timeout=5, socket_connect_timeout=5, retry_on_timeout=False)
        self._script_delex = self._redis.register_script(self._LUA_DELEX)

    @classmethod
    def _chave_sala(cls, sala_id):
        return f"{cls.PREFIXO_SALA}{sala_id}"

    @classmethod
    def _chave_resumo(cls, sala_id):
        return f"{cls.PREFIXO_RESUMO}{sala_id}"

    @classmethod
    def _chave_sid(cls, client_id):
        return f"{cls.PREFIXO_SID}{client_id}"

    @classmethod
    def _chave_ip(cls, ip):
        return f"{cls.PREFIXO_IP}{ip}"

    @classmethod
    def _comprimir(cls, texto):
        """
        Comprime um blob do Lobby (gzip→base64) se valer a pena; devolve o
        texto original caso contrário (pequeno ou que não encolheu). Base64 por
        causa do `decode_responses=True` do cliente — o Redis é configurado para
        devolver strings.
        """
        if not isinstance(texto, str) or len(texto) < cls.LIMIAR_COMPRESSAO:
            return texto
        comprimido = zlib.compress(texto.encode("utf-8"), 6)
        if len(comprimido) >= len(texto):
            return texto
        return cls.PREFIXO_COMPRESSAO + base64.b64encode(comprimido).decode("ascii")

    @classmethod
    def _descomprimir(cls, bloco):
        """
        Devolve o texto original (descomprimindo blobs novos); blobs antigos sem
        o marcador passam intactos — compat retroativa. Corrompido cai no texto
        cru para o `json.loads` de quem chamou tratar como blob inválido.
        """
        if not isinstance(bloco, str) or not bloco.startswith(cls.PREFIXO_COMPRESSAO):
            return bloco
        try:
            return zlib.decompress(
                base64.b64decode(bloco[len(cls.PREFIXO_COMPRESSAO):])
            ).decode("utf-8")
        except (zlib.error, ValueError, TypeError):
            return bloco

    def carregar_sala(self, sala_id):
        bloco = self._redis.get(self._chave_sala(sala_id))
        if not bloco:
            return None
        try:
            return Lobby.de_dict(json.loads(self._descomprimir(bloco)))
        except (ValueError, TypeError, KeyError):
            # Mesma política da Fase 28 (H1): bloco corrompido não derruba o
            # handler — a sala é tratada como inexistente e recriada no GC.
            return None

    def salvar_sala(self, lobby):
        bloco = json.dumps(lobby.para_dict(), ensure_ascii=False)
        self._redis.set(self._chave_sala(lobby.sala_id),
                        self._comprimir(bloco), ex=self.TTL_SALA)

    def salvar_sala_com_resumo(self, lobby, resumo, resumo_mudou=True):
        """
        Fase 60: Lobby (comprimido) + resumo da busca num único pipeline —
        `atualizar_lista_usuarios` fazia 1 SET + 1 pipeline (resumo) separados.
        Com o resumo inalterado (dedup), grava só o Lobby.
        """
        bloco = json.dumps(lobby.para_dict(), ensure_ascii=False)
        with self._redis.pipeline() as pipe:
            pipe.set(self._chave_sala(lobby.sala_id),
                     self._comprimir(bloco), ex=self.TTL_SALA)
            if resumo_mudou:
                rbloco = json.dumps(resumo, ensure_ascii=False)
                pipe.set(self._chave_resumo(lobby.sala_id), rbloco, ex=self.TTL_RESUMO)
                pipe.sadd(self.CHAVE_RESUMOS, lobby.sala_id)
            pipe.execute()

    def remover_sala(self, sala_id):
        self._redis.delete(self._chave_sala(sala_id))

    def listar_lobbys(self):
        lobbys = []
        for chave in self._redis.scan_iter(match=f"{self.PREFIXO_SALA}*"):
            bloco = self._redis.get(chave)
            if not bloco:
                continue
            try:
                # Fase 60: blob pode estar comprimido (`_comprimir`) — descomprime
                # como no `carregar_sala`, senão o fallback de busca por client_id
                # (`buscar_lobby_pelo_client_id`) perderia a sala silenciosamente.
                lobbys.append(Lobby.de_dict(json.loads(self._descomprimir(bloco))))
            except (ValueError, TypeError, KeyError):
                continue
        return lobbys

    def proximo_numero(self):
        return self._redis.incr(self.CHAVE_SEQUENCIA)

    def salvar_resumo(self, sala_id, resumo):
        bloco = json.dumps(resumo, ensure_ascii=False)
        # Grava o resumo e inscreve a sala no índice num único pipeline.
        with self._redis.pipeline() as pipe:
            pipe.set(self._chave_resumo(sala_id), bloco, ex=self.TTL_RESUMO)
            pipe.sadd(self.CHAVE_RESUMOS, sala_id)
            pipe.execute()

    def remover_resumo(self, sala_id):
        with self._redis.pipeline() as pipe:
            pipe.delete(self._chave_resumo(sala_id))
            pipe.srem(self.CHAVE_RESUMOS, sala_id)
            pipe.execute()

    def carregar_resumo(self, sala_id):
        bloco = self._redis.get(self._chave_resumo(sala_id))
        if not bloco:
            return None
        try:
            return json.loads(bloco)
        except (ValueError, TypeError):
            return None

    def listar_resumos(self):
        # Caminho rápido: SMEMBERS no índice + MGET nos resumos; fallback de
        # varredura (scan_iter) quando o índice está vazio (deploy antigo).
        ids = list(self._redis.smembers(self.CHAVE_RESUMOS))
        if not ids:
            ids = [c[len(self.PREFIXO_RESUMO):]
                   for c in self._redis.scan_iter(match=f"{self.PREFIXO_RESUMO}*")]
            for lote in self._lotes(ids, 100):
                self._redis.sadd(self.CHAVE_RESUMOS, *lote)
            if not ids:
                return []
        resumos = []
        mortos = []
        for lote in self._lotes(ids, 100):
            valores = self._redis.mget(*[self._chave_resumo(i) for i in lote])
            for sala_id, bloco in zip(lote, valores):
                if not bloco:
                    mortos.append(sala_id)
                    continue
                try:
                    resumos.append(json.loads(bloco))
                except (ValueError, TypeError):
                    continue
        if mortos:
            # Resumos expirados (TTL) saem do índice na próxima listagem.
            self._redis.srem(self.CHAVE_RESUMOS, *mortos)
        return resumos

    @staticmethod
    def _lotes(lista, tamanho):
        for inicio in range(0, len(lista), tamanho):
            yield lista[inicio:inicio + tamanho]

    def registrar_sid(self, client_id, sala_id):
        self._redis.set(self._chave_sid(client_id), sala_id, ex=self.TTL_SID)

    def sala_do_sid(self, client_id):
        return self._redis.get(self._chave_sid(client_id))

    def desregistrar_sid(self, client_id):
        self._redis.delete(self._chave_sid(client_id))

    def registrar_ip(self, ip, client_id):
        chave = self._chave_ip(ip)
        with self._redis.pipeline() as pipe:
            pipe.sadd(chave, client_id)
            pipe.expire(chave, self.TTL_IP)
            pipe.execute()
        return self._redis.scard(chave)

    def remover_ip(self, ip, client_id):
        self._redis.srem(self._chave_ip(ip), client_id)

    def sids_do_ip(self, ip):
        return list(self._redis.smembers(self._chave_ip(ip)))

    def _comando(self, *args):
        """
        Tradutor de comandos no formato usado pelo lock distribuído
        (`trancar_sala_distribuida`): SET NX/EX adquire, DELEX IFEQ libera com
        compare-and-del atômico (script Lua). Devolve `{"result": ...}` no mesmo
        formato da REST da Upstash, para o contexto do lock não mudar.
        """
        op = args[0]
        if op == "SET":
            chave, valor = args[1], args[2]
            restantes = args[3:]
            nx = "NX" in restantes
            ex = None
            if "EX" in restantes:
                ex = int(restantes[restantes.index("EX") + 1])
            ok = self._redis.set(chave, valor, nx=nx, ex=ex)
            return {"result": "OK" if ok else None}
        if op == "DELEX":
            chave, token = args[1], args[3]
            removido = self._script_delex(keys=[chave], args=[token])
            return {"result": removido}
        if op == "GET":
            return {"result": self._redis.get(args[1])}
        if op == "DEL":
            return {"result": self._redis.delete(*args[1:])}
        if op == "INCR":
            return {"result": self._redis.incr(args[1])}
        if op == "SADD":
            return {"result": self._redis.sadd(args[1], *args[2:])}
        if op == "SMEMBERS":
            return {"result": list(self._redis.smembers(args[1]))}
        if op == "SREM":
            return {"result": self._redis.srem(args[1], *args[2:])}
        if op == "SCARD":
            return {"result": self._redis.scard(args[1])}
        if op == "EXPIRE":
            return {"result": self._redis.expire(args[1], int(args[2]))}
        if op == "MGET":
            return {"result": list(self._redis.mget(args[1:]))}
        return {"result": None}

    def _pipeline(self, comandos):
        """Executa uma sequência de comandos (formato `_comando`) num pipeline."""
        resultados = []
        with self._redis.pipeline() as pipe:
            for comando in comandos:
                op = comando[0]
                if op == "SET":
                    restantes = comando[3:]
                    pipe.set(comando[1], comando[2], nx="NX" in restantes,
                             ex=int(restantes[restantes.index("EX") + 1]) if "EX" in restantes else None)
                elif op == "DEL":
                    pipe.delete(*comando[1:])
                elif op == "SADD":
                    pipe.sadd(comando[1], *comando[2:])
                elif op == "SREM":
                    pipe.srem(comando[1], *comando[2:])
                else:
                    resultados.append(self._comando(*comando).get("result"))
                    continue
                resultados.append(None)
            pipe.execute()
        return {"result": resultados}


def _selecionar_armazenamento():
    if os.environ.get("DADINHO_STORE", "").strip().lower() == "memoria":
        return ArmazenamentoMemoria()
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip()
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if url and token:
        return ArmazenamentoUpstash(url, token)
    url_redis = os.environ.get("DADINHO_REDIS_URL", "").strip()
    if url_redis:
        return ArmazenamentoRedis(url_redis)
    # Fase 27 (I2): sem o store configurado, o app caía em ArmazenamentoMemoria()
    # sem nenhum sinal — em serverless cada cold start vira um store vazio e todo
    # o estado some sem aviso. Em produção o fallback é proibido: falha no boot.
    if os.environ.get("VERCEL") == "1":
        raise RuntimeError(
            "Store não configurado em produção: defina UPSTASH_REDIS_REST_URL e "
            "UPSTASH_REDIS_REST_TOKEN (ou DADINHO_STORE=memoria apenas em dev). "
            "DADINHO_REDIS_URL (Redis TCP) é só para o deploy na VPS — um Redis "
            "local não é alcançável do runtime serverless da Vercel. "
            "Sem isso a Vercel rodaria em memória e todo o estado sumiria no cold start."
        )
    return ArmazenamentoMemoria()


armazenamento = _selecionar_armazenamento()


def carregar_sala(sala_id):
    return _leitura_segura(lambda: armazenamento.carregar_sala(sala_id), None)


# Detector CAS de lost-update (Fase 40, alerta — NÃO substitui o lock
# distribuído). Em processo, por instância: registra a última revisão salva de
# cada sala; se um save chega com o lobby numa revisão menor que a já salva,
# é sinal de que outro handler salvou depois que este lobby foi carregado
# (concorrência que o lock deveria ter evitado — loga para calibrar o
# `TRAVA_TTL` ou achar um caminho que esqueceu o lock). Cross-instance fica
# sob responsabilidade do próprio lock.
_revisoes_salvas = {}
_revisoes_guard = threading.Lock()


def salvar_sala(lobby):
    if lobby is None:
        return
    with _revisoes_guard:
        anterior = _revisoes_salvas.get(lobby.sala_id, 0)
        if anterior and lobby.revisao < anterior:
            _log.warning(
                "Fase 52 (CAS): sala %s salva com revisão %s (última salva: %s) "
                "— possível lost-update; save ABORTADO (lock distribuído deveria "
                "ter evitado)",
                lobby.sala_id, lobby.revisao, anterior)
            raise ConflitoDeEstado(lobby.sala_id)
        lobby.revisao = max(lobby.revisao, anterior) + 1
        _revisoes_salvas[lobby.sala_id] = lobby.revisao
    armazenamento.salvar_sala(lobby)
    # Mantém o cache de re-sync do heartbeat com o objeto recém-persistido.
    _armazenar_cache_sala(lobby.sala_id, lobby)


def remover_sala(sala_id):
    with _cache_salas_guard:
        _cache_salas.pop(sala_id, None)
    with _revisoes_guard:
        _revisoes_salvas.pop(sala_id, None)
    armazenamento.remover_sala(sala_id)


def listar_lobbys():
    return _leitura_segura(armazenamento.listar_lobbys, [])


def proximo_numero():
    return armazenamento.proximo_numero()


_resumos_assinatura = {}
_resumos_assinatura_guard = threading.Lock()


def salvar_resumo(sala_id, resumo):
    """
    Evita reescrever o resumo da busca quando o conteúdo não mudou: muitos
    eventos chamam `atualizar_lista_usuarios` sem alterar os campos relevantes
    (ex.: revelação de seed, reconexões), e cada gravação custa comandos na
    Upstash. O cache é por instância; entre instâncias a próxima divergência
    corrige. Fase 60: mantém o cache de leitura do resumo em dia.
    """
    assinatura = json.dumps(resumo, ensure_ascii=False, sort_keys=True)
    with _resumos_assinatura_guard:
        if _resumos_assinatura.get(sala_id) == assinatura:
            return
        _resumos_assinatura[sala_id] = assinatura
    _armazenar_cache_resumo(sala_id, resumo)
    armazenamento.salvar_resumo(sala_id, resumo)


def remover_resumo(sala_id):
    with _resumos_assinatura_guard:
        _resumos_assinatura.pop(sala_id, None)
    with _cache_resumos_guard:
        _cache_resumos.pop(sala_id, None)
    armazenamento.remover_resumo(sala_id)


def listar_resumos():
    return _leitura_segura(armazenamento.listar_resumos, [])


def carregar_resumo(sala_id):
    """
    Resumo leve de uma sala (OG dinâmico da home/listagem). Fase 60: cache em
    processo com TTL curto — leituras repetidas no mesmo instante não fazem GET
    no Redis (o resumo só muda em transições de estado). Não-cache não guarda
    `None`: um resumo que acaba de nascer não pode ficar invisível por 5s.
    """
    with _cache_resumos_guard:
        entrada = _cache_resumos.get(sala_id)
        if entrada is not None and (time.monotonic() - entrada[1]) < CACHE_RESUMO_TTL:
            return entrada[0]
    resumo = _leitura_segura(lambda: armazenamento.carregar_resumo(sala_id), None)
    if resumo is not None:
        _armazenar_cache_resumo(sala_id, resumo)
    return resumo


def salvar_sala_com_resumo(lobby, resumo):
    """
    Fase 60: persiste o Lobby e o resumo da busca numa SÓ operação no store
    (pipeline com SET sala + SET resumo + SADD índice) — o caminho quente do
    `atualizar_lista_usuarios` fazia 2-3 requests em sequência. Mantém as mesmas
    garantias: CAS/revisão da `salvar_sala` (possível lost-update aborta) +
    dedup de assinatura da `salvar_resumo` (com o resumo inalterado, grava só o
    Lobby). Atualiza ambos os caches como as chamadas separadas fariam.
    """
    if lobby is None:
        return
    assinatura = json.dumps(resumo, ensure_ascii=False, sort_keys=True)
    with _resumos_assinatura_guard:
        if _resumos_assinatura.get(lobby.sala_id) == assinatura:
            resumo_mudou = False
        else:
            _resumos_assinatura[lobby.sala_id] = assinatura
            resumo_mudou = True
    with _revisoes_guard:
        anterior = _revisoes_salvas.get(lobby.sala_id, 0)
        if anterior and lobby.revisao < anterior:
            _log.warning(
                "Fase 52 (CAS): sala %s salva com revisão %s (última salva: %s) "
                "— possível lost-update; save ABORTADO (lock distribuído deveria "
                "ter evitado)",
                lobby.sala_id, lobby.revisao, anterior)
            raise ConflitoDeEstado(lobby.sala_id)
        lobby.revisao = max(lobby.revisao, anterior) + 1
        _revisoes_salvas[lobby.sala_id] = lobby.revisao
    armazenamento.salvar_sala_com_resumo(lobby, resumo, resumo_mudou)
    _armazenar_cache_sala(lobby.sala_id, lobby)
    if resumo_mudou:
        _armazenar_cache_resumo(lobby.sala_id, resumo)


def registrar_sid(client_id, sala_id):
    armazenamento.registrar_sid(client_id, sala_id)


def sala_do_sid(client_id):
    return _leitura_segura(lambda: armazenamento.sala_do_sid(client_id), None)


def desregistrar_sid(client_id):
    armazenamento.desregistrar_sid(client_id)


def registrar_ip(ip, client_id):
    """Adiciona client_id ao SET de IPs e devolve a cardinalidade (Fase 59)."""
    return armazenamento.registrar_ip(ip, client_id)


def remover_ip(ip, client_id):
    """Remove client_id do SET de IPs (Fase 59, disconnect)."""
    armazenamento.remover_ip(ip, client_id)


def sids_do_ip(ip):
    """Devolve os client_ids ativos de um IP (Fase 59)."""
    return _leitura_segura(lambda: armazenamento.sids_do_ip(ip), [])