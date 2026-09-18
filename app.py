# Fase 61: motor cooperativo opt-in por env (VPS). O worker `gevent` do gunicorn
# já aplica `monkey.patch_all()` ANTES de importar o app; este guard só cobre o
# dev local (`python app.py` com DADINHO_ASYNC_MODE=gevent). O patch é
# idempotente e precisa vir ANTES dos imports de socket/ssl/threading em runtime
# (Flask, redis, socketio) — por isso fica no topo, antes de tudo. O motor é
# SÓ gevent (ADR-006); eventlet não está nas dependências.
import os as _os

_async_mode_lido = _os.environ.get("DADINHO_ASYNC_MODE", "threading").strip().lower()
if _async_mode_lido == "gevent":
    from gevent import monkey as _monkey_gevent
    if not _monkey_gevent.is_module_patched("socket"):
        _monkey_gevent.patch_all()
del _async_mode_lido, _os

from flask import Flask, Response, make_response, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from funcoes_gerais import (buscar_lobby_pelo_client_id, mudar_pagina, normalizar_sala, obter_sala,
                            atualizar_lista_usuarios, montar_payload_lista_usuarios, remover_sala,
                            salvar_sala, validar_input, enviar_snapshot_sala, listar_resumos_partidas,
                            registrar_cliente, desregistrar_cliente, sala_do_cliente, tem_cooldown,
                            gerar_codigo_sala, GRACE_RECONEXAO_SEGUNDOS, MAX_ESPECTADORES, SALA_PADRAO,
                            emitir_status_conferencia, emitir_status_vitoria, emitir_status_rolagem,
                            emitir_dispatcher_turno)
from modelos import Jogador
from store import trancar_sala, trancar_sala_distribuida, esquecer_sala
from datetime import datetime
from socketio.manager import Manager as GerenciadorSocketIOBase
import anti_fraude
import functools
import hmac
import http.client
import ipaddress
import json
import os
import secrets
import socketio as pacote_socketio
import store
import ia
import narrador
import observabilidade
import tema
import threading
import urllib.parse

app = Flask(__name__)
# Fase 27 (I3): sem `DADINHO_SECRET_KEY` definida, uma chave aleatória por
# processo (a sessão não é usada, então não há requisito de estabilidade entre
# requests). Sempre substituir pelo valor fixo comodado que vazava de um deploy
# para o outro.
app.secret_key = os.environ.get("DADINHO_SECRET_KEY") or secrets.token_hex(32)


@app.after_request
def _cache_estaticos(resposta):
    """
    Fase 27 (I6): os estáticos de /static/ passam pelo catch-all do Flask sem
    header de cache (a Vercel não os serve como arquivo estático com o builder
    @vercel/python). Sem fingerprint nos URLs, um max-age longo fazia navegador
    e CDN (Cloudflare à frente do domínio) servirem JS/CSS velhos até 24h após
    um deploy — HTML novo + estático velho = página quebrada. `no-cache,
    must-revalidate` força revalidação por ETag (304) a cada carga: conteúdo do
    deploy atual sempre, sem custo.
    """
    if request.path.startswith('/static/'):
        resposta.headers['Cache-Control'] = 'public, no-cache, must-revalidate'
    return resposta

# Janelas de rate limit leve por sid (Fase 7, V2): protegem o free tier da Upstash.
COOLDOWN_ESCRITA = 0.5
COOLDOWN_BUSCA = 2.0

# Nível de IA usado na jogada automática de um humano atrasado (Fase 21): um
# nível médio produz apostas razoáveis sem virar "assistente de jogo".
AUTO_IA_NIVEL = 2

# Limite de sockets simultâneos por IP (Fase 59): opt-in por env — quem não
# setar não muda nada (regressão zero nos deploys atuais). '0' = desligado.
def _ler_limite_sockets_ip():
    bruto = os.environ.get("DADINHO_LIMITE_SOCKETS_IP", "0") or "0"
    try:
        return max(0, int(bruto))
    except (TypeError, ValueError):
        observabilidade.log_advertencia(
            "DADINHO_LIMITE_SOCKETS_IP inválido — usando 0 (desligado).", valor=bruto)
        return 0


LIMITE_SOCKETS_IP = _ler_limite_sockets_ip()
# Origens fixas permitidas quando a produção está com CORS aberto (`*`): as
# páginas da Vercel (domínio canônico + alias do projeto). Usadas como fallback
# do guard de produção da Fase 59.
CORS_PADRAO_PRODUCAO = (
    "https://dadinho.memetrigger.com",
    "https://dadinho-hazel.vercel.app",
)
_EM_PRODUCAO = (os.environ.get("VERCEL_ENV") == "production"
                or os.environ.get("DADINHO_ENV") == "production")


def _normalizar_cors(origens, producao):
    """
    Garante que produção nunca aceite CORS `*` (Fase 59): um site malicioso
    poderia abrir sockets no `session.id` de um jogador desatento. Em produção
    com `*`, cai para as origens fixas do frontend (Vercel) com aviso no log.
    """
    if not origens:
        return None
    if not producao or "*" not in origens:
        return list(origens)
    observabilidade.log_advertencia(
        "CORS '*' em produção é inseguro — caindo para as origens fixas do frontend.",
        origens=origens, fallback=list(CORS_PADRAO_PRODUCAO),
    )
    return list(CORS_PADRAO_PRODUCAO)


class GerenciadorThreadSeguro(GerenciadorSocketIOBase):
    """
    Corrige uma corrida do python-socketio em async_mode 'threading' (a instância
    quente da Vercel atende requests concorrentes): basic_leave_room apaga o
    namespace quando a última sala sai, enquanto outro thread acabou de registrar
    o sid em manager.connect. O join_room seguinte então estoura
    "sid is not connected to requested namespace" (ou KeyError), o handler de
    connect falha e o cliente entra em loop de reconexão.

    Serializa as mutações do registro de rooms com um RLock reentrante; connect,
    join_room e leave_room passam a ser atômicos entre si.
    """

    def __init__(self):
        super().__init__()
        self._trava_registro = threading.RLock()

    def connect(self, eio_sid, namespace):
        with self._trava_registro:
            return super().connect(eio_sid, namespace)

    def basic_enter_room(self, sid, namespace, room, eio_sid=None):
        with self._trava_registro:
            return super().basic_enter_room(sid, namespace, room, eio_sid=eio_sid)

    def basic_leave_room(self, sid, namespace, room):
        with self._trava_registro:
            return super().basic_leave_room(sid, namespace, room)

    def basic_disconnect(self, sid, namespace, **kwargs):
        with self._trava_registro:
            return super().basic_disconnect(sid, namespace, **kwargs)

    def basic_close_room(self, room, namespace):
        with self._trava_registro:
            return super().basic_close_room(room, namespace)


class GerenciadorRedisSeguro(pacote_socketio.RedisManager):
    """
    Fase 25: mesma correção de corrida do GerenciadorThreadSeguro aplicada ao
    RedisManager (pub/sub). O PubSubManager herda do Manager, então as 5
    mutações do registro de rooms continuam sendo serializadas pelo RLock —
    agora também entre o handler do request e a thread de listener da fila.
    """

    def __init__(self, url, channel="dadinho", redis_options=None):
        super().__init__(url=url, channel=channel, redis_options=redis_options)
        self._trava_registro = threading.RLock()

    def connect(self, eio_sid, namespace):
        with self._trava_registro:
            return super().connect(eio_sid, namespace)

    def basic_enter_room(self, sid, namespace, room, eio_sid=None):
        with self._trava_registro:
            return super().basic_enter_room(sid, namespace, room, eio_sid=eio_sid)

    def basic_leave_room(self, sid, namespace, room):
        with self._trava_registro:
            return super().basic_leave_room(sid, namespace, room)

    def basic_disconnect(self, sid, namespace, **kwargs):
        with self._trava_registro:
            return super().basic_disconnect(sid, namespace, **kwargs)

    def basic_close_room(self, room, namespace):
        with self._trava_registro:
            return super().basic_close_room(room, namespace)


# Transporte e armazenamento ajustáveis por ambiente (ver Fase 2 do todo.md).
async_mode = os.environ.get("DADINHO_ASYNC_MODE", "threading").strip() or "threading"
# A Vercel passou a suportar WebSocket nativamente (beta, jun/2026). O WS fixa a
# conexão numa instância; com long-polling cada request de poll pode cair numa
# instância sem a sessão Engine.IO (em memória por instância) e voltar
# "Invalid session", fazendo o cliente reconectar sem parar ("Reconectando...").
# Por isso o WS é o padrão; DADINHO_PERMITIR_WEBSOCKET=0 desliga o upgrade.
padrao_permitir_websocket = "true"
permitir_websocket = os.environ.get("DADINHO_PERMITIR_WEBSOCKET", padrao_permitir_websocket).strip().lower() \
    not in ("0", "false", "nao", "no")
# Fase 25: message queue opt-in por env. Com DADINHO_MESSAGE_QUEUE (URL
# rediss:// do Upstash, ou redis:// de um Redis TCP local na VPS) os emits
# alcançam clientes de qualquer instância via pub/sub; sem a env, mantém o
# GerenciadorThreadSeguro atual (regressão zero).
url_mq = os.environ.get("DADINHO_MESSAGE_QUEUE", "").strip()
if url_mq:
    opcoes_redis = {"ssl_cert_reqs": "required"} if url_mq.startswith("rediss://") else {}
    gerenciador = GerenciadorRedisSeguro(url_mq, channel="dadinho",
                                         redis_options=opcoes_redis)
else:
    gerenciador = GerenciadorThreadSeguro()
# Fase 46 (VPS): quando a API roda na VPS separada do frontend (que fica na
# Vercel), o browser conecta cross-origin no /socket.io da VPS. O Socket.IO
# só aceita a mesma origem por padrão — `DADINHO_CORS_ORIGINS` lista as origens
# permitidas (separadas por vírgula, ou `*`). Vazio mantém o comportamento atual
# (same-origin, regressão zero no deploy 100% Vercel).
_cors_env = os.environ.get("DADINHO_CORS_ORIGINS", "").strip()
cors_permitidos = None
if _cors_env:
    cors_permitidos = _normalizar_cors(
        [o.strip() for o in _cors_env.split(",") if o.strip()], _EM_PRODUCAO)
socketio = SocketIO(
    app,
    async_mode=async_mode,
    client_manager=gerenciador,
    allow_upgrades=permitir_websocket,
    cors_allowed_origins=cors_permitidos,
    ping_interval=15,
    ping_timeout=20,
    http_compression=False,
    # Fase 15: os payloads do cliente são minúsculos (aposta, chave, nonce).
    # Limitar a entrada (default 1 MB) reduz a superfície de abuso/DoS.
    max_http_buffer_size=100_000,
)

# Fase 59 (segurança): captcha no connect é opt-in (`DADINHO_CAPTCHA_ATIVO`).
# Usa o Cloudflare Turnstile (grátis, invisível por padrão). O frontend recebe
# a SITEKEY pelo <meta>, roda o widget e manda o token no handshake; a API
# valida o token no `siteverify` com o SECRET (nunca exposto ao cliente).
#
# Separação de responsabilidades (deploy Fase 46: frontend na Vercel + API na
# VPS — o frontend NÃO tem o SECRET):
#   - CAPTCHA_WIDGET: renderiza o <meta>; exige só a sitekey (Vercel usa).
#   - CAPTCHA_ATIVO:  valida o token; exige sitekey + secret (API da VPS usa).
# Sem sitekey nada liga; sem secret o processo só renderiza (não valida).
# Faltando algo, NÃO derruba os connects — apenas não protege (avisa no log).
TURNSTILE_SITEKEY = os.environ.get("DADINHO_TURNSTILE_SITEKEY", "").strip()
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "").strip()
_captcha_pedido = os.environ.get("DADINHO_CAPTCHA_ATIVO", "").strip().lower() in ("1", "true", "sim")
CAPTCHA_WIDGET = _captcha_pedido and bool(TURNSTILE_SITEKEY)
CAPTCHA_ATIVO = CAPTCHA_WIDGET and bool(TURNSTILE_SECRET)
if _captcha_pedido and not CAPTCHA_WIDGET:
    observabilidade.log_advertencia(
        "DADINHO_CAPTCHA_ATIVO ligado sem DADINHO_TURNSTILE_SITEKEY — o widget do "
        "captcha NÃO será renderizado e ninguém conseguiria resolver; nada ligou.")
elif CAPTCHA_WIDGET and not CAPTCHA_ATIVO:
    observabilidade.log_redigido(
        evento="captcha_sem_secret",
        mensagem="sitekey presente sem TURNSTILE_SECRET: este processo só renderiza "
                 "o widget (o backend que valida o token é a API da VPS).")


def _ip_do_cliente():
    """
    IP real do cliente na arquitetura atual (Fase 59). A API roda atrás do
    Cloudflare Tunnel da VPS: `REMOTE_ADDR` é sempre loopback/nginx (cloudflared).
    As camadas de verdade, em ordem:
      1. `Cf-Connecting-Ip` — header definido pelo cloudflared (o padrão na VPS);
      2. `X-Forwarded-For` (1º valor) — proxy genérico;
      3. `REMOTE_ADDR` — fallback (dev local, Vercel sem proxy à frente).
    Cada candidato é validado como IP (formato) antes de virar chave do índice:
    um header forjado não pode criar chaves arbitrárias nem poluir os logs.
    """
    candidatos = [
        request.headers.get("Cf-Connecting-Ip", "").strip(),
        request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip(),
        (request.remote_addr or "").strip(),
    ]
    for candidato in candidatos:
        if not candidato:
            continue
        try:
            ipaddress.ip_address(candidato)
            return candidato
        except ValueError:
            continue
    return "desconhecido"


def _validar_captcha(token, remoteip):
    """
    Valida o token do Cloudflare Turnstile (Fase 59) em `siteverify`. Qualquer
    falha de rede/HTTP devolve False (fail-closed: no pico de abuso, recusar a
    mais não custa; um bot a menos, sim). Só roda quando `CAPTCHA_ATIVO`
    (sitekey + secret presentes), então o frontend sem secret nunca chega aqui.
    """
    if not CAPTCHA_ATIVO:
        return True
    corpo = f"secret={urllib.parse.quote(TURNSTILE_SECRET)}&response={urllib.parse.quote(token)}"
    if remoteip:
        corpo += f"&remoteip={urllib.parse.quote(remoteip)}"
    try:
        conexao = http.client.HTTPSConnection("challenges.cloudflare.com", timeout=6)
        conexao.request("POST", "/turnstile/v0/siteverify", body=corpo,
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        resposta = conexao.getresponse()
        dados = json.loads(resposta.read().decode("utf-8"))
        conexao.close()
        return bool(dados.get("success"))
    except Exception:
        return False


def achar_jogador(client_id):
    """
    Procura o jogador com o client_id informado em todas as salas.
    Usa o índice em processo (sala_do_cliente) para achar a sala direto no store,
    caindo na varredura completa caso o índice esteja desatualizado.
    Antes de responder, expurga jogadores cuja janela de reconexão expirou (Fase 9).
    Retorna o par (lobby, jogador); (None, None) caso não esteja em nenhuma sala.
    """
    sala_id = sala_do_cliente(client_id)
    if sala_id is not None:
        lobby = store.carregar_sala(sala_id)
        if lobby is not None:
            if _gc_sala(lobby):
                return None, None
            jogador = lobby.buscar_jogador_pelo_client_id(client_id)
            if jogador is not None:
                return lobby, jogador
    lobby = buscar_lobby_pelo_client_id(client_id)
    if lobby is None:
        return None, None
    if _gc_sala(lobby):
        return None, None
    return lobby, lobby.buscar_jogador_pelo_client_id(client_id)


def _remover_jogador_da_sala(lobby, jogador):
    """
    Remove o jogador de uma sala (lobby + partida/rodada se estiver jogando),
    cuidando dos contadores, do avanço da vez e da declaração de vencedor.
    Extraído do handle_disconnect para ser reusado pela janela de reconexão (Fase 9).
    """
    # Fase 6 (B2): se o desconectado já tinha confirmado a vitória, o contador
    # fica maior que o lobby atual e o "Ok" da vitória nunca libera o reset.
    if jogador.confirmou_vencedor:
        lobby.conferiram_vencedor = max(0, lobby.conferiram_vencedor - 1)
    # Fase 30: registra a vaga liberada (para o retorno explicar o retomar_negado).
    lobby.registrar_vaga_perdida(jogador)
    lobby.remover_jogador(jogador.client_id)

    partida = jogador.partida_atual
    if partida is not None and jogador in partida.jogadores:
        rodada = jogador.rodada_atual
        indice_antigo = partida.jogadores.index(jogador)
        # Fase 6 (B1): remove o desconectado também da rodada e desfaz a
        # confirmação dele, senão a conferência espera um fantasma pra sempre.
        if rodada is not None and jogador in rodada.jogadores:
            if jogador.confirmou_rodada:
                rodada.conferiram = max(0, rodada.conferiram - 1)
            rodada.jogadores.remove(jogador)
        if jogador in partida.jogadores:
            partida.jogadores.remove(jogador)
        if len(partida.jogadores) == 1:
            # Sobrou só um jogador com dado: é o vencedor da partida.
            partida.declarar_vencedor(partida.jogadores[0])
        elif len(partida.jogadores) > 1:
            if rodada is not None and rodada.vez_atual == jogador:
                # Era a vez do desconectado: passa o turno pro próximo da ordem
                # circular (se ele era o último da lista, volta pro primeiro).
                proximo = partida.jogadores[indice_antigo % len(partida.jogadores)]
                rodada.vez_atual = proximo
                rodada.atualizar_front_pro_da_vez(proximo)
            # Se a rolagem só esperava este jogador, desbloqueia quem já jogou.
            # Só na página de rolagem (1): na conferência/vitória todos já rolaram
            # e o desbloqueio reverteria a tela para os turnos.
            if (lobby.pagina == 1 and rodada is not None
                    and rodada.verificar_se_todos_ja_jogaram_seus_dados()):
                lobby.pagina = 2
                mudar_pagina(2, sala=lobby.sala_id)

    # Fase 22: a remoção muda quem ainda falta conferir/rolar — reapresenta o
    # status (a partida pode ter avançado ou ter declarado um vencedor acima).
    if lobby.pagina == 1:
        emitir_status_rolagem(lobby)
    elif lobby.pagina == 3:
        emitir_status_conferencia(lobby)
    elif lobby.pagina == 4:
        emitir_status_vitoria(lobby)


def _substituir_por_ia(lobby, jogador, motivo='timeout'):
    """
    Converte um desconectado em bot (Fase 11), quando o master ativou a opção:
    preserva dados/turno e deixa a partida seguir. Só vale se ainda houver outro
    humano ativo — senão a sala seguiria só com bots. Quem ainda não entrou numa
    partida (espera) só é substituído quando a partida começa (`iniciar_partida`
    resolve os caídos antes de montar a mesa) — o expurgo da espera remove, não
    substitui (ver `_purgar_desconectados`).

    O `motivo` ('timeout' ou 'ausente') vai na narração para os demais jogadores
    entenderem por que o humano virou IA.
    """
    if not lobby.config.get('substituir_desconectado_por_ia'):
        return False
    tem_humano_ativo = any(not j.is_ia and j is not jogador and j.desconectado_em is None
                           for j in lobby.jogadores)
    if not tem_humano_ativo:
        return False
    jogador.is_ia = True
    jogador.ia_nivel = int(lobby.config.get('ia_nivel_padrao', 2) or 2)
    ia.sorteiar_personalidade(jogador)
    jogador.desconectado_em = None
    jogador.pronto = True
    emit('narracao', narrador.narracao_substituicao(jogador, motivo), to=lobby.sala_room())
    return True


def _purgar_desconectados(lobby):
    """
    Remove da sala os jogadores cuja janela de reconexão (grace) já expirou
    (Fase 9). Com a opção do master ligada, em vez de remover, o desconectado
    vira bot (Fase 11) e a partida continua. Devolve True se algo mudou.
    """
    agora = datetime.now()
    mudou = False
    for jogador in list(lobby.jogadores):
        if jogador.desconectado_em is None:
            continue
        if (agora - jogador.desconectado_em).total_seconds() >= GRACE_RECONEXAO_SEGUNDOS:
            # Fase 30: só quem já estava numa partida vira IA aqui. Quem caiu na
            # ESPERA é removido (a substituição de um caído da espera acontece no
            # `iniciar_partida`, que resolve os caídos antes de montar a mesa).
            if jogador.partida_atual is not None and _substituir_por_ia(lobby, jogador):
                mudou = True
                continue
            _remover_jogador_da_sala(lobby, jogador)
            mudou = True
    # Remoções e substituições podem ter derrubado o master (ex.: o master virou
    # bot): repõe um master humano. É no-op se já houver um.
    if mudou:
        lobby.definir_master()
        ia.processar(lobby)
    return mudou


def _resolver_caidos_para_partida(lobby):
    """
    Fase 30: antes de iniciar, resolve quem caiu na ESPERA e ainda está na janela
    de graça — vira IA (se a opção do master estiver ligada, houver outro humano
    ativo e o jogador já tiver apelido) ou é removido. NUNCA entra na partida
    como fantasma (rolagem/turnos ficariam presos esperando um socket que não
    existe) nem como bot sem nome (travaria `pode_iniciar` em `sem_apelido`
    para sempre). O retorno via `retomar_identidade` continua devolvendo o
    controle a quem vira bot. Devolve True se algo mudou.
    """
    mudou = False
    for jogador in list(lobby.jogadores):
        if jogador.desconectado_em is None:
            continue
        if jogador.username and _substituir_por_ia(lobby, jogador, motivo='ausente'):
            mudou = True
            continue
        _remover_jogador_da_sala(lobby, jogador)
        mudou = True
    if mudou:
        lobby.definir_master()
        atualizar_lista_usuarios(lobby)
    return mudou


def _tem_humano_recente(lobby):
    """
    True se a sala tem um humano CONECTADO ou dentro da janela de reconexão
    (desconectado_em marcado e ainda não expirado). Bots não contam. É a base do
    GC de sala (Fase 23): o último humano de uma partida só com IAs que cai por
    um blip (tab em segundo plano, reciclagem da função na Vercel) tem a janela
    de graça para voltar — antes, a sala morria junto na hora do disconnect.
    """
    agora = datetime.now()
    for jogador in lobby.jogadores:
        if jogador.is_ia:
            continue
        if jogador.desconectado_em is None:
            return True
        if (agora - jogador.desconectado_em).total_seconds() < GRACE_RECONEXAO_SEGUNDOS:
            return True
    return any(not e.is_ia for e in lobby.espectadores)


def _gc_sala(lobby):
    """
    GC unificado de sala: expurga a janela de reconexão (Fase 9/11) e fecha a
    sala quando não resta humano conectado NEM na janela de reconexão (Fase
    15/23). Todo caminho que toca o estado passa por aqui, para que nenhum fluxo
    deixe uma sala sem humano persistida (só bots, todos na janela de graça
    expirada, instância morta sem disconnect). Devolve True se a sala foi fechada.
    """
    mudou = _purgar_desconectados(lobby)
    if not _tem_humano_recente(lobby):
        remover_sala(lobby.sala_id)
        esquecer_sala(lobby.sala_id)
        return True
    # Fase 15: partida sem nenhum jogador restante (todos saíram) mas ainda com
    # espectador humano conectado ficaria presa em "jogando" para sempre — quem
    # entra depois só vira espectador e ninguém reinicia. Volta à sala de espera
    # promovendo os espectadores a jogadores (e elegendo um master).
    if not lobby.jogadores and lobby.espectadores:
        lobby.resetar_para_lobby()
        lobby.definir_master()
        mudar_pagina(0, sala=lobby.sala_id)
        mudou = True
    if mudou:
        atualizar_lista_usuarios(lobby)
    return False


def evento_mutavel(func=None, *, cooldown=COOLDOWN_ESCRITA, lock_distribuido=True):
    """
    Wrapper padrão para handlers que mutam estado de sala (Fase 7):
    - V2: rate limit leve por sid (desligável com `cooldown=None` para eventos
      de confirmação — conferência/vitória são idempotentes e espaçados pelo
      fluxo do jogo, e um drop silencioso pelo cooldown travaria a partida);
    - A4: lock por sala no processo, cobrindo todo o read-modify-write;
    - Fase 24: lock distribuído por sala (Upstash) por dentro do local —
      serializa a mutação ENTRE instâncias (pré-requisito da message queue);
    - V3: payload malformado aborta silenciosamente (nunca exceção no evento).

    Fase 60: `lock_distribuido=False` é para caminhos apenas-leitura que servem
    de re-sync (heartbeat) — o lock distribuído é adquirido pontualmente DENTRO
    do handler só quando há mutação de fato (economia de 2 comandos por batida
    em salas ociosas, onde a mutação é inexistente).
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            client_id = request.sid
            if cooldown is not None and tem_cooldown(client_id, cooldown):
                return
            sala_id = sala_do_cliente(client_id)
            try:
                if sala_id is None:
                    return func(*args, **kwargs)
                with trancar_sala(sala_id):
                    if lock_distribuido:
                        with trancar_sala_distribuida(sala_id):
                            return func(*args, **kwargs)
                    return func(*args, **kwargs)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OverflowError,
                    store.TravaIndisponivel,
                    # Fase 52: save de um lobby stale (possível lost-update) —
                    # aborta a operação em vez de sobrescrever (corrupção
                    # silenciosa). `invalidar_cache_sala` abaixo garante que a
                    # próxima leitura recarregue fresco do store.
                    store.ConflitoDeEstado,
                    # Fase B: falhas de rede/IO do store distribuído (Upstash) também
                    # abortam silenciosamente — sem elas, um blip de rede estoura o
                    # handler, loga traceback e perde o estado do read-modify-write.
                    OSError, http.client.HTTPException,
                    # Fase 46/60: o ArmazenamentoRedis (VPS) fala com o Redis via
                    # redis-py, cujas falhas (ConnectionError, TimeoutError,
                    # ResponseError) herdam de RedisError, não de OSError; a
                    # classe entra na tupla lazy (`store.erros_de_rede`) para não
                    # importar o pacote no boot da Vercel.
                    store.erros_de_rede()):
                # Aborto no meio de uma mutação: o objeto vivo do cache de re-sync
                # pode ter sido poluído — descarta para a próxima leitura recarregar.
                if sala_id is not None:
                    store.invalidar_cache_sala(sala_id)
                return
        return wrapper
    if func is not None:
        return decorator(func)
    return decorator


def evento_leitura(func):
    """
    Wrapper para eventos somente-leitura (ex.: busca de partidas): só o rate limit (V2).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if tem_cooldown(request.sid, COOLDOWN_BUSCA):
            return
        return func(*args, **kwargs)
    return wrapper


def _chave_simples(dados):
    """Extrai a chave secreta do payload no formato padrão {'chave': ...}."""
    return dados.get('chave', '')


def _chave_aninhada(dados):
    """Extrai a chave do payload de aposta/desconfiança: {'dados': {'chave': ...}}."""
    internos = dados.get('dados')
    if not isinstance(internos, dict):
        return ''
    return internos.get('chave', '')


def autenticar(exigir_master=False, extrair_chave=_chave_simples):
    """
    Centraliza o boilerplate de autenticação dos handlers de jogador (Fase 10, S5):
    localiza (lobby, jogador) pelo sid, valida a chave secreta extraída do payload
    (passe `extrair_chave=None` para eventos sem chave) e, opcionalmente, exige que
    o jogador seja o master. Em falha, aborta silenciosamente; no sucesso injeta
    (dados, lobby, jogador) na assinatura do handler decorado.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(dados=None, *args, **kwargs):
            dados = dados if isinstance(dados, dict) else {}
            lobby, jogador = achar_jogador(request.sid)
            if jogador is None or lobby is None:
                return
            if exigir_master and not jogador.master:
                return
            if extrair_chave is not None and not hmac.compare_digest(
                    jogador.chave_secreta, str(extrair_chave(dados) or '')):
                return
            return func(dados, lobby, jogador, *args, **kwargs)
        return wrapper
    return decorator


OG_GENERICO = {
    'titulo': 'Dadinho — Jogo de Blefe de Dados Online Multiplayer | MemeTrigger',
    'descricao': ('Jogue Dadinho, o jogo oficial do MemeTrigger! Jogo multiplayer de blefe de dados '
                  'em tempo real no navegador. Sem cadastro — crie uma sala e jogue com os amigos.'),
}

# Fase 46 (VPS): URL pública da API (socket.io). Quando a API roda numa VPS
# separada do frontend (Vercel), o template injeta essa URL para o `io()` do
# cliente conectar na VPS. Vazio = mesmo host (regressão zero no deploy 100%
# Vercel e no dev local).
API_URL = os.environ.get("DADINHO_API_URL", "").strip().rstrip("/")


# Fase 44 (S6/S7): Content Security Policy. Com os `onclick` inline migrados
# para `data-acao` (S5) e o stub do `window.va` removido, não resta script
# inline executável (o ld+json é dado, não executa) — `script-src` dispensa
# 'unsafe-inline'/nonce. `style-src` mantém 'unsafe-inline' porque o jogo usa
# `style=` inline e `element.style` em massa no JS (endurecer isso é refactor
# separado). Default: **Report-Only** (não bloqueia; revisar violações no
# navegador antes de virar bloqueante com `DADINHO_CSP_MODO=bloqueante`).
# Fase 46: com a API na VPS (cross-origin), o connect-src precisa da origem
# dela para o WebSocket/polling do socket.io não ser bloqueado em modo
# bloqueante. Sem DADINHO_API_URL, mantém o 'self' (regressão zero).
_origem_api_csp = f" {API_URL}" if API_URL else ""
# Fase 59: com o widget de captcha (Turnstile) ativo, o script/iframe/conexões
# do challenges.cloudflare.com exigem as origens no CSP (senão a política
# bloqueante quebraria o widget). Sem `DADINHO_CAPTCHA_ATIVO`, intacto.
_captcha_csp = " https://challenges.cloudflare.com" if CAPTCHA_WIDGET else ""
CSP = (
    "default-src 'self'; "
    f"script-src 'self' https://cdn.socket.io https://cdn.jsdelivr.net{_captcha_csp}; "
    f"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com{_captcha_csp}; "
    f"font-src 'self' https://fonts.gstatic.com{_captcha_csp}; "
    f"img-src 'self' data:{_captcha_csp}; "
    f"connect-src 'self'{_origem_api_csp} https://fonts.gstatic.com https://va.vercel-scripts.com{_captcha_csp}; "
    f"frame-src 'self'{_captcha_csp}; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
)


def _og_sala(sala_id, url_atual):
    """
    Fase 42 (N1): Open Graph dinâmico para crawlers — bots de preview (WhatsApp,
    Telegram, Discord, X) não executam JS, então o convite de sala precisa vir no
    HTML estático. Lê o resumo leve da sala no store e monta um og específico
    ("Fulano te chamou pra uma partida"). Sala inexistente/inválida cai no
    genérico. O og:image permanece estático (gerar imagem por sala exigiria um
    serviço de renderização — fica para depois).
    """
    resumo = store.carregar_resumo(sala_id)
    if resumo is None:
        return dict(OG_GENERICO, url=url_atual)
    nome = resumo.get('nome') or f"Partida #{sala_id}"
    jogadores = int(resumo.get('jogadores') or 0)
    maximo = int(resumo.get('max_jogadores') or 6)
    status = resumo.get('status', 'espera')
    if status == 'jogando':
        descricao = f"{nome} — partida em andamento ({jogadores} jogador(es) na mesa)."
    elif resumo.get('pode_entrar'):
        descricao = (f"{nome} — {jogadores}/{maximo} jogador(es). "
                     "Sem cadastro, entre e jogue Dadinho com os amigos!")
    else:
        descricao = f"{nome} — {jogadores}/{maximo} jogador(es)."
    return {
        'titulo': f"{nome} | Dadinho — jogo de blefe de dados",
        'descricao': descricao,
        'url': url_atual,
    }


@app.route("/")
def index():
    og = dict(OG_GENERICO, url=request.url)
    sala_id = normalizar_sala(request.args.get('sala'))
    if sala_id != SALA_PADRAO:
        og = _og_sala(sala_id, request.url)
    resposta = make_response(render_template(
        "jogo.html", og=og, api_url=API_URL,
        captcha_sitekey=TURNSTILE_SITEKEY if CAPTCHA_WIDGET else ''))
    # Fase 44: CSP em Report-Only por padrão; `DADINHO_CSP_MODO=bloqueante`
    # aplica a política de verdade (depois de revisar as violações no browser).
    if os.environ.get("DADINHO_CSP_MODO", "").strip().lower() == "bloqueante":
        resposta.headers['Content-Security-Policy'] = CSP
    else:
        resposta.headers['Content-Security-Policy-Report-Only'] = CSP
    return resposta


@app.route("/robots.txt")
def robots_txt():
    """
    Permite a indexação da home e afasta crawlers do endpoint WebSocket (não
    renderiza conteúdo) e das URLs ?sala= (transitórias, sem conteúdo indexável).
    A URL do sitemap usa o Host do request para valer também em previews/dev.
    """
    base = request.url_root
    texto = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /socket.io/\n"
        "Disallow: /?sala=\n"
        "\n"
        f"Sitemap: {base}sitemap.xml\n"
    )
    resposta = Response(texto, mimetype="text/plain")
    resposta.headers['Cache-Control'] = 'public, max-age=3600'
    return resposta


@app.route("/sitemap.xml")
def sitemap_xml():
    """
    Sitemap do site. O jogo é uma SPA única (home + salas ?sala= efêmeras), então
    o sitemap lista só a raiz. lastmod dinâmico reflete o dia do deploy.
    """
    base = request.url_root.rstrip('/')
    ultima = datetime.now().strftime('%Y-%m-%d')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{base}/</loc>
    <lastmod>{ultima}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
'''
    resposta = Response(xml, mimetype="application/xml")
    resposta.headers['Cache-Control'] = 'public, max-age=3600'
    return resposta


@app.route("/tema.mid")
def tema_midi():
    """
    Serve o tema oficial vigente (Fase 12). A música é gerada
    deterministicamente a partir da janela de 12h (ver `tema.py`), então todas
    as instâncias devolvem a mesma composição sem persistência nem timers.
    Cache-Control expira exatamente na virada da janela; se a geração falhar,
    cai no MIDI estático versionado como fallback.
    """
    try:
        midi, bpm, seed = tema.tema_atual()
    except Exception:
        return send_from_directory(os.path.join(app.root_path, 'static', 'sons'),
                                   'dadinho_tema.mid', mimetype='audio/midi')
    resposta = Response(midi, mimetype='audio/midi')
    resposta.headers['Cache-Control'] = f'public, max-age={max(0, tema.segundos_ate_virada())}'
    resposta.headers['X-Dadinho-Tema-Seed'] = str(seed)
    resposta.headers['X-Dadinho-Tema-Bpm'] = str(bpm)
    return resposta


@socketio.on('connect')
def handle_connect():
    """
    Esta função é executada no momento da conexão de um cliente web do servidor.
    Ela deve determinar a sala do cliente (via ?sala= na URL/front-end), juntá-lo à room da sala,
    criar uma instância de jogador, e decidir se ele é master, caso não haja algum na sala.

    Fase 4: se já existir um jogador com este sid (reconexão da mesma sessão) ou com a
    chave secreta guardada no sessionStorage (refresh), reaproveita-o em vez de duplicar,
    e envia um snapshot da sala para o cliente reconstruir a tela (página atual intacta).

    Fase 16: a sala padrão compartilhada foi aposentada. Quem chega sem código (ou com
    `?sala=padrao`, que `normalizar_sala` usa como fallback de inválidos) recebe uma sala
    própria em vez de disputar vagas de uma sala única que enche e trava todo mundo. O
    cliente navega para o código devolvido e reconecta já na sala nova.
    """
    client_id = request.sid
    # Fase 59: limite de sockets simultâneos por IP (opt-in) + captcha opcional.
    # O índice de IPs vive no store (`dadinho:ip:<ip>`); um blip de rede ao
    # gravar o índice NÃO barra ninguém (fail-open com registro suspeito — só
    # o handicap de segurança perde, o jogo segue).
    ip = _ip_do_cliente()
    if LIMITE_SOCKETS_IP > 0:
        try:
            total_no_ip = store.registrar_ip(ip, client_id) or 0
        except Exception:
            observabilidade.log_evento_suspeito(
                "store_indisponivel_ip", client_id, ip, {'dimensao': 'indice_ip'})
            total_no_ip = 0
        if total_no_ip > LIMITE_SOCKETS_IP:
            # Refusado: devolve a vaga já (senão cada tentativa recusada
            # inflaria o índice e bloquearia o IP até o TTL expirar).
            try:
                store.remover_ip(ip, client_id)
            except Exception:
                pass
            observabilidade.log_evento_suspeito(
                "multiplas_contas", client_id, ip,
                {'limite': LIMITE_SOCKETS_IP, 'conexoes_do_ip': total_no_ip})
            raise pacote_socketio.exceptions.ConnectionRefusedError(
                'limite_de_conexoes',
                {'motivo': {'chave': 'msg.muitas_contas',
                            'params': {'limite': LIMITE_SOCKETS_IP}}})
    elif CAPTCHA_ATIVO:
        # Sem limite por IP, o captcha no connect segura a abertura em massa.
        try:
            store.registrar_ip(ip, client_id)
        except Exception:
            pass
    # `hcaptcha_token` é aceito como fallback durante a troca hCaptcha→Turnstile
    # (JS antigo em cache enviando o token); o nome canônico é `captcha_token`.
    token_captcha = (request.args.get('captcha_token')
                     or request.args.get('hcaptcha_token') or '')
    if CAPTCHA_ATIVO and not _validar_captcha(token_captcha, ip):
        try:
            store.remover_ip(ip, client_id)
        except Exception:
            pass
        observabilidade.log_evento_suspeito(
            "captcha_falhou", client_id, ip,
            {"captcha_ativo": True, "possuia_token": bool(token_captcha)})
        raise pacote_socketio.exceptions.ConnectionRefusedError(
            'captcha_invalido', {'motivo': {'chave': 'msg.captcha_invalido'}})

    sala_id = normalizar_sala(request.args.get('sala'))
    if sala_id == SALA_PADRAO:
        # Fase 18: chegou sem código (ou com código inválido) — home, não cria
        # sala automaticamente. O cliente fica conectado (o socket é necessário
        # para `criar_sala` e `listar_partidas`), mas sem sala nem jogador até
        # escolher criar uma sala ou entrar pela busca.
        emit('connect_start', {'is_master': False, 'chave_secreta': '', 'sala': None},
             to=client_id, ignore_queue=True)
        return
    with trancar_sala(sala_id):
        try:
            with trancar_sala_distribuida(sala_id):
                lobby = obter_sala(sala_id)
                join_room(lobby.sala_room(), sid=client_id)

                jogador = lobby.buscar_jogador_pelo_client_id(client_id)
                # Fase D2 (refresh): quem conecta com `tem_chave=1` (chave guardada no
                # sessionStorage) está prestes a retomar a identidade pela primeira
                # mensagem (`retomar_identidade`). NO SNAPSHOT imediato do placeholder:
                # ele piscaria como ESPECTADOR (a partida está em andamento) e, na tela
                # de conferência (3), o evento `espectador` esconderia o botão "Ok" sem
                # que o snapshot real o reexibisse — a rodada travava em "Aguardando
                # você...". O snapshot sai na retomada (ou, se a chave for stale, no
                # `retomar_negado`).
                deferir_snapshot = jogador is None and request.args.get('tem_chave', '') == '1'
                if jogador is None:
                    # Fase D: a `chave_secreta` não trafega mais na query string do
                    # handshake (vazava em logs de acesso/histórico). Aqui cria-se um
                    # Jogador "placeholder"; a identidade real é retomada logo depois
                    # pelo primeiro evento (`retomar_identidade`), quando o cliente
                    # envia a chave guardada no sessionStorage. `tem_chave` é apenas um
                    # sinal booleano (não-secreto) para o servidor não barrar quem pode
                    # estar retomando identidade (sala cheia/GC) — o placeholder é
                    # transitório.
                    tem_chave = request.args.get('tem_chave', '') == '1'
                    if not tem_chave:
                        if (lobby.jogadores or lobby.espectadores) and _gc_sala(lobby):
                            lobby = obter_sala(sala_id)
                    # Fase 29 (H3): o cap vale para o placeholder também. Antes,
                    # `tem_chave=1` (apenas um sinal booleano de possível retomada)
                    # pulava as checagens de limite e criava jogador/espectador sem
                    # respeitar `max_jogadores`/`MAX_ESPECTADORES` (e sem GC). A
                    # retomada da chave só reaproveita se a sala ainda comportar;
                    # senão `sala_cheia`.
                    if lobby.status == 'jogando':
                        # Fase 15: entrou no meio da partida (pela busca) — vira
                        # espectador, sem ocupar vaga nem contar como jogador.
                        if len(lobby.espectadores) >= MAX_ESPECTADORES:
                            emit('sala_cheia', {'sala': lobby.sala_id}, to=client_id, ignore_queue=True)
                            leave_room(lobby.sala_room(), sid=client_id)
                            return
                    else:
                        # Sala de espera lotada (config 'max_jogadores'): não deixa entrar mais ninguém.
                        if len(lobby.jogadores) >= int(lobby.config.get('max_jogadores', 6)):
                            emit('sala_cheia', {'sala': lobby.sala_id}, to=client_id, ignore_queue=True)
                            leave_room(lobby.sala_room(), sid=client_id)
                            return
                    master = False if lobby.verificar_jogador_master() else True
                    jogador = Jogador(client_id=client_id, master=master)
                    jogador.lobby_atual = lobby
                    if lobby.status == 'jogando':
                        lobby.espectadores.append(jogador)
                    else:
                        lobby.adicionar_jogador(jogador)

                registrar_cliente(client_id, sala_id)

                emit("connect_start",
                     {"is_master": jogador.master, 'chave_secreta': jogador.chave_secreta, 'sala': lobby.sala_id,
                      'username': jogador.username})
                atualizar_lista_usuarios(lobby)
                if not deferir_snapshot:
                    enviar_snapshot_sala(lobby, jogador)
                # Fase 11: se a partida parou na vez de uma IA (ex.: troca de instância),
                # o connect destrava o fluxo.
                if ia.processar(lobby):
                    salvar_sala(lobby)
        except (store.TravaIndisponivel, store.ConflitoDeEstado, store.erros_de_rede(),
                OSError, http.client.HTTPException):
            # Lock distribuído ocupado/indisponível, save stale (Fase 52), ou
            # falha do Redis local da VPS (Fase 46): aborta o connect. O cliente
            # reconecta com backoff e o heartbeat re-sincroniza da mesma forma
            # que hoje em dia com um blip de rede.
            # Fase 60 (P2/P3): o aborto pode ter deixado caches/estado em processo
            # inconsistentes — descarta para a próxima leitura recarregar fresco.
            store.invalidar_cache_sala(sala_id)
            return


@socketio.on('retomar_identidade')
@evento_mutavel(cooldown=None)
def retomar_identidade(dados=None):
    """
    Fase D: retoma a identidade pela `chave_secreta` — primeira mensagem do
    cliente logo após o connect (a chave não trafega mais na query string do
    handshake). Troca o Jogador placeholder criado no connect pela identidade
    real persistida (refresh/reconexão): religa o sid atual, encerra a janela
    de reconexão e reemite o snapshot (mesma lógica do antigo caminho de
    `buscar_jogador_pela_chave` no connect).

    `cooldown=None`: é idempotente (o primeiro vale) e chega logo após o
    connect — um drop silencioso deixaria o jogador preso no placeholder.
    """
    dados = dados if isinstance(dados, dict) else {}
    client_id = request.sid
    chave = dados.get('chave', '')
    if not chave:
        return
    sala_id = sala_do_cliente(client_id)
    if sala_id is None:
        return
    lobby = store.carregar_sala(sala_id)
    if lobby is None:
        return
    alvo = lobby.buscar_jogador_pela_chave(chave)
    if alvo is None:
        # A chave não pertence a esta sala (ex.: sessão de outra sala, ou o
        # jogador já saiu/expirou a janela de graça). O placeholder continua
        # valendo como identidade nova — avisa o front para persistir a chave
        # dele (senão a chave stale ficaria para sempre no sessionStorage).
        # Fase 30: o `motivo` diz se a vaga foi perdida por inatividade nesta
        # sala (registrada em `vagas_recentes`) ou se a sessão é de outro lugar.
        # Fase D2: quem veio com `tem_chave=1` não recebeu snapshot no connect
        # (adiado justamente para a retomada), então o placeholder precisa dele
        # agora que virou a identidade definitiva.
        placeholder = lobby.buscar_jogador_pelo_client_id(client_id)
        if placeholder is not None:
            enviar_snapshot_sala(lobby, placeholder)
        vaga = lobby.buscar_vaga_recente(chave)
        if vaga is not None:
            motivo = {'chave': 'msg.vaga_perdida_inatividade'}
        else:
            motivo = {'chave': 'msg.retomar_outra_sala'}
        emit('retomar_negado', {'motivo': motivo}, to=client_id, ignore_queue=True)
        return
    if alvo.client_id == client_id:
        return
    placeholder = lobby.buscar_jogador_pelo_client_id(client_id)
    if placeholder is not None and placeholder is not alvo:
        if placeholder in lobby.espectadores:
            lobby.espectadores.remove(placeholder)
        elif placeholder in lobby.jogadores:
            lobby.jogadores.remove(placeholder)
    # Fase 11: se o humano tinha sido substituído por um bot
    # (`substituir_desconectado_por_ia`), retomar a identidade devolve o
    # controle a ele; bots nativos (client_id `ia:...`) não são afetados
    # (nunca reconectam por chave).
    era_bot_nativo = str(alvo.client_id).startswith('ia:')
    alvo.client_id = client_id
    alvo.desconectado_em = None
    voltou_de_ia = alvo.is_ia and not era_bot_nativo
    if voltou_de_ia:
        alvo.is_ia = False
        alvo.ia_nivel = None
    lobby.definir_master()
    emit("connect_start",
         {"is_master": alvo.master, 'chave_secreta': alvo.chave_secreta,
          'sala': lobby.sala_id, 'username': alvo.username}, to=client_id, ignore_queue=True)
    # Fase 11/30: avisa a sala que o humano reassumiu o controle que a IA tocava.
    if voltou_de_ia:
        emit('narracao', narrador.narracao_retorno(alvo), to=lobby.sala_room())
    atualizar_lista_usuarios(lobby)
    enviar_snapshot_sala(lobby, alvo)
    if ia.processar(lobby):
        salvar_sala(lobby)


@socketio.on('disconnect')
def handle_disconnect():
    """
    Esta função é executada no momento da desconexão de um cliente web do servidor.
    Ela deve remover o jogador da sala e caso este jogador seja um master e haja mais jogadores no lobby
    dele, selecionar outro jogador, por ordem de entrada, mais antigo pro mais novo, para se tornar o novo master do
    lobby, caso não seja um master, apenas remover, caso apenas ele no lobby, reinicia tudo.

    Fase 4: se o desconectado ainda estiver numa partida em andamento, ele é removido também da
    partida (senão travaria a rolagem/conferência/turno já que a partida continua esperando ele);
    se for a vez dele, o turno passa pro próximo; se sobrar apenas um, ele é declarado vencedor.
    """
    client_id = request.sid
    # Fase 59: o registro do anti-fraude é por sid (único por socket); sem
    # limpar aqui, o processo persistente da VPS acumularia uma entrada por
    # conexão (a heurística não precisa sobreviver ao fim do socket).
    anti_fraude.limpar(client_id)
    # Fase 59: devolve a vaga no índice de IPs (opt-in). Fail-open: um blip de
    # rede aqui só deixa o SET "engordar" até o TTL expirar (6h).
    if LIMITE_SOCKETS_IP > 0 or CAPTCHA_ATIVO:
        try:
            store.remover_ip(_ip_do_cliente(), client_id)
        except Exception:
            pass
    sala_id = sala_do_cliente(client_id)
    if sala_id is None:
        return
    sala_esvaziou = False
    with trancar_sala(sala_id):
        try:
            with trancar_sala_distribuida(sala_id):
                lobby = store.carregar_sala(sala_id)
                desregistrar_cliente(client_id, sala_id)
                if lobby is None:
                    return
                jogador = lobby.buscar_jogador_pelo_client_id(client_id)
                if jogador is None:
                    return
                leave_room(lobby.sala_room(), sid=client_id)

                # Fase 15: espectador não é jogador — sai na hora, sem janela de graça.
                if jogador in lobby.espectadores:
                    lobby.espectadores.remove(jogador)
                else:
                    # Fase 9: janela de reconexão (grace). Quem cai fica marcado
                    # (desconectado_em) por GRACE_RECONEXAO_SEGUNDOS e pode voltar
                    # via chave_secreta (retomar_identidade limpa o marcador, Fase D).
                    # Fase 30: vale também para quem cai na ESPERA — antes, um blip
                    # de conexão (tab em segundo plano, reciclagem da função na
                    # Vercel) removia o jogador na hora e ele voltava com apelido e
                    # prontidão perdidos. Com a graça, o retorno restaura tudo; o
                    # expurgo pós-graça fica com o `verificar_desconectados`/GC.
                    # Fase 23: a janela vale mesmo sem outro HUMANO ativo — antes, numa
                    # partida só com IAs o último humano era removido na hora e a sala
                    # inteira apagada junto; um blip de conexão perdia a partida
                    # inteira. Sem outro humano o expurgo fica a cargo de um GC
                    # posterior (novo humano no connect, `verificar_desconectados`,
                    # ou o TTL do store).
                    jogador.desconectado_em = datetime.now()
                    emit('jogador_desconectado',
                         {'nome': jogador.username or '', 'grace': GRACE_RECONEXAO_SEGUNDOS},
                         to=lobby.sala_room())

                if lobby.contar_jogadores() > 0:
                    lobby.definir_master()
                # Fase 11/15/23: a sala só é fechada quando não resta humano conectado
                # NEM na janela de reconexão — o último humano de uma partida de IAs pode
                # voltar. Sem ninguém conectado/na janela não há evento futuro para o
                # expurgo do serverless, então fechar aqui evita salas vazias no store.
                if _tem_humano_recente(lobby):
                    # S6: atualizar_lista_usuarios já persiste a sala (e o resumo da busca).
                    atualizar_lista_usuarios(lobby)
                else:
                    remover_sala(lobby.sala_id)
                    sala_esvaziou = True
        except (store.TravaIndisponivel, store.ConflitoDeEstado, store.erros_de_rede(),
                OSError, http.client.HTTPException):
            # Lock distribuído indisponível, save stale (Fase 52), ou falha do
            # Redis local da VPS (Fase 46): aborta silenciosamente — o ID do
            # jogador continua indexado (TTL limpa) e a limpeza segue na próxima
            # batida ou no GC, mesmo comportamento de hoje com blip de rede.
            # Fase 60 (P2/P3): o aborto pode ter deixado caches/estado em
            # processo inconsistentes — descarta (idempotente até após remover).
            store.invalidar_cache_sala(sala_id)
            return
    # Depois de soltar o lock (evita corrida com um connect novo da mesma sala).
    if sala_esvaziou:
        esquecer_sala(sala_id)


@socketio.on('apelido')
@evento_mutavel
@autenticar(extrair_chave=None)
def escolher_apelido(dados, lobby, jogador):
    """
    Esta função recebe o apelido do jogador no front-end e atualiza o seu modelo, antes faz umas validações.
    """
    if jogador.partida_atual is None and jogador.rodada_atual is None and jogador.turno_atual is None:
        # Apelido é editável na espera quantas vezes o jogador quiser, mas fica
        # travado a partir do "ficar pronto" (mesma regra do front-end).
        if jogador.pronto:
            return
        apelido = dados.get("apelido_msg", '')
        apelido_n = lobby.verificar_apelido(apelido if validar_input(apelido) else 'NOME_BUGADO',
                                            atual=jogador.username)
        jogador.username = apelido_n
        emit("update_username", {'nome_jogador': jogador.username}, to=jogador.client_id, ignore_queue=True)
        atualizar_lista_usuarios(lobby)


@socketio.on('iniciar_partida')
@evento_mutavel
@autenticar(exigir_master=True)
def iniciar_partida(dados, lobby, jogador):
    """
    Esta função inicia uma nova partida, é executada pelo master do lobby da sala.
    Só libera quando todos os jogadores (não-master) estiverem prontos e houver ao menos 2.
    :param dados: Vem do front, é o número de dados que cada jogador recebe para jogar.
    """
    if 'dados_qtd' in dados:
        try:
            lobby.definir_config({'dados_qtd': int(dados.get('dados_qtd', 1))})
        except (ValueError, TypeError):
            pass
    # Fase 30: gate de status ANTES do resolver — um `iniciar_partida` repetido
    # (clique duplo, segundo tab, snapshot atrasado) com a sala já em `jogando`
    # não pode converter/remover jogadores que estão na janela de reconexão.
    if lobby.status != 'espera':
        return
    # Fase 30: quem caiu na espera (janela de graça) não entra na mesa como
    # fantasma — vira IA (opção ligada) ou é removido antes da validação.
    _resolver_caidos_para_partida(lobby)
    pode, motivo = lobby.pode_iniciar()
    if not pode:
        emit('iniciar_negado', {'motivo': motivo}, to=jogador.client_id, ignore_queue=True)
        return
    # Verificação ativa: resolve a entropia e fixa a seed ANTES de criar a partida.
    seed_info = lobby.finalizar_seed()
    partida = lobby.construir_partida(dados_qtd=int(lobby.config.get('dados_qtd', 1)), seed_info=seed_info)
    partida.construir_rodada()
    ia.processar(lobby)
    # Fase 8: status virou 'jogando' — atualiza o resumo da busca de partidas.
    # Marca o sinal de vida antes de persistir para o blob guardar o instante.
    lobby.marcar_visto()
    salvar_sala(lobby)
    store.salvar_resumo(lobby.sala_id, lobby.resumo_partida())


@socketio.on('configurar_partida')
@evento_mutavel
@autenticar(exigir_master=True)
def configurar_partida(dados, lobby, jogador):
    """
    Aplica as configurações da partida definidas pelo master na sala de espera
    (nome, quantidade de dados, máximo de jogadores, coringa, pública).
    """
    if lobby.status != 'espera':
        return
    if lobby.definir_config(dados.get('config', {})):
        atualizar_lista_usuarios(lobby)


@socketio.on('ficar_pronto')
@evento_mutavel
@autenticar()
def ficar_pronto(dados, lobby, jogador):
    """
    Alterna a prontidão do jogador na sala de espera. O jogo só inicia quando
    todos os jogadores (não-master) estiverem prontos.
    """
    if lobby.status != 'espera':
        return
    jogador.pronto = not jogador.pronto
    atualizar_lista_usuarios(lobby)


@socketio.on('comprometer_seed')
@evento_mutavel(cooldown=None)
@autenticar()
def comprometer_seed(dados, lobby, jogador):
    """
    Verificação de integridade (provably fair), fase de compromisso: o cliente
    envia apenas o compromisso SHA-256 do nonce dele (o nonce fica no cliente).
    O servidor publica o compromisso e, quando todos comprometeram, pede a
    revelação dos nonces.
    `cooldown=None`: o commit é idempotente (o primeiro vale) e dispara em
    rajada única no fluxo da espera — um drop silencioso pelo cooldown deixaria
    o jogador de fora da seed (sem_reveal) sem como recuperar.
    """
    if not lobby.config.get('verificacao_ativa') or lobby.status != 'espera':
        return
    if lobby.registrar_compromisso(jogador, dados.get('compromisso')):
        emit('seed_compromissos', lobby.info_publica_seed(), to=lobby.sala_room())
        if lobby.compromissos_completos():
            emit('seed_revelar', {'sala': lobby.sala_id}, to=lobby.sala_room())
        salvar_sala(lobby)


@socketio.on('revelar_seed')
@evento_mutavel(cooldown=None)
@autenticar()
def revelar_seed(dados, lobby, jogador):
    """
    Verificação de integridade (provably fair), fase de revelação: o cliente
    revela o nonce e o servidor confere contra o compromisso publicado. A
    revelação é transmitida à sala (pública) para que qualquer cliente recompute
    a seed e detecte substituição do nonce pelo servidor. A partida só libera
    quando todos revelam (ver `Lobby.pode_iniciar`).

    `cooldown=None`: o `seed_revelar` chega logo após o compromisso (dentro da
    janela do cooldown), e o cliente marca a revelação como enviada sem retry —
    um drop silencioso deixaria `pode_iniciar` preso em "aguardando_revelacao"
    para sempre, com todos prontos e o master sem conseguir iniciar.
    """
    if not lobby.config.get('verificacao_ativa') or lobby.status != 'espera':
        return
    if lobby.registrar_revelacao(jogador, dados.get('nonce')):
        emit('seed_revelacao', {'client_id': jogador.client_id, 'nonce': jogador.nonce_seed},
             to=lobby.sala_room())
        # Recalcula `pode_iniciar`/motivo e atualiza os botões de todos.
        atualizar_lista_usuarios(lobby)


@socketio.on('solicitar_auditoria')
@evento_leitura
@autenticar()
def solicitar_auditoria(dados, lobby, jogador):
    """
    Reenvia o payload de auditoria da partida atual (ex.: reconexão na tela 4).
    Fase 52: somente-leitura — não adquire o lock distribuído (evento_leitura),
    só o cooldown, como `listar_partidas`/`criar_sala`.
    """
    partida = jogador.partida_atual
    if partida is None or not partida.seed_info:
        return
    emit('auditoria_partida', partida.montar_auditoria(), to=jogador.client_id, ignore_queue=True)


@socketio.on('adicionar_ia')
@evento_mutavel
@autenticar(exigir_master=True)
def adicionar_ia(dados, lobby, jogador):
    """O master adiciona bots à sala de espera (níveis 1-4, Fase 11)."""
    if lobby.status != 'espera':
        return
    if ia.adicionar_bots(lobby, dados.get('nivel', 2), dados.get('quantidade', 1)):
        atualizar_lista_usuarios(lobby)
        _avisar_lobby_lotado(lobby, jogador)


@socketio.on('completar_com_ias')
@evento_mutavel
@autenticar(exigir_master=True)
def completar_com_ias(dados, lobby, jogador):
    """O master preenche as vagas restantes da sala com bots (Fase 11)."""
    if lobby.status != 'espera':
        return
    if ia.completar_bots(lobby, dados.get('nivel', 2)):
        atualizar_lista_usuarios(lobby)
        _avisar_lobby_lotado(lobby, jogador)


@socketio.on('remover_ia')
@evento_mutavel
@autenticar(exigir_master=True)
def remover_ia(dados, lobby, jogador):
    """O master remove bots da sala de espera, por nível ou todos (Fase 11)."""
    if lobby.status != 'espera':
        return
    if ia.remover_bots(lobby, dados.get('nivel')) > 0:
        atualizar_lista_usuarios(lobby)


def _avisar_lobby_lotado(lobby, jogador):
    """
    Avisa o master quando a sala de espera lotou com os bots recém-adicionados
    (Fase 57): no mobile o cliente usa o `lobby_lotado` para voltar o carrossel
    do lobby ao card "Jogadores" — só volta quando TODAS as vagas foram
    preenchidas, não a cada bot adicionado. Só dispara se o limite foi
    atingido; quem ainda tem vaga não recebe o evento.
    """
    limite = int(lobby.config.get('max_jogadores', 6))
    if len(lobby.jogadores) >= limite:
        emit('lobby_lotado', {}, to=jogador.client_id, ignore_queue=True)


@socketio.on('expulsar_jogador')
@evento_mutavel
@autenticar(exigir_master=True)
def expulsar_jogador(dados, lobby, jogador):
    """
    O master expulsa um jogador (humano ou IA) da sala. Vale na sala de espera
    e durante a partida: o expulso é removido do lobby (e da partida/rodada, se
    estiver jogando) e, se for humano, perde a identidade na sala — sai da room,
    perde o índice sid e recebe `expulso_da_sala` para voltar à home. A remoção
    reusa o fluxo de desconexão (`_remover_jogador_da_sala`), então a vez, a
    conferência e a vitória nunca ficam presas esperando o expulso.
    """
    alvo_id = dados.get('client_id', '')
    if not isinstance(alvo_id, str) or not alvo_id:
        return
    alvo = lobby.buscar_jogador_pelo_client_id(alvo_id)
    if alvo is None or alvo is jogador:
        return
    nome = alvo.username or 'Jogador'
    if alvo in lobby.espectadores:
        lobby.espectadores.remove(alvo)
    else:
        _remover_jogador_da_sala(lobby, alvo)
        # Fase 30: expulso não é "vaga perdida por inatividade" — se voltar com a
        # chave antiga, o `retomar_negado` não deve acusar inatividade.
        lobby.vagas_recentes.pop(alvo.chave_secreta, None)
    if not alvo.is_ia:
        desregistrar_cliente(alvo_id, lobby.sala_id)
        leave_room(lobby.sala_room(), sid=alvo_id)
        emit('expulso_da_sala', {'sala': lobby.sala_id}, to=alvo_id)
    lobby.definir_master()
    emit('jogador_expulso', {'nome': nome}, to=lobby.sala_room())
    ia.processar(lobby)
    atualizar_lista_usuarios(lobby)


@socketio.on('sair_da_sala')
@evento_mutavel(cooldown=None)
@autenticar(extrair_chave=None)
def sair_da_sala(dados, lobby, jogador):
    """
    Fase 30: sair da sala explicitamente e voltar ao menu. Duas situações valem:
    - ESPECTADOR (assistindo uma partida em andamento): sai na hora — identidade
      é o sid, sem chave (não tem stake na sala).
    - JOGADOR fora de uma partida: na ESPERA (lobby) ou já eliminado (zerou os
      dados e virou espectador na tela, mas ainda conta como jogador do lobby) —
      abandono explícito: remove imediatamente, sem consumir a janela de
      reconexão (a graça é para queda/refresh, não para sair). Exige a chave
      secreta; a vaga liberada não vira "perdida por inatividade".
    Jogador ativo no meio de uma partida: no-op — continua usando a janela de
    reconexão (`handle_disconnect`), como antes. Se o master sai, `definir_master`
    repassa a outra pessoa; se era o último humano, o GC fecha a sala. O
    `saiu_da_sala` faz o front limpar a chave e navegar para a home.
    `cooldown=None`: idempotente e voltado ao usuário — um drop silencioso
    deixaria o clique do jogador sem efeito.
    """
    if jogador in lobby.espectadores:
        lobby.espectadores.remove(jogador)
    elif jogador.partida_atual is None or jogador not in jogador.partida_atual.jogadores:
        if not hmac.compare_digest(jogador.chave_secreta, str(dados.get('chave', '') or '')):
            return
        _remover_jogador_da_sala(lobby, jogador)
        # Fase 30: saída explícita não é "vaga perdida por inatividade" (como na
        # expulsão) — o retorno com a chave antiga não deve acusar inatividade.
        lobby.vagas_recentes.pop(jogador.chave_secreta, None)
        lobby.definir_master()
    else:
        return
    desregistrar_cliente(jogador.client_id, lobby.sala_id)
    leave_room(lobby.sala_room(), sid=jogador.client_id)
    emit('saiu_da_sala', {'sala': lobby.sala_id}, to=jogador.client_id, ignore_queue=True)
    if _gc_sala(lobby):
        return
    atualizar_lista_usuarios(lobby)


@socketio.on('listar_partidas')
@evento_leitura
def listar_partidas(dados):
    """
    Retorna a listagem de partidas públicas (com filtros) para a tela de busca.
    Responde apenas ao cliente que pediu (to=client_id).
    """
    dados = dados if isinstance(dados, dict) else {}
    client_id = request.sid
    filtros = dados.get('filtros', {})
    sala_atual = dados.get('sala_atual')
    resumos = listar_resumos_partidas(filtros, sala_atual=sala_atual)
    emit('partidas_listadas', {'partidas': resumos}, to=client_id, ignore_queue=True)


@socketio.on('criar_sala')
@evento_leitura
def criar_sala(dados=None):
    """
    Gera um código de sala no servidor (Fase 9): charset sem caracteres ambíguos
    e checagem de colisão no store. O cliente navega para a sala devolvida.
    Evento somente-leitura (não cria o Lobby; o connect o faz).
    """
    codigo = gerar_codigo_sala()
    if codigo is None:
        return
    emit('sala_criada', {'sala': codigo}, to=request.sid, ignore_queue=True)


@socketio.on('verificar_desconectados')
@evento_mutavel
@autenticar(extrair_chave=None)
def verificar_desconectados(dados, lobby, jogador):
    """
    Os clientes agendam este evento após receberem 'jogador_desconectado'
    (Fase 9): garante que alguém expurgue, após a janela de graça, quem caiu no
    meio da partida e não voltou — sem depender de timer no servidor.
    achar_jogador já faz o GC unificado; aqui só o disparamos de novo.
    """
    _gc_sala(lobby)


@socketio.on('espectador_leitura')
@evento_mutavel(cooldown=None, lock_distribuido=True)
@autenticar()
def espectador_leitura(dados, lobby, jogador):
    """
    Fase 69: poll do espectador. Quando a partida fica SEM humano com dados
    (o último humano foi eliminado, ou a sala é só de bots), o `ia.processar`
    deixa de simular a partida inteira numa tacada e passa a liberar um lance
    por chamada, no ritmo do relógio gravado no lobby (`proximo_lance_em`).

    Quem paga o ritmo é o cliente que assiste: ele chama este evento, e o
    servidor responde `espectador_ritmo` com o tempo que falta para o próximo
    lance (ou 0, se o lance já rodou e a narração vem na sequência). O poll
    nunca precisa "adivinhar" o ritmo — sem isso, um poll cedo demais ficaria
    sem resposta e o cliente pararia de pedir.

    Exige a `chave_secreta` do jogador (invariante dos handlers mutáveis): o
    poll não muta nada por conta própria — a mutação (um lance) acontece em
    `ia.processar`, idempotente pelo relógio —, mas a chave evita que um socket
    qualquer force o avanço da sala. `cooldown=None`: um drop silencioso pelo
    cooldown travaria a única fonte de avanço da partida assistida.
    """
    if ia.processar(lobby):
        salvar_sala(lobby)
    restante = ia.ms_ate_proximo_lance(lobby)
    if restante is not None:
        emit('espectador_ritmo', {'restante_ms': restante}, to=jogador.client_id, ignore_queue=True)


@socketio.on('heartbeat')
@evento_mutavel(lock_distribuido=False)
def heartbeat(dados=None):
    """
    Renova o sinal de vida do resumo da sala na busca (Fase 17). Sem isso, uma
    instância serverless que morre sem disparar disconnect deixa o resumo
    congelado e a sala fantasma aparecia como ativa por até o TTL do store.

    Fase 18/19 (Vercel): na sala de espera o heartbeat vira o canal de re-sync
    entre instâncias. As rooms/emits do Socket.IO vivem em memória por instância,
    então quem entrou/ficou pronto numa instância diferente não alcança o
    broadcast do host; aqui o servidor devolve o snapshot atual do lobby (lido
    do store compartilhado) direcionado ao cliente que bateu.

    Fase E: além da lista da espera, o heartbeat re-sincroniza MUDANÇAS DE
    PÁGINA. O cliente informa a página atual (`pagina`); se ela divergir da
    autoritativa (ex.: o master iniciou a partida e o `mudar_pagina` ficou na
    instância dele), o servidor devolve o snapshot completo da tela atual
    (`enviar_snapshot_sala`) — senão o jogador da outra instância fica preso na
    sala de espera para sempre.

    Fase E2: o re-sync da espera SEMPRE lê o estado fresco do store (não só o
    master, e não via o cache da Fase C). Antes, o jogador não-master da espera
    recebia a lista do cache defasado e o início da partida só era detectado
    quando o cache expirava — na Vercel isso era o bug recorrente de o host não
    ver quem entra/fica pronto e o jogador não avançar de tela.

    Fase D2: o re-sync da partida ganhou o indicador de vez. O cliente informa
    a página e quem ele acredita estar na vez (`vez`); se o da vez divergir do
    autoritativo (um `meu_turno`/`espera_turno` de troca de vez se perdeu entre
    instâncias — comum logo após um refresh, já que o socket novo pode pousar
    numa instância diferente da dos demais), o servidor reemite só o dispatcher
    de vez (`emitir_dispatcher_turno`) em vez do snapshot inteiro.

    Fase C: ao contrário dos demais handlers, este NÃO passa por `autenticar` —
    lê pelo índice em processo (`sala_do_cliente`) e usa o cache tolerante a
    defasagem (`store.carregar_sala_leve`) para o heartbeat da PARTIDA, evitando
    um GET + deserialização na Upstash por cliente (estourava o free tier). Com
    o estado vindo do cache (até 25s de defasagem) não roda `ia.processar` —
    mutação só com leitura fresca, para não mover duas vezes o mesmo turno entre
    instâncias. O `visto_em` tem piso de 60s para o resumo não ser reescrito a
    cada batida.

    Fase 60 (fast path): a maioria das batidas NÃO pode mutar nada — sala de
    espera (ia é inerte na página 0) ou partida ociosa servida do cache sem
    divergência. Nessas, o lock distribuído (2 comandos no store) é desnecessário
    e o heartbeat roda apenas com o lock local: espera re-sincroniza SEMPRE do
    store (E2, leitura sem lock — nunca muta a sala), partida quieta não
    reescreve nada além do resumo. Só quando há mutação possível — leitura
    fresca (cache estourou) OU divergência detectada, numa sala EM PARTIDA — o
    handler adquire `trancar_sala_distribuida` e refaz a leitura DENTRO do lock
    antes de `ia.processar` (evita mover o turno com estado de antes do lock).
    """
    dados = dados if isinstance(dados, dict) else {}
    client_id = request.sid
    sala_id = sala_do_cliente(client_id)
    if sala_id is None:
        return
    lobby, veio_do_cache = store.carregar_sala_leve(sala_id)
    if lobby is None or lobby.buscar_jogador_pelo_client_id(client_id) is None:
        return
    jogador = lobby.buscar_jogador_pelo_client_id(client_id)
    pagina_cliente = int(dados.get('pagina', 0) or 0)
    pagina_sala = lobby.pagina or 0
    # Fase D2 (refresh/cross-instance): o cliente também informa quem ele
    # acredita ser o da vez na página de turnos (2). Se divergir do estado
    # autoritativo, o `meu_turno`/`espera_turno` de uma troca de vez ficou na
    # instância de origem (gap entre instâncias) e o jogador ficaria preso sem
    # o menu de jogada — o heartbeat reemite só o dispatcher de vez.
    vez_cliente = str(dados.get('vez', '') or '')
    vez_sala = ''
    espectador_aux = True
    if pagina_sala == 2:
        partida_aux = lobby.partidas[-1] if lobby.partidas else None
        if partida_aux is not None and partida_aux.rodadas:
            vez_aux = partida_aux.rodadas[-1].vez_atual
            if vez_aux is not None:
                vez_sala = vez_aux.username or ''
            espectador_aux = jogador not in partida_aux.jogadores
    # Espectador não tem menu de jogada: nunca dispara o re-sync de vez.
    vez_divergente = pagina_sala == 2 and not espectador_aux and vez_cliente != vez_sala

    # Fase 60 (fast path): o lock distribuído só entra quando o heartbeat PODE
    # mutar a sala — leitura fresca (cache estourou) OU divergência detectada,
    # numa sala em partida (status != espera). Espera e partida quieta servida
    # do cache NÃO mutam o Lobby: a espera re-sincroniza do store SEM lock (ia é
    # inerte e a leitura é pura — sem risco de lost-update), a partida quieta só
    # renova o resumo. A lista da espera e o snapshot da página corrente vêm do
    # store compartilhado para quem bateu, cobrindo o gap dos broadcasts que
    # ficam presos na instância de origem (Fases 18/19/E/E2).
    def _vez_divergente_de(lobby_re, jogador_re):
        """
        Recomputa a divergência de vez do lobby RELIDO: o valor calculado antes
        do lock pode ter mudado entre a leitura e a aquisição (outra instância
        avançou o turno). Espectador não tem menu de jogada (nunca reemite).
        """
        if (lobby_re.pagina or 0) != 2:
            return False
        partida_re = lobby_re.partidas[-1] if lobby_re.partidas else None
        if partida_re is None or not partida_re.rodadas:
            return False
        vez_re = partida_re.rodadas[-1].vez_atual
        if vez_re is None or jogador_re not in partida_re.jogadores:
            return False
        return vez_cliente != (vez_re.username or '')

    def _emitir_re_sync(lobby_re, jogador_re, pagina_sala_re, vez_divergente_re):
        if lobby_re.status == 'espera':
            emit("update_user_list", montar_payload_lista_usuarios(lobby_re), to=client_id, ignore_queue=True)
        if pagina_cliente != pagina_sala_re:
            enviar_snapshot_sala(lobby_re, jogador_re)
        elif vez_divergente_re:
            # Tela já montada e na página certa: falta só o indicador de vez
            # (menu de jogada) que se perdeu entre instâncias.
            emitir_dispatcher_turno(lobby_re, jogador_re)

    def _renovar_sinal(lobby_re):
        if lobby_re.visto_em is None or (datetime.now() - lobby_re.visto_em).total_seconds() >= 60:
            lobby_re.marcar_visto()
        store.salvar_resumo(lobby_re.sala_id, lobby_re.resumo_partida())

    # Fase 69: partida só de IAs (o último humano foi eliminado) com relógio
    # pendente — o avanço é pago pelo poll do espectador; o heartbeat entra
    # como rede de segurança (fechou a aba, o poll morreu?). Força o caminho
    # lockado mesmo com o cache quente, senão a sala ficaria parada.
    partida_so_ias = (lobby.status != 'espera' and lobby.pagina in (1, 2, 3, 4)
                      and ia.somente_ias_com_dados(lobby) and ia.tem_relogio(lobby))

    if (not veio_do_cache or pagina_cliente != pagina_sala or vez_divergente
            or partida_so_ias) and lobby.status != 'espera':
        with trancar_sala_distribuida(sala_id):
            # Re-leitura fresca DENTRO do lock: entre a leitura pré-lock e a
            # aquisição outra instância pode ter avançado o turno — processar
            # com o objeto de antes do lock moveria a partida duas vezes.
            lobby = store.carregar_sala(sala_id)
            if lobby is None or lobby.buscar_jogador_pelo_client_id(client_id) is None:
                return
            jogador = lobby.buscar_jogador_pelo_client_id(client_id)
            pagina_sala = lobby.pagina or 0
            # Re-sync lento (cache estourado/divergência): reemite o que se
            # perdeu entre instâncias — lista da espera, snapshot da página, ou
            # o menu de vez (gap de broadcast preso na instância de origem).
            _emitir_re_sync(lobby, jogador, pagina_sala, _vez_divergente_de(lobby, jogador))
            if lobby.visto_em is None or (datetime.now() - lobby.visto_em).total_seconds() >= 60:
                lobby.marcar_visto()
            if ia.processar(lobby):
                # Um SÓ save para o Lobby + resumo da busca (Fase 60).
                store.salvar_sala_com_resumo(lobby, lobby.resumo_partida())
                return
            _renovar_sinal(lobby)
        return

    if lobby.status == 'espera':
        # Fase E2: o re-sync da espera SEMPRE lê o estado fresco do store (o
        # cache tolerante a defasagem da Fase C fica só para o heartbeat da
        # partida). Recarregar a cada batida da espera (a cada 20s) é o custo
        # certo para o re-sync; o cache ainda evita o GET da partida.
        lobby = store.carregar_sala(sala_id)
        if lobby is None or lobby.buscar_jogador_pelo_client_id(client_id) is None:
            return
        if lobby.status == 'espera':
            jogador = lobby.buscar_jogador_pelo_client_id(client_id)
            _emitir_re_sync(lobby, jogador, lobby.pagina or 0, _vez_divergente_de(lobby, jogador))
            _renovar_sinal(lobby)
            return
        # A leitura fresca revelou que a partida começou (o cache dizia espera):
        # o re-sync e a limpeza de fila de IA agora precisam do lock distribuído.
        with trancar_sala_distribuida(sala_id):
            lobby = store.carregar_sala(sala_id)
            if lobby is None or lobby.buscar_jogador_pelo_client_id(client_id) is None:
                return
            jogador = lobby.buscar_jogador_pelo_client_id(client_id)
            pagina_sala = lobby.pagina or 0
            _emitir_re_sync(lobby, jogador, pagina_sala, _vez_divergente_de(lobby, jogador))
            if lobby.visto_em is None or (datetime.now() - lobby.visto_em).total_seconds() >= 60:
                lobby.marcar_visto()
            if ia.processar(lobby):
                store.salvar_sala_com_resumo(lobby, lobby.resumo_partida())
                return
            _renovar_sinal(lobby)
        return

    # Partida quieta servida do cache (sem divergência): nada mutável — o
    # resumo da busca é o único write, e só quando o `visto_em` passou de 60s.
    _renovar_sinal(lobby)


@socketio.on('jogar_dados')
@evento_mutavel
@autenticar()
def jogar_dados(dados, lobby, jogador):
    """
    Esta função envia os números dos dados sorteados aos jogadores, cada jogador recebe seus
    respectivos dados sorteados.
    """
    if jogador.rodada_atual is None:
        return
    # Fase 7 (A6): idempotência explícita por rodada — já rolou não rola de novo.
    if jogador.joguei_dados:
        # Reenvio idempotente: se o jogador já rolou mas perdeu o resultado
        # (cooldown/rede), o re-clique reentrega o `jogar_dados_resultado` em
        # vez de abortar em silêncio — destrava a rolagem (Fase 22).
        emit("jogar_dados_resultado", {"jogador": jogador.client_id, "dados_jogador": jogador.dados},
             to=jogador.client_id, ignore_queue=True)
        # Fase 72: repõe também a pill de confirmação da rolagem. Só o primeiro
        # branch a emitia; sem isto, um retry de resultado perdido devolvia os
        # dados mas deixava o status desatualizado (pill "não definida").
        emitir_status_rolagem(lobby)
        return
    jogador.joguei_dados = True
    # Fase 22: mostra em tempo real quem já rolou e quem ainda falta.
    emitir_status_rolagem(lobby)
    # Fase 10 (S4): escopo explícito — o resultado é só de quem rolou.
    emit("jogar_dados_resultado", {"jogador": jogador.client_id, "dados_jogador": jogador.dados},
         to=jogador.client_id, ignore_queue=True)
    salvar_sala(lobby)


@socketio.on('joguei_dados')
@evento_mutavel
@autenticar(extrair_chave=lambda d: d.get('chave_secreta', ''))
def joguei_dados(dados, lobby, jogador):
    """
    Esta função é executada por cada jogador da partida quando termina de executar e visualizar o resultado de seus
    dados. Ela deve redirecionar todos os jogadores para a próxima tela (2), onde se inicia a partida de fato, com os
    turnos, mas somente depois de todos os dados terem sido jogados.
    """
    if jogador.rodada_atual is None:
        return
    # Fase 10 (S4): escopo explícito — os dados são só de quem confirmou.
    emit('meus_dados', {'dados': jogador.dados}, to=jogador.client_id, ignore_queue=True)
    rodada = jogador.rodada_atual
    # Executar isso \/ quando o último jogar os dados
    if rodada.verificar_se_todos_ja_jogaram_seus_dados():
        lobby.pagina = 2
        mudar_pagina(2, sala=lobby.sala_id)
    ia.processar(lobby)
    salvar_sala(lobby)


@socketio.on('autojogar')
@evento_mutavel(cooldown=None)
@autenticar()
def autojogar(dados, lobby, jogador):
    """
    Jogada automática por tempo máximo (Fase 21/22): o cliente inicia um contador
    ao entrar na rolagem (página 1), quando recebe `meu_turno` (página 2) ou ao
    abrir a conferência/vitória (páginas 3 e 4); ao expirar, dispara este evento
    e o servidor joga pelo humano atrasado — rola os dados, decide uma
    aposta/desconfiança válida com o motor da IA (`ia.decidir`/`ia.executar_acao`)
    ou confirma o "Ok" da conferência/vitória, sem revelar dados de ninguém.

    O servidor confere o tempo decorrido desde `rodada.inicio_rolagem_em`
    (rolagem), `rodada.vez_em` (turno), `rodada.conferencia_em` (conferência) ou
    `partida.vitoria_em` (vitória) antes de agir, então o evento não vira um
    "auto-play instantâneo" que beneficiaria o jogador.

    `cooldown=None`: o evento é idempotente (o servidor só age se for realmente
    a vez do jogador e o tempo já tiver passado) e espaçado pelo fluxo — um drop
    silencioso pelo cooldown deixaria a sala presa, que é o travamento que esta
    funcionalidade existe para evitar.
    """
    tempo_max = int(lobby.config.get('tempo_max_jogada', 0) or 0)
    if tempo_max <= 0:
        return
    agora = datetime.now()
    if lobby.pagina == 1:
        # Rolar os dados do atrasado (o avanço de página continua no fluxo do
        # `joguei_dados`/`ia.processar`, como na jogada manual).
        rodada = jogador.rodada_atual
        if rodada is None or jogador not in rodada.jogadores or jogador.joguei_dados:
            return
        inicio = rodada.inicio_rolagem_em
        if inicio is not None and (agora - inicio).total_seconds() < tempo_max:
            return
        jogador.joguei_dados = True
        emit("jogar_dados_resultado", {"jogador": jogador.client_id, "dados_jogador": jogador.dados},
             to=jogador.client_id)
        emitir_status_rolagem(lobby)
        ia.processar(lobby)
    elif lobby.pagina == 2:
        rodada = jogador.rodada_atual
        if rodada is None or rodada.vez_atual is not jogador:
            return
        vez_em = rodada.vez_em
        if vez_em is not None and (agora - vez_em).total_seconds() < tempo_max:
            return
        acao = ia.decidir(jogador, rodada, AUTO_IA_NIVEL)
        ia.executar_acao(jogador, rodada, acao)
        ia.processar(lobby)
    elif lobby.pagina == 3:
        # Fase 22: auto-confirma o "Ok" da conferência para o humano atrasado
        # (jogador away from keyboard não trava mais a tela). O fluxo de avanço
        # da rodada fica com o `ia.processar`, como na confirmação manual.
        rodada = jogador.rodada_atual
        if rodada is None or jogador not in rodada.jogadores or jogador.confirmou_rodada:
            return
        inicio = rodada.conferencia_em
        if inicio is not None and (agora - inicio).total_seconds() < tempo_max:
            return
        jogador.confirmou_rodada = True
        rodada.conferiram += 1
        emitir_status_conferencia(lobby)
        if rodada.conferiram >= len(rodada.jogadores):
            jogador.partida_atual.construir_rodada()
        ia.processar(lobby)
    elif lobby.pagina == 4:
        # Fase 22: idem na tela de vitória — confirma o reset pelo atrasado.
        partida = jogador.partida_atual
        if jogador not in lobby.jogadores or jogador.confirmou_vencedor:
            return
        inicio = partida.vitoria_em if partida else None
        if inicio is not None and (agora - inicio).total_seconds() < tempo_max:
            return
        jogador.confirmou_vencedor = True
        lobby.conferiram_vencedor += 1
        emitir_status_vitoria(lobby)
        if lobby.conferiram_vencedor >= len(lobby.jogadores):
            lobby.resetar_para_lobby()
            atualizar_lista_usuarios(lobby)
            mudar_pagina(0, sala=lobby.sala_id)
        ia.processar(lobby)
    else:
        return
    salvar_sala(lobby)


@socketio.on('apostar')
@evento_mutavel
@autenticar(extrair_chave=_chave_aninhada)
def aposta(dados, lobby, jogador):
    """
    Função executada pelo jogador quando ele faz uma aposta, mas antes verifica se o jogador está em uma rodada e se
    ele é o da vez no turno.
    """
    # Fase 15: só vale na tela de turnos (2). Sem o gate, um cliente atrasado
    # (ou malicioso) poderia apostar durante a conferência/vitória e corromper
    # a rodada (a vez continua sendo dele quando a desconfiança fecha).
    if lobby.pagina != 2:
        return
    internos = dados.get('dados')
    if not isinstance(internos, dict):
        return
    dados_aposta = internos.copy()
    dados_aposta.pop('chave', None)
    rodada = jogador.rodada_atual
    if rodada and rodada.vez_atual == jogador:
        # Fase 59: heurística anti-automação — aposta em <200ms ou padrão de
        # horário marca o jogador como suspeito (delay extra nas ações) e vai
        # para o log estruturado (sem PII).
        for detecao in anti_fraude.registrar_acao(jogador.client_id, 'aposta'):
            observabilidade.log_evento_suspeito(detecao, jogador.client_id,
                                                _ip_do_cliente())
            anti_fraude.marcar_suspeito(jogador, detecao)
        rodada.construir_turno(jogador=jogador, dados=dados_aposta)
        ia.processar(lobby)
        salvar_sala(lobby)


@socketio.on('desconfiar')
@evento_mutavel
@autenticar(extrair_chave=_chave_aninhada)
def desconfiar(dados, lobby, jogador):
    """
    Função executada pelo jogador quando ele desconfia de uma aposta, mas antes verifica se o jogador está em uma
    rodada e se ele é o da vez no turno.
    """
    # Fase 15: idem `aposta` — desconfiar só na tela de turnos (2), senão um
    # segundo desconfio durante a conferência re-emitiria/alteraria a rodada.
    if lobby.pagina != 2:
        return
    rodada = jogador.rodada_atual
    if rodada and rodada.vez_atual == jogador and len(rodada.turnos) > 0:
        # Fase 59: heurística anti-automação — rajada de desconfianças (<5s)
        # e análise binomial da taxa de acerto das apostas.
        for detecao in anti_fraude.registrar_acao(jogador.client_id, 'desconfiar'):
            observabilidade.log_evento_suspeito(detecao, jogador.client_id,
                                                _ip_do_cliente())
            anti_fraude.marcar_suspeito(jogador, detecao)
        rodada.desconfiar(jogador=jogador)
        # Se a conferência já foi montada (desconfiança aceita), alimenta a
        # estatística binomial do apostador que errou/acertou — se a taxa dele
        # cruzar o limiar, vira suspeito (bot calcula aposta exata).
        conferencia = getattr(rodada, 'conferencia', None)
        if conferencia and len(rodada.turnos) > 0:
            apostador = rodada.turnos[-1].do_jogador
            if anti_fraude.marcar_resultado_aposta(
                    apostador.client_id, conferencia.get('verdadeira', False)):
                # `ip=None`: o request corrente é do DESCONFIADOR; não temos o IP
                # do apostador aqui (não inventar auditoria trocada).
                observabilidade.log_evento_suspeito(
                    'acuracia_binomial', apostador.client_id, None)
                anti_fraude.marcar_suspeito(apostador, 'acuracia_binomial')
        ia.processar(lobby)
        salvar_sala(lobby)


@socketio.on('conferencia_final')
@evento_mutavel(cooldown=None)
@autenticar()
def conferencia_final(dados, lobby, jogador):
    """
    Quanto todos os participantes da rodada clicam em ok, na conferência final da rodada, esta função engatilha
    uma nova rodada na partida.
    """
    if jogador.rodada_atual is None or jogador.partida_atual is None:
        return
    # Fase 15: só vale na tela de conferência (3). Sem este gate, um cliente
    # podia confirmar durante os turnos e adiantar/encerrar a rodada.
    if lobby.pagina != 3:
        return
    if jogador.confirmou_rodada:
        return
    rodada = jogador.rodada_atual
    jogador.confirmou_rodada = True
    rodada.conferiram += 1
    # Fase 22: mostra em tempo real quem já clicou no "Ok" e quem falta.
    emitir_status_conferencia(lobby)
    # `>=` (não `==`): se um jogador foi removido da rodada no meio da conferência,
    # o contador pode já estar igual/maior que o total atual — travar o jogo aqui
    # deixaria a tela de conferência presa para sempre.
    if rodada.conferiram >= len(rodada.jogadores):
        jogador.partida_atual.construir_rodada()
    ia.processar(lobby)
    salvar_sala(lobby)


@socketio.on('vencedor_final')
@evento_mutavel(cooldown=None)
@autenticar()
def vencedor_final(dados, lobby, jogador):
    """
    Quanto todos os participantes da rodada clicam em ok, na tela de vencedor, esta função engatilha
    uma nova partida no lobby.
    """
    if jogador.confirmou_vencedor:
        return
    # Fase 15: só vale na tela de vitória (4) e para jogadores da sala — um
    # espectador não pode contar para o reset.
    if lobby.pagina != 4 or jogador not in lobby.jogadores:
        return
    jogador.confirmou_vencedor = True
    lobby.conferiram_vencedor += 1
    # Fase 22: mostra em tempo real quem já clicou no "Ok" e quem falta.
    emitir_status_vitoria(lobby)
    # `>=` (não `==`): mesma ressalva da conferência — jogador removido no meio
    # não pode deixar o contador de vitória maior que o lobby e travar o reset.
    if lobby.conferiram_vencedor >= len(lobby.jogadores):
        lobby.resetar_para_lobby()
        atualizar_lista_usuarios(lobby)
        mudar_pagina(0, sala=lobby.sala_id)
    ia.processar(lobby)
    salvar_sala(lobby)


@socketio.on('foguetear_click')
@evento_mutavel
@autenticar()
def foguetear(dados, lobby, jogador):
    """
    Função que torna os fogos de comemoração compartilhados com todos na partida.
    """
    partida = jogador.partida_atual
    rodada = jogador.rodada_atual
    # Fase 6 (B4): partida encerrada por desconexão não define rodada.vencedor,
    # mas sim partida.vencedor_final — o vencedor precisa poder comemorar.
    if rodada is not None and rodada.vencedor == jogador:
        emit('soltar_fogos', to=lobby.sala_room())
    elif partida is not None and partida.vencedor_final == jogador:
        emit('soltar_fogos', to=lobby.sala_room())


if __name__ == '__main__':
    if os.environ.get("VERCEL") != "1":
        socketio.run(app, host='0.0.0.0', allow_unsafe_werkzeug=True)