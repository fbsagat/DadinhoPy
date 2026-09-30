"""Runner da verificação do Dadinho (Fase 45, M5).

A infra (helpers/globals/constantes) vive em `tests/base.py`; os testes de
integração em `tests/test_integracao.py`; este arquivo só orquestra:
  py_compile -> node --check -> boot VERCEL=1 -> round-trip -> integração.
"""
from tests.base import *  # noqa: F401,F403

import re


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
    print("2) node --check static/*.js + cobertura i18n + acoes do HTML + sons + motor da musica")
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
    verificar_musica(node)
    verificar_sons(node)
    verificar_acoes_html(node)
    verificar_fila_eventos(node)


# ---------------------------------------------------------------------------
# 2a) todo arquivo de static/sons/ está registrado em `sons_disponiveis`
# ---------------------------------------------------------------------------
# `tocar_som` é silencioso quando o nome não está no mapa (`sons_disponiveis[nome]`
# devolve undefined e a função retorna) e o `new Audio` de um arquivo inexistente
# também não dá erro visível — um `.mp3` novo copiado para a pasta, ou uma
# entrada com o nome do arquivo digitado errado, simplesmente não toca nada.
# Este guard fecha essa classe de bug nos dois sentidos.
_CODIGO_SONS = r"""
const fs = require('fs'), path = require('path');
const js = fs.readFileSync(process.argv[1], 'utf8');
const dir = process.argv[2];
// Comentários citam nomes de som ao explicar a troca; o que interessa é o mapa.
const code = js.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/.*$/gm, '$1');
const bloco = code.match(/const\s+sons_disponiveis\s*=\s*\{([\s\S]*?)\n\};/);
if (!bloco) { console.error('sons_disponiveis nao encontrado em script.js'); process.exit(1); }
const mapeados = new Map();
const reEntrada = /([A-Za-z_$][\w$]*)\s*:\s*'([^']+)'/g;
let m;
while ((m = reEntrada.exec(bloco[1])) !== null) mapeados.set(m[2], m[1]);
let faltando = 0;
for (const arquivo of fs.readdirSync(dir).filter((f) => f.endsWith('.mp3')).sort()) {
  if (!mapeados.has(arquivo)) {
    console.error('static/sons/' + arquivo + ' sem entrada em sons_disponiveis (nunca toca)');
    faltando++;
  }
}
for (const [arquivo, nome] of [...mapeados].sort()) {
  if (!fs.existsSync(path.join(dir, arquivo))) {
    console.error('sons_disponiveis.' + nome + ' aponta para ' + arquivo + ', que nao existe');
    faltando++;
  }
}
if (faltando) process.exit(1);
console.log('sons=' + mapeados.size);
"""


def verificar_sons(node):
    resultado = subprocess.run(
        [node, "-e", _CODIGO_SONS, os.path.join(RAIZ, "static", "script.js"),
         os.path.join(RAIZ, "static", "sons")],
        capture_output=True, text=True,
    )
    _checar("sons de static/sons/", resultado.returncode == 0,
            (resultado.stderr or resultado.stdout).strip())


_CODIGO_MUSICA = r"""
// Guarda de regressão do motor da música: ele é um sequenciador em tempo real
// no AudioContext vivo. Voltar ao OfflineAudioContext reintroduz os ~30s de
// render bloqueante (a música só ligava dezenas de segundos depois do clique).
const fs = require('fs');
// Comentários citam o termo antigo para explicar a troca; o que interessa é o
// código. Remove `//` e `/* */` antes de procurar.
const cru = fs.readFileSync(process.argv[1], 'utf8');
const code = cru.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/.*$/gm, '$1');
const exige = [
  ['function bombear_musica', 'sem o agendador de notas'],
  ['setInterval(bombear_musica', 'a bomba não está no relógio'],
  ['function ancorar_ciclo_musica', 'sem ancoragem de ciclo/fade do loop'],
  ['notas.sort(', 'as notas não estão ordenadas por início (o sequenciador exige)'],
  ['function agendar_voz', 'as vozes não se limpam (vazam nós a cada volta)'],
];
let faltando = 0;
for (const [marca, erro] of exige) {
  if (code.indexOf(marca) < 0) { console.error(erro + ': falta ' + marca); faltando++; }
}
if (code.indexOf('OfflineAudioContext') >= 0) {
  console.error('OfflineAudioContext voltou: renderizar o tema inteiro trava a aba por ~30s');
  faltando++;
}
if (faltando) process.exit(1);
console.log('motor em tempo real ok');
"""


def verificar_musica(node):
    resultado = subprocess.run(
        [node, "-e", _CODIGO_MUSICA, os.path.join(RAIZ, "static", "script.js")],
        capture_output=True, text=True,
    )
    _checar("motor da musica (tempo real)", resultado.returncode == 0,
            (resultado.stderr or resultado.stdout).strip())


# ---------------------------------------------------------------------------
# 2a) paridade das listas de emojis entre o servidor e o cliente
# ---------------------------------------------------------------------------
# O picker é renderizado a partir de uma CÓPIA hard-coded em `static/script.js`
# (o servidor nunca emite o catálogo), então adicionar emoji só em
# `funcoes_gerais.py` não faz nada no frontend — e o caminho inverso é pior: o
# servidor descarta o emoji com `return` silencioso. As duas listas já divergiram
# uma vez (🤫/🖕/🍀/🎲 existiam no servidor e eram invisíveis no picker). Este
# guard fecha a classe de bug comparando as duas fontes.
_RE_LISTA_JS = re.compile(r"const\s+EMOJIS_POR_CATEGORIA\s*=\s*\{(.*?)\};", re.S)
_RE_CATEGORIA_JS = re.compile(r"(\w+)\s*:\s*\[(.*?)\]", re.S)
_RE_LISTA_PY = re.compile(r"^EMOJIS_(PROVOCATIVOS|AMIGAVEIS|GERAIS)\s*=\s*\[(.*?)\]", re.M)
_RE_POOL_IA = re.compile(r"^_EMOJI_\w+\s*=\s*\[(.*?)\]", re.M)


def _emojis_de(bruto):
    """Emojis de uma lista literal (`['a', 'b']` ou `["a", "b"]`)."""
    return [v.strip().strip("\"'") for v in bruto.split(",") if v.strip().strip("\"'")]


def _texto(rel):
    with open(os.path.join(RAIZ, rel), encoding="utf-8") as arquivo:
        return arquivo.read()


def _esc(emojis):
    """Emojis como `\\U0001f92b`. Segunda camada: `tests.base` já força UTF-8 no
    stream, mas se o `reconfigure` não puder ser aplicado (stdout capturado por
    um harness), o `_falhou` estoura UnicodeEncodeError em vez de reportar a
    falha — e uma verificação que MORRE é pior que uma que falha."""
    return ", ".join("".join(f"\\U{ord(c):08X}" for c in e) for e in emojis) or "(nenhum)"


def verificar_paridade_emojis():
    print("2a) paridade das listas de emojis (funcoes_gerais.py <-> static/script.js)")
    achados = {m.group(1): _emojis_de(m.group(2))
               for m in _RE_LISTA_PY.finditer(_texto("funcoes_gerais.py"))}
    servidor = {}
    for chave, categoria in (("PROVOCATIVOS", "provocativo"),
                             ("AMIGAVEIS", "amigavel"),
                             ("GERAIS", "geral")):
        if chave not in achados:
            _falhou("paridade emojis", f"funcoes_gerais.py sem EMOJIS_{chave}")
        else:
            servidor[categoria] = achados[chave]

    bloco = _RE_LISTA_JS.search(_texto(os.path.join("static", "script.js")))
    if bloco is None:
        _falhou("paridade emojis", "script.js sem `const EMOJIS_POR_CATEGORIA`")
        return
    cliente = {m.group(1): _emojis_de(m.group(2))
               for m in _RE_CATEGORIA_JS.finditer(bloco.group(1))}

    problemas = []
    if set(cliente) != set(servidor):
        problemas.append(f"categorias servidor={sorted(servidor)} cliente={sorted(cliente)}")
    for categoria in sorted(set(servidor) & set(cliente)):
        if servidor[categoria] != cliente[categoria]:
            problemas.append(
                f"{categoria}: so no servidor (invisivel no picker) "
                f"{_esc(sorted(set(servidor[categoria]) - set(cliente[categoria])))}; "
                f"so no cliente (rejeitado pelo servidor) "
                f"{_esc(sorted(set(cliente[categoria]) - set(servidor[categoria])))}")

    # Os pools de reação dos bots são uma lista independente e um emoji fora da
    # whitelist é descartado em silêncio por `bot_enviar_emoji` (a reação nunca
    # aparece) — sem erro, sem log.
    permitidos = {e for lista in servidor.values() for e in lista}
    for linha in _RE_POOL_IA.finditer(_texto("ia.py")):
        fora = sorted(set(_emojis_de(linha.group(1))) - permitidos)
        if fora:
            problemas.append(f"ia.py pool {linha.group(0).split('=')[0].strip()}: "
                             f"fora da whitelist {_esc(fora)}")

    if problemas:
        _falhou("paridade emojis", "; ".join(problemas))
    else:
        total = sum(len(v) for v in servidor.values())
        _ok(f"emojis: {total} em {len(servidor)} categorias, cliente identico e pools da IA na whitelist")


# ---------------------------------------------------------------------------
# 2b) todo `data-acao` do HTML tem função exportada em `window.Dadinho`
# ---------------------------------------------------------------------------
# O template não usa `onclick` inline (o CSP estrito bloquearia): o clique é
# delegado por `data-acao` e resolvido em `window.Dadinho`. Uma ação nova no
# HTML sem export correspondente é silenciosamente ignorada no clique — o
# botão "aparece" e não faz nada. Este guard fecha essa classe de bug.
_CODIGO_ACOES = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[1], 'utf8');
const js = fs.readFileSync(process.argv[2], 'utf8');
const acoes = new Set();
const reAcao = /data-acao="([^"]+)"/g;
let m;
while ((m = reAcao.exec(html)) !== null) acoes.add(m[1]);
// `fechar_alerta` é resolvido no próprio delegate (lê `data-resultado`).
acoes.delete('fechar_alerta');
const bloco = js.match(/window\.Dadinho\s*=\s*\{([\s\S]*?)\n\};/);
if (!bloco) { console.error('window.Dadinho nao encontrado em script.js'); process.exit(1); }
const exportadas = new Set();
const reNome = /([A-Za-z_$][\w$]*)/g;
while ((m = reNome.exec(bloco[1])) !== null) exportadas.add(m[1]);
const faltando = [...acoes].filter((a) => !exportadas.has(a)).sort();
if (faltando.length) {
  console.error('data-acao sem export em window.Dadinho: ' + faltando.join(', '));
  process.exit(1);
}
console.log('acoes=' + acoes.size);
"""


def verificar_acoes_html(node):
    resultado = subprocess.run(
        [node, "-e", _CODIGO_ACOES, os.path.join(RAIZ, "templates", "jogo.html"),
         os.path.join(RAIZ, "static", "script.js")],
        capture_output=True, text=True,
    )
    _checar("data-acao do HTML exportado em window.Dadinho", resultado.returncode == 0,
            (resultado.stderr or resultado.stdout).strip())
    verificar_chave_identidade(node)


# ---------------------------------------------------------------------------
# 2b) a chave de identidade (retomar_identidade) é persistida POR SALA em
# localStorage — e não mais lida de sessionStorage por aba. A sessionStorage
# era per-aba: um jogador que reabría a partida numa aba nova entrava sem a
# chave (tem_chave=0), virava placeholder de espectador num lobby `jogando`
# e adotava a chave do placeholder — ficava preso e não retomava o jogador
# (nem mesmo o substituído por IA). O guarda garante a contratação que permite
# "voltar a jogar a qualquer momento" a partir de outra aba.
# ---------------------------------------------------------------------------
_CODIGO_CHAVE = r"""
const fs = require('fs');
const js = fs.readFileSync(process.argv[1], 'utf8');
const code = js.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/.*$/gm, '$1');
let erros = [];
// 1) leitura primária da chave deve passar por localStorage por sala.
if (code.indexOf('function _chave_armazenamento(sala)') < 0)
    erros.push('falta a funcao storage por sala');
if (code.indexOf('let chave_resumo = (sala_atual && ler_chave_resumo(sala_atual))') < 0
    && code.indexOf('let chave_resumo = (sala_atual && ler_chave_resumo(sala_atual)) ||') < 0)
    erros.push('chave_resumo nao e lida via ler_chave_resumo(sala_atual)');
// 2) a leitura legacy por-aba (sessionStorage) foi substituída: não pode mais
//    ser a fonte da chave no boot.
if (/let\s+chave_resumo\s*=\s*sessionStorage\.getItem\(['\x22]dadinho_chave['\x22]\)/.test(code))
    erros.push('chave_resumo ainda lida direto do sessionStorage (per-aba)');
// 3) gravação e limpeza do placeholder devem ter a chave por sala (não só a antiga).
if (code.indexOf('localStorage.setItem(_chave_armazenamento(') < 0)
    erros.push('nao grava a chave por sala no localStorage');
if (code.indexOf('localStorage.removeItem(_chave_armazenamento(') < 0)
    erros.push('nao limpa a chave por sala no localStorage');
// 4) os handlers reais de conexão/saída usam os helpers (não a sessionStorage direta).
if (code.indexOf('gravar_chave_resumo(') < 0)
    erros.push('nao persiste a chave via gravar_chave_resumo no connect_start/retumar_negado');
if (code.indexOf('limpar_chave_resumo(') < 0)
    erros.push('nao limpa a chave via limpar_chave_resumo nos handlers de saída');
if (erros.length) { console.error(erros.join(' | ')); process.exit(1); }
console.log('chave identidade cross-tab (localStorage/sala) ok');
"""


def verificar_chave_identidade(node):
    resultado = subprocess.run(
        [node, "-e", _CODIGO_CHAVE, os.path.join(RAIZ, "static", "script.js")],
        capture_output=True, text=True,
    )
    _checar("chave de identidade por-sala em localStorage (cross-tab)",
            resultado.returncode == 0,
            (resultado.stderr or resultado.stdout).strip())


# ---------------------------------------------------------------------------
# 2c) a fila serial de animação re-arma após uma exceção dentro de um item.
# O motor da página não roda no servidor: os eventos chegam com `atraso`, são
# filas de animação serial no cliente (`static/script.js`) para preservar a
# ordem e encaixar as pausas de "pensamento" dos bots sem timers no backend.
# O `_onevent_original` já é envolto em try/catch, mas `mostrar_pensando` e o
# agendamento do `setTimeout` ficavam fora de proteção (Fase 80). Se um lança
# (ex.: `narracao` de bot com chave de página que falhou de forma inesperada),
# a exceção escapa pra cima pro Socket.IO, o `processando_eventos` fica `true`
# pra sempre e a fila MORRE: nada mais é aplicado, incluindo o `mudar_pagina` e
# o snapshot do heartbeat — travamento PERMANENTE e sem recupero automático.
# Este guard é um teste comportamental: extrai a função REAL do script, a roda
# em um sandbox com `mostrar_pensando` lançando no 1º pacote, e exige que a
# exceção NÃO escape e que os 3 eventos seguintes (inclusive `mudar_pagina`)
# cheguem — o mesmo caso de antes/depois que provou a correção.
# ---------------------------------------------------------------------------
_CODIGO_FILA = r"""
const fs = require('fs'), vm = require('vm');
const js = fs.readFileSync(process.argv[1], 'utf8');
function extrair(src, header) {
  const i = src.indexOf(header);
  if (i < 0) return null;
  const ini = src.indexOf('{', i);
  let prof = 1, j = ini + 1;
  while (j < src.length && prof > 0) {
    if (src[j] === '{') prof++;
    else if (src[j] === '}') prof--;
    j++;
  }
  // inclui o header `function NAME() {...}` (ou `socket.onevent = function(){...}`):
  // o wrapper evita `return` solto dentro do vm.runInContext (top-level return é ilegal).
  return src.slice(i, j);
}
const corpoFila = extrair(js, 'function _processar_fila_eventos() {');
const corpoOne = extrair(js, 'socket.onevent = function (packet) {');
if (!corpoFila || !corpoOne) { console.error('nao extraiu fila/onevent'); process.exit(1); }
const entregues = [];
let mostrar_chamado = 0;
let esconder = 0;
let escapou = null;
const socket = { onevent: null };
const ctx = {
  console: { error: () => {}, log: (m) => console.log(m) },
  setTimeout: (f, ms) => setTimeout(f, ms),
  clearTimeout: (t) => clearTimeout(t),
  Math, Array, Number, Object, JSON, Boolean, String,
  nome_jogador: 'Eu', MAX_ATRASO_FILA: 8000,
  _segurar_emoji: () => {}, _liberar_emojis_segurados: () => {},
  mostrar_pensando: () => {
    mostrar_chamado += 1;
    if (mostrar_chamado === 1) throw new Error('boom em mostrar_pensando');
  },
  esconder_pensando: () => { esconder += 1; },
  _onevent_original: (p) => { entregues.push(p.data[0]); },
  socket,
};
vm.createContext(ctx);
vm.runInContext(
  'var fila_eventos = [];\nvar processando_eventos = false;\nvar atraso_pendente_total = 0;\n'
  + corpoFila + '\n' + corpoOne, ctx);
const pacotes = [
  { data: ['narracao', { is_ia: true, jogador: 'Bot', atraso: 0 }] },
  { data: ['narracao', { is_ia: true, jogador: 'Bot', atraso: 0 }] },
  { data: ['mudar_pagina', { pagina: 2, pag_numero: 2, atraso: 0 }] },
  { data: ['meu_turno', { atraso: 0 }] },
];
for (const p of pacotes) {
  try { socket.onevent(p); } catch (e) { escapou = e.message; }
}
setTimeout(() => {
  const travou = ctx.processando_eventos === true;
  const ok = (!escapou) && (!travou)
      && entregues.join(',') === 'narracao,mudar_pagina,meu_turno';
  if (!ok) {
    console.error('fila travou apos excecao: escapou=' + escapou
      + ' travado=' + travou + ' entregues=[' + entregues.join(',') + ']');
    process.exit(1);
  }
  console.log('fila serial re-arma apos excecao em mostrar_pensando (Fase 80) ok');
  process.exit(0);
}, 200);
"""


def verificar_fila_eventos(node):
    resultado = subprocess.run(
        [node, "-e", _CODIGO_FILA, os.path.join(RAIZ, "static", "script.js")],
        capture_output=True, text=True,
    )
    _checar("fila serial de eventos re-arma após exceção (Fase 80)",
            resultado.returncode == 0,
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
    "pagina=r.get_data(as_text=True);"
    "preload='as=\"fetch\" href=\"/tema.mid\"';"
    "assert preload in pagina, 'sem preload do tema (a musica ligaria atrasada)';"
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
    # `PYTHONIOENCODING` + decodificação explícita: a checagem casa um texto com
    # acento. Sem isso, o filho escreve na codificação do console (cp1252 num
    # Windows) e o pai decodifica em UTF-8 (ou vice-versa) — a comparação falha
    # por mojibake, não pelo store. O CI (ubuntu) passa por acaso; a máquina de
    # desenvolvimento não.
    ambiente = dict(os.environ, PYTHONIOENCODING="utf-8")
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ, env=ambiente,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
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
    import ia
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
                  'embaralhar': 'rodada',
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
    bot.ia_estilo = ia.ESTILO_PRUDENTE
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
    # Fase 76: o estilo do bot viaja no store — sem ele, um prudente reconstrído
    # de outra instância voltaria a ser o bot genérico do nível (e a partida segue
    # no meio, em estado distribuído).
    _checar("round-trip estilo do bot",
            [j.ia_estilo for j in copia.jogadores if j.is_ia] == [ia.ESTILO_PRUDENTE])

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

    # v8 -> v9: o relógio do próximo lance dos bots (Fase 69) entra no formato.
    v8 = {"sala_id": "v8", "lobby_num": 1, "versao": 8, "jogadores": [],
          "partidas": [{"partida_num": 1, "rodadas": [{"rodada_num": 1, "turnos": []}]}]}
    m8 = modelos.Lobby.de_dict(dict(v8))
    _checar("migração v8 -> v9",
            m8.partidas[0].proximo_lance_em is None
            and m8.partidas[0].rodadas[0].proximo_lance_em is None)

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

    # v9 -> v10: o estilo de jogo do bot (Fase 76) — ausente vira None (o
    # repertório por nível), nunca um estilo que não existe.
    v9 = {"sala_id": "v9", "lobby_num": 1, "versao": 9, "jogadores": [
        {"client_id": "w", "is_ia": True, "ia_nivel": 3},
        {"client_id": "h", "is_ia": False}], "espectadores": [], "partidas": []}
    m9 = modelos.Lobby.de_dict(dict(v9))
    _checar("migração v9 -> v10",
            m9.jogadores[0].ia_estilo is None and m9.jogadores[1].ia_estilo is None,
            str([j.ia_estilo for j in m9.jogadores]))

    # v10 -> v11: o carimbo de "sala sem nenhum humano" entra no formato.
    # Sala antiga (v10) fica com None = "nunca esvaziou", que é o estado neutro
    # (não cancela nada por acidente logo no deploy).
    v10 = {"sala_id": "v10", "lobby_num": 1, "versao": 10, "jogadores": [
        {"client_id": "h", "is_ia": False}], "espectadores": [], "partidas": []}
    m10 = modelos.Lobby.de_dict(dict(v10))
    _checar("migração v10 -> v11", m10.sem_humano_em is None, str(m10.sem_humano_em))

    # v11 -> v12: a chave `embaralhar` entra no config (default 'rodada' — novo
    # comportamento padrão da Fase 81).
    v11 = {"sala_id": "v11", "lobby_num": 1, "versao": 11,
           "jogadores": [], "espectadores": [], "partidas": []}
    m11 = modelos.Lobby.de_dict(dict(v11))
    _checar("migração v11 -> v12",
            m11.config.get('embaralhar') == 'rodada', str(m11.config.get('embaralhar')))

    # O carimbo precisa sobreviver ao round-trip E viajar no resumo (é o que a
    # varredura de salas abandonadas lê, sem reidratar o Lobby inteiro).
    from datetime import datetime as _dt
    lobby_sem_humano = modelos.Lobby(sala_id="rt2", lobby_numero=8)
    marca = _dt(2026, 1, 2, 3, 4, 5)
    lobby_sem_humano.sem_humano_em = marca
    copia_selo = modelos.Lobby.de_dict(lobby_sem_humano.para_dict())
    _checar("round-trip sem_humano_em", copia_selo.sem_humano_em == marca,
            str(copia_selo.sem_humano_em))
    _checar("resumo carrega sem_humano_em",
            lobby_sem_humano.resumo_partida().get("sem_humano_em") == marca.isoformat(),
            str(lobby_sem_humano.resumo_partida().get("sem_humano_em")))


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
# 4c) apelido de IA: pool podado no limite, único e maior que a sala
# ---------------------------------------------------------------------------
def verificar_nomes_ia():
    print("4c) pool de apelidos de IA (limite de 12 caracteres)")
    import ia
    import funcoes_gerais
    from modelos.lobby import MAX_JOGADORES, Lobby
    from modelos.jogador import Jogador

    limite = funcoes_gerais.LIMITE_APELIDO
    # O caminho antigo compunha o nome em runtime e 36% saíam com 9+ caracteres
    # (máx. 14). O pool é podado no import, então a invariante é do CONJUNTO:
    # se alguém mexer nas listas de matéria-prima, o erro aparece aqui.
    estourados = [nome for nome in ia.POOL if len(nome) > limite]
    _checar(f"todo apelido do pool cabe em {limite}", not estourados,
            f"{len(estourados)} estourado(s): {estourados[:5]}")
    _checar("pool sem entradas repetidas", len(set(ia.POOL)) == len(ia.POOL),
            f"{len(ia.POOL)} entradas, {len(set(ia.POOL))} distintas")
    _checar("todo apelido do pool traz o marcador 🤖",
            all(nome.startswith(ia.MARCADOR_IA) for nome in ia.POOL), "")

    # `nome_livre` só acha nome livre se o pool for maior que a sala: é o que
    # garante o retorno em caminho finito e o que impede um bot sem apelido
    # (que trava `pode_iniciar` em `sem_apelido`).
    maior_sala = MAX_JOGADORES + funcoes_gerais.MAX_ESPECTADORES
    _checar(f"pool maior que a sala ({len(ia.POOL)} > {maior_sala})",
            len(ia.POOL) > maior_sala, f"pool com {len(ia.POOL)} entradas")

    lobby = Lobby(sala_id="nomes", lobby_numero=1)
    # Sala lotada de bots: cada um tem que sair com nome próprio, dentro do
    # limite — é o caminho que `adicionar_bots` percorre de verdade.
    for _ in range(MAX_JOGADORES):
        jogador = Jogador.criar_ia(3, ia.nome_livre(lobby))
        lobby.adicionar_jogador(jogador)
    apelidos = [jogador.username for jogador in lobby.jogadores]
    _checar(f"{MAX_JOGADORES} bots na sala -> {MAX_JOGADORES} apelidos distintos",
            len(set(apelidos)) == len(apelidos), str(apelidos))
    _checar(f"{MAX_JOGADORES} bots na sala -> todo apelido no limite",
            all(isinstance(nome, str) and 0 < len(nome) <= limite
                for nome in apelidos), str(apelidos))
    # Nome Explicitamente ocupado: `nome_livre` pula e devolve outro do pool.
    ocupado = lobby.jogadores[0].username
    _checar("apelido ocupado -> devolve outro do pool",
            ia.nome_livre(lobby, ocupado) != ocupado, "")
    # `nome_livre` sem candidato também nunca devolve `None`.
    _checar("nome_livre sem candidato nunca devolve None (bot sem apelido trava a partida)",
            all(ia.nome_livre(lobby) is not None for _ in range(50)), "")

    # Fase 76: o marcador do substituto. É o mesmo `🤖` do bot natural, no mesmo
    # campo (o apelido guardado) — precisa ser idempotente nos dois sentidos,
    # senão o `🤖` se duplica na troca ou sobra no nome de quem voltou.
    _checar("marcador: aplicar/verificar/remover é ida e volta",
            ia.tem_marcador_ia(ia.aplicar_marcador_ia("Ana"))
            and ia.remover_marcador_ia(ia.aplicar_marcador_ia("Ana")) == "Ana"
            and ia.aplicar_marcador_ia("Ana") == f"{ia.MARCADOR_IA}Ana", "")
    _checar("marcador: idempotente (não duplica o 🤖)",
            ia.aplicar_marcador_ia(ia.aplicar_marcador_ia("Ana")) == f"{ia.MARCADOR_IA}Ana"
            and ia.remover_marcador_ia(ia.remover_marcador_ia(f"{ia.MARCADOR_IA}Ana")) == "Ana", "")
    _checar("marcador: tolera apelido vazio (jogador sem nome não quebra a troca)",
            ia.aplicar_marcador_ia(None) is None and ia.remover_marcador_ia(None) is None, "")
    # Substituto marcado colide com um bot natural de mesmo nome: dois cards com
    # o mesmo apelido dariam o mesmo id no DOM, então o nome fica sem marcador.
    colisao = Lobby(sala_id="colide", lobby_numero=1)
    humana = Jogador(client_id="s1")
    humana.username = "Ana"
    colisao.adicionar_jogador(humana)
    bot = Jogador.criar_ia(3, f"{ia.MARCADOR_IA}Ana")
    colisao.adicionar_jogador(bot)
    humana.is_ia = True
    _checar("marcador: colisão de apelido mantém o nome (não duplica id de card)",
            ia.marcar_substituto(colisao, humana) == "Ana", "")
    # Sem colisão, marca: é o caminho normal da substituição.
    livre = Lobby(sala_id="marca", lobby_numero=1)
    outra = Jogador(client_id="s2")
    outra.username = "Bia"
    livre.adicionar_jogador(outra)
    alvo = Jogador(client_id="s3")
    alvo.username = "Ana"
    livre.adicionar_jogador(alvo)
    _checar("marcador: substituto sem colisão ganha o 🤖 guardado",
            ia.marcar_substituto(livre, alvo) == f"{ia.MARCADOR_IA}Ana", "")


# ---------------------------------------------------------------------------
# 4d) bot prudente (Fase 76): o arquétipo que joga pelo humano desconectado
# ---------------------------------------------------------------------------
def _mesa_do_prudente(dados_bot, dados_rival, aposta, com_coringa=True, nivel=3):
    """
    Mesa de 2 (humano + bot prudente) com a aposta `aposta` já na mesa, para os
    testes do turno do prudente. O turno é montado direto (como no honeypot do
    `anti_fraude`) porque `construir_turno` emite — aqui só o estado interessa;
    o que ele manteria (`coringa_atual_qtd` quando a face é 1) é ajustado à mão
    para a mesa ficar fiel.
    """
    import ia
    from modelos import Jogador, Lobby, Partida, Rodada, Turno

    lobby = Lobby(sala_id="prud", lobby_numero=1)
    humano = Jogador(client_id="humano")
    humano.username = "Ana"
    humano.dados = list(dados_rival)
    humano.dados_qtd = len(dados_rival)
    bot = Jogador.criar_ia(nivel, "🤖 Prudente")
    bot.ia_estilo = ia.ESTILO_PRUDENTE
    bot.dados = list(dados_bot)
    bot.dados_qtd = len(dados_bot)
    lobby.adicionar_jogador(humano)
    lobby.adicionar_jogador(bot)
    partida = Partida(do_lobby=lobby, jogadores=[humano, bot], partida_numero=1,
                      dados_qtd=max(len(dados_bot), len(dados_rival), 1))
    lobby.partidas.append(partida)
    rodada = Rodada(partida=partida, jogadores=[humano, bot], rodada_numero=1,
                    vez_atual=bot, com_coringa=com_coringa)
    partida.rodadas.append(rodada)
    for jogador in (humano, bot):
        jogador.partida_atual = partida
        jogador.rodada_atual = rodada
    if aposta is not None:
        turno = Turno(da_rodada=rodada, dado=aposta[0], jogador=humano,
                      dado_qtd=aposta[1], turno_numero=1)
        rodada.turnos.append(turno)
        rodada.vez_atual = bot
        if aposta[0] == 1:
            rodada.coringa_atual_qtd = aposta[1]
            rodada.coringa_atual_jogador = humano
    return lobby, bot, rodada


def _conjunto_coberto(rodada, jogador):
    """Apostas garantidas pelo PRÓPRIO dado do bot (com o coringa contado)."""
    import ia

    return {aposta for aposta in ia.gerar_apostas_validas(rodada)
            if aposta[1] <= ia.contar_suporte(list(jogador.dados), aposta[0],
                                              rodada.com_coringa)}


def verificar_bot_prudente():
    print("4d) bot prudente (Fase 76): só aposta o que sustenta, chama só o claro")
    import ia
    import simular_ia
    import modelos

    # O estilo é do BOT: um humano que retomou o controle (ou que só entrou em
    # auto-jogar por atraso) não entra no caminho cauteloso.
    bot = modelos.Jogador.criar_ia(3, "🤖 B")
    _checar("bot sem estilo -> repertório de nível", ia.eh_prudente(bot) is False, "")
    bot.ia_estilo = ia.ESTILO_PRUDENTE
    _checar("bot com estilo -> prudente", ia.eh_prudente(bot) is True, "")
    humano = modelos.Jogador(client_id="h")
    humano.ia_estilo = ia.ESTILO_PRUDENTE
    _checar("humano nunca é prudente (mesmo com a flag)",
            ia.eh_prudente(humano) is False, "")

    # Abertura: 1 dado na face de maior suporte — nunca arrisca abrir a rodada.
    _, bot, rodada = _mesa_do_prudente([4, 4, 2], [6, 6, 6], None)
    acao = ia.decidir(bot, rodada, bot.ia_nivel)
    face, qtd = acao.get('dado'), acao.get('quantidade')
    _checar("abertura com 1 dado", acao.get('acao') == 'apostar' and qtd == 1, str(acao))
    _checar("abertura em face que o bot tem",
            ia.contar_suporte(list(bot.dados), face, rodada.com_coringa) >= 1, str(acao))

    # Invariantes de TURNO, numa grade de estados (dados do bot, dados do rival,
    # aposta na mesa). Vale para qualquer arrangement: é a mesma regra.
    # - nunca joga fora das regras;
    # - se existe aposta coberta, escolhe uma delas (risco zero);
    # - sem coberta, cai na MÍNIMA legal — determinística;
    # - desconfia SE E SÓ SE a conta está abaixo do limiar (nenhum impulso).
    casos = 0
    fora_das_regras = []
    fora_das_cobertas = []
    nao_minima = []
    for dados_bot in ([1], [6], [2, 5], [3, 3], [4, 4, 4], [1, 6], [5, 5, 2]):
        for dados_rival in ([1], [6], [2, 5], [3, 3, 1]):
            for aposta in (None, (6, 1), (5, 2), (1, 2), (3, 3), (2, 5)):
                for nivel in (1, 3, 4):
                    casos += 1
                    _, bot, rodada = _mesa_do_prudente(dados_bot, dados_rival, aposta, nivel=nivel)
                    turno_anterior = rodada.turnos[-1] if rodada.turnos else None
                    acao = ia.decidir(bot, rodada, nivel)
                    if acao.get('acao') != 'apostar':
                        # Desconfiança tem que ser a conta e só a conta.
                        p = ia._probabilidade_ultima(rodada, bot, turno_anterior, nivel)
                        limiar = ia._limiar_prudente(rodada)
                        if p is None or not p < limiar:
                            fora_das_regras.append(f"desconfiou com P={p} limiar={limiar}")
                        continue
                    face, qtd = acao['dado'], acao['quantidade']
                    if not rodada.jogada_valida(face, qtd, turno_anterior,
                                                 len(rodada.turnos) + 1):
                        fora_das_regras.append(f"jogada ilegal {face}/{qtd}")
                        continue
                    cobertas = _conjunto_coberto(rodada, bot)
                    if cobertas:
                        if (face, qtd) not in cobertas:
                            fora_das_cobertas.append(f"{face}/{qtd} vs {sorted(cobertas)}")
                    else:
                        minimas = min(ia.gerar_apostas_validas(rodada),
                                      key=ia._chave_de_exposicao)
                        if (face, qtd) != minimas:
                            nao_minima.append(f"{face}/{qtd} vs min {minimas}")
    _checar(f"{casos} turnos do prudente: jogada legal e desconfiança só com a conta clara",
            not fora_das_regras, "; ".join(fora_das_regras[:3]))
    _checar(f"{casos} turnos: nunca aposta acima do próprio dado (havia coberta)",
            not fora_das_cobertas, "; ".join(fora_das_cobertas[:3]))
    _checar(f"{casos} turnos: sem coberta, cai na jogada mínima",
            not nao_minima, "; ".join(nao_minima[:3]))

    # O nível não escolhe a jogada, ele afina só a CONTA da desconfiança: duas
    # mesas idênticas, níveis 1 e 4, jogam do mesmo conjunto permitido (a coberta
    # ou a mínima) e, quando não há coberta — caminho determinístico — caem na
    # jogada EXATA igual. (A variadinha entre as duas cobertas de menor
    # exposição é a única fonte de diferença, por desenho.)
    pares = 0
    fora_do_permitido = []
    minima_iguais = 0
    minima_pares = 0
    for dados_bot, dados_rival, aposta in (([2, 5], [6, 6, 6], (6, 1)),
                                           ([1, 1], [3, 3, 3], (5, 2)),
                                           ([3, 3, 3], [2, 2, 2], (1, 2)),
                                           ([5, 1, 1], [4, 4, 4], (6, 3)),
                                           ([6, 6], [2, 2], (4, 1))):
        _, bot1, rodada1 = _mesa_do_prudente(dados_bot, dados_rival, aposta, nivel=1)
        _, bot4, rodada4 = _mesa_do_prudente(dados_bot, dados_rival, aposta, nivel=4)
        a1, a4 = ia.decidir(bot1, rodada1, 1), ia.decidir(bot4, rodada4, 4)
        if a1.get('acao') != 'apostar' or a4.get('acao') != 'apostar':
            continue  # um nível achou a aposta clara: a conta decide, não a jogada
        cobertas = _conjunto_coberto(rodada1, bot1)
        permitidas = cobertas or {min(ia.gerar_apostas_validas(rodada1),
                                      key=ia._chave_de_exposicao)}
        pares += 1
        for acao in (a1, a4):
            if (acao['dado'], acao['quantidade']) not in permitidas:
                fora_do_permitido.append(f"{acao['dado']}/{acao['quantidade']} vs {sorted(permitidas)}")
        if not cobertas:
            minima_pares += 1
            minima_iguais += 1 if a1 == a4 else 0
    _checar("nível não amplia a exposição do prudente (só a leitura da desconfiança)",
            pares > 0 and not fora_do_permitido, "; ".join(fora_do_permitido[:3]))
    _checar("sem coberta, a jogada do prudente é a mesma em qualquer nível",
            minima_pares > 0 and minima_iguais == minima_pares,
            f"{minima_iguais}/{minima_pares} iguais")

    # Anti-arrastão: uma mesa SÓ de prudentes tem que FECHAR. O prudente quase
    # nunca chama e nunca infla a aposta — se a rodada não terminar sozinha, a
    # sala fica presa; o limiar crescente é o que impede, e este teste é o que
    # prova (rodadas_max é o teto do `jogar`).
    salvo = _salvar_emit()
    try:
        _silenciar_emit()  # o `jogar` roda fora de request: emit não tem room
        vencedor = simular_ia.jogar([2, 2, 3, 3], 3, True, estilo=ia.ESTILO_PRUDENTE)
        _checar("mesa só de prudentes termina (a rodada não arrasta)",
                vencedor in (2, 3), f"vencedor nível {vencedor}")
    except RuntimeError as erro:
        _checar("mesa só de prudentes termina (a rodada não arrasta)", False, str(erro))
    finally:
        _restaurar_emit(salvo)


def verificar_tempo_pensamento():
    print("4e) tempo de pensamento: humano na mesa atrasa, mesa só de bots acelera")
    import narrador

    # Determiniza o sorteio da faixa (randbelow(n) -> 0 => atraso = faixa[0]) e
    # restaura o `secrets` original no fim. O que se afirma é a RELAÇÃO entre os
    # três caminhos, não o valor: com humano é mais lento, só bots mais rápido.
    original = narrador.secrets
    narrador.secrets = type("FakeSecrets", (), {"randbelow": staticmethod(lambda n: 0)})()
    try:
        base = narrador.FAIXAS_PENSAMENTO[3][0]
        com_humano = narrador.tempo_pensamento(3, jogador=None, so_ias=False)
        so_ias = narrador.tempo_pensamento(3, jogador=None, so_ias=True)
        _checar("humano na mesa multiplica a pausa por FATOR_COM_HUMANO",
                com_humano == int(base * narrador.FATOR_COM_HUMANO) > base,
                f"base={base} com_humano={com_humano}")
        _checar("mesa só de bots acelera (0.70) e fica abaixo do humano",
                so_ias == int(base * 0.70) < com_humano,
                f"so_ias={so_ias} com_humano={com_humano}")
        # A personalidade continua modulando dentro de cada regime.
        bot = type("Bot", (), {"is_ia": True, "ia_risco": 1.0, "ia_agressividade": 1.0})()
        agressivo = narrador.tempo_pensamento(3, jogador=bot, so_ias=False)
        _checar("personalidade ousada/agressiva decide mais rápido",
                agressivo < com_humano, f"agressivo={agressivo} com_humano={com_humano}")
    finally:
        narrador.secrets = original


# ---------------------------------------------------------------------------
# 4f) embaralhamento da ordem de jogadores (Fase 81)
# ---------------------------------------------------------------------------
# Tres modos via config `embaralhar`:
#   'chegada' — ordem de chegada na lobby (sem embaralhar)
#   'partida' — embaralha uma vez em construir_partida
#   'rodada'  — embaralha a cada construir_rodada
# A regra de quem começa (vez_atual) não muda em nenhum modo. No verificado,
# a permutação vem da seed (seed.indice_ordem, com rodada_num) — "provably
# fair"; no legado usa secrets.
def verificar_embaralhamento():
    print("4f) embaralhamento da ordem (Fase 81 — chegada/partida/rodada)")
    import seed
    import modelos
    from modelos.jogador import Jogador

    sala, total = "emb", 4
    seed_a = seed.derivar_seed('servidor', 'nonce_srv_a',
                               {'c1': 'n1', 'c2': 'n2', 'c3': 'n3', 'c4': 'n4'})
    seed_b = seed.derivar_seed('servidor', 'nonce_srv_b',
                               {'c1': 'n1', 'c2': 'n2', 'c3': 'n3', 'c4': 'n4'})
    oa = seed.indice_ordem(seed_a, sala, 1, total)
    _checar("indice_ordem: permutação válida [0..n-1] sem repetição",
            sorted(oa) == list(range(total)), str(oa))
    _checar("indice_ordem: determinismo (mesma seed/sala/partida/rodada → igual)",
            oa == seed.indice_ordem(seed_a, sala, 1, total), str(oa))
    _checar("indice_ordem: seed diferente → ordem diferente (alta prob)",
            oa != seed.indice_ordem(seed_b, sala, 1, total))
    _checar("indice_ordem: não é identidade (realmente embaralha)",
            oa != [0, 1, 2, 3], str(oa))
    _checar("indice_ordem: partida diferente → ordem diferente",
            oa != seed.indice_ordem(seed_a, sala, 2, total))
    _checar("indice_ordem: rodada diferente → ordem diferente",
            oa != seed.indice_ordem(seed_a, sala, 1, total, rodada_num=2))
    _checar("indice_ordem: 0/1 jogador → ordem neutra",
            seed.indice_ordem(seed_a, sala, 1, 0) == []
            and seed.indice_ordem(seed_a, sala, 1, 1) == [0])

    emit_salvo = _salvar_emit()
    _silenciar_emit()
    try:
        def montar_lobby(nome_sala="emb_l"):
            lby = modelos.Lobby(sala_id=nome_sala, lobby_numero=1)
            for cid, nome in (("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")):
                j = Jogador(client_id=cid)
                j.username = nome
                j.pronto = True
                lby.adicionar_jogador(j)
            lby.jogadores[0].master = True
            return lby

        ids_em_ordem = lambda lby: [j.client_id for j in lby.jogadores]

        # --- Modo 'chegada': NADA é embaralhado -----------------------
        lobby_c = montar_lobby("emb_chegada")
        lobby_c.definir_config({'embaralhar': 'chegada'})
        partida_c = lobby_c.construir_partida(dados_qtd=1)
        _checar("chegada: partida == lobby (ordem de chegada preservada)",
                [j.client_id for j in partida_c.jogadores] == ids_em_ordem(lobby_c))
        rodada_c = partida_c.construir_rodada()
        _checar("chegada: rodada não reembaralha",
                [j.client_id for j in partida_c.jogadores] == ids_em_ordem(lobby_c))

        # --- Modo 'partida': embaralha uma vez, fixo por rodada --------
        lobby_p = montar_lobby("emb_partida")
        lobby_p.definir_config({'embaralhar': 'partida'})
        partida_p = lobby_p.construir_partida(dados_qtd=6)
        ordem_p = [j.client_id for j in partida_p.jogadores]
        _checar("partida: partida embaralha (ordem !== lobby)",
                ordem_p != ids_em_ordem(lobby_p))
        _checar("partida: lobby preserva ordem de chegada",
                ids_em_ordem(lobby_p) == ["a", "b", "c", "d"])
        rodada_p1 = partida_p.construir_rodada()
        _checar("partida: rodada 1 não reembaralha (ordem fixa)",
                [j.client_id for j in partida_p.jogadores] == ordem_p)
        # Finge o fim da rodada 1 e inicia rodada 2 — a partida não reembaralha
        # de novo; ordem fixa por toda a partida.
        rodada_p1.perdedor = partida_p.jogadores[0]
        rodada_p1.vencedor = partida_p.jogadores[1]
        rodada_p2 = partida_p.construir_rodada()
        _checar("partida: rodada 2 mantém a mesma ordem da partida",
                [j.client_id for j in partida_p.jogadores] == ordem_p)

        # --- Modo 'rodada': embaralha de novo a cada rodada ------------
        # Usa seed_info para tornar o embaralhamento determinístico (o
        # caminho não-verificado com secrets.randbelow é um Fisher-Yates
        # padrão; a probabilidade de identity com 4 jogadores é 1/24, o
        # que deixaria o teste fraco).
        seed_final_r = seed.derivar_seed('servidor', 'nonce_srv_r',
                                        {'a': 'na', 'b': 'nb', 'c': 'nc', 'd': 'nd'})
        seed_info_r = {'seed_final': seed_final_r, 'fonte': 'servidor',
                       'entropia_externa': 'nonce_srv_r', 'participantes': [],
                       'nonce_servidor': 'nonce_srv_r',
                       'compromisso_servidor': seed.compromisso('nonce_srv_r')}
        lobby_r = montar_lobby("emb_rodada")
        lobby_r.definir_config({'embaralhar': 'rodada', 'verificacao_ativa': True})
        partida_r = lobby_r.construir_partida(dados_qtd=6, seed_info=seed_info_r)
        _checar("rodada: construir_partida NÃO embaralha (deixa pro rodada)",
                [j.client_id for j in partida_r.jogadores] == ids_em_ordem(lobby_r))
        # Rodada 1: embaralha usando indice_ordem(seed, rodada=1)
        rodada_r1 = partida_r.construir_rodada()
        ordem_r1 = seed.indice_ordem(seed_final_r, "emb_rodada", 1, 4, rodada_num=1)
        esperado_r1 = [lobby_r.jogadores[i].client_id for i in ordem_r1]
        _checar("rodada: rodada 1 embaralha (indice_ordem, rodada=1)",
                [j.client_id for j in partida_r.jogadores] == esperado_r1)
        # Rodada 2: reembaralha usando indice_ordem(seed, rodada=2)
        rodada_r1.perdedor = partida_r.jogadores[0]
        rodada_r1.vencedor = partida_r.jogadores[1]
        # Captura a ordem da rodada 1 (após possível remoção de perdedor):
        ordem_r1_atual = [j.client_id for j in partida_r.jogadores]
        rodada_r2 = partida_r.construir_rodada()
        ordem_r2 = seed.indice_ordem(seed_final_r, "emb_rodada", 1, 4, rodada_num=2)
        esperado_r2 = [ordem_r1_atual[i] for i in ordem_r2]
        _checar("rodada: rodada 2 reembaralha (ordem !== rodada 1, ALTA PROB)",
                [j.client_id for j in partida_r.jogadores] == esperado_r2
                and esperado_r2 != esperado_r1)

        # --- Verificado: determinismo por rodada ----------------------
        seed_final = seed.derivar_seed('servidor', 'nonce_srv_v',
                                       {'a': 'na', 'b': 'nb', 'c': 'nc', 'd': 'nd'})
        lobby_v = montar_lobby("emb_verif")
        lobby_v.definir_config({'embaralhar': 'rodada', 'verificacao_ativa': True})
        seed_info = {'seed_final': seed_final, 'fonte': 'servidor',
                     'entropia_externa': 'nonce_srv_v', 'participantes': [],
                     'nonce_servidor': 'nonce_srv_v',
                     'compromisso_servidor': seed.compromisso('nonce_srv_v')}
        pv1 = lobby_v.construir_partida(dados_qtd=6, seed_info=seed_info)
        # Quem começa não muda: jogador_sorteado vale para a partida inteira.
        _checar("verificado: jogador_sorteado na partida (quem começa não muda)",
                pv1.jogador_sorteado is not None)
        rodada_v1 = pv1.construir_rodada()
        ordem1 = seed.indice_ordem(seed_final, "emb_verif", 1, 4, rodada_num=1)
        esperado1 = [lobby_v.jogadores[i].client_id for i in ordem1]
        _checar("verificado: rodada 1 segue indice_ordem(seed, rodada=1)",
                [j.client_id for j in pv1.jogadores] == esperado1,
                f"{[j.username for j in pv1.jogadores]} vs {esperado1}")
        # Captura a ordem da rodada 1 ANTES de construir rodada 2: rodada 2
        # embaralha a sobre a lista DA RODADA 1 (não sobre a original).
        ordem_r1_ids = [j.client_id for j in pv1.jogadores]
        rodada_v1.perdedor = pv1.jogadores[0]
        rodada_v1.vencedor = pv1.jogadores[1]
        rodada_v2 = pv1.construir_rodada()
        ordem2 = seed.indice_ordem(seed_final, "emb_verif", 1, 4, rodada_num=2)
        esperado2 = [ordem_r1_ids[i] for i in ordem2]
        _checar("verificado: rodada 2 segue indice_ordem(seed, rodada=2) — diferente da 1",
                [j.client_id for j in pv1.jogadores] == esperado2
                and esperado2 != esperado1)
        _checar("verificado: jogador_sorteado ainda em jogo após rodada 2",
                pv1.jogador_sorteado in pv1.jogadores)
    finally:
        _restaurar_emit(emit_salvo)

    _ok("Fase 81 (sorteo de ordem — 3 modos + determinismo por rodada)")


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
    verificar_paridade_emojis()
    verificar_boot()
    verificar_store_producao()
    verificar_gevent()
    verificar_roundtrip()
    verificar_tema()
    verificar_nomes_ia()
    verificar_bot_prudente()
    verificar_tempo_pensamento()
    verificar_embaralhamento()
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
