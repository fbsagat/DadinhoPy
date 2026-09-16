"""Testes das otimizações de performance (Fase 60).

Assertões DETERMINÍSTICAS apenas — o CI não pode depender de timing real
(nada de "respondeu em < X ms"). Cada teste valida a MUDANÇA DE COMPORTAMENTO
otimizada: cache de resumo e LRU da IA evitam repetição, o fast path do
heartbeat não toca o lock distribuído quando nada pode mudar, o save combinado
não reescreve resumo inalterado, e a compressão gzip é transparente (compat
retroativa com blobs antigos).

Importado LAZY pelo runner DEPOIS de `_preparar_integracao()` (mesmo padrão
do `tests/test_integracao.py`).
"""
from tests.base import *  # noqa: F401,F403

import contextlib
import time as _time


def _limpar_perf():
    for sala_id in ("perf-lru", "perf-resumo-a", "perf-combo", "perf-gz", "perf-abort"):
        modulo_store.remover_sala(sala_id)


def teste_lru_ia():
    """Fase 60: `probabilidade_verdade` é cacheada (LRU) — a mesma combinação
    de (face, quantidade, suporte, desconhecidos, coringa) não recalcula o
    `math.comb` binomial a cada candidata avaliada pela IA."""
    import ia as modulo_ia
    antes = modulo_ia.probabilidade_verdade.cache_info()
    v1 = modulo_ia.probabilidade_verdade(4, 3, 2, 4, False)
    v2 = modulo_ia.probabilidade_verdade(4, 3, 2, 4, False)
    assert v1 == v2
    depois = modulo_ia.probabilidade_verdade.cache_info()
    assert depois.hits >= antes.hits + 1, \
        f"segunda chamada idêntica deve ser cache hit (hits {antes.hits}->{depois.hits})"


def teste_cache_resumo():
    """Fase 60: `carregar_resumo` serve do cache em processo (TTL curto) e o
    `remover_resumo` invalidates — leituras repetidas pela home/OG não fazem GET
    no store a cada request."""
    class _MemoriaComContador(modulo_store.ArmazenamentoMemoria):
        def __init__(self):
            super().__init__()
            self.leituras = 0

        def carregar_resumo(self, sala_id):
            self.leituras += 1
            return super().carregar_resumo(sala_id)

    original = modulo_store.armazenamento
    spy = _MemoriaComContador()
    modulo_store.armazenamento = spy
    resumo = {"sala": "perf-resumo-a", "nome": "Mesa zzz", "jogadores": 2}
    try:
        modulo_store._resumos_assinatura.pop("perf-resumo-a", None)
        modulo_store._cache_resumos.pop("perf-resumo-a", None)
        c1 = modulo_store.carregar_resumo("perf-resumo-a")
        assert c1 is None and spy.leituras == 1, "miss inicial vai ao store"
        # `carregar_resumo` NÃO cacheia None (resumo recém-nascido não pode
        # ficar invisível por 5s).
        c2 = modulo_store.carregar_resumo("perf-resumo-a")
        assert c2 is None and spy.leituras == 2, "None não pode ser cacheado"
        modulo_store.salvar_resumo("perf-resumo-a", resumo)
        c3 = modulo_store.carregar_resumo("perf-resumo-a")
        assert c3 == resumo and spy.leituras == 2, \
            "resumo salvo é servido do cache, sem novo GET"
        # TTL expirado (simulado): volta ao store.
        modulo_store._cache_resumos["perf-resumo-a"] = (resumo, _time.monotonic() - 10)
        c4 = modulo_store.carregar_resumo("perf-resumo-a")
        assert c4 == resumo and spy.leituras == 3, "TTL expirado deve revalidar"
        # Invalidates no remover.
        modulo_store.remover_resumo("perf-resumo-a")
        c5 = modulo_store.carregar_resumo("perf-resumo-a")
        assert c5 is None and spy.leituras == 4, "remover_resumo deve invalidar o cache"
    finally:
        modulo_store.armazenamento = original


def teste_salvar_sala_com_resumo_dedup():
    """Fase 60: `salvar_sala_com_resumo` grava Lobby + resumo em UMA operação e
    reusa o dedup de assinatura da `salvar_resumo` (resumo inalterado não é
    reescrito)."""
    import modelos

    class _Espiao:
        def __init__(self):
            self.chamadas = []
            self.salas = {}
            self.resumos = {}

        def salvar_sala_com_resumo(self, lobby, resumo, resumo_mudou=True):
            self.chamadas.append(resumo_mudou)
            self.salas[lobby.sala_id] = lobby
            if resumo_mudou:
                self.resumos[lobby.sala_id] = resumo

        def salvar_resumo(self, sala_id, resumo):
            self.resumos[sala_id] = resumo

        def remover_resumo(self, sala_id):
            self.resumos.pop(sala_id, None)

        def carregar_sala(self, sala_id):
            return self.salas.get(sala_id)

        def carregar_resumo(self, sala_id):
            return self.resumos.get(sala_id)

        def listar_resumos(self):
            return list(self.resumos.values())

        def listar_lobbys(self):
            return []

        def remover_sala(self, sala_id):
            self.salas.pop(sala_id, None)
            self.resumos.pop(sala_id, None)

    original = modulo_store.armazenamento
    espiao = _Espiao()
    modulo_store.armazenamento = espiao
    lobby = modelos.Lobby(sala_id="perf-combo", lobby_numero=5)
    jogador = modelos.Jogador(client_id="cli-combo")
    jogador.username = "Ana"
    jogador.pronto = True
    lobby.adicionar_jogador(jogador)
    resumo_a = {"sala": "perf-combo", "nome": "Mesa combo", "jogadores": 1}
    resumo_b = dict(resumo_a, jogadores=2)
    try:
        modulo_store._resumos_assinatura.pop("perf-combo", None)
        modulo_store._revisoes_salvas.pop("perf-combo", None)
        modulo_store._cache_resumos.pop("perf-combo", None)
        modulo_store._cache_salas.pop("perf-combo", None)
        modulo_store.salvar_sala_com_resumo(lobby, resumo_a)
        modulo_store.salvar_sala_com_resumo(lobby, resumo_a)
        modulo_store.salvar_sala_com_resumo(lobby, resumo_b)
        lobby_mod = modulo_store.carregar_sala("perf-combo")
        assert lobby_mod is not None and lobby_mod.jogadores[0].username == "Ana"
        assert espiao.chamadas == [True, False, True], \
            "resumo idêntico não pode ser reescrito; mudança sim"
        assert espiao.resumos["perf-combo"] == resumo_b
    finally:
        modulo_store.armazenamento = original


class _RedisFake:
    """Mínimo de redis-py (decode_responses=True) + pipeline para o
    ArmazenamentoRedis usar na Fase 60 (set/get/pipeline)."""

    def __init__(self):
        self._dados = {}
        self._idx_resumos = set()

    def set(self, chave, valor, ex=None):
        self._dados[chave] = valor
        return True

    def get(self, chave):
        return self._dados.get(chave)

    def pipeline(self):
        return _PipelineFake(self)

    def scan_iter(self, match=None):
        return iter(self._dados)


class _PipelineFake:
    def __init__(self, redis):
        self._redis = redis
        self._ops = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set(self, chave, valor, ex=None):
        self._ops.append(("set", chave, valor))

    def sadd(self, chave, membro):
        self._ops.append(("sadd", chave, membro))

    def execute(self):
        for op in self._ops:
            if op[0] == "set":
                self._redis._dados[op[1]] = op[2]
            elif op[0] == "sadd":
                self._redis._idx_resumos.add(op[2])
        self._ops = []
        return []


def teste_compressao_redis():
    """Fase 60: blobs do Lobby são comprimidos (gzip->base64) no Redis TCP da
    VPS quando vale a pena; blobs antigos sem o marcador continuam legíveis."""
    import json
    import modelos

    arm = modulo_store.ArmazenamentoRedis("redis://localhost:6379/0")
    arm._redis = _RedisFake()

    textoao = "abc123xyz" * 600
    comprimido = arm._comprimir(textoao)
    assert comprimido.startswith(arm.PREFIXO_COMPRESSAO), "texto grande deve comprimir"
    assert arm._descomprimir(comprimido) == textoao, "round-trip da compressão"
    assert arm._comprimir("curto") == "curto", "abaixo do limiar não comprime"
    assert arm._descomprimir("blob-antigo-cru") == "blob-antigo-cru", \
        "blob sem o marcador é compat retroativa"

    lobby = modelos.Lobby(sala_id="perf-gz", lobby_numero=9)
    for i in range(12):
        jogador = modelos.Jogador(client_id=f"gz{i}")
        jogador.username = "Jogador generico de teste " * 40
        jogador.pronto = True
        lobby.adicionar_jogador(jogador)
    arm.salvar_sala(lobby)
    chave = arm._chave_sala(lobby.sala_id)
    guardado = arm._redis._dados.get(chave)
    assert guardado is not None
    raw = json.dumps(lobby.para_dict(), ensure_ascii=False)
    if len(raw) >= arm.LIMIAR_COMPRESSAO:
        assert guardado.startswith(arm.PREFIXO_COMPRESSAO), \
            f"lobby grande deve sair comprimido (len {len(raw)})"
        assert len(guardado) < len(raw), "compressão deve reduzir o tamanho"
    recarregado = arm.carregar_sala(lobby.sala_id)
    assert recarregado is not None
    assert [j.username for j in recarregado.jogadores] == [j.username for j in lobby.jogadores]

    # Salvar Lobby + resumo num pipeline (caminho quente do heartbeat/atualizar).
    resumo = lobby.resumo_partida()
    arm.salvar_sala_com_resumo(lobby, resumo)
    assert arm._redis._dados.get(arm._chave_resumo(lobby.sala_id)) is not None, \
        "pipeline deve gravar o resumo"
    assert lobby.sala_id in arm._redis._idx_resumos, "pipeline deve indexar na busca"
    salvo = arm._redis._dados.get(arm._chave_sala(lobby.sala_id))
    assert salvo is not None and len(salvo) < len(raw), \
        "save combinado também comprime o Lobby"

    # Blob antigo (sem compressão) ainda carrega.
    legado = json.dumps(lobby.para_dict(), ensure_ascii=False)
    arm._redis._dados[chave] = legado
    rec_legado = arm.carregar_sala(lobby.sala_id)
    assert rec_legado is not None and rec_legado.jogadores[0].username == lobby.jogadores[0].username


def teste_listar_lobbys_comprime():
    """Fase 60/P1 (revisor): `listar_lobbys` do Redis TCP não pode omitir a sala
    cujo blob foi salvo comprimido — o `json.loads` cru leria o marcador `gz1:`
    e pularia a sala, quebrando o fallback `buscar_lobby_pelo_client_id` após
    restart/expiração do índice. Descomprime igual ao `carregar_sala`."""
    import modelos

    arm = modulo_store.ArmazenamentoRedis("redis://localhost:6379/0")
    arm._redis = _RedisFake()

    lobby = modelos.Lobby(sala_id="perf-listagz", lobby_numero=11)
    for i in range(12):
        jogador = modelos.Jogador(client_id=f"lgz{i}")
        jogador.username = "Jogador para listagem comprimida " * 40
        jogador.pronto = True
        lobby.adicionar_jogador(jogador)
    arm.salvar_sala(lobby)
    guardado = arm._redis._dados.get(arm._chave_sala(lobby.sala_id))
    assert guardado.startswith(arm.PREFIXO_COMPRESSAO), \
        "blob grande deve estar comprimido no fake"
    lista = arm.listar_lobbys()
    assert any(l.sala_id == lobby.sala_id for l in lista), \
        "sala comprimida tem que aparecer na listagem, não pode ser pulada"


def teste_invalida_estado_pos_aborto():
    """Fase 60/P2-P3 (revisor): `invalidar_cache_sala` (chamado pelo
    `evento_mutavel`/connect/disconnect ao abortar no meio de uma mutação) limpa
    TAMBÉM o cache do resumo (um conteúdo de mutação revertida não pode ser
    servido ao OG por 5s), a assinatura de dedup (conteúdo NUNCA gravado não
    pode ser marcado como gravado — o save seguinte igual seria ignorado) e o
    watermark de revisão do CAS (senão todo save posterior abortaria como
    ConflitoDeEstado até `remover_sala` — sala presa)."""
    import modelos

    try:
        resumo = {"sala": "perf-abort", "nome": "Mesa abort", "jogadores": 1}
        modulo_store.salvar_resumo("perf-abort", resumo)
        lobby = modelos.Lobby(sala_id="perf-abort", lobby_numero=7)
        # Estado EM PROCESSO que sobra quando uma escrita aborta no meio:
        modulo_store._cache_resumos["perf-abort"] = (resumo, _time.monotonic())
        modulo_store._resumos_assinatura["perf-abort"] = "digest-simulado"
        modulo_store._revisoes_salvas["perf-abort"] = 99
        modulo_store._armazenar_cache_sala("perf-abort", lobby)

        modulo_store.invalidar_cache_sala("perf-abort")

        assert "perf-abort" not in modulo_store._cache_salas
        assert "perf-abort" not in modulo_store._cache_resumos, \
            "resumo de mutação revertida não pode ficar no cache"
        assert "perf-abort" not in modulo_store._resumos_assinatura, \
            "conteúdo nunca gravado não pode ficar marcado como gravado"
        assert "perf-abort" not in modulo_store._revisoes_salvas, \
            "watermark de revisão abortado não pode prender saves futuros"
    finally:
        modulo_store.remover_sala("perf-abort")


def teste_lazy_import_redis():
    """Fase 60: a Vercel (Upstash/memória) nunca instancia o `ArmazenamentoRedis`
    — o `redis` (cliente TCP) é lazy no store: no boot serverless o store não
    resolve a classe real do pacote nem cria cliente/canal TCP (quem importa o
    flask_socketio pode carregar o pacote `redis` transitivamente, mas o store
    só o toca no modo VPS)."""
    codigo = (
        "import os;"
        "os.environ['DADINHO_STORE']='memoria';"
        "os.environ.pop('VERCEL', None);"
        "os.environ.pop('UPSTASH_REDIS_REST_URL', None);"
        "os.environ.pop('UPSTASH_REDIS_REST_TOKEN', None);"
        "os.environ.pop('DADINHO_REDIS_URL', None);"
        "os.environ.pop('DADINHO_MESSAGE_QUEUE', None);"
        "import store;"
        "assert type(store.armazenamento).__name__=='ArmazenamentoMemoria', type(store.armazenamento).__name__;"
        "assert store._REDIS_ERRO_LAZY is None, 'store não resolve a classe real do redis no boot';"
        "assert store.carregar_sala('nao-sai-na-rede') is None;"
        "erros = store.erros_de_rede();"
        "assert isinstance(erros, tuple) and isinstance(erros[-1], type);"
        "print('LAZY_OK')"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ,
        capture_output=True, text=True, timeout=60,
    )
    _checar("lazy import do redis (boot serverless)",
            resultado.returncode == 0 and "LAZY_OK" in resultado.stdout,
            (resultado.stderr or resultado.stdout).strip()[-500:])


def teste_heartbeat_fast_path():
    """Fase 60: o fast path do heartbeat só adquire o lock distribuído quando
    há mutação possível — espera (re-sync fresco SEM lock, ia inerte) e partida
    quieta servida do cache não tocam no lock; divergência de página escala."""
    _limpar()
    original = modulo_app.trancar_sala_distribuida
    contagem = {"locks": 0}

    @contextlib.contextmanager
    def _contando(sala_id):
        contagem["locks"] += 1
        with original(sala_id):
            yield

    modulo_app.trancar_sala_distribuida = _contando
    try:
        # (a) espera: re-sync do store SEM lock distribuído (leitura pura).
        c1, cs1, _ = _conectar()
        c1.emit("apelido", {"apelido_msg": "Ana"})
        base = contagem["locks"]
        c1.emit("heartbeat", {"chave": cs1["chave_secreta"], "pagina": 0})
        assert contagem["locks"] == base, \
            "heartbeat da espera não pode adquirir o lock distribuído"
        c1.disconnect()

        _limpar()
        clis, lobby = _conectar_trio(1)
        rodada = lobby.partidas[-1].rodadas[-1]
        vez = rodada.vez_atual.username
        ana = clis["Ana"]
        ana[0].get_received()

        # (b) partida quieta servida do cache (página e vez corretas): sem lock.
        base = contagem["locks"]
        ana[0].emit("heartbeat", {"chave": ana[1], "pagina": 2, "vez": vez})
        assert contagem["locks"] == base, \
            "partida quieta servida do cache não pode adquirir o lock distribuído"

        # (c) divergência de página: escala para o lock (mutação possível).
        ana[0].emit("heartbeat", {"chave": ana[1], "pagina": 0})
        assert contagem["locks"] == base + 1, \
            "divergência de página deve escalar para o lock distribuído"

        _desconectar_todos(clis)
    finally:
        modulo_app.trancar_sala_distribuida = original
        _limpar()


def rodar():
    """Runner chamado pelo `verificar.py` (padrão Fase 45)."""
    checks = [
        ("lru-ia", teste_lru_ia),
        ("cache-resumo", teste_cache_resumo),
        ("save-combo-dedup", teste_salvar_sala_com_resumo_dedup),
        ("compressao-redis", teste_compressao_redis),
        ("lista-lobbys-comprime", teste_listar_lobbys_comprime),
        ("invalida-estado-aborto", teste_invalida_estado_pos_aborto),
        ("lazy-import-redis", teste_lazy_import_redis),
        ("heartbeat-fast-path", teste_heartbeat_fast_path),
    ]
    try:
        for nome, func in checks:
            try:
                func()
            except Exception as erro:  # noqa: BLE001 (agrega falhas)
                _falhou(nome, repr(erro))
    finally:
        _limpar_perf()