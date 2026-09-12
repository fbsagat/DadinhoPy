# -*- coding: utf-8 -*-
"""
Script único de verificação do Dadinho (Fase 10).

Roda, em sequência:
  1. py_compile de todos os módulos Python do projeto;
  2. node --check dos JS de static/ e cobertura dos dicionários i18n (quando o Node está no PATH);
  3. boot com VERCEL=1 respondendo 200 na rota /;
  4. round-trip de serialização + migrações de versão do Lobby (S3);
  5. integração via flask_socketio.test_client cobrindo as Fases 6, 7 e 15.

Uso (do root do repo, com a .venv ativa):
    python verificar.py

Sai com código 0 se tudo passou; 1 se alguma checagem falhou.
Consolida os scripts que antes viviam em `%TEMP%\\opencode\\teste_fase*.py`.
"""
import os

# Estado local determinístico: nunca toca na Upstash mesmo com env vars no shell.
os.environ["DADINHO_STORE"] = "memoria"
os.environ.pop("UPSTASH_REDIS_REST_URL", None)
os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

import py_compile
import shutil
import subprocess
import sys
import time

RAIZ = os.path.dirname(os.path.abspath(__file__))
MODULOS = [
    "app.py", "modelos.py", "funcoes_gerais.py", "store.py", "ia.py", "seed.py",
    "tema.py", "gerar_musica.py", "narrador.py", "simular_ia.py", "api/index.py",
]
SALA = "verificacao"

_falhas = []


def _ok(nome):
    print(f"  [OK] {nome}")


def _falhou(nome, detalhe=""):
    print(f"  [FALHOU] {nome} {detalhe}".rstrip())
    _falhas.append(nome)


def _checar(nome, condicao, detalhe=""):
    if condicao:
        _ok(nome)
    else:
        _falhou(nome, detalhe)
    return condicao


# ---------------------------------------------------------------------------
# 1) py_compile
# ---------------------------------------------------------------------------
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
# 4) round-trip de serialização + migrações (S3)
# ---------------------------------------------------------------------------
def verificar_roundtrip():
    print("4) serialização/migração do Lobby")
    import modelos

    lobby = modelos.Lobby(sala_id="rt", lobby_numero=7)
    for cid, nome in (("cli1", "Ana"), ("cli2", "Bia")):
        jogador = modelos.Jogador(client_id=cid)
        jogador.username = nome
        jogador.pronto = True
        lobby.adicionar_jogador(jogador)
    espectador = modelos.Jogador(client_id="spec1")
    espectador.username = "Eva"
    espectador.lobby_atual = lobby
    lobby.espectadores.append(espectador)
    dados = lobby.para_dict()
    _checar("grava versão atual", dados.get("versao") == modelos.VERSAO_ATUAL, str(dados.get("versao")))

    copia = modelos.Lobby.de_dict(dados)
    _checar("round-trip jogadores", [j.username for j in copia.jogadores] == ["Ana", "Bia"])
    _checar("round-trip espectadores", [e.username for e in copia.espectadores] == ["Eva"])
    _checar("round-trip config", copia.config == lobby.config)
    _checar("round-trip numero de partida", copia.proxima_partida_num == lobby.proxima_partida_num)

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


# ---------------------------------------------------------------------------
# 5) Integração (Fases 6 e 7)
# ---------------------------------------------------------------------------
def _preparar_integracao():
    global modulo_store, modulo_app, funcoes_gerais, socketio, app
    import store as modulo_store
    import app as modulo_app
    import funcoes_gerais
    from app import app, socketio
    # Cooldown desligado no fluxo principal; o teste V2 religa o real.
    modulo_app.tem_cooldown = lambda *a, **k: False
    return modulo_store, modulo_app, funcoes_gerais


def _achar_evento(lista, nome):
    for evento in lista:
        if evento["name"] == nome:
            return evento["args"][0] if evento["args"] else True
    return None


def _contar_eventos(lista, nome):
    return sum(1 for evento in lista if evento["name"] == nome)


def _limpar():
    modulo_store.remover_sala(SALA)


def _conectar():
    c = socketio.test_client(app, query_string=f"sala={SALA}")
    eventos = c.get_received()
    cs = _achar_evento(eventos, "connect_start")
    assert cs is not None, "deve receber connect_start"
    return c, cs, eventos


def _conectar_trio(dados_qtd):
    clis = {}
    for nome in ("Ana", "Bia", "Caio"):
        c, cs, _ = _conectar()
        c.emit("apelido", {"apelido_msg": nome})
        clis[nome] = (c, cs["chave_secreta"])
    clis["Bia"][0].emit("ficar_pronto", {"chave": clis["Bia"][1]})
    clis["Caio"][0].emit("ficar_pronto", {"chave": clis["Caio"][1]})
    clis["Ana"][0].emit("iniciar_partida", {"chave": clis["Ana"][1], "dados_qtd": dados_qtd})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1
    for c, chave in clis.values():
        c.emit("jogar_dados", {"chave": chave})
    for c, chave in clis.values():
        c.emit("joguei_dados", {"chave_secreta": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2
    return clis, lobby


def _rodada_ate_conferencia(clis):
    """Da página de turnos à conferência: cada um aposta e o último desconfia."""
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    rodada = partida.rodadas[-1]
    ordem = list(partida.jogadores)
    while ordem[0] != rodada.vez_atual:
        ordem.append(ordem.pop(0))
    n = len(ordem)
    for i in range(n - 1):
        jogador = ordem[i]
        if i == 0:
            face = jogador.dados[0] if jogador.dados else 1
            qtd = 1
        else:
            face = 6
            qtd = i + 1
        clis[jogador.username][0].emit(
            "apostar",
            {"dados": {"chave": clis[jogador.username][1], "dado": face, "quantidade": qtd}},
        )
    desconfia = ordem[n - 1]
    clis[desconfia.username][0].emit(
        "desconfiar", {"dados": {"chave": clis[desconfia.username][1]}}
    )
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 3, f"deve estar na conferência, página={lobby.pagina}"
    return lobby


def _desconectar_todos(clis):
    for c, _ in clis.values():
        if c.is_connected():
            c.disconnect()


def _purgar_grace(clis):
    """Com a janela de graça em 0, um evento de qualquer ativo expurga os caídos."""
    ativo = next(c for c, _ in clis.values() if c.is_connected())
    ativo.emit("verificar_desconectados")


# --- Fase 6 -----------------------------------------------------------------
def teste_b3_aposta_invalida():
    _limpar()
    clis, lobby = _conectar_trio(1)
    rodada = lobby.partidas[-1].rodadas[-1]
    vez = rodada.vez_atual
    cli_vez, chave_vez = clis[vez.username]
    invalidas = [
        {"dado": 0, "quantidade": 1},
        {"dado": 7, "quantidade": 1},
        {"dado": 3, "quantidade": 0},
        {"dado": 3, "quantidade": -1},
        {"quantidade": 2},
        {"dado": "abc", "quantidade": 2},
    ]
    for aposta in invalidas:
        cli_vez.emit("apostar", {"dados": {"chave": chave_vez, **aposta}})
    eventos = cli_vez.get_received()
    invalida = _achar_evento(eventos, "jogada_invalida")
    assert invalida is not None, "deve receber jogada_invalida"
    assert isinstance(invalida, dict) and invalida.get("txtchave"), \
        "jogada_invalida deve trazer a chave i18n (txtchave)"
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert len(rodada.turnos) == 0, "aposta inválida não pode criar turno"
    assert rodada.vez_atual == vez, "jogador da vez não pode mudar com aposta inválida"
    _desconectar_todos(clis)
    _limpar()
    _ok("B3 (aposta inválida)")


def teste_b6_bools_reais():
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"com_coringa": "false", "publica": "false"}})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.config["com_coringa"] is True, "string não pode desativar o coringa (B6)"
    assert lobby.config["publica"] is True, "string não pode tornar a sala privada (B6)"
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"com_coringa": False, "publica": False}})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.config["com_coringa"] is False and lobby.config["publica"] is False
    c1.disconnect()
    _limpar()
    _ok("B6 (bools reais)")


def teste_b1_b7_desconexao_conferencia():
    _limpar()
    clis, _ = _conectar_trio(2)
    lobby = _rodada_ate_conferencia(clis)
    rodada = lobby.partidas[-1].rodadas[-1]
    perdedor_nome = rodada.perdedor.username if rodada.perdedor else None

    # B1: um jogador (que não o perdedor da rodada) confirma e cai; a
    # conferência não pode travar num fantasma.
    quem_cai = next(nome for nome in ("Ana", "Bia", "Caio") if nome != perdedor_nome)
    clis[quem_cai][0].emit("conferencia_final", {"chave": clis[quem_cai][1]})
    clis[quem_cai][0].disconnect()
    _purgar_grace(clis)
    lobby = modulo_store.carregar_sala(SALA)
    rodada = lobby.partidas[-1].rodadas[-1]
    assert lobby.pagina == 3, "desconexão na conferência não pode voltar para a página 2"
    assert rodada.conferiram == 0, "confirmação do desconectado deve ser desfeita (B1)"
    assert len(rodada.jogadores) == 2, "desconectado não pode continuar na rodada"
    assert len(lobby.jogadores) == 2

    for c, chave in clis.values():
        if c.is_connected():
            c.emit("conferencia_final", {"chave": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1, f"rodada 2 deve começar, página={lobby.pagina}"
    partida = lobby.partidas[-1]
    assert len(partida.rodadas) == 2, "deve ter criado a rodada 2"
    assert 1 in [j.dados_qtd for j in partida.jogadores], "alguém deve ter perdido um dado"

    for c, chave in clis.values():
        if c.is_connected():
            c.emit("jogar_dados", {"chave": chave})
    for c, chave in clis.values():
        if c.is_connected():
            c.emit("joguei_dados", {"chave_secreta": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2

    # B7: tab novo na página 2 da rodada 2 recebe reset_rodada com dados por jogador.
    c4, _, eventos_iniciais = _conectar()
    reset = _achar_evento(eventos_iniciais, "reset_rodada")
    assert reset is not None, "snapshot em rodada 2+ deve emitir reset_rodada (B7)"
    partida = lobby.partidas[-1]
    esperado = [j.dados_qtd for j in partida.jogadores]
    assert reset["jogadores_dados_qtd"] == esperado, f"{reset['jogadores_dados_qtd']} != {esperado}"
    assert len(set(reset["jogadores_dados_qtd"])) > 1, "contagens devem refletir a perda de dados"
    assert reset["jogadores_nomes"] == [j.username for j in partida.jogadores]
    c4.disconnect()
    _desconectar_todos(clis)
    _limpar()
    _ok("B1/B7 (desconexão na conferência)")


def teste_b2_desconexao_vitoria():
    _limpar()
    clis, _ = _conectar_trio(1)
    _rodada_ate_conferencia(clis)
    for c, chave in clis.values():
        c.emit("conferencia_final", {"chave": chave})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert len(partida.jogadores) == 2 and lobby.pagina == 1

    for c, chave in clis.values():
        c.emit("jogar_dados", {"chave": chave})
    for c, chave in clis.values():
        c.emit("joguei_dados", {"chave_secreta": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2
    _rodada_ate_conferencia(clis)
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    for j in partida.jogadores:
        clis[j.username][0].emit("conferencia_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert lobby.pagina == 4, f"deve estar na vitória, página={lobby.pagina}"
    assert partida.vencedor_final is not None
    assert len(lobby.jogadores) == 3, "todos seguem no lobby (incluindo eliminados)"

    # B2: um eliminado confirma a vitória e cai; o contador deve ser desfeito.
    vencedor = partida.vencedor_final
    quem_confirma = next(nome for nome in ("Caio", "Bia", "Ana") if nome != vencedor.username)
    clis[quem_confirma][0].emit("vencedor_final", {"chave": clis[quem_confirma][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.conferiram_vencedor == 1
    clis[quem_confirma][0].disconnect()
    _purgar_grace(clis)
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.conferiram_vencedor == 0, "confirmação do desconectado deve ser desfeita (B2)"
    assert len(lobby.jogadores) == 2

    for j in lobby.jogadores:
        clis[j.username][0].emit("vencedor_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 0 and lobby.status == "espera", "vitória confirmada deve resetar o lobby"
    _desconectar_todos(clis)
    _limpar()
    _ok("B2 (desconexão na vitória)")


def teste_b4_vencedor_por_desconexao():
    _limpar()
    clis, _ = _conectar_trio(1)
    clis["Bia"][0].disconnect()
    clis["Caio"][0].disconnect()
    _purgar_grace(clis)
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert partida.vencedor_final is not None, "vencedor deve ser declarado por desconexão"
    assert lobby.pagina == 4
    vencedor = partida.vencedor_final
    cli_venc, chave_venc = clis[vencedor.username]
    cli_venc.emit("foguetear_click", {"chave": chave_venc})
    eventos = cli_venc.get_received()
    assert _achar_evento(eventos, "soltar_fogos") is not None, "vencedor deve soltar fogos (B4)"
    _desconectar_todos(clis)
    _limpar()
    _ok("B4 (vencedor por desconexão)")


# --- Fase 7 -----------------------------------------------------------------
def teste_a3_a6_chave_e_idempotencia():
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    for c, nome in ((c1, "Ana"), (c2, "Bia")):
        c.emit("apelido", {"apelido_msg": nome})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})

    c1.emit("iniciar_partida", {"chave": "errada", "dados_qtd": 2})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.status == "espera", "iniciar_partida sem chave correta não pode iniciar (A3)"
    assert lobby.pagina == 0

    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 2})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1
    assert all(j.joguei_dados is False for j in lobby.jogadores)

    c1.emit("jogar_dados", {"chave": "errada"})
    eventos = c1.get_received()
    assert _achar_evento(eventos, "jogar_dados_resultado") is None, "chave errada deve ser ignorada (A3)"

    c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
    eventos = c1.get_received()
    assert _contar_eventos(eventos, "jogar_dados_resultado") == 1, "deve rolar exatamente uma vez"
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    dados_apos = list(ana.dados)
    assert ana.joguei_dados is True

    c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
    eventos = c1.get_received()
    assert _contar_eventos(eventos, "jogar_dados_resultado") == 0, "segundo jogar_dados deve ser ignorado (A6)"
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.dados == dados_apos, "dados não podem mudar num re-rolar (A6)"

    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("A3/A6 (chave e idempotência)")


def teste_v3_payloads_malformados():
    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    for c, nome in ((c1, "Ana"), (c2, "Bia")):
        c.emit("apelido", {"apelido_msg": nome})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})

    c1.emit("apelido", None)
    c1.emit("iniciar_partida", "texto qualquer")
    c1.emit("iniciar_partida", None)
    c1.emit("configurar_partida", None)
    c1.emit("ficar_pronto", None)
    c1.emit("listar_partidas", None)
    c1.emit("jogar_dados", None)
    c1.emit("joguei_dados", None)
    c1.emit("apostar", None)
    c1.emit("apostar", {"dados": "não é dict"})
    c1.emit("desconfiar", None)
    c1.emit("conferencia_final", None)
    c1.emit("vencedor_final", None)
    c1.emit("foguetear_click", None)

    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.status == "espera"
    assert all(j.joguei_dados is False for j in lobby.jogadores)

    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 1
    for c, chave in ((c1, cs1["chave_secreta"]), (c2, cs2["chave_secreta"])):
        c.emit("jogar_dados", {"chave": chave})
    for c, chave in ((c1, cs1["chave_secreta"]), (c2, cs2["chave_secreta"])):
        c.emit("joguei_dados", {"chave_secreta": chave})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2

    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("V3 (payloads malformados)")


def teste_v2_cooldown():
    _sleep_real = time.sleep
    sid_teste = "sid-cooldown"
    assert funcoes_gerais.tem_cooldown(sid_teste, 0.5) is False
    assert funcoes_gerais.tem_cooldown(sid_teste, 0.5) is True

    _limpar()
    modulo_app.tem_cooldown = funcoes_gerais.tem_cooldown
    try:
        c1, cs1, _ = _conectar()
        c2, cs2, _ = _conectar()
        c1.emit("apelido", {"apelido_msg": "Ana"})
        _sleep_real(0.6)
        c2.emit("apelido", {"apelido_msg": "Bia"})
        _sleep_real(0.6)
        c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
        _sleep_real(0.6)
        c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby.pagina == 1
        _sleep_real(0.6)

        c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
        c1.emit("jogar_dados", {"chave": cs1["chave_secreta"]})
        eventos = c1.get_received()
        assert _contar_eventos(eventos, "jogar_dados_resultado") == 1, "segundo emit cai no cooldown (V2)"

        _sleep_real(0.6)
        c2.emit("jogar_dados", {"chave": cs2["chave_secreta"]})
        _sleep_real(0.6)
        c1.emit("joguei_dados", {"chave_secreta": cs1["chave_secreta"]})
        _sleep_real(0.6)
        c2.emit("joguei_dados", {"chave_secreta": cs2["chave_secreta"]})
        lobby = modulo_store.carregar_sala(SALA)
        assert lobby.pagina == 2
        c1.disconnect()
        c2.disconnect()
    finally:
        modulo_app.tem_cooldown = lambda *a, **k: False
    _limpar()
    _ok("V2 (cooldown)")


def teste_a4_a5_lock_e_sorteio():
    _limpar()
    clis, lobby = _conectar_trio(1)
    partida = lobby.partidas[-1]
    assert partida.jogador_sorteado in partida.jogadores, "jogador_sorteado deve ser membro (A5)"
    _rodada_ate_conferencia(clis)
    _desconectar_todos(clis)
    _limpar()
    _ok("A4/A5 (lock e sorteio)")


def teste_partida_completa():
    _limpar()
    clis, lobby = _conectar_trio(1)
    partida = lobby.partidas[-1]
    _rodada_ate_conferencia(clis)
    narracoes = [e for e in clis[partida.jogadores[0].username][0].get_received()
                 if e["name"] == "narracao"]
    assert narracoes, "a partida deve emitir narracao"
    assert narracoes[0]["args"][0].get("segmentos"), "narracao deve trazer segmentos i18n"
    for j in partida.jogadores:
        clis[j.username][0].emit("conferencia_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert lobby.pagina == 1 and len(partida.jogadores) == 2

    for j in partida.jogadores:
        clis[j.username][0].emit("jogar_dados", {"chave": clis[j.username][1]})
    for j in partida.jogadores:
        clis[j.username][0].emit("joguei_dados", {"chave_secreta": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2
    _rodada_ate_conferencia(clis)
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    for j in partida.jogadores:
        clis[j.username][0].emit("conferencia_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert lobby.pagina == 4, f"vencedor declarado, página={lobby.pagina}"
    vencedor = partida.vencedor_final
    assert vencedor is not None

    cli_venc, chave_venc = clis[vencedor.username]
    cli_venc.emit("foguetear_click", {"chave": "errada"})
    assert _achar_evento(cli_venc.get_received(), "soltar_fogos") is None
    cli_venc.emit("foguetear_click", {"chave": chave_venc})
    assert _achar_evento(cli_venc.get_received(), "soltar_fogos") is not None

    for j in lobby.jogadores:
        clis[j.username][0].emit("vencedor_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 0 and lobby.status == "espera"
    _desconectar_todos(clis)
    _limpar()
    _ok("partida completa (Fases 6/7)")


def teste_gate_pagina_confirmacoes():
    _limpar()
    clis, lobby = _conectar_trio(1)  # 3 jogadores, página 2 (turnos)
    assert lobby.pagina == 2

    # Fase 15: confirmar a conferência durante os turnos não pode adiantar a rodada.
    for c, chave in clis.values():
        c.emit("conferencia_final", {"chave": chave})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert lobby.pagina == 2, f"gate: conferência precoce não pode sair dos turnos (pagina={lobby.pagina})"
    assert len(partida.rodadas) == 1, "gate: turnos não podem criar nova rodada"
    assert all(not j.confirmou_rodada for j in partida.jogadores)

    # Fase 15: confirmar a vitória durante os turnos não pode resetar o lobby.
    for j in partida.jogadores:
        clis[j.username][0].emit("vencedor_final", {"chave": clis[j.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 2 and lobby.status == "jogando", "gate: vitória precoce não pode resetar"
    assert lobby.conferiram_vencedor == 0, "gate: contador de vitória não pode subir nos turnos"

    _desconectar_todos(clis)
    _limpar()
    _ok("gate de página das confirmações (B1)")


def teste_espectador_nao_e_jogador():
    _limpar()
    clis, lobby = _conectar_trio(1)  # 3 jogadores, página 2
    assert len(lobby.jogadores) == 3 and not lobby.espectadores

    c4, _, eventos4 = _conectar()  # entra no meio da partida
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert len(lobby.jogadores) == 3, "espectador não pode virar jogador do lobby (B2)"
    assert len(lobby.espectadores) == 1, "espectador deve ir para lobby.espectadores"
    assert all(j not in partida.jogadores for j in lobby.espectadores)
    assert _achar_evento(eventos4, "espectador") is not None, "snapshot deve marcar ESPECTADOR"

    # Duas desistências declaram o terceiro vencedor. O espectador não entra na
    # conta da vitória (len(lobby.jogadores)).
    for nome in ("Bia", "Caio"):
        clis[nome][0].disconnect()
    _purgar_grace(clis)
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert partida.vencedor_final is not None
    assert len(lobby.jogadores) == 1, "só o vencedor humano resta no lobby"
    assert len(lobby.espectadores) == 1

    vencedor = partida.vencedor_final
    clis[vencedor.username][0].emit("vencedor_final", {"chave": clis[vencedor.username][1]})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.pagina == 0 and lobby.status == "espera", "vitória deve resetar com 1 jogador"
    # O espectador é promovido a jogador na próxima partida, sem duplicar.
    assert not lobby.espectadores, "espectadores devem ser promovidos no reset"
    assert len(lobby.jogadores) == 2

    c4.disconnect()
    _desconectar_todos(clis)
    _limpar()
    _ok("espectador não é jogador (B2)")


def teste_sala_so_com_bot_e_removida():
    _limpar()
    c1, cs1, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c1.emit("adicionar_ia", {"chave": cs1["chave_secreta"], "nivel": 2, "quantidade": 1})
    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    assert any(j.is_ia for j in lobby.jogadores)

    # Fase 15: um bot não conta como "outro ativo" — o humano sai na hora e a
    # sala (só com bots) é removida em vez de ficar órfã na janela de graça.
    c1.disconnect()
    assert modulo_store.carregar_sala(SALA) is None, "sala só com bots deve ser removida (B3)"
    _limpar()
    _ok("sala só com bot é removida (B3)")


def teste_sala_padrao_cria_nova():
    # Fase 16: a sala padrão compartilhada foi aposentada. Sem código (ou com
    # `?sala=padrao`), o connect devolve um código novo em vez de lotar a padrão.
    _limpar()
    modulo_store.remover_sala(funcoes_gerais.SALA_PADRAO)
    c1 = socketio.test_client(app, query_string="sala=padrao")
    eventos = c1.get_received()
    criada = _achar_evento(eventos, "sala_criada")
    assert criada and criada.get("sala"), "connect na sala padrão deve devolver um código novo"
    assert criada["sala"] != funcoes_gerais.SALA_PADRAO
    assert _achar_evento(eventos, "connect_start") is None, "não pode entrar na sala padrão"
    assert modulo_store.carregar_sala(funcoes_gerais.SALA_PADRAO) is None, \
        "a sala padrão não pode ser materializada"
    c1.disconnect()

    # Código inválido também gera sala nova (normalizar_sala cai no sentinela).
    c2 = socketio.test_client(app, query_string="sala=invalida!")
    criada2 = _achar_evento(c2.get_received(), "sala_criada")
    assert criada2 and criada2.get("sala"), "sala inválida deve gerar código novo"
    c2.disconnect()

    # O código devolvido funciona como uma sala normal.
    nova = criada["sala"]
    c3 = socketio.test_client(app, query_string=f"sala={nova}")
    eventos3 = c3.get_received()
    assert _achar_evento(eventos3, "connect_start") is not None
    assert modulo_store.carregar_sala(nova) is not None
    c3.disconnect()
    modulo_store.remover_sala(nova)
    _limpar()
    _ok("sala padrão cria sala nova (Fase 16)")


def teste_resumo_malformado_nao_quebra_busca():
    _limpar()
    modulo_store.salvar_resumo("quebrado", {"sala": "quebrado", "publica": True})
    try:
        for ordenar in ("jogadores", "nome", "recentes"):
            funcoes_gerais.listar_resumos_partidas({"ordenar": ordenar})
    except Exception as erro:  # noqa: BLE001
        raise AssertionError(f"resumo malformado não pode quebrar a busca: {erro!r}")
    finally:
        modulo_store.remover_resumo("quebrado")
    _ok("resumo malformado na busca (B6)")


def teste_cooldown_expurga_antigos():
    with funcoes_gerais._cooldowns_guard:
        funcoes_gerais._cooldowns.clear()
        agora = funcoes_gerais.time.time()
        for i in range(5000):
            funcoes_gerais._cooldowns[f"antigo{i}"] = agora - 120
    try:
        assert funcoes_gerais.tem_cooldown("novo", 0.5) is False
        with funcoes_gerais._cooldowns_guard:
            restantes = len(funcoes_gerais._cooldowns)
        assert restantes < 5000, "cooldowns antigos devem ser expurgados (B8)"
    finally:
        with funcoes_gerais._cooldowns_guard:
            funcoes_gerais._cooldowns.clear()
    _ok("cooldown com expurgo (B8)")


def teste_poda_partidas():
    import modelos
    emit_original = modelos.emit
    modelos.emit = lambda *a, **k: None  # fora de request não há room/namespace
    try:
        lobby = modelos.Lobby(sala_id="poda", lobby_numero=1)
        for cid, nome in (("a", "A"), ("b", "B")):
            jogador = modelos.Jogador(client_id=cid)
            jogador.username = nome
            lobby.adicionar_jogador(jogador)
        lobby.jogadores[0].master = True
        p1 = lobby.construir_partida(dados_qtd=1)
        assert p1.partida_num == 1
        lobby.resetar_para_lobby()
        p2 = lobby.construir_partida(dados_qtd=1)
        assert p2.partida_num == 2, "numeração deve continuar após a poda"
        lobby.resetar_para_lobby()
        assert len(lobby.partidas) <= 1, "histórico antigo deve ser podado"
        copia = modelos.Lobby.de_dict(lobby.para_dict())
        assert copia.proxima_partida_num == 3, "numeração deve sobreviver ao round-trip"
    finally:
        modelos.emit = emit_original
    _ok("poda de partidas antigas")


def teste_commit_reveal():
    import seed

    _limpar()
    c1, cs1, _ = _conectar()
    c2, cs2, _ = _conectar()
    c1.emit("apelido", {"apelido_msg": "Ana"})
    c2.emit("apelido", {"apelido_msg": "Bia"})
    c1.emit("configurar_partida", {"chave": cs1["chave_secreta"],
                                   "config": {"verificacao_ativa": True}})
    c2.emit("ficar_pronto", {"chave": cs2["chave_secreta"]})
    assert modulo_store.carregar_sala(SALA).config["verificacao_ativa"] is True

    # Fase de compromisso: só o hash vai para o servidor (o nonce fica local).
    n1, n2 = seed.gerar_nonce(), seed.gerar_nonce()
    c1.emit("comprometer_seed", {"chave": cs1["chave_secreta"], "compromisso": seed.compromisso(n1)})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.compromisso_seed == seed.compromisso(n1) and ana.nonce_seed is None, \
        "o servidor não pode receber o nonce no commit"
    pode, motivo = lobby.pode_iniciar()
    assert not pode and motivo["chave"] == "msg.motivo.aguardando_revelacao"

    c2.emit("comprometer_seed", {"chave": cs2["chave_secreta"], "compromisso": seed.compromisso(n2)})
    lobby = modulo_store.carregar_sala(SALA)
    assert lobby.compromissos_completos() and lobby.revelacoes_pendentes()

    # Compromisso imutável: o primeiro vale.
    n1b = seed.gerar_nonce()
    c1.emit("comprometer_seed", {"chave": cs1["chave_secreta"], "compromisso": seed.compromisso(n1b)})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.compromisso_seed == seed.compromisso(n1), "primeiro compromisso deve valer"

    # Fase de revelação (pública: a sala toda recebe os nonces).
    c1.emit("revelar_seed", {"chave": cs1["chave_secreta"], "nonce": n1})
    c2.emit("revelar_seed", {"chave": cs2["chave_secreta"], "nonce": n2})
    lobby = modulo_store.carregar_sala(SALA)
    assert not lobby.revelacoes_pendentes(), "todos revelaram"
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert ana.nonce_seed == n1 and ana.revelado_seed
    revelacoes = [e["args"][0] for e in c2.get_received() if e["name"] == "seed_revelacao"]
    assert any(r.get("nonce") == n1 for r in revelacoes), "revelação deve ser pública"

    # Nonce errado é rejeitado (revelação não pode mentir).
    ana.revelado_seed = False
    ana.nonce_seed = None
    modulo_store.salvar_sala(lobby)
    c1.emit("revelar_seed", {"chave": cs1["chave_secreta"], "nonce": seed.gerar_nonce()})
    lobby = modulo_store.carregar_sala(SALA)
    ana = next(j for j in lobby.jogadores if j.username == "Ana")
    assert not ana.revelado_seed, "nonce que não bate com o compromisso deve ser recusado"
    c1.emit("revelar_seed", {"chave": cs1["chave_secreta"], "nonce": n1})

    c1.emit("iniciar_partida", {"chave": cs1["chave_secreta"], "dados_qtd": 1})
    lobby = modulo_store.carregar_sala(SALA)
    partida = lobby.partidas[-1]
    assert partida.seed_info and partida.seed_final
    assert partida.seed_info["fonte"] == "servidor", "entropia secreta do servidor"
    assert partida.seed_info["entropia_externa"] == partida.seed_info["nonce_servidor"]
    assert all(not p["sem_reveal"] for p in partida.seed_info["participantes"]), \
        "todos revelaram: nada pode cair no fallback"
    c1.disconnect()
    c2.disconnect()
    _limpar()
    _ok("commit-reveal (nonce só na revelação)")


def teste_upstash_indice_resumos():
    arm = modulo_store.ArmazenamentoUpstash("http://fake", "tok")
    estado = {"dados": {}, "indice": set()}

    def fake_pipeline(comandos):
        for cmd in comandos:
            op = cmd[0]
            if op == "SET":
                estado["dados"][cmd[1]] = cmd[2]
            elif op == "SADD":
                estado["indice"].add(cmd[2])
            elif op == "DEL":
                estado["dados"].pop(cmd[1], None)
            elif op == "SREM":
                estado["indice"].discard(cmd[2])
        return {"result": "OK"}

    def fake_comando(*args):
        op = args[0]
        if op == "SMEMBERS":
            return {"result": list(estado["indice"])}
        if op == "MGET":
            return {"result": [estado["dados"].get(k) for k in args[1:]]}
        if op == "SADD":
            estado["indice"].update(args[2:])
            return {"result": len(args) - 2}
        if op == "SREM":
            for item in args[2:]:
                estado["indice"].discard(item)
            return {"result": len(args) - 2}
        return {"result": None}

    arm._pipeline = fake_pipeline
    arm._comando = fake_comando
    arm._varrer_chaves = lambda prefixo: []

    arm.salvar_resumo("s1", {"sala": "s1", "nome": "Um"})
    assert "s1" in estado["indice"], "salvar_resumo deve indexar a sala"
    assert [r["sala"] for r in arm.listar_resumos()] == ["s1"]

    # Resumo expirado sai do índice na listagem (sem SCAN).
    del estado["dados"][arm._chave_resumo("s1")]
    assert arm.listar_resumos() == []
    assert "s1" not in estado["indice"], "resumo expirado deve sair do índice"

    arm.salvar_resumo("s2", {"sala": "s2", "nome": "Dois"})
    arm.remover_resumo("s2")
    assert arm.listar_resumos() == []
    assert "s2" not in estado["indice"], "remover_resumo deve desindexar"
    _ok("índice de resumos da Upstash")


def teste_resumo_dedup():
    class Espiao:
        def __init__(self):
            self.chamadas = 0

        def salvar_resumo(self, sala_id, resumo):
            self.chamadas += 1

        def remover_resumo(self, sala_id):
            pass

    original = modulo_store.armazenamento
    espiao = Espiao()
    modulo_store.armazenamento = espiao
    try:
        modulo_store._resumos_assinatura.clear()
        resumo = {"sala": "d", "nome": "Igual", "jogadores": 2}
        modulo_store.salvar_resumo("d", dict(resumo))
        modulo_store.salvar_resumo("d", dict(resumo))
        assert espiao.chamadas == 1, "resumo idêntico não pode ser reescrito"
        mudado = dict(resumo, jogadores=3)
        modulo_store.salvar_resumo("d", mudado)
        assert espiao.chamadas == 2, "resumo diferente deve ser gravado"
    finally:
        modulo_store.armazenamento = original
        modulo_store._resumos_assinatura.clear()
    _ok("dedup de resumo (economia de comandos)")


def verificar_integracao():
    print("5) integração flask_socketio.test_client (Fases 6, 7 e 15)")
    global modulo_store, modulo_app, funcoes_gerais, socketio, app
    modulo_store, modulo_app, funcoes_gerais = _preparar_integracao()
    from app import app, socketio  # noqa: F811 (rebind após preparar)

    grace_original = modulo_app.GRACE_RECONEXAO_SEGUNDOS
    modulo_app.GRACE_RECONEXAO_SEGUNDOS = 0
    testes_fase6 = [
        ("B3", teste_b3_aposta_invalida),
        ("B6", teste_b6_bools_reais),
        ("B1/B7", teste_b1_b7_desconexao_conferencia),
        ("B2", teste_b2_desconexao_vitoria),
        ("B4", teste_b4_vencedor_por_desconexao),
    ]
    testes_fase7 = [
        ("A3/A6", teste_a3_a6_chave_e_idempotencia),
        ("V3", teste_v3_payloads_malformados),
        ("V2", teste_v2_cooldown),
        ("A4/A5", teste_a4_a5_lock_e_sorteio),
        ("partida completa", teste_partida_completa),
    ]
    testes_fase15 = [
        ("B1-gate", teste_gate_pagina_confirmacoes),
        ("B2-espectador", teste_espectador_nao_e_jogador),
        ("B3-bot-solo", teste_sala_so_com_bot_e_removida),
        ("sala-padrao", teste_sala_padrao_cria_nova),
    ]
    testes_hardening = [
        ("B6-resumo", teste_resumo_malformado_nao_quebra_busca),
        ("B8-cooldown", teste_cooldown_expurga_antigos),
        ("poda-partidas", teste_poda_partidas),
        ("upstash-indice", teste_upstash_indice_resumos),
        ("resumo-dedup", teste_resumo_dedup),
    ]
    testes_seed = [
        ("commit-reveal", teste_commit_reveal),
    ]
    try:
        for nome, func in testes_fase6 + testes_fase7 + testes_fase15 + testes_hardening + testes_seed:
            try:
                func()
            except Exception as erro:  # noqa: BLE001 (agrega falhas dos testes)
                _falhou(nome, repr(erro))
    finally:
        modulo_app.GRACE_RECONEXAO_SEGUNDOS = grace_original


def main():
    inicio = time.time()
    verificar_py_compile()
    verificar_node()
    verificar_boot()
    verificar_roundtrip()
    verificar_integracao()
    print()
    if _falhas:
        print(f"FALHAS ({len(_falhas)}): " + ", ".join(_falhas))
        return 1
    print(f"TUDO OK em {time.time() - inicio:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
