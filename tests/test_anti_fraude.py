"""Testes da Fase 59: anti-fraude, limite por IP e observabilidade."""
import time

from tests.base import (
    app, socketio, modulo_app, modulo_store, modulo_app as _app_modulo,
    _checar, _ok, _falhou, _limpar, subprocess, sys, RAIZ,
)


# Funções isoladas para testes unitários (sem dependência de store/socket).
import anti_fraude
import observabilidade
import store
import ia


def _testar_observabilidade():
    """_redigir remove campos sensíveis e log_redigido não estoura."""
    original = {'chave_secreta': 'abc123', 'ip': '1.2.3.4',
                'client_id': 'sid-teste', 'motivo': {'chave': 'msg.x'}}
    redigido = observabilidade._redigir(original)
    _checar('redigir_remove_chave_secreta',
            redigido.get('chave_secreta') is None)
    _checar('redigir_mantem_ip', redigido.get('ip') == '1.2.3.4')
    observabilidade.log_redigido(client_id='test', dados=original)
    observabilidade.log_advertencia('aviso de teste', chave='valor')
    _ok('log_nao_estourou')


def _testar_anti_fraude_acoes():
    """Ações rápidas (<200ms) disparam detecção de aposta_rapida_demais."""
    anti_fraude.limpar('sid-teste')
    anti_fraude.registrar_acao('sid-teste', 'aposta')
    time.sleep(0.05)  # <200ms
    deteccoes = anti_fraude.registrar_acao('sid-teste', 'aposta')
    _checar('aposta_rapida_demais',
            'aposta_rapida_demais' in deteccoes,
            f"esperava 'aposta_rapida_demais' em {deteccoes}")
    anti_fraude.limpar('sid-teste')


def _testar_anti_fraude_rajada():
    """3+ desconfianças em 5s dispara detecção de rajada."""
    anti_fraude.limpar('sid-rajada')
    for _ in range(2):
        anti_fraude.registrar_acao('sid-rajada', 'desconfiar')
        time.sleep(0.01)
    deteccoes = anti_fraude.registrar_acao('sid-rajada', 'desconfiar')
    _checar('desconfianca_em_rajada',
            'desconfianca_em_rajada' in deteccoes,
            f"esperava 'desconfianca_em_rajada' em {deteccoes}")
    anti_fraude.limpar('sid-rajada')


def _testar_anti_fraude_binomial():
    """Taxa de acerto muito alta em apostas (>85%) dispara binomial."""
    anti_fraude.limpar('sid-binomial')
    for _ in range(17):
        anti_fraude.marcar_resultado_aposta('sid-binomial', True)
    # 17/17 até aqui: abaixo da amostra mínima (20) — não deve disparar
    _checar('binomial_abaixo_minimo',
            not anti_fraude.marcar_resultado_aposta('sid-binomial', False))
    # 18/19 ≈ 94,7% mas ainda com menos de 20 amostras — não deve disparar
    _checar('binomial_ainda_abaixo_minimo',
            not anti_fraude.marcar_resultado_aposta('sid-binomial', True))
    # 20ª amostra: 19/20 = 95% — acima do limiar (85%) — dispara
    _checar('binomial_atinge_limiar',
            anti_fraude.marcar_resultado_aposta('sid-binomial', True))
    anti_fraude.limpar('sid-binomial')


def _testar_delay_adicional():
    """Jogador suspeito recebe delay de 1500ms; normal recebe 0."""
    import modelos.jogador as j_mod
    j = j_mod.Jogador('sid-delay')
    _checar('delay_normal_zero', anti_fraude.delay_adicional(j) == 0)
    j.suspeito = 'aposta_rapida_demais'
    _checar('delay_suspeito_1500', anti_fraude.delay_adicional(j) == 1500)


def _testar_poda():
    """Fase 59: o registro por client_id (sid) tem teto — o processo persistente
    da VPS não acumula uma entrada por conexão para sempre."""
    original = anti_fraude.MAX_CLIENTES
    try:
        anti_fraude.MAX_CLIENTES = 5
        for i in range(30):
            anti_fraude.registrar_acao(f'podar-{i}', 'aposta')
        _checar('anti_fraude_poda_teto', len(anti_fraude._acoes) <= 5,
                f"esperava <= 5, {len(anti_fraude._acoes)}")
    finally:
        anti_fraude.MAX_CLIENTES = original
        for i in range(30):
            anti_fraude.limpar(f'podar-{i}')


def _testar_ip_do_cliente():
    """Fase 59: um header forjado que não é IP não vira chave do índice de IPs
    (cai no REMOTE_ADDR validado)."""
    with app.test_request_context(
            '/', headers={'Cf-Connecting-Ip': 'nao-e-ip',
                          'X-Forwarded-For': 'tambem-nao'},
            environ_base={'REMOTE_ADDR': '198.51.100.9'}):
        _checar('ip_forjado_cai_no_remote_addr',
                modulo_app._ip_do_cliente() == '198.51.100.9',
                modulo_app._ip_do_cliente())
    with app.test_request_context('/', headers={'Cf-Connecting-Ip': '203.0.113.9'}):
        _checar('ip_valido_do_header',
                modulo_app._ip_do_cliente() == '203.0.113.9',
                modulo_app._ip_do_cliente())


def _testar_captcha_misconfig():
    """Fase 59 (Cloudflare Turnstile): a separação WIDGET x ATIVO —
    - sem sitekey: nada liga (CAPTCHA_WIDGET False);
    - só sitekey (frontend/Vercel): renderiza o widget mas NÃO valida;
    - sitekey + secret (API/VPS): valida o token.
    Pela metade nunca derruba os connects por engano."""
    base = (
        "import os;"
        "os.environ['DADINHO_STORE']='memoria';"
        "os.environ['DADINHO_CAPTCHA_ATIVO']='1';"
        "[os.environ.pop(v, None) for v in ('VERCEL','UPSTASH_REDIS_REST_URL',"
        "'UPSTASH_REDIS_REST_TOKEN','DADINHO_REDIS_URL','DADINHO_MESSAGE_QUEUE',"
        "'TURNSTILE_SECRET','DADINHO_TURNSTILE_SITEKEY')];"
    )
    sem_sitekey = subprocess.run(
        [sys.executable, "-c", base +
         "import app; print('CAPTCHA', app.CAPTCHA_WIDGET, app.CAPTCHA_ATIVO)"],
        cwd=RAIZ, capture_output=True, text=True, timeout=60)
    _checar('captcha_sem_sitekey_nada_liga',
            'CAPTCHA False False' in (sem_sitekey.stdout or ''),
            (sem_sitekey.stderr or sem_sitekey.stdout or '').strip()[-300:])
    so_widget = subprocess.run(
        [sys.executable, "-c", base +
         "os.environ['DADINHO_TURNSTILE_SITEKEY']='site-x';"
         "import app; print('CAPTCHA', app.CAPTCHA_WIDGET, app.CAPTCHA_ATIVO)"],
        cwd=RAIZ, capture_output=True, text=True, timeout=60)
    _checar('captcha_sitekey_sem_secret_so_widget',
            'CAPTCHA True False' in (so_widget.stdout or ''),
            (so_widget.stderr or so_widget.stdout or '').strip()[-300:])
    completo = subprocess.run(
        [sys.executable, "-c", base +
         "os.environ['DADINHO_TURNSTILE_SITEKEY']='site-x';"
         "os.environ['TURNSTILE_SECRET']='sec-y';"
         "import app; print('CAPTCHA', app.CAPTCHA_WIDGET, app.CAPTCHA_ATIVO)"],
        cwd=RAIZ, capture_output=True, text=True, timeout=60)
    _checar('captcha_completo_valida',
            'CAPTCHA True True' in (completo.stdout or ''),
            (completo.stderr or completo.stdout or '').strip()[-300:])


def _testar_limite_ip():
    """
    Abre sockets e valida o limite por IP. Usa um `Cf-Connecting-Ip` próprio para
    o teste (caminho usado atrás do Cloudflare Tunnel) e altera o limiar
    diretamente no módulo para não depender de env no boot.
    """
    from tests.base import _limpar

    _app_modulo.LIMITE_SOCKETS_IP = 3
    ip_teste = '203.0.113.7'
    cabecalho = {"Cf-Connecting-Ip": ip_teste}
    clientes = []
    try:
        for i in range(10):
            try:
                c = socketio.test_client(
                    app, query_string=f"sala=af_ip_{i}", headers=cabecalho)
            except Exception:
                c = None
            clientes.append(c)

        conectados = sum(1 for c in clientes if c and c.is_connected())
        _checar('limite_ip_3_conectados', conectados == 3,
                f"esperava 3 conectados, {conectados}")
        _checar('indice_ip_com_3_sids',
                len(store.sids_do_ip(ip_teste)) == 3,
                f"sids: {store.sids_do_ip(ip_teste)}")

        # Desconecta o primeiro conectado e tenta abrir um novo
        for c in clientes:
            if c and c.is_connected():
                c.disconnect()
                break
        try:
            novo = socketio.test_client(
                app, query_string="sala=af_ip_novo", headers=cabecalho)
        except Exception:
            novo = None
        _checar('limite_ip_desconectar_libera_vaga',
                novo and novo.is_connected(),
                f"novo socket deve conectar após desconexão (got {novo})")
        if novo:
            novo.disconnect()

    finally:
        # Desconecta ANTES de zerar o limiar: o disconnect devolve a vaga no
        # índice de IPs (o handler só limpa com o limite/captcha ativos).
        for c in clientes:
            if c and c.is_connected():
                c.disconnect()
        _app_modulo.LIMITE_SOCKETS_IP = 0
        _limpar()
        _checar('indice_ip_limpo_apos_desconexoes',
                not store.sids_do_ip(ip_teste),
                f"sids restantes: {store.sids_do_ip(ip_teste)}")


class _RNGDeterministico:
    """Substituto de `secrets` para a IA: sequência fixa e reproduzível entre rodadas."""

    def __init__(self, valor):
        self._valor = int(valor)

    def randbelow(self, n):
        if not isinstance(n, int) or n <= 0:
            return 0
        return min(self._valor, n - 1)

    def choice(self, seq):
        return seq[0]


def _montar_rodada_ia_limpa(escondidos, dados_bot, aposta):
    """
    Sala com 1 humano + 1 bot e uma rodada em andamento. O parâmetro
    `escondidos` preenche o que o servidor sabe mas um jogador não deveria ver
    (`todos_os_dados`/`dados_por_jogador` da rodada atual) — do jeito que o
    teste quer: corrompido com faces-sentinela.
    """
    from modelos import Lobby, Partida, Rodada, Turno, Jogador

    lobby = Lobby(sala_id="ia_limpa", lobby_numero=1)
    humano = Jogador(client_id="humano-1")
    humano.username = "Fulano"
    humano.dados_qtd = len(escondidos)
    humano.dados = list(escondidos)
    bot = Jogador.criar_ia(3, "🤖 Bot")
    bot.dados_qtd = len(dados_bot)
    bot.dados = list(dados_bot)
    # Personalidade fixa: comparações entre cenários precisam do mesmo bot.
    bot.ia_risco = 0.5
    bot.ia_agressividade = 0.5
    lobby.adicionar_jogador(humano)
    lobby.adicionar_jogador(bot)
    partida = Partida(do_lobby=lobby, jogadores=[humano, bot], partida_numero=1,
                      dados_qtd=len(dados_bot))
    lobby.partidas.append(partida)
    rodada = Rodada(partida=partida, jogadores=[humano, bot], rodada_numero=1,
                    vez_atual=humano, com_coringa=True)
    partida.rodadas.append(rodada)
    for jogador in (humano, bot):
        jogador.partida_atual = partida
        jogador.rodada_atual = rodada
        jogador.dados_qtd = len(jogador.dados)
    face, qtd = aposta  # aposta pública feita pelo humano
    turno = Turno(da_rodada=rodada, dado=face, jogador=humano, dado_qtd=qtd, turno_numero=1)
    rodada.turnos.append(turno)
    humano.turno_atual = turno
    humano.turnos.append(turno)
    rodada.vez_atual = bot
    rodada.todos_os_dados = list(escondidos)
    rodada.dados_por_jogador = {humano.client_id: list(escondidos),
                                bot.client_id: list(dados_bot)}
    return lobby, bot, rodada


def _testar_ia_nao_espiona():
    """
    Honeypot: a IA decide usando só dados próprios + informação pública. Monta
    a rodada atual duas vezes com os dados escondidos corrompidos de formas
    opostas (um mundo onde a verdade estaria nos escondidos, outro onde não);
    com o RNG da IA travado, a decisão tem que ser IDÊNTICA nos dois mundos.
    Se algum dia o motor ler `todos_os_dados`/`dados_por_jogador` da rodada
    em andamento, a corrupção muda a decisão e o teste falha.
    """
    # (dados_do_bot, aposta(face, qtd), escondidos_A, escondidos_B)
    # Em cada cenário, A deixa a aposta mentirosa e B a torna verdadeira:
    # se o motor lesse os escondidos, a decisão mudaria de um mundo pro outro.
    # Cenário 1: apoio baixo -> honestamente desconfia nos dois.
    # Cenário 2: apoio alto -> honestamente responde com outra aposta.
    cenarios = [
        ([1, 2, 3], (5, 4), [6, 6, 6], [5, 5, 5]),
        ([5, 5, 1], (5, 5), [2, 2, 2], [5, 5, 5]),
    ]
    original = ia.secrets
    try:
        for nivel in (1, 2, 3, 4):
            for rng_valor in (0, 99):
                for idx, (dados_bot, aposta, escondidos_a, escondidos_b) in enumerate(cenarios):
                    _, bot_a, rodada_a = _montar_rodada_ia_limpa(escondidos_a, dados_bot, aposta)
                    _, bot_b, rodada_b = _montar_rodada_ia_limpa(escondidos_b, dados_bot, aposta)
                    ia.secrets = _RNGDeterministico(rng_valor)
                    decisao_a = ia.decidir(bot_a, rodada_a, nivel)
                    decisao_b = ia.decidir(bot_b, rodada_b, nivel)
                    _checar(f'ia_nao_espiona_n{nivel}_rng{rng_valor}_c{idx}',
                            decisao_a == decisao_b,
                            f'A: {decisao_a} | B: {decisao_b}')
    finally:
        ia.secrets = original


def rodar():
    """Executa todos os testes da Fase 59 e devolve True se OK."""
    _testar_observabilidade()
    _testar_anti_fraude_acoes()
    _testar_anti_fraude_rajada()
    _testar_anti_fraude_binomial()
    _testar_delay_adicional()
    _testar_poda()
    _testar_ip_do_cliente()
    _testar_captcha_misconfig()
    _testar_limite_ip()
    _testar_ia_nao_espiona()
    return True