"""Runner da verificação do Dadinho (Fase 45, M5).

A infra (helpers/globals/constantes) vive em `tests/base.py`; os testes de
integração em `tests/test_integracao.py`; este arquivo só orquestra:
  py_compile -> node --check -> boot VERCEL=1 -> round-trip -> integração.
"""
from tests.base import *  # noqa: F401,F403


def verificar_py_compile():
    print("1) py_compile")
    for rel in MODULOS:
        caminho = os.path.join(RAIZ, rel)
        try:
            py_compile.compile(caminho, doraise=True)
        except py_compile.PyCompileError as erro:
            _falhou(rel, str(erro))
        else:
            _ok(rel)


# ---------------------------------------------------------------------------
# 2) node --check
# ---------------------------------------------------------------------------
_CODIGO_I18N = r"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync(process.argv[1], 'utf8') + '\nglobalThis.__D = I18N_DICIONARIOS;';
const stub = { querySelectorAll() { return []; }, getElementById() { return null; } };
const sandbox = {
  document: Object.assign({ readyState: 'complete', addEventListener() {}, documentElement: {} }, stub),
  navigator: { language: 'en' },
  localStorage: { getItem() { return null; }, setItem() {} },
  window: {},
  console,
};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const d = sandbox.__D;
const en = Object.keys(d.en);
let faltando = 0;
for (const lang of Object.keys(d)) {
  if (lang === 'en') continue;
  const ausentes = en.filter((k) => !(k in d[lang]));
  if (ausentes.length) {
    faltando += ausentes.length;
    console.error(lang + ' faltando: ' + ausentes.join(', '));
  }
}
if (faltando) process.exit(1);
console.log('idiomas=' + Object.keys(d).length + ' chaves=' + en.length);
"""


def verificar_node():
    print("2) node --check static/*.js + cobertura i18n")
    node = shutil.which("node")
    if node is None:
        print("  [PULADO] Node não está no PATH")
        return
    for arquivo in ("script.js", "i18n.js"):
        resultado = subprocess.run(
            [node, "--check", os.path.join(RAIZ, "static", arquivo)],
            capture_output=True, text=True,
        )
        _checar("static/" + arquivo, resultado.returncode == 0, resultado.stderr.strip())
    resultado = subprocess.run(
        [node, "-e", _CODIGO_I18N, os.path.join(RAIZ, "static", "i18n.js")],
        capture_output=True, text=True,
    )
    _checar("cobertura i18n", resultado.returncode == 0,
            (resultado.stderr or resultado.stdout).strip())


# ---------------------------------------------------------------------------
# 3) boot VERCEL=1
# ---------------------------------------------------------------------------
_CODIGO_BOOT = (
    "import os;"
    "os.environ['VERCEL']='1';"
    "os.environ['DADINHO_STORE']='memoria';"
    "from app import app;"
    "r=app.test_client().get('/');"
    "assert r.status_code==200, r.status_code;"
    "rob=app.test_client().get('/robots.txt');"
    "assert rob.status_code==200 and 'Sitemap:' in rob.get_data(as_text=True), rob.status_code;"
    "mapa=app.test_client().get('/sitemap.xml');"
    "assert mapa.status_code==200 and '<urlset' in mapa.get_data(as_text=True), mapa.status_code;"
    "s=app.test_client().get('/static/custom_styles.css');"
    "assert s.status_code==200, s.status_code;"
    "assert 'Cache-Control' in s.headers, 'estatico sem Cache-Control (I6)';"
    "tema=app.test_client().get('/tema.mid');"
    "assert tema.status_code==200, ('/tema.mid', tema.status_code);"
    "assert tema.data[:4]==b'MThd', 'tema nao e MIDI';"
    "assert tema.headers.get('X-Dadinho-Tema-Seed') is not None, 'sem seed';"
    "cc=tema.headers.get('Cache-Control','');"
    "assert cc.startswith('public, max-age='), cc;"
    "assert int(cc.split('=',1)[1])>0, 'max-age nao acompanha a janela';"
    "print('BOOT_OK')"
)


def verificar_boot():
    print("3) boot VERCEL=1 (GET / == 200)")
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", _CODIGO_BOOT], cwd=RAIZ,
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        _falhou("boot VERCEL=1", "timeout")
        return
    _checar(
        "boot VERCEL=1",
        resultado.returncode == 0 and "BOOT_OK" in resultado.stdout,
        (resultado.stderr or resultado.stdout).strip()[-500:],
    )


# ---------------------------------------------------------------------------
# 3b) store em produção: sem configuração, o boot FALHA de forma explícita (I2)
# ---------------------------------------------------------------------------
def verificar_store_producao():
    print("3b) boot VERCEL=1 sem store configurado falha explicitamente (I2)")
    codigo = (
        "import os;"
        "os.environ['VERCEL']='1';"
        "os.environ.pop('DADINHO_STORE', None);"
        "os.environ.pop('UPSTASH_REDIS_REST_URL', None);"
        "os.environ.pop('UPSTASH_REDIS_REST_TOKEN', None);"
        "os.environ.pop('DADINHO_REDIS_URL', None);"
        "import store;"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ,
        capture_output=True, text=True, timeout=60,
    )
    saida = (resultado.stderr or "") + (resultado.stdout or "")
    _checar(
        "boot sem store falha (não cai em memória)",
        resultado.returncode != 0 and "Store não configurado" in saida,
        saida.strip()[-400:],
    )


# ---------------------------------------------------------------------------
# 3c) Fase 61: motor cooperativo gevent importa sem erro (dev/VPS)
# ---------------------------------------------------------------------------
def verificar_gevent():
    print("3c) boot com DADINHO_ASYNC_MODE=gevent (Fase 61)")
    codigo = (
        "import os;"
        "os.environ['DADINHO_ASYNC_MODE']='gevent';"
        "os.environ['DADINHO_STORE']='memoria';"
        "os.environ.pop('VERCEL', None);"
        "os.environ.pop('UPSTASH_REDIS_REST_URL', None);"
        "os.environ.pop('UPSTASH_REDIS_REST_TOKEN', None);"
        "os.environ.pop('DADINHO_REDIS_URL', None);"
        # O worker `gevent` do gunicorn (ggevent.py) importa `packaging.version`;
        # sem o pacote pinado o deploy da VPS sobe com "class uri 'gevent'
        # invalid or not found". Garante a dependência no ambiente limpo do CI.
        "import packaging.version;"
        "import app;"
        "assert app.socketio.async_mode == 'gevent', app.socketio.async_mode;"
        # Regressao Fase 61 (WS 500 na VPS): com `gevent-websocket` instalado o
        # engineio exige `environ['wsgi.websocket']`, que o worker `gevent` puro
        # do gunicorn nao fornece -> todo handshake WebSocket responde 500. O
        # driver so cai no `simple-websocket` (que funciona) quando o pacote
        # NAO existe, entao o guard falha se ele reaparecer nas dependencias.
        "from engineio.async_drivers import gevent as _eg;"
        "assert _eg.SimpleWebSocketWSGI is not None, "
        "'gevent-websocket instalado quebra o WebSocket do worker gevent';"
        "print('GEVENT_OK')"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ,
        capture_output=True, text=True, timeout=60,
    )
    _checar(
        "boot async_mode=gevent",
        resultado.returncode == 0 and "GEVENT_OK" in (resultado.stdout or ""),
        ((resultado.stderr or "") + (resultado.stdout or "")).strip()[-400:],
    )


# ---------------------------------------------------------------------------
# 4) round-trip de serialização + migrações (S3)
# ---------------------------------------------------------------------------
def verificar_roundtrip():
    print("4) serialização/migração do Lobby")
    import modelos

    lobby = modelos.Lobby(sala_id="rt", lobby_numero=7)
    # A política de defaults da sala é fonte única (`config_padrao`); o
    # cliente só espelha via `config_padrao` do payload de `update_user_list`.
    _checar("config padrão (fonte única)",
            modelos.Lobby.config_padrao() == {
                'dados_qtd': 3,
                'max_jogadores': 4,
                'com_coringa': True,
                'publica': True,
                'substituir_desconectado_por_ia': True,
                'ia_nivel_padrao': 3,
                'verificacao_ativa': True,
                'tempo_max_jogada': 60,
            },
            str(modelos.Lobby.config_padrao()))
    for cid, nome in (("cli1", "Ana"), ("cli2", "Bia")):
        jogador = modelos.Jogador(client_id=cid)
        jogador.username = nome
        jogador.pronto = True
        lobby.adicionar_jogador(jogador)
    bot = modelos.Jogador.criar_ia(3, "🤖 Teste")
    bot.ia_risco = 0.3
    bot.ia_agressividade = 0.9
    lobby.adicionar_jogador(bot)
    espectador = modelos.Jogador(client_id="spec1")
    espectador.username = "Eva"
    espectador.lobby_atual = lobby
    lobby.espectadores.append(espectador)
    dados = lobby.para_dict()
    _checar("grava versão atual", dados.get("versao") == modelos.VERSAO_ATUAL, str(dados.get("versao")))

    copia = modelos.Lobby.de_dict(dados)
    _checar("round-trip jogadores", [j.username for j in copia.jogadores] == ["Ana", "Bia", "🤖 Teste"])
    _checar("round-trip espectadores", [e.username for e in copia.espectadores] == ["Eva"])
    _checar("round-trip config", copia.config == lobby.config)
    _checar("round-trip numero de partida", copia.proxima_partida_num == lobby.proxima_partida_num)
    _checar("round-trip personalidade IA",
            [(j.ia_risco, j.ia_agressividade) for j in copia.jogadores if j.is_ia] == [(0.3, 0.9)])

    # Fase 30: vagas recentes (motivo do retomar_negado) sobrevivem ao round-trip.
    lobby.registrar_vaga_perdida(espectador)
    dados_com_vaga = lobby.para_dict()
    copia_vaga = modelos.Lobby.de_dict(dados_com_vaga)
    _checar("round-trip vagas recentes",
            espectador.chave_secreta in copia_vaga.vagas_recentes
            and copia_vaga.vagas_recentes[espectador.chave_secreta].get('nome') == "Eva")

    # v7 -> v8: o registro de vagas recentes passa a existir (vazio em salas antigas).
    v7 = {"sala_id": "v7", "lobby_num": 1, "versao": 7, "jogadores": [], "partidas": []}
    m7 = modelos.Lobby.de_dict(dict(v7))
    _checar("migração v7 -> v8", m7.vagas_recentes == {}, str(m7.vagas_recentes))

    # v1 -> v3: campos da sala de espera e prontidão passam a existir.
    v1 = {"sala_id": "v1", "lobby_num": 1, "versao": 1,
          "jogadores": [{"client_id": "x", "chave_secreta": "k"}], "partidas": []}
    m1 = modelos.Lobby.de_dict(dict(v1))
    _checar(
        "migração v1 -> v3",
        m1.status == "espera" and m1.config["com_coringa"] is True
        and m1.jogadores[0].pronto is False and m1.jogadores[0].is_ia is False,
    )

    # v2 -> v3: jogadores IA e configs de bots passam a existir.
    v2 = {"sala_id": "v2", "lobby_num": 1, "versao": 2, "config": {"com_coringa": False},
          "jogadores": [{"client_id": "y", "pronto": True}], "partidas": []}
    m2 = modelos.Lobby.de_dict(dict(v2))
    _checar(
        "migração v2 -> v3",
        m2.config["com_coringa"] is False and m2.config["ia_nivel_padrao"] == 2
        and m2.jogadores[0].is_ia is False,
    )

    # Formato mais novo não deve ser rebaixado.
    futuro = {"sala_id": "v4", "versao": 99, "jogadores": [], "partidas": []}
    migrado = modelos.Lobby._migrar(dict(futuro))
    _checar("versão futura preservada", migrado.get("versao") == 99, str(migrado.get("versao")))

    # v3 -> v4: espectadores ganham lista própria (vazia em salas antigas).
    v3 = {"sala_id": "v3", "lobby_num": 1, "versao": 3,
          "jogadores": [{"client_id": "z"}], "partidas": []}
    m3 = modelos.Lobby.de_dict(dict(v3))
    _checar("migração v3 -> v4", m3.espectadores == [] and len(m3.jogadores) == 1)

    # v4 -> v5: numeração de partida passa a ser própria (max + 1).
    m4_dir = modelos._migrar_v4_para_v5({"versao": 4, "partidas": [{"partida_num": 7}]})
    _checar("migração v4 -> v5", m4_dir.get("proxima_partida_num") == 8,
            str(m4_dir.get("proxima_partida_num")))

    # v5 -> v6: personalidade dos bots (risco/agressividade) passa a existir.
    v5 = {"sala_id": "v5", "lobby_num": 1, "versao": 5,
          "jogadores": [{"client_id": "w", "is_ia": True, "ia_nivel": 3}], "partidas": []}
    m5 = modelos.Lobby.de_dict(dict(v5))
    _checar("migração v5 -> v6",
            m5.jogadores[0].ia_risco == 0.5 and m5.jogadores[0].ia_agressividade == 0.5,
            f"{m5.jogadores[0].ia_risco}/{m5.jogadores[0].ia_agressividade}")


# ---------------------------------------------------------------------------
# 4b) tema rotativo (geração a cada 12h)
# ---------------------------------------------------------------------------
def verificar_tema():
    print("4b) tema rotativo (geração a cada 12h)")
    import tema as modulo_tema

    # O teste precisa da rotação real, não de um tema congelado no ambiente.
    fixo_previo = os.environ.pop("DADINHO_TEMA_SEED", None)
    try:
        agora = time.time()
        janela = modulo_tema.janela_atual(agora)
        meio1, bpm1, seed1 = modulo_tema.tema_atual(agora)
        meio2, bpm2, seed2 = modulo_tema.tema_atual(agora + 1)
        _checar("mesma janela de 12h -> mesmo tema",
                meio1 == meio2 and bpm1 == bpm2 and seed1 == seed2,
                f"seeds {seed1}/{seed2}")
        meio3, _, seed3 = modulo_tema.tema_atual(agora + modulo_tema.PERIODO_SEGUNDOS)
        _checar("12h após a virada -> outro tema",
                meio3 != meio1 and seed3 != seed1,
                f"seeds {seed1}/{seed3}")
        _checar("seed derivado da janela",
                seed1 == modulo_tema._seed_da_janela(janela), str(seed1))
        restante = modulo_tema.segundos_ate_virada(agora)
        _checar("vira exatamente no Cache-Control",
                0 < restante <= modulo_tema.PERIODO_SEGUNDOS, str(restante))
    finally:
        if fixo_previo is not None:
            os.environ["DADINHO_TEMA_SEED"] = fixo_previo


# ---------------------------------------------------------------------------
# 5) Integração (Fases 6 e 7)
# ---------------------------------------------------------------------------

def main():
    # M5: a integração vive em tests/test_integracao.py, importado LAZY
    # DEPOIS de _preparar_integracao() setar os globals (o `from verificar
    # import modulo_store, ...` captura o valor na hora do import).
    _preparar_integracao()
    from tests.test_integracao import verificar_integracao
    from tests.test_cross_instance import rodar as verificar_cross_instance
    from tests.test_anti_fraude import rodar as verificar_anti_fraude
    from tests.test_performance import rodar as verificar_performance
    inicio = time.time()
    verificar_py_compile()
    verificar_node()
    verificar_boot()
    verificar_store_producao()
    verificar_gevent()
    verificar_roundtrip()
    verificar_tema()
    verificar_integracao()
    verificar_cross_instance()
    verificar_anti_fraude()
    verificar_performance()
    print()
    if _falhas:
        print(f"FALHAS ({len(_falhas)}): " + ", ".join(_falhas))
        return 1
    print(f"TUDO OK em {time.time() - inicio:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
