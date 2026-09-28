// Fase 53: namespacing — o arquivo inteiro roda dentro de um IIFE para não
// vazar dezenas de globals (`indiceAtual`, `chave_secreta`, `sala_atual`, ...)
// que poluem `window` e podem colidir com bibliotecas de terceiros. Estado,
// socket e handlers ficam fechados no escopo do IIFE; só as ações do
// `data-acao` (que a delegação de cliques resolve por nome) são expostas em
// `window.Dadinho` (ver fim do arquivo). Sem `"use strict"`: o arquivo é
// clássico (sloppy) e o strict poderia quebrar comportamento existente.
(function () {
let indiceAtual = 0;
let chave_secreta = '';
let nome_jogador = '';
let sala_atual = getParamSala();
// Fase 18: sem código válido na URL o jogador fica na home — não cria sala
// automaticamente. `modo_home` controla qual painel da tela 0 aparece.
let modo_home = !sala_atual;
let sou_master = false;
// Contexto da aposta recebido em `meu_turno` para calibrar o mínimo do input.
let contexto_min_aposta = null;
// Fase 30: se o cliente está assistindo (espectador) — mostra o botão de sair.
let eh_espectador = false;
// Fase D: enquanto retoma identidade, o chave_secreta não corresponde ao
// servidor — ações mutáveis seriam rejeitadas silenciosamente. A flag
// bloqueia cliques até a retomada completar (segundo connect_start) ou
// ser descartada (retomar_negado / sala nova sem chave_resumo).
let chave_confirmada = true;
// Fase D3: sid da conexão cujo `connect_start` já foi processado. O socket.io
// pode disparar o `connect` local DEPOIS de processar a primeira mensagem do
// servidor (o `connect_start`) na mesma conexão; sem isso, o `connect`
// clobberaria a decisão do `connect_start` e travaria os botões para sempre.
let sid_ultimo_connect_start = null;

// Imagens dos dados (1-6): constante global reutilizada na animação de rolagem.
const diceImages = [
    "../static/imagens/dado/1.png",
    "../static/imagens/dado/2.png",
    "../static/imagens/dado/3.png",
    "../static/imagens/dado/4.png",
    "../static/imagens/dado/5.png",
    "../static/imagens/dado/6.png"
];

// Fase D / Fase P-Recover: a chave de identidade (para `retamar_identidade`) é
// lida de / gravada em localStorage POR SALA — e não mais em sessionStorage
// por aba. A sessionStorage era per-aba: quem abria a partida numa nova aba
// (ou tinha perdido a aba original) entrava sem `chave_resumo`, conectava com
// `tem_chave=0`, virava placeholder de espectador num lobby `jogando` e adotava a
// chave falsa do placeholder — ficava preso assistindo e NUNCA retomava o
// jogador (o humano caído e substituído por IA não voltava). Com a chave em
// localStorage[sala], a nova aba chega com `tem_chave=1`, o servidor adia o
// snapshot ao placeholder e o `retamar_identidade` recupera o jogador real
// (inclusive o substituído por IA) — "voltar a jogar a qualquer momento".
const CHAVE_ID = 'dadinho_chave';
// Chave de storage indexada pela sala: não vaza identidade entre abas de salas
// distintas (um jogador pode ter duas salas abertas). O salt é só evitar colisão
// com a chave legacy `dadinho_chave` (per-aba) durante a transição.
function _chave_armazenamento(sala) {
    return sala ? `${CHAVE_ID}:${sala}` : CHAVE_ID;
}
// Lê a chave: localStorage por sala (compartilhada entre abas) com fallback para
// a entrada legacy por-aba — migra-a na primeira leitura e limpa a sessionStorage
// para não deixar a aba antiga com identidade dupla.
function ler_chave_resumo(sala) {
    if (sala) {
        const local = localStorage.getItem(_chave_armazenamento(sala));
        if (local) {
            return local;
        }
    }
    const legacy = sessionStorage.getItem(CHAVE_ID) || '';
    if (legacy && sala) {
        localStorage.setItem(_chave_armazenamento(sala), legacy);
    }
    sessionStorage.removeItem(CHAVE_ID);
    return legacy;
}
function gravar_chave_resumo(chave) {
    if (chave && sala_atual) {
        localStorage.setItem(_chave_armazenamento(sala_atual), chave);
    }
    sessionStorage.removeItem(CHAVE_ID);
}
function limpar_chave_resumo() {
    if (sala_atual) {
        localStorage.removeItem(_chave_armazenamento(sala_atual));
    }
    localStorage.removeItem(CHAVE_ID);
    sessionStorage.removeItem(CHAVE_ID);
}
let chave_resumo = (sala_atual && ler_chave_resumo(sala_atual)) || '';
// Fase 46 (VPS): URL pública da API de socket.io lida do `<meta
// name="dadinho-api-url">` (injetado pelo servidor). Quando a API roda na VPS
// separada do frontend, o io() conecta na origem dela; vazio = mesmo host.
const api_url = (document.querySelector('meta[name="dadinho-api-url"]') || {}).content || '';
// WebSocket como transporte ÚNICO (Fase 66/E1, ADR-008): no serverless da
// Vercel o long-polling quebra (cada request de poll pode cair numa instância
// sem a sessão Engine.IO) e, na VPS multi-réplica, o polling pode ser
// fragmentado entre réplicas quando o IP real muda no meio da conexão (rede
// móvel/CGNAT) — a conexão nunca fecha e a tela "trava" sem erro. Com WS puro
// a tentativa inteira é UM upgrade HTTP: uma única decisão de roteamento do
// nginx, independente do sticky por IP. Redes que bloqueiam WS cru perdem o
// fallback de polling — a falha vira um `connect_error` explícito (Fase 65/M1)
// em vez de um hang silencioso.
// Fase 59 (captcha no connect, Cloudflare Turnstile): quando o servidor injeta
// <meta name="dadinho-turnstile-sitekey">, o connect é adiado até o token sair
// (a API recusa o handshake sem ele). Sem a meta, nada muda.
const captcha_sitekey = (document.querySelector('meta[name="dadinho-turnstile-sitekey"]') || {}).content || '';
const socket = io(api_url || undefined, {
    autoConnect: !captcha_sitekey,
    transports: ['websocket'],
    query: { sala: sala_atual, tem_chave: chave_resumo ? '1' : '0' },
    // Fase 68: o socket.io 4.6.0 embarca o engine.io-client 6.4, cujo default
    // `closeOnBeforeunload: true` registra um listener de `beforeunload` que
    // fecha o WebSocket de forma SÍNCRONA durante o reload/navegação. O close do
    // WS pelo Cloudflare Tunnel pode atrasar o unload e a página fica "travada/
    // em branco" no refresh — pior na rede móvel (Fase 64-66). O default só
    // mudou para `false` no engine.io 6.5. Aqui o socket é destruído junto com a
    // página; o servidor limpa o sid órfão no ping timeout e a retomada por
    // `chave_secreta` reconstrói o jogador no próximo connect.
    closeOnBeforeunload: false,
});

// Fase 67: o captcha é um script de terceiro e o connect só sai depois que ele
// resolve — em produção isso custa alguns segundos e, até o `connect_start`
// chegar, a tela mostrava o lobby "padrão" (badge `#padrao`, config travada).
// Aqui: (a) mostra "conectando" em vez do `#padrao` enganoso; (b) watchdog —
// se o Turnstile não carregar/travar, conecta mesmo assim (o servidor decide;
// com captcha ativo o `connect_error` mostra o motivo), nunca mais uma tela
// muda sem feedback. O script do Turnstile já vem no `<head>` (async, com
// preconnect) para começar a baixar antes do resto da página.
const CAPTCHA_TIMEOUT_MS = 6000;
let _captcha_conectou = false;

function _conectar_uma_vez() {
    if (_captcha_conectou) {
        return;
    }
    _captcha_conectou = true;
    socket.connect();
}

function conecta_com_token(token) {
    if (_captcha_conectou) {
        return;
    }
    socket.io.opts.query = Object.assign({}, socket.io.opts.query, { captcha_token: token });
    _conectar_uma_vez();
}

function conecta_com_captcha() {
    // Fail-open no CLIENTE: se o Turnstile não carregar ou der erro (rede,
    // bloqueador, sitekey/domínio errado), conecta sem token — o servidor
    // decide (com captcha ativo na API o connect é recusado e o erro aparece).
    if (!window.turnstile) {
        _conectar_uma_vez();
        return;
    }
    try {
        const caixa = document.createElement('div');
        caixa.style.display = 'none';
        document.body.appendChild(caixa);
        // Modo invisível: resolve sozinho na maioria dos casos; o token chega
        // pelo `callback`. `execute` dispara a verificação.
        const widget = window.turnstile.render(caixa, {
            sitekey: captcha_sitekey,
            size: 'invisible',
            callback: conecta_com_token,
            'error-callback': _conectar_uma_vez,
            'timeout-callback': _conectar_uma_vez,
        });
        window.turnstile.execute(widget);
    } catch (erro) {
        _conectar_uma_vez();
    }
}

if (captcha_sitekey) {
    // Estado visível enquanto a verificação não termina (evita o `#padrao`).
    if (sala_atual) {
        const badge_sala = document.getElementById('sala_atual');
        if (badge_sala) {
            badge_sala.textContent = '…';
        }
    }
    _atualizar_status_conexao('js.conectando', 'text-warning');
    const _inicio_captcha = Date.now();
    (function _esperar_turnstile() {
        if (_captcha_conectou) {
            return;
        }
        if (window.turnstile) {
            conecta_com_captcha();
            return;
        }
        if (Date.now() - _inicio_captcha > CAPTCHA_TIMEOUT_MS) {
            _conectar_uma_vez();
            return;
        }
        setTimeout(_esperar_turnstile, 100);
    })();
} else {
    _conectar_uma_vez();
}

// Fase 59: connect recusado pelo servidor (limite de conexões por IP ou
// captcha inválido). O servidor manda `motivo` com chave i18n — resolve aqui
// mesmo no cliente (invariante: o servidor nunca escolhe idioma). Só nesse caso
// (recusa intencional) o socket é desconectado de vez: sem isso, a reconexão
// automática repetiria o handshake num loop com o mesmo erro. Erro transitório
// (queda de rede, réplica reiniciando, ping timeout) NÃO desconecta — o
// socket.io continua tentando com backoff (o status_conexao sinaliza).
//
// Fase 65 (M1): erro genérico (sem `motivo`) também precisa sinalizar — antes
// caía num `return` silencioso e a tela parecia 100% normal enquanto o socket
// reconectava, daí o "trava sem erro" (ex.: handshake fragmentado entre
// réplicas, Fase 64). `connect_error` dispara a cada tentativa de conexão que
// falha (inclusive a primeira), então é o contador confiável: enquanto for
// oscilação breve mostra "reconectando"; depois de `TENTATIVAS_SEM_CONEXAO`
// falhas seguidas, vira um estado explícito de "sem conexão".
const TENTATIVAS_SEM_CONEXAO = 5;
let _tentativas_reconexao = 0;
// Fase 68: marcado quando o servidor recusa a conexão de propósito (captcha/
// limite de IP). Diferente de uma queda de rede, aqui não devemos reconectar
// sozinhos — o resync de `visibilitychange`/`online` respeita esta flag.
let _conexao_recusada = false;

socket.on('connect_error', function (erro) {
    const dados = (erro && erro.data) || null;
    if (!dados || !dados.motivo || !dados.motivo.chave) {
        _tentativas_reconexao += 1;
        if (_tentativas_reconexao >= TENTATIVAS_SEM_CONEXAO) {
            _atualizar_status_conexao('js.sem_conexao', 'text-danger');
        } else {
            _atualizar_status_conexao('js.reconectando', 'text-warning');
        }
        return;
    }
    _conexao_recusada = true;
    socket.disconnect();
    mostrar_alerta(t(dados.motivo.chave, dados.motivo.params || {}), 'erro');
});

// Heartbeat de sala: renova o "visto_em" no servidor para a busca distinguir
// salas vivas das órfãs do serverless (instância que morreu sem disconnect).
// Na sala de espera o intervalo é curto: o servidor usa a batida como re-sync
// do lobby entre instâncias (ver `heartbeat` no app.py) — quem entrou/ficou
// pronto numa instância diferente não alcança o broadcast do host, então o
// servidor devolve o snapshot atual do lobby para cada cliente que bate.
// Só emite quando o socket está conectado e já temos a chave de uma sala.
const INTERVALO_HEARTBEAT_ESPERA = 20000;
const INTERVALO_HEARTBEAT_PARTIDA = 60000;

// Fase 53: timer único guardado — o `agendar_heartbeat` recursivo antigo podia
// (a) morrer em silêncio se o callback lançasse erro antes de re-agendar (o
// `socket.emit` ou um acesso a estado com exceção) e (b) duplicar timers se a
// função fosse chamada duas vezes (spam de heartbeat no servidor). Agora há no
// máximo UM `setTimeout` pendente (`_timer_heartbeat`), o callback está em
// `try/catch` (o erro nunca derruba a batida seguinte) e o re-agendamento é
// garantido mesmo com exceção.
let _timer_heartbeat = null;

function agendar_heartbeat() {
    if (_timer_heartbeat !== null) return;
    const intervalo = indiceAtual === 0 ? INTERVALO_HEARTBEAT_ESPERA : INTERVALO_HEARTBEAT_PARTIDA;
    _timer_heartbeat = setTimeout(function () {
        _timer_heartbeat = null;
        try {
            if (socket.connected && chave_secreta) {
                socket.emit('heartbeat', { chave: chave_secreta, pagina: indiceAtual, vez: vez_atual_nome });
            }
        } catch (erro) {
            console.error('Erro ao bater o heartbeat', erro);
        }
        agendar_heartbeat();
    }, intervalo);
}
agendar_heartbeat();

// ---------------------------------------------------------------------------
// Fila de animação + narrador.
// O servidor pode anexar "atraso" (ms) ao payload de um evento para simular o
// tempo de pensamento dos bots. Todos os eventos passam por uma fila serial no
// cliente, preservando a ordem original e encaixando as pausas — sem timers no
// servidor (serverless-safe).
// ---------------------------------------------------------------------------
const _onevent_original = socket.onevent.bind(socket);
const fila_eventos = [];
let processando_eventos = false;

// Fase 53: a fila preserva a ordem e insere as pausas de "pensamento" dos bots.
// Se o servidor manda muitos eventos rápidos (ex.: 4 bots jogando em sequência),
// as pausas acumulam e a UI fica com "lag" crescente. Aqui o ATRASO é limitado:
// quando já há `MAX_ATRASO_FILA` ms de pausa pendente na fila, os próximos
// eventos entram com atraso 0 (processa na hora) — a ORDEM é preservada e
// nenhum evento é descartado, só as pausas extras são puladas.
// Dimensionado para ~2 lances de nível 4 (topo de `FAIXAS_PENSAMENTO`, 3560ms)
// antes de começar a pular pausas.
const MAX_ATRASO_FILA = 8000;
let atraso_pendente_total = 0;

function _processar_fila_eventos() {
    if (fila_eventos.length === 0) {
        processando_eventos = false;
        atraso_pendente_total = 0;
        esconder_pensando();
        return;
    }
    const item = fila_eventos.shift();
    atraso_pendente_total = Math.max(0, atraso_pendente_total - item.atraso);
    if (item.ia_nome) {
        mostrar_pensando(item.ia_nome, item.atraso);
    }
    setTimeout(function () {
        try {
            _onevent_original(item.packet);
        } catch (erro) {
            console.error('Erro ao processar evento', erro);
        }
        _processar_fila_eventos();
    }, item.atraso);
}

socket.onevent = function (packet) {
    const dados = packet && Array.isArray(packet.data) ? packet.data : [];
    const nome = dados[0];
    const payload = dados.length > 1 ? dados[1] : null;
    let atraso = 0;
    if (payload && typeof payload === 'object' && Number.isFinite(Number(payload.atraso))) {
        atraso = Math.max(0, Math.floor(Number(payload.atraso)));
    }
    if (atraso_pendente_total >= MAX_ATRASO_FILA) {
        atraso = 0;
    } else {
        atraso_pendente_total += atraso;
    }
    const ia_nome = (nome === 'narracao' && payload && payload.is_ia) ? (payload.jogador || 'Bot') : null;
    fila_eventos.push({ packet: packet, atraso: atraso, ia_nome: ia_nome });
    if (!processando_eventos) {
        processando_eventos = true;
        _processar_fila_eventos();
    }
};

// Defaults das preferências locais do cliente (não vão ao servidor). Ficam
// centralizados aqui: cada variável persistida abaixo só cai no valor daqui
// quando não há nada salvo em localStorage. Idioma é o único fora daqui —
// mora em i18n.js (`_detectar_idioma`), que detecta o navegador e cai em `en`.
const PADROES_CLIENTE = {
    som_ativado: true,
    volume_som: 70,
    musica_ativada: false,
    volume_musica: 40,
    narrador: 'completo',
    dicas: true,
};

// Modo de exibição do narrador, persistido entre sessões:
//   completo  -> histórico de falas (padrão)
//   ultima    -> mostra só a última fala
//   desligado -> painel escondido
// No mobile "completo" equivale a "ultima" (Fase 56).
const NARRADOR_MODOS = {
    completo: { icone: '🎙️', titulo: 'js.narrador.modo.completo', classe: 'btn-outline-info' },
    ultima: { icone: '💬', titulo: 'js.narrador.modo.ultima', classe: 'btn-outline-warning' },
    desligado: { icone: '🔕', titulo: 'js.narrador.modo.desligado', classe: 'btn-outline-secondary' },
};
const NARRADOR_CICLO = ['completo', 'ultima', 'desligado'];
// Fase 56: no mobile o narrador vira um toast que mostra só a última fala,
// então "todas as falas" e "só a última" são a mesma coisa — o botão do menu
// sandwich oferece apenas "só a última" e "desligado".
const NARRADOR_CICLO_MOBILE = ['ultima', 'desligado'];
let narrador_modo = localStorage.getItem('dadinho_narrador');
if (!NARRADOR_MODOS[narrador_modo]) {
    narrador_modo = PADROES_CLIENTE.narrador;
}

// Fase 35: no mobile (<768px) o narrador e as dicas viram um toast temporário
// (só a última fala, some sozinho) — os painéis fixos ficam fora do caminho.
function eh_mobile() {
    return window.matchMedia('(max-width: 768px)').matches;
}

// Fase 56: no mobile o painel é escondido e cada fala vira um toast, logo o
// modo "completo" se comporta como "ultima" — o modo efetivo normaliza isso.
function narrador_modo_efetivo() {
    return eh_mobile() && narrador_modo === 'completo' ? 'ultima' : narrador_modo;
}

function aplicar_estado_narrador() {
    const botao = document.getElementById('botao_narrador');
    const botao_menu = document.getElementById('menu_narrador');
    const painel = document.getElementById('narrador');
    const cfg = NARRADOR_MODOS[narrador_modo_efetivo()];
    if (botao) {
        botao.textContent = cfg.icone;
        botao.title = t(cfg.titulo);
        Object.keys(NARRADOR_MODOS).forEach(function (chave) {
            botao.classList.remove(NARRADOR_MODOS[chave].classe);
        });
        botao.classList.add(cfg.classe);
    }
    // Fase 33 (M1): o botão do drawer mostra o modo atual junto ao label.
    if (botao_menu) {
        botao_menu.textContent = cfg.icone + ' ' + t('ui.menu.narrador');
        Object.keys(NARRADOR_MODOS).forEach(function (chave) {
            botao_menu.classList.remove(NARRADOR_MODOS[chave].classe);
        });
        botao_menu.classList.add(cfg.classe);
    }
    if (painel) {
        painel.style.display = (eh_mobile() || narrador_modo === 'desligado' || indiceAtual === 0) ? 'none' : 'flex';
    }
    if (narrador_modo === 'ultima') {
        const log = document.getElementById('narrador_log');
        while (log && log.children.length > 1) {
            log.removeChild(log.firstChild);
        }
    }
    if (narrador_modo === 'desligado') {
        esconder_pensando();
    }
}

function alternar_narrador() {
    // Fase 56: no mobile o ciclo pula a opção "todas as falas" (idêntica à
    // "só a última" no toast) e alterna entre "só a última" e "desligado".
    const ciclo = eh_mobile() ? NARRADOR_CICLO_MOBILE : NARRADOR_CICLO;
    let pos = ciclo.indexOf(narrador_modo_efetivo());
    if (pos === -1) {
        pos = 0;
    }
    narrador_modo = ciclo[(pos + 1) % ciclo.length];
    localStorage.setItem('dadinho_narrador', narrador_modo);
    aplicar_estado_narrador();
}

function narrador_linha(texto) {
    if (narrador_modo === 'desligado') {
        return;
    }
    if (eh_mobile()) {
        mostrar_toast_mobile(texto);
        return;
    }
    const log = document.getElementById('narrador_log');
    if (!log) {
        return;
    }
    const linha = document.createElement('div');
    linha.className = 'narrador-linha';
    linha.textContent = texto;
    if (narrador_modo === 'ultima') {
        log.innerHTML = '';
    }
    log.appendChild(linha);
    const limite = narrador_modo === 'ultima' ? 1 : 40;
    while (log.children.length > limite) {
        log.removeChild(log.firstChild);
    }
    log.scrollTop = log.scrollHeight;
}

function mostrar_pensando(nome, ms) {
    if (narrador_modo === 'desligado') {
        return;
    }
    if (eh_mobile()) {
        mostrar_pensando_mobile(nome, ms);
        return;
    }
    const el = document.getElementById('narrador_pensando');
    if (!el) {
        return;
    }
    el.style.display = 'flex';
    el.innerHTML = '';
    const spinner = document.createElement('span');
    spinner.className = 'spinner-grow spinner-grow-sm text-info me-1';
    spinner.setAttribute('role', 'status');
    el.appendChild(spinner);
    el.appendChild(document.createTextNode(t('js.pensando', { nome: nome || 'Bot' })));
    clearTimeout(el._timer);
    el._timer = setTimeout(function () {
        el.style.display = 'none';
    }, ms + 800);
}

// Fase 60 (M5): no mobile o "pensando" usa um badge próprio, acima do toast, em
// vez de reutilizar o `#toast_mobile` (slot único que sobrescrevia a fala na
// hora e a impedia de ser lida). Enquanto o bot pensa, a fala anterior continua
// visível. Reforço: o timer do toast é rearmado para a duração do pensamento,
// garantindo o tempo de leitura mesmo quando `atraso` é grande.
function mostrar_pensando_mobile(nome, ms) {
    if (!pensando_mobile) {
        return;
    }
    pensando_mobile.innerHTML = '';
    const spinner = document.createElement('span');
    spinner.className = 'spinner-grow spinner-grow-sm text-info me-1';
    spinner.setAttribute('role', 'status');
    pensando_mobile.appendChild(spinner);
    pensando_mobile.appendChild(document.createTextNode(t('js.pensando', { nome: nome || 'Bot' })));
    pensando_mobile.classList.add('visivel');
    posicionar_pensando_mobile();
    clearTimeout(pensando_mobile._timer);
    pensando_mobile._timer = setTimeout(function () {
        pensando_mobile.classList.remove('visivel');
    }, ms + 800);
    if (toast_mobile && toast_mobile.classList.contains('visivel')) {
        clearTimeout(mostrar_toast_mobile._timer);
        mostrar_toast_mobile._timer = setTimeout(function () {
            toast_mobile.classList.remove('visivel');
        }, ms + 800);
    }
}

function esconder_pensando() {
    const el = document.getElementById('narrador_pensando');
    if (el) {
        el.style.display = 'none';
    }
    if (pensando_mobile) {
        clearTimeout(pensando_mobile._timer);
        pensando_mobile.classList.remove('visivel');
    }
}

function limpar_narrador() {
    esconder_toast_mobile();
    const log = document.getElementById('narrador_log');
    if (log) {
        log.innerHTML = '';
    }
    esconder_pensando();
}

// Fase 35/57 (mobile): toast temporário acima do painel de jogada (onde aparece
// "É a sua vez"). Serve de "última fala" para o narrador e de aviso para as
// dicas; some sozinho após alguns segundos. Fica em fluxo no `#rodape_acao` e
// nunca bloqueia o toque (`pointer-events: none`). Fase 57: em vez de fixo no
// topo da tela, flutua na área vazia logo acima do rodapé de ação (a altura
// do `#rodape_acao` é medida a cada exibição, pois o rodapé cresce quando é a
// vez do jogador — badge + dados + Apostar/Desconfiar — e encolhe no aguarde).
const toast_mobile = document.getElementById('toast_mobile');
// Fase 60 (M5): badge do "pensando" dos bots no mobile — elemento próprio para
// não roubar o slot único do toast (que exibe a fala atual).
const pensando_mobile = document.getElementById('pensando_mobile');

function esconder_toast_mobile() {
    if (!toast_mobile) {
        return;
    }
    clearTimeout(mostrar_toast_mobile._timer);
    toast_mobile.classList.remove('visivel');
}

// Reposiciona o toast na área vazia logo acima do rodapé de ação. É chamado a
// cada exibição e sempre que o rodapé muda de tamanho (menu de jogada abre/
// fecha em `meu_turno`/`espera_turno`, jogador vira espectador, resize).
function posicionar_toast_mobile() {
    if (!eh_mobile() || !toast_mobile) {
        return;
    }
    if (toast_mobile.classList.contains('visivel')) {
        const rodape = document.getElementById('rodape_acao');
        if (rodape && rodape.offsetParent !== null) {
            const topo_rodape = rodape.getBoundingClientRect().top;
            toast_mobile.style.bottom = Math.max(0, window.innerHeight - topo_rodape + 8) + 'px';
        }
    }
    posicionar_pensando_mobile();
}

// Fase 60 (M5): posiciona o badge do "pensando" logo acima do toast (medindo a
// borda superior do toast); se o toast estiver oculto, usa o topo do rodapé,
// como o próprio toast faz. Sem toque bloqueado e sem sobrepor o conteúdo.
function posicionar_pensando_mobile() {
    if (!eh_mobile() || !pensando_mobile || !pensando_mobile.classList.contains('visivel')) {
        return;
    }
    if (toast_mobile && toast_mobile.classList.contains('visivel')) {
        const rect = toast_mobile.getBoundingClientRect();
        pensando_mobile.style.bottom = Math.max(0, window.innerHeight - rect.top + 6) + 'px';
        return;
    }
    const rodape = document.getElementById('rodape_acao');
    if (rodape && rodape.offsetParent !== null) {
        const topo_rodape = rodape.getBoundingClientRect().top;
        pensando_mobile.style.bottom = Math.max(0, window.innerHeight - topo_rodape + 8) + 'px';
    }
}

function mostrar_toast_mobile(texto, duracao) {
    if (!eh_mobile() || !toast_mobile) {
        return;
    }
    toast_mobile.textContent = texto;
    toast_mobile.classList.add('visivel');
    posicionar_toast_mobile();
    clearTimeout(mostrar_toast_mobile._timer);
    mostrar_toast_mobile._timer = setTimeout(function () {
        toast_mobile.classList.remove('visivel');
    }, duracao || 4500);
}

if (window.addEventListener) {
    window.addEventListener('resize', posicionar_toast_mobile);
    window.addEventListener('orientationchange', posicionar_toast_mobile);
}

socket.on('narracao', function (data) {
    // Fase P3: narração de replay do snapshot (marca `reconstrucao`). O fanfarra
    // de vitória e sons do gancho ficam mudos até o `mudar_pagina` final.
    if (data && data.reconstrucao === true) {
        reconstruindo_snapshot = true;
    }
    esconder_pensando();
    const texto = traduzirSegmentos(data && data.segmentos, data && data.texto);
    if (texto) {
        narrador_linha(texto);
    }
    if (data && data.tipo === 'vitoria') {
        tocar_fanfarra();
    }
    // Fase 69: cada lance da partida só de IAs é pago por um poll do
    // espectador; a resposta (`espectador_ritmo`) agenda o próximo.
    if (eh_espectador && data && data.is_ia) {
        agendar_poll_espectador(POLL_ESPECTADOR_PADRAO);
    }
});

// Fase 69: poll do espectador (partida só de IAs). O servidor libera UM lance
// por chamada, no ritmo de "pensamento" dos bots; aqui pedimos o próximo e o
// servidor responde `espectador_ritmo` com o tempo que falta (nunca
// adivinhamos o ritmo no cliente). Sem o poll, a partida assistida ficaria
// parada esperando uma jogada humana que não existe mais.
let _timer_poll_espectador = null;
const POLL_ESPECTADOR_PADRAO = 600;
const POLL_ESPECTADOR_MAX = 8000;

function parar_poll_espectador() {
    if (_timer_poll_espectador !== null) {
        clearTimeout(_timer_poll_espectador);
        _timer_poll_espectador = null;
    }
}

function agendar_poll_espectador(ms) {
    if (!eh_espectador || !sala_atual) {
        return;
    }
    let espera = Number(ms);
    if (!Number.isFinite(espera) || espera < 0) {
        espera = POLL_ESPECTADOR_PADRAO;
    }
    espera = Math.min(POLL_ESPECTADOR_MAX, espera);
    parar_poll_espectador();
    _timer_poll_espectador = setTimeout(function () {
        _timer_poll_espectador = null;
        if (!eh_espectador || indiceAtual === 0) {
            return;
        }
        socket.emit('espectador_leitura', { chave: chave_secreta, pagina: indiceAtual });
    }, espera);
}

// O servidor diz quanto falta para o próximo lance (ou 0 se acabou de rodar):
// reagenda o poll com esse tempo, em vez de martelar o servidor.
socket.on('espectador_ritmo', function (data) {
    agendar_poll_espectador(data && data.restante_ms);
});

function getParamSala() {
    const params = new URLSearchParams(window.location.search);
    const sala = (params.get('sala') || '').trim().toLowerCase();
    // Mesmo charset validado pelo servidor em `normalizar_sala`; inválido vira
    // home (sem sala) em vez de materializar a sala padrão.
    return /^[a-z0-9\-_]{1,24}$/.test(sala) ? sala : '';
}

// Mostra a home (criar/buscar) quando não há sala, ou o painel da sala de
// espera quando o jogador está numa sala.
function aplicar_modo_home() {
    const painel_home = document.getElementById('painel_home');
    const painel_sala = document.getElementById('painel_sala');
    if (painel_home) {
        painel_home.style.display = modo_home ? 'block' : 'none';
    }
    if (painel_sala) {
        painel_sala.style.display = modo_home ? 'none' : 'block';
    }
}
aplicar_modo_home();

function ir_para_sala(codigo) {
    const url = new URL(window.location.href);
    url.searchParams.set('sala', codigo);
    window.location.href = url.toString();
}

// Fase 42 (N2): eventos de funil no Vercel Web Analytics, SEM PII (nunca
// client_id/chave_secreta). Guardado por try/catch e pelo stub `window.va` —
// no-op se o analytics não estiver habilitado no projeto.
function rastrear_funil(evento, dados) {
    try {
        window.va && window.va('event', { name: evento, data: dados || {} });
    } catch (e) { /* analytics nunca deve quebrar o jogo */ }
}

// Fase 65 (M2/M3): watchdog de resposta. `criar_sala`/`listar_partidas`
// dependem da conexão viva; se a resposta não chega em `TEMPO_LIMITE_RESPOSTA_MS`
// (handshake fragmentado, Fase 64), o usuário não via nada — o clique parecia
// "travar". O watchdog avisa com opção de tentar de novo, mas NUNCA reemite
// sozinho (se a resposta só estiver atrasada, reemitir duplicaria a ação).
const TEMPO_LIMITE_RESPOSTA_MS = 6000;
let _watchdog_criar_sala = null;
let _watchdog_buscar = null;

function _cancelar_watchdog(timer_id) {
    if (timer_id !== null) {
        clearTimeout(timer_id);
    }
    return null;
}

function criar_sala() {
    // Fase 9: o código é gerado no servidor (charset sem ambíguos + colisão);
    // ao receber 'sala_criada', o cliente navega para a sala criada.
    socket.emit('criar_sala');
    _watchdog_criar_sala = _cancelar_watchdog(_watchdog_criar_sala);
    _watchdog_criar_sala = setTimeout(function () {
        _watchdog_criar_sala = null;
        mostrar_alerta(t('msg.criar_sala_timeout'), 'confirmar').then(function (tentar) {
            if (tentar) {
                criar_sala();
            }
        });
    }, TEMPO_LIMITE_RESPOSTA_MS);
}

socket.on('sala_criada', function (data) {
    _watchdog_criar_sala = _cancelar_watchdog(_watchdog_criar_sala);
    if (data && data.sala) {
        rastrear_funil('sala_criada');
        ir_para_sala(data.sala);
    }
});

function copiar_link_sala() {
    const url = new URL(window.location.href);
    url.searchParams.set('sala', sala_atual);
    const texto = url.toString();
    const promessa = (navigator.clipboard && navigator.clipboard.writeText)
        ? navigator.clipboard.writeText(texto)
        : Promise.reject();
    promessa.then(function () {
        mostrar_alerta(t('msg.link_copiado'), 'sucesso');
    }).catch(function () {
        // Fallback para contextos sem Clipboard API (ex.: HTTP não seguro).
        const area = document.createElement('textarea');
        area.value = texto;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        let copiou = false;
        try {
            copiou = document.execCommand('copy');
        } catch (erro) {
            copiou = false;
        }
        document.body.removeChild(area);
        mostrar_alerta(t('msg.link_copiado'), copiou ? 'sucesso' : 'aviso');
    });
}

// --- Busca de partidas (tela client-side) ---
// Facilidade: os filtros da busca são lembrados entre sessões (localStorage).
const CHAVE_FILTROS_BUSCA = 'dadinho_busca';

function restaurar_filtros_busca() {
    let salvo = null;
    try {
        salvo = JSON.parse(localStorage.getItem(CHAVE_FILTROS_BUSCA) || 'null');
    } catch (erro) {
        salvo = null;
    }
    if (!salvo) {
        return;
    }
    const mapeamento = {
        busca: 'filtro_busca',
        status: 'filtro_status',
        com_coringa: 'filtro_coringa',
        ordenar: 'filtro_ordenar',
    };
    Object.keys(mapeamento).forEach(function (campo) {
        const el = document.getElementById(mapeamento[campo]);
        if (el && salvo[campo] !== undefined && salvo[campo] !== null) {
            el.value = String(salvo[campo]);
        }
    });
    const vaga = document.getElementById('filtro_vaga');
    if (vaga && salvo.com_vaga !== undefined) {
        vaga.checked = !!salvo.com_vaga;
    }
}

function salvar_filtros_busca(filtros) {
    try {
        localStorage.setItem(CHAVE_FILTROS_BUSCA, JSON.stringify(filtros));
    } catch (erro) {
        // sem persistência: filtros valem só para esta sessão.
    }
}

function abrir_busca() {
    document.getElementById('tela_jogadores').style.display = 'none';
    document.getElementById('tela_busca').style.display = 'block';
    const input_busca = document.getElementById('filtro_busca');
    if (input_busca) {
        input_busca.focus();
    }
    buscar_partidas();
}

function fechar_busca() {
    // Fase corrente: só fecha a busca se ela estiver aberta. O handler global
    // de ESC chama isto em todas as telas; sem o guard, `tela_jogadores`
    // (lobby) volta a ficar visível por cima da partida (bug: lobby aparece
    // no meio do jogo ao apertar ESC fora da busca).
    const tela_busca = document.getElementById('tela_busca');
    const tela_jogadores = document.getElementById('tela_jogadores');
    if (!tela_busca || tela_busca.style.display !== 'block' || !tela_jogadores) {
        return;
    }
    tela_busca.style.display = 'none';
    tela_jogadores.style.display = 'block';
}

function buscar_partidas() {
    const filtros = {
        busca: document.getElementById('filtro_busca').value.trim(),
        status: document.getElementById('filtro_status').value,
        com_coringa: document.getElementById('filtro_coringa').value,
        ordenar: document.getElementById('filtro_ordenar').value,
        com_vaga: document.getElementById('filtro_vaga').checked,
    };
    salvar_filtros_busca(filtros);
    socket.emit('listar_partidas', { filtros: filtros, sala_atual: sala_atual });
    // Fase 65 (M3): mesma proteção do `criar_sala` — a busca depende da conexão
    // e antes ficava em silêncio se a resposta não chegasse.
    _watchdog_buscar = _cancelar_watchdog(_watchdog_buscar);
    _watchdog_buscar = setTimeout(function () {
        _watchdog_buscar = null;
        mostrar_alerta(t('msg.buscar_timeout'), 'confirmar').then(function (tentar) {
            if (tentar) {
                buscar_partidas();
            }
        });
    }, TEMPO_LIMITE_RESPOSTA_MS);
}

restaurar_filtros_busca();

function entrar_partida(codigo) {
    tocar_som_variante('pegar_dados', [1, 2]);
    ir_para_sala(codigo);
}

socket.on('partidas_listadas', function (data) {
    _watchdog_buscar = _cancelar_watchdog(_watchdog_buscar);
    const lista = document.getElementById('lista_partidas');
    lista.innerHTML = '';
    const partidas = data.partidas || [];

    if (partidas.length === 0) {
        const vazio = document.createElement('small');
        vazio.className = 'text-muted';
        vazio.textContent = t('js.busca.vazia');
        lista.appendChild(vazio);
        return;
    }

    partidas.forEach((partida) => {
        const div = document.createElement('div');
        div.className = 'border rounded p-2 mb-2 bg-black bg-opacity-50 d-flex flex-wrap align-items-center justify-content-between gap-2';
        div.style.setProperty('--bs-bg-opacity', '.3');

        const info = document.createElement('div');
        info.className = 'text-start';

        const nome = document.createElement('div');
        nome.className = 'fw-bold';
        const jogando = partida.status === 'jogando';
        nome.textContent = `${partida.nome} (${partida.jogadores}/${partida.max_jogadores})`;

        const detalhes = document.createElement('small');
        detalhes.className = 'text-muted d-block';
        const detalhes_parts = [
            t('js.busca.dados', { n: partida.dados_qtd }),
            partida.com_coringa ? t('js.busca.coringa_sim') : t('js.busca.coringa_nao'),
            t('js.busca.master', { nome: partida.master || '?' }),
            // Fase F: selo de justiça verificável na busca.
            partida.verificacao_ativa ? t('js.fair.ativo') : t('js.fair.inativo'),
            jogando ? t('js.busca.em_andamento') : t('js.prontos', { prontos: partida.prontos, total: partida.jogadores }),
        ];
        detalhes.textContent = detalhes_parts.join(' · ');

        info.appendChild(nome);
        info.appendChild(detalhes);

        const botao = document.createElement('button');
        if (jogando) {
            // Fase 9: assistir partidas em andamento pela busca é liberado; quem
            // entra vira espectador (a sala em jogo não trava mais a entrada).
            botao.className = 'btn btn-sm btn-outline-info';
            botao.textContent = t('js.busca.assistir');
            botao.title = t('js.busca.assistir_titulo');
            botao.onclick = () => entrar_partida(partida.sala);
        } else if (partida.pode_entrar) {
            botao.className = 'btn btn-sm btn-success';
            botao.textContent = t('js.busca.entrar');
            botao.onclick = () => entrar_partida(partida.sala);
        } else {
            botao.className = 'btn btn-sm btn-outline-secondary';
            botao.textContent = t('js.busca.lotada');
            botao.disabled = true;
        }

        div.appendChild(info);
        div.appendChild(botao);
        lista.appendChild(div);
    });
});

socket.on('sala_cheia', function () {
    // Fase 73: resposta terminal do connect (sem `connect_start`) — desarma o
    // watchdog antes de criar a sala nova.
    _watchdog_connect_start = _cancelar_watchdog(_watchdog_connect_start);
    _watchdog_connect_tentativas = 0;
    // Sala pedida lotada: em vez de travar no alerta, cria uma sala nova.
    mostrar_alerta(t('msg.sala_cheia'), 'aviso')
        .then(() => criar_sala());
});

socket.on('iniciar_negado', function (data) {
    const motivo = data && data.motivo;
    const texto = (motivo && motivo.chave) ? t(motivo.chave, motivo.params) : (motivo || '');
    mostrar_alerta(t('msg.iniciar_negado', { motivo: texto }), 'aviso');
});

// Fase: avisa quem tentou ficar pronto sem nome definido.
socket.on('pronto_sem_nome', function () {
    mostrar_alerta(t('msg.preencha_nome'), 'aviso');
});

// O pré-preenchimento e a persistência do apelido ficam no bloco
// `atualizar_botao_apelido` (lá embaixo), junto do estado do botão.

// Selo de verificação de integridade (provably fair) na sala de espera.
function renderizar_badge_fair(config) {
    const badge = document.getElementById('badge_fair');
    if (!badge) {
        return;
    }
    const ativo = !!(config && config.verificacao_ativa);
    badge.style.display = 'inline-block';
    badge.textContent = ativo ? t('js.fair.ativo') : t('js.fair.inativo');
    badge.classList.toggle('text-bg-success', ativo);
    badge.classList.toggle('text-bg-warning', !ativo);
}

// Atualiza a lista de jogadores e o estado da sala de espera
socket.on("update_user_list", (data) => {
    const userListItems = document.getElementById("lista_de_jogadores");
    userListItems.innerHTML = ""; // Limpa a lista existente

    // Nome, status e prontidão da partida.
    const nome_partida = document.getElementById('nome_partida');
    if (nome_partida) {
        nome_partida.textContent = data.nome || t('ui.partida.titulo');
    }
    const status_partida = document.getElementById('status_partida');
    if (status_partida) {
        const jogando = data.status === 'jogando';
        status_partida.textContent = jogando ? t('js.status.jogando') : t('js.status.espera');
        status_partida.className = 'badge ' + (jogando ? 'text-bg-success' : 'text-bg-secondary');
    }
    const prontidao_partida = document.getElementById('prontidao_partida');
    if (prontidao_partida) {
        const prontos = data.prontos.filter(Boolean).length;
        prontidao_partida.textContent = t('js.prontos', { prontos: prontos, total: data.users.length });
    }
    const motivo_iniciar = document.getElementById('motivo_iniciar');
    if (motivo_iniciar) {
        if (data.users.length >= 2 && data.status === 'espera') {
            if (data.pode_iniciar) {
                motivo_iniciar.textContent = t('js.pode_iniciar');
            } else if (data.motivo && data.motivo.chave) {
                motivo_iniciar.textContent = t(data.motivo.chave, data.motivo.params);
            } else {
                motivo_iniciar.textContent = data.motivo || '';
            }
        } else {
            motivo_iniciar.textContent = '';
        }
    }

    // Aplica a configuração da partida (read-only para não-master).
    aplicar_config(data.config);

    // Fonte única dos defaults: o servidor manda o padrão vigente junto do
    // estado da sala, então HTML/JS nunca precisam manter uma cópia à mão.
    if (data.config_padrao) {
        CONFIG_PADRAO_LOCAL = data.config_padrao;
    }

    // Fase F: selo de verificação de integridade (provably fair) na espera.
    renderizar_badge_fair(data.config);

    // Facilidade: master numa sala recém-criada herda a configuração salva.
    aplicar_config_salva(data.config);

    // Verificação ativa na sala de espera: guarda o compromisso do servidor e
    // envia o nonce/compromisso deste cliente (provably fair).
    if (data.config && data.config.verificacao_ativa && data.seed && data.status === 'espera') {
        seed_estado = data.seed;
        garantir_compromisso_seed();
    }

    if (data.users.length === 0) {
        const vazio = document.createElement('small');
        vazio.textContent = t('ui.lista.aguardando');
        userListItems.appendChild(vazio);
    } else {
        // Ranking dos campeões: junta os arrays paralelos do payload em objetos
        // (nome/master/pronto/id/pontos), ordena por pontuação decrescente e
        // coroa o líder. A ordenação é só visual — os índices originais do
        // payload continuam válidos para expulsar (`id` guardado no objeto).
        const ranking = data.users.map((user, index) => ({
            nome: user,
            master: data.masters[index] === true,
            pronto: data.prontos[index] === true,
            bot: data.bots ? data.bots[index] === true : false,
            id: data.ids ? data.ids[index] : null,
            pontos: Number(data.pontos[index]) || 0,
        }));
        ranking.sort((a, b) => b.pontos - a.pontos);

        const rowDiv = document.createElement("div");
        rowDiv.className = "row border-bottom ranking-cabecalho";

        const jogadoresDiv = document.createElement("div");
        jogadoresDiv.className = "lista-nome fw-bold";
        jogadoresDiv.textContent = t('js.ranking');

        // Estado de pronto e expulsar têm coluna própria (Fase 74); no cabeçalho
        // as duas ficam vazias — sem texto novo e as bases fixas mantêm as
        // colunas alinhadas com as linhas.
        const estadoCabecalhoDiv = document.createElement("div");
        estadoCabecalhoDiv.className = "lista-pronto";

        const pontuacaoDiv = document.createElement("div");
        pontuacaoDiv.className = "lista-pontos fw-bold";
        pontuacaoDiv.textContent = t('js.pontuacao');

        const expulsarCabecalhoDiv = document.createElement("div");
        expulsarCabecalhoDiv.className = "lista-expulsar";

        userListItems.appendChild(rowDiv);
        rowDiv.appendChild(jogadoresDiv);
        rowDiv.appendChild(estadoCabecalhoDiv);
        rowDiv.appendChild(pontuacaoDiv);
        rowDiv.appendChild(expulsarCabecalhoDiv);

        ranking.forEach((jogador, posicao) => {
            const campeao = posicao === 0 && jogador.pontos > 0;
            const headerRow = document.createElement("div");
            headerRow.className = "row border-bottom ranking-linha";
            if (campeao) {
                headerRow.classList.add('ranking-campeao');
            }

            const userItem = document.createElement("div");
            userItem.className = "lista-nome";

            const master = jogador.master ? '🏁' : '';
            const coroa = campeao ? '👑 ' : '';
            // O nome fica num span próprio: o editor do master (Fase 75) troca
            // esse span por um input sem ter que remontar a linha inteira.
            const nomeSpan = document.createElement("span");
            nomeSpan.className = "lista-nome-texto";
            // Sem espaço sobrando: o espaço fixo depois do nome virava largura
            // perdida na coluna do nome (que é a única elástica da linha).
            nomeSpan.textContent = `${coroa}${jogador.nome}${master ? ' ' + master : ''}`;
            userItem.appendChild(nomeSpan);

            // Fase 75: só o master renomeia, e só na espera (é quando o servidor
            // aceita o `renomear_ia`) — o lápis fica na célula do nome, sem criar
            // coluna nova, para não apertar a lista no celular.
            if (sou_master && jogador.bot && jogador.id && data.status === 'espera') {
                const botao_renomear = document.createElement("button");
                botao_renomear.className = "btn btn-sm btn-link lista-lapis";
                botao_renomear.textContent = ICONE_LAPIS;
                botao_renomear.title = t('js.ia_renomear_titulo');
                botao_renomear.setAttribute('aria-label', t('js.ia_renomear_titulo'));
                botao_renomear.onclick = function () {
                    abrir_editor_nome_ia(userItem, botao_renomear, jogador,
                        data.marcador_ia || '', Number(data.limite_nome_ia) || 0);
                };
                userItem.appendChild(botao_renomear);
            }

            // Fase 74: o ✅/⏳ sai do texto do nome para a coluna própria.
            const prontoDiv = document.createElement("div");
            prontoDiv.className = "lista-pronto";
            prontoDiv.textContent = jogador.pronto ? '✅' : '⏳';

            // A célula de expulsar é sempre criada (mesmo vazia) para a coluna
            // ter a mesma largura em todas as linhas.
            const expulsarDiv = document.createElement("div");
            expulsarDiv.className = "lista-expulsar";

            // Fase 19: o master pode expulsar qualquer jogador (humano ou IA),
            // exceto ele mesmo. O client_id vem no payload `ids` (mesmo índice).
            if (sou_master && jogador.nome !== nome_jogador && jogador.id) {
                const botao_expulsar = document.createElement("button");
                botao_expulsar.className = "btn btn-sm btn-outline-danger";
                botao_expulsar.textContent = t('js.expulsar');
                botao_expulsar.title = t('js.expulsar_titulo');
                botao_expulsar.onclick = function () {
                    expulsar_jogador(jogador.id, jogador.nome);
                };
                expulsarDiv.appendChild(botao_expulsar);
            }

            const pontosDiv = document.createElement("div");
            pontosDiv.className = "lista-pontos";
            pontosDiv.id = `pontos_${jogador.nome}`;
            pontosDiv.textContent = jogador.pontos;

            userListItems.appendChild(headerRow); // Adiciona cada row à lista
            headerRow.appendChild(userItem); // Nome (com coroa e bandeira do master)
            headerRow.appendChild(prontoDiv); // Estado de pronto (✅/⏳)
            headerRow.appendChild(pontosDiv); // Pontuação
            headerRow.appendChild(expulsarDiv); // Botão de expulsar (só master)
        });

        // Botão "Ficar pronto" reflete o estado atual do próprio jogador.
        const bot_pronto = document.getElementById('bot_pronto');
        const meu_indice = data.users.indexOf(nome_jogador);
        const eu_pronto = meu_indice !== -1 && data.prontos[meu_indice] === true;
        // Sem nome na lista (meu_indice === -1): o jogador ainda não definiu
        // apelido — "ficar pronto" é travado para evitar o bug do invisível.
        const sem_nome = meu_indice === -1;
        if (bot_pronto) {
            bot_pronto.textContent = eu_pronto ? t('js.pronto_desfazer') : t('js.ficar_pronto');
            bot_pronto.disabled = data.status === 'jogando' || sem_nome;
            bot_pronto.title = sem_nome ? t('msg.preencha_nome') : '';
            bot_pronto.setAttribute('aria-label', sem_nome ? t('msg.preencha_nome') : (eu_pronto ? t('js.pronto_desfazer') : t('js.ficar_pronto')));
        }
        // Apelido editável na espera quantas vezes o jogador quiser, mas travado
        // ao ficar pronto (e destravado ao desfazer o pronto). O input e o botão
        // têm o estado (ok/lápis, enabled) desenhado num lugar só —
        // `atualizar_botao_apelido`.
        apelido_travado = data.status === 'jogando' || eu_pronto;
        atualizar_botao_apelido();

        const iniciar_jogo = document.getElementById('iniciar_jogo');
        if (iniciar_jogo) {
            // Fase E: o botão fica ativo para o master na espera mesmo com a
            // lista defasada entre instâncias (Vercel) — o servidor valida
            // `pode_iniciar` fresco no `iniciar_partida` (devolve
            // `iniciar_negado` com o motivo se ainda não dá).
            iniciar_jogo.disabled = !(data.status === 'espera' && data.users.length >= 2);
            iniciar_jogo.style.display = sou_master ? 'block' : 'none';
        }
    }
});

socket.on('atualizar_pontos', function (data) {
    (data.nomes || []).forEach((nome, index) => {
        const pontos = document.getElementById(`pontos_${nome}`);
        if (pontos) {
            pontos.textContent = data.pontos[index];
        }
    });
})

// Funções para o "master" do servidor
socket.on("master_def", function (data) {
    if (data.is_master) {
        sou_master = true;
        aplicar_master();
    }
});

function aplicar_master() {
    // Só o master vê o botão de iniciar e pode editar as configurações.
    const iniciar_jogo = document.getElementById('iniciar_jogo');
    if (iniciar_jogo) {
        iniciar_jogo.style.display = sou_master ? 'block' : 'none';
    }
    document.querySelectorAll('#painel_config input, #painel_config select, #painel_ia input, #painel_ia select, #painel_ia button').forEach(el => {
        el.disabled = !sou_master;
    });
}

function aplicar_config(config) {
    if (!config) {
        return;
    }
    const config_nome = document.getElementById('config_nome');
    const config_dados = document.getElementById('config_dados');
    const config_max = document.getElementById('config_max');
    const config_coringa = document.getElementById('config_coringa');
    const config_publica = document.getElementById('config_publica');
    if (config_nome && document.activeElement !== config_nome) {
        config_nome.value = config.nome || '';
    }
    if (config_dados) {
        config_dados.value = String(config.dados_qtd);
    }
    if (config_max) {
        config_max.value = String(config.max_jogadores);
    }
    if (config_coringa) {
        config_coringa.checked = config.com_coringa === true;
    }
    if (config_publica) {
        config_publica.checked = config.publica === true;
    }
    const config_substituir_ia = document.getElementById('config_substituir_ia');
    if (config_substituir_ia) {
        config_substituir_ia.checked = config.substituir_desconectado_por_ia === true;
    }
    const config_verificacao = document.getElementById('config_verificacao');
    if (config_verificacao) {
        config_verificacao.checked = config.verificacao_ativa === true;
    }
    const config_tempo = document.getElementById('config_tempo');
    if (config_tempo) {
        config_tempo.value = String(config.tempo_max_jogada);
    }
    const ia_nivel = document.getElementById('ia_nivel');
    if (ia_nivel && config.ia_nivel_padrao) {
        ia_nivel.value = String(config.ia_nivel_padrao);
    }
}

// Envia as configurações definidas pelo master (sala de espera).
function enviar_config() {
    if (!sou_master) {
        return;
    }
    const config = {
        nome: document.getElementById('config_nome').value.trim(),
        dados_qtd: document.getElementById('config_dados').value,
        max_jogadores: document.getElementById('config_max').value,
        com_coringa: document.getElementById('config_coringa').checked,
        publica: document.getElementById('config_publica').checked,
        substituir_desconectado_por_ia: document.getElementById('config_substituir_ia').checked,
        ia_nivel_padrao: document.getElementById('ia_nivel').value,
        verificacao_ativa: document.getElementById('config_verificacao').checked,
        tempo_max_jogada: document.getElementById('config_tempo').value,
    };
    socket.emit('configurar_partida', { chave: chave_secreta, config: config });
    salvar_config_local();
}

// --- Facilidade: lembra a configuração da partida entre sessões ---
// Fallback do padrão de `Lobby.config_padrao` (modelos.py) usado só até o
// servidor mandar `config_padrao` em `update_user_list` — a partir daí o
// cliente adota o valor autoritativo do servidor (fonte única). Quando o master
// entra numa sala recém-criada (config ainda é a padrão), a preferência salva é
// aplicada e enviada de uma vez — não precisa reconfigurar toda vez.
let CONFIG_PADRAO_LOCAL = {
    dados_qtd: 3,
    max_jogadores: 4,
    com_coringa: true,
    publica: true,
    substituir_desconectado_por_ia: true,
    ia_nivel_padrao: 3,
    verificacao_ativa: true,
    tempo_max_jogada: 60,
};

function config_igual_padrao(config) {
    if (!config) {
        return false;
    }
    return Object.keys(CONFIG_PADRAO_LOCAL).every(function (k) {
        return String(config[k]) === String(CONFIG_PADRAO_LOCAL[k]);
    });
}

function carregar_config_local() {
    try {
        return JSON.parse(localStorage.getItem('dadinho_config') || 'null');
    } catch (erro) {
        return null;
    }
}

function salvar_config_local() {
    const config = {
        nome: document.getElementById('config_nome').value.trim(),
        dados_qtd: document.getElementById('config_dados').value,
        max_jogadores: document.getElementById('config_max').value,
        com_coringa: document.getElementById('config_coringa').checked,
        publica: document.getElementById('config_publica').checked,
        substituir_desconectado_por_ia: document.getElementById('config_substituir_ia').checked,
        verificacao_ativa: document.getElementById('config_verificacao').checked,
        tempo_max_jogada: document.getElementById('config_tempo').value,
        ia_nivel_padrao: document.getElementById('ia_nivel').value,
        // A quantidade de IAs é só do cliente (controle do painel), não vai ao servidor.
        ia_quantidade: document.getElementById('ia_quantidade').value,
    };
    try {
        localStorage.setItem('dadinho_config', JSON.stringify(config));
    } catch (erro) {
        // sem persistência: configuração vale só para esta sessão.
    }
}

// Aplica a configuração salva uma única vez por conexão, quando a sala ainda
// está com a configuração padrão (recém-criada). Evita sobrescrever uma sala
// que já foi personalizada ou reemitir a cada snapshot.
let _config_local_aplicada = false;

function aplicar_config_salva(config) {
    if (!sou_master || _config_local_aplicada) {
        return;
    }
    const salvo = carregar_config_local();
    if (!salvo || !config_igual_padrao(config)) {
        return;
    }
    _config_local_aplicada = true;
    aplicar_config(salvo);
    const ia_qtd = document.getElementById('ia_quantidade');
    if (ia_qtd && salvo.ia_quantidade) {
        ia_qtd.value = String(salvo.ia_quantidade);
    }
    enviar_config();
}

// --- Jogadores IA (Fase 11) ---
function adicionar_ia() {
    const nivel = document.getElementById('ia_nivel').value;
    const quantidade = document.getElementById('ia_quantidade').value;
    socket.emit('adicionar_ia', { chave: chave_secreta, nivel: nivel, quantidade: quantidade });
}

function completar_com_ias() {
    const nivel = document.getElementById('ia_nivel').value;
    socket.emit('completar_com_ias', { chave: chave_secreta, nivel: nivel });
}

function remover_ias() {
    socket.emit('remover_ia', { chave: chave_secreta });
}

// --- Renomear bot (Fase 75) ---
// O editor nasce na própria célula do nome: um input (com o `🤖` do apelido
// guardado já retirado) mais o "ok". Enter/ok salvam, Escape e o blur cancelam
// (mesma gramática do editor de apelido próprio). A confirmação do servidor
// chega pelo `update_user_list` do broadcast, que já traz o nome final — com o
// marcador e o sufixo de colisão, se houver — e remonta a linha.
function abrir_editor_nome_ia(celula, botao_lapis, jogador, marcador_ia, limite) {
    if (!celula || !jogador || !jogador.id || !sou_master) {
        return;
    }
    const nomeSpan = celula.querySelector('.lista-nome-texto');
    if (!nomeSpan) {
        return;
    }
    const nome = jogador.nome || '';
    const dica = t('js.ia_renomear_dica', { limite: limite });
    let fechado = false;

    const input = document.createElement("input");
    input.type = "text";
    input.className = "form-control form-control-sm lista-nome-input";
    input.maxLength = limite;
    input.placeholder = dica;
    input.title = dica;
    input.setAttribute('aria-label', dica);
    input.value = (marcador_ia && nome.indexOf(marcador_ia) === 0)
        ? nome.slice(marcador_ia.length) : nome;

    const ok = document.createElement("button");
    ok.className = "btn btn-sm btn-primary lista-ok";
    ok.textContent = t('ui.apelido_ok');
    ok.title = dica;

    function fechar() {
        if (fechado) {
            return;  // um-shot: blur depois do "ok" não reabre nada
        }
        fechado = true;
        input.remove();
        ok.remove();
        nomeSpan.style.display = '';
        botao_lapis.style.display = '';
    }

    function salvar() {
        const apelido = input.value.trim();
        fechar();
        if (!apelido) {
            mostrar_alerta(t('msg.preencha_nome'), 'aviso');
            return;
        }
        socket.emit('renomear_ia', { chave: chave_secreta, client_id: jogador.id, apelido: apelido });
    }

    ok.onclick = salvar;
    // Sem preventDefault no pressionar o input perderia o foco primeiro e o
    // editor fecharia por baixo do botão (o "ok" nunca dispararia). O
    // `pointerdown` cobre o toque, onde o `mousedown` não chega.
    ok.onmousedown = function (evento) {
        evento.preventDefault();
    };
    ok.onpointerdown = function (evento) {
        evento.preventDefault();
    };
    input.onkeydown = function (evento) {
        if (evento.key === 'Enter') {
            salvar();
        } else if (evento.key === 'Escape') {
            fechar();
        }
    };
    input.onblur = fechar;

    nomeSpan.style.display = 'none';
    botao_lapis.style.display = 'none';
    celula.appendChild(input);
    celula.appendChild(ok);
    input.focus();
    input.select();
}

// Recusa do servidor: o motivo chega como chave + params (o servidor não escolhe
// idioma) e a linha volta ao estado normal no próximo `update_user_list`. O
// fallback é uma mensagem sem parametro — a chave de recusa sempre traz o
// `{limite}` e um payload quebrado mostraria o marcador cru na tela.
socket.on('renomear_ia_negado', function (data) {
    const motivo = data && data.motivo;
    mostrar_alerta(t(motivo && motivo.chave ? motivo.chave : 'msg.preencha_nome',
        (motivo && motivo.params) || {}), 'erro');
});

// Fase 57: quando "Adicionar IA" ou "Completar vagas" LOTAR a sala de espera,
// o servidor avisa o master (`lobby_lotado`). O drawer de configurações fecha
// para o master voltar a ver a lista completa; quem ainda não completou todas
// as vagas não recebe o evento e permanece no painel de IA.
socket.on('lobby_lotado', function () {
    fechar_config_sala();
    fechar_config_desktop();
});

// --- Expulsão de jogador (Fase 19) ---
function expulsar_jogador(client_id, nome) {
    if (!sou_master || !client_id) {
        return;
    }
    mostrar_alerta(t('js.confirmar_expulsar', { nome: nome }), 'confirmar').then(function (confirmado) {
        if (confirmado) {
            socket.emit('expulsar_jogador', { chave: chave_secreta, client_id: client_id });
        }
    });
}

// Quem foi expulso volta para a home: limpa a identidade da sala e recarrega
// sem o parâmetro ?sala (o servidor já o removeu da sala e da room).
socket.on('expulso_da_sala', function () {
    chave_secreta = '';
    limpar_chave_resumo();
    mostrar_alerta(t('msg.expulso_da_sala'), 'erro').then(function () {
        const url = new URL(window.location.href);
        url.searchParams.delete('sala');
        url.searchParams.delete('chave_secreta');
        window.location.href = url.toString();
    });
});

// Fase 30: botão de "Sair da sala". Aparece em dois momentos: na sala de espera
// (página 0) para qualquer jogador — sair explícito não consome a janela de
// reconexão — e durante a partida só para quem está assistindo (espectador);
// quem está jogando usa a janela de reconexão.
function atualizar_botao_sair() {
    const botao = document.getElementById('bot_sair_da_sala');
    if (botao) {
        const na_espera_em_sala = indiceAtual === 0 && sala_atual && !modo_home;
        botao.style.display = (eh_espectador || na_espera_em_sala) ? 'block' : 'none';
    }
}

// O espectador escolheu sair: o servidor confirma e voltamos ao menu.
socket.on('saiu_da_sala', function () {
    rastrear_funil('jogador_saiu_antes');
    chave_secreta = '';
    limpar_chave_resumo();
    const url = new URL(window.location.href);
    url.searchParams.delete('sala');
    url.searchParams.delete('chave_secreta');
    window.location.href = url.toString();
});

function sair_da_sala() {
    socket.emit('sair_da_sala', { chave: chave_secreta });
}

// Aviso para quem ficou na sala: o master expulsou alguém.
socket.on('jogador_expulso', function (data) {
    const painel = document.getElementById('motivo_iniciar');
    if (painel && data && data.nome) {
        painel.textContent = t('msg.jogador_expulso', { nome: data.nome });
    }
});

// Alterna a prontidão do jogador na sala de espera.
function alternar_pronto() {
    socket.emit('ficar_pronto', { chave: chave_secreta });
}

// O master aplica as configurações ao alterar qualquer campo da sala de espera.
['config_nome', 'config_dados', 'config_max', 'config_coringa', 'config_publica', 'config_substituir_ia', 'config_verificacao', 'ia_nivel', 'config_tempo'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
        el.addEventListener('change', enviar_config);
    }
});

// Funções para mudança de página
socket.on("mudar_pagina", function (data) {
    // Fase P3: o snapshot de reconexão termina aqui — libera sons (bip da vez,
    // virar_papel, etc.) e o ciclo normal de jogada volta a tocar. É o ÚLTIMO
    // evento do reconstruction, por isso vem antes da lógica de página.
    reconstruindo_snapshot = false;
    // Fase 42 (N2): funil — partida iniciada (página 1) e concluída (página 4).
    if (data.pag_numero === 1) {
        rastrear_funil('partida_iniciada');
    } else if (data.pag_numero === 4) {
        rastrear_funil('partida_concluida');
    }
    // Fase 21: contador da jogada automática segue o ciclo de páginas.
    // - Entrou na rolagem (1): mantém o contador (a rolagem acabou de ser
    //   armada pelo `construtor_dados`).
    // - Entrou nos turnos (2): se for a minha vez, (re)começa o contador.
    // - Sair de uma tela de jogo: encerra o contador.
    if (data.pag_numero === 2) {
        // Fase 21: o contador do turno é exibido para todos; só o da vez emite
        // `autojogar` ao zerar.
        if (sou_da_vez) {
            iniciar_timer_jogada(tempo_turno_max, true);
            // Fase 76: quem abre a ordem da rodada recebeu o `meu_turno` lá
            // atrás, ainda na conferência/vitória (para a tela de jogar dados),
            // então o bip da vez não saiu. Aqui a decisão aparece de fato — é a
            // hora do aviso. A trava garante um bip só.
            tocar_bip_sua_vez();
        } else if (tempo_turno_max > 0) {
            iniciar_timer_jogada(tempo_turno_max, false);
        }
    } else if (data.pag_numero === 1 || data.pag_numero === 3 || data.pag_numero === 4) {
        // Manter o contador: na rolagem (1) ele é iniciado em `construtor_dados`;
        // na conferência/vitória (3/4) em `cards_conferencia`/`vencedor_da_partida`.
    } else {
        parar_timer_jogada();
    }
    // Fase D2: fora da página de turnos não há "da vez" — zera o indicador.
    // Se o jogador voltar à página 2 sem receber dispatcher (gap de refresh),
    // `vez=''` faz o heartbeat pedir o `meu_turno`/`espera_turno` de volta.
    if (data.pag_numero !== 2) {
        vez_atual_nome = '';
    }
    tocar_som('virar_papel');
    const tela_busca = document.getElementById('tela_busca');
    if (tela_busca) {
        tela_busca.style.display = 'none'; // Fecha a busca caso esteja aberta (navegação do servidor)
    }
    const logo = document.getElementById('titulo_img');
    const logodiv = document.getElementById('div_titulo_img');
    if (data.pag_numero === 0) {
        const painel_aud = document.getElementById('painel_auditoria');
        if (painel_aud) {
            painel_aud.style.display = 'none';
        }
        // Fase 30: de volta ao lobby (reset/entrada), ninguém é espectador.
        eh_espectador = false;
        limpar_narrador();
        parar_celebracao();
        // Fase 69: de volta ao lobby não há partida só de IAs para ritmar.
        parar_poll_espectador();
    }
    const paginas = [
        document.getElementById('tela_jogadores'),
        document.getElementById('tela_jogar_dados'),
        document.getElementById('tela_partida'),
        document.getElementById('tela_conferencia'),
        document.getElementById('tela_vitoria')
    ]
    paginas[indiceAtual].style.display = "none";
    // Atualiza o índice para a próxima página
    indiceAtual = data.pag_numero % paginas.length; // Ciclo entre 0 e o número de páginas
    // Fase 30: reavalia o botão de "Sair da sala" em TODA transição — na espera
    // (0) ele fica visível para todos; nas páginas de jogo some para quem está
    // jogando (só espectador continua vendo). O "zera espectador" acima vale
    // para a volta ao lobby; o refresh no meio da partida se corrige sozinho.
    atualizar_botao_sair();
    aplicar_estado_narrador();
    // Mostra a próxima página
    paginas[indiceAtual].style.display = "block";
    // Fase 33 (M3): no mobile a tela da partida vira flex-column 100dvh com
    // rodapé de ação fixo — `em_tela_2` no body e `tela-partida-ativa` na tela
    // disparam o layout de app (CSS). Desktop não é afetado (regras em media
    // query ≤768px).
    const em_partida = data.pag_numero === 2;
    document.body.classList.toggle('em_tela_2', em_partida);
    if (paginas[2]) {
        paginas[2].classList.toggle('tela-partida-ativa', em_partida);
    }
    // Fase 75: o contador precisa estar no DOM ANTES de a próxima página ser
    // mostrada, senão ele fica preso no ancestral que o `mudar_pagina` acabou de
    // esconder. Só na tela de turnos ele volta para o rodapé de ação.
    posicionar_contador_jogada();
    // Menu de sala: qualquer troca de página fecha o drawer de configurações
    // (o master pode estar com ele aberto ao iniciar a partida). O dropdown de
    // som/idioma do topo também fecha.
    fechar_config_sala();
    fechar_config_desktop();
    // Fase 32 (P1): o título é texto "DADINHO" (sem imagens titulo.png/titulo_p).
    // Só o tamanho varia por página para abrir espaço nas telas de jogo.
    if (data.pag_numero === 2) {
        logodiv.style.height = '8vh';
        logo.style.fontSize = 'clamp(1.6rem, 2.6vw, 2.8rem)';
    } else if (data.pag_numero === 3) {
        logodiv.style.height = '12vh';
        logo.style.fontSize = 'clamp(2rem, 3.4vw, 3.6rem)';
    } else {
        logodiv.style.height = '12vh';
        logo.style.fontSize = 'clamp(2rem, 3.6vw, 3.8rem)';
    }
    // Assinatura do jogo: some durante as telas de jogo (1 e 2) para dar espaço.
    const subtitulo = document.getElementById('subtitulo_jogo');
    if (subtitulo) {
        subtitulo.style.display = (data.pag_numero === 1 || data.pag_numero === 2) ? 'none' : 'block';
    }
    mostrar_dica(data.pag_numero);

    // Fase 58 (M7): no mobile a conferência entra já mostrando o título e os
    // cards — o scroll posiciona o "Conferência" no topo do viewport, pulando
    // o banner de vitória/derrota (os cards já foram montados pelo
    // `cards_conferencia`, que o servidor emite antes do `mudar_pagina`).
    if (data.pag_numero === 3 && eh_mobile()) {
        const titulo_conf = document.getElementById('titulo_conferencia');
        if (titulo_conf) {
            titulo_conf.scrollIntoView({ block: 'start' });
        }
    }
    // Fase 69: um espectador que acabou de entrar/atualizar numa página de
    // jogo precisa do poll rodando (o snapshot não traz `narracao`).
    if (eh_espectador && data.pag_numero !== 0) {
        agendar_poll_espectador(POLL_ESPECTADOR_PADRAO);
    }
});

// Função para preencher os dados do jogador na página de partida
socket.on('meus_dados', function (data) {
    const meus_dados = document.getElementById('meus_dados');
    meus_dados.innerHTML = "";
    const span = document.createElement('span');
    span.className = "fs-5 text-white me-2";
    span.innerText = t('js.seus_dados');
    meus_dados.appendChild(span);

    data.dados.forEach((dado, index) => {
        const col_dado = document.createElement('div');
        col_dado.className = "col-auto";

        const img_dado = document.createElement('img');
        img_dado.className = "img-fluid me-2";
        img_dado.alt = `imagem ${index}`;
        img_dado.width = 30;
        img_dado.height = 30;
        img_dado.src = `../static/imagens/dado/${dado}.png`;

        meus_dados.appendChild(col_dado);
        col_dado.appendChild(img_dado);
    });

});

// Total de dados vivos na mesa (vem em `dados_mesa`): F3 usa para capar o
// botão de aumentar a quantidade (o servidor clampeia a aposta — Fase 29 H2).
let total_dados_mesa = 0;

// Função para preencher a info sobre os dados na mesa
socket.on('dados_mesa', function (data) {
    total_dados_mesa = Number(data.total) || 0;
    const dados_mesa = document.getElementById('dados_mesa')
    const total = data.total
    dados_mesa.innerHTML = ""
    const span = document.createElement('span')
    span.className = 'fs-5 text-white me-2'
    span.innerHTML = t('js.dados_mesa', { total: total });
    dados_mesa.appendChild(span)
});

// Função pra preencher a info sobre o coringa
socket.on('atualizar_coringa', function (data) {
    const coringa_n = Number(data.coringa_atual)
    const coringa_j = String(data.ultimo_coringa)
    const coringa_cancelado = data.coringa_cancelado
    const coringa_atual_el = document.getElementById('corin_atual')
    coringa_atual_el.innerHTML = ""

    if (coringa_cancelado) {
        const span3 = document.createElement('span')
        span3.className = 'fs-5 text-danger me-2'
        span3.innerText = t('js.coringa_cancelado');
        coringa_atual_el.appendChild(span3)
    } else {
        if (coringa_n === 0) {
            const span3 = document.createElement('span')
            span3.className = 'fs-6 text-white me-2'
            span3.innerText = t('js.coringa_nao_jogado');
            coringa_atual_el.appendChild(span3)
        } else {
            const span1 = document.createElement('span')
            span1.className = 'fs-5 text-white me-2'
            span1.innerText = t('js.coringa_atual');
            const img1 = document.createElement('img')
            img1.className = "img-fluid"
            img1.alt = 'imagem coringa';
            img1.width = 30
            img1.height = 30
            img1.src = '../static/imagens/dado/1.png'
            const span2 = document.createElement('span')
            span2.className = 'fs-5 text-white me-2'
            span2.innerText = t('js.coringa_x', { n: coringa_n, jogador: coringa_j })
            coringa_atual_el.appendChild(span1)
            coringa_atual_el.appendChild(img1)
            coringa_atual_el.appendChild(span2)
        }
    }
})

// Fase: cabeçalho do card com o nome truncável e a quantidade de dados num
// badge de largura fixa. O nome longo corta com reticências, mas a contagem
// nunca some (antes ia no fim do texto e era a primeira coisa cortada).
function montar_cabecalho_card(cabecalho, jogador, qtd) {
    cabecalho.textContent = '';
    const nome = document.createElement('span');
    nome.className = 'nome-jogador';
    nome.textContent = jogador;
    const badge = document.createElement('span');
    badge.className = 'badge-dados';
    badge.textContent = `🎲 ${qtd}`;
    cabecalho.appendChild(nome);
    cabecalho.appendChild(badge);
    cabecalho.title = jogador;
}

// Função para criar cada seção de dados
function createDiceSection(text, opacityClass, imageIndex, destaque = false) {
    const col = document.createElement('div');
    col.className = `col-md-12 mb-1 ${opacityClass}`;

    const diceDiv = document.createElement('div');
    diceDiv.className = 'd-flex align-items-center justify-content-evenly border rounded';
    if (destaque) {
        diceDiv.classList.add('jogada-destaque');
    }

    const imgDiv = document.createElement('div');
    const img = document.createElement('img');
    img.src = `../static/imagens/dado/${imageIndex}.png`;
    img.className = 'diceImage img-fluid ms-1';
    img.alt = 'Imagem 1';
    img.width = 26;
    img.height = 26;
    imgDiv.appendChild(img);

    const textDiv = document.createElement('div');
    textDiv.className = 'mt-0';
    const heading = document.createElement('h1');
    heading.className = 'fs-6 mb-0';
    heading.textContent = text;
    textDiv.appendChild(heading);

    diceDiv.appendChild(imgDiv);
    diceDiv.appendChild(textDiv);
    col.appendChild(diceDiv);
    return col;
}

// Fase 55: guardas da rolagem NO CLIENTE para a rodada corrente. O servidor
// continua idempotente (reenvia o resultado se o evento se perder), mas o
// cliente não re-dispara o `jogar_dados` nem reinicia a animação a cada clique
// — antes, cliques repetidos re-rolavam visualmente os dados. `rolagem_pedida`
// trava o emit; `rolagem_animada` impede a animação de recomeçar num reenvio
// idempotente do servidor. O `construtor_dados` rearma ambos a cada rodada.
let rolagem_pedida = false;
let rolagem_animada = false;

// Fase 72: watchdog da rolagem — fecha o deadlock do "Jogar dados". O servidor
// é idempotente no re-clique (app.py:1641-1647), mas o cliente trava o emit e
// desativa o botão (ver `jogar_dados`): se o `jogar_dados` se perde no
// transporte/cooldown/lock, o jogador fica preso até o `autojogar`. Este timer
// devolve o botão após alguns segundos, no mesmo espírito de
// `aposta`/`desconfiar`/OK, que nunca desativam por causa de evento perdido.
// `jogar_dados_resultado` e `construtor_dados` cancelam o timer.
const ROLAGEM_RETRY_MS = 6000;
let timer_rolagem_retry = null;

function cancelar_retry_rolagem() {
    if (timer_rolagem_retry !== null) {
        clearTimeout(timer_rolagem_retry);
        timer_rolagem_retry = null;
    }
}

function armar_retry_rolagem() {
    cancelar_retry_rolagem();
    timer_rolagem_retry = setTimeout(function () {
        timer_rolagem_retry = null;
        // Resultado chegou (rolagem_animada) — nada a destravar.
        if (rolagem_animada) {
            return;
        }
        rolagem_pedida = false;
        const botao = document.getElementById('dadobotao');
        if (botao) {
            botao.disabled = false;
        }
    }, ROLAGEM_RETRY_MS);
}

// Função para construir a tela dos dados (1-6 dados em tela_jogar_dados).
socket.on('construtor_dados', function (data) {
    // Fase P3: primero marcador do snapshot — arma o mute de sons até o mudar_pagina.
    if (data && data.reconstrucao === true) {
        reconstruindo_snapshot = true;
    }
    const espectador = data.espectador;
    // Fase 30: quem entra assistindo (vaga perdida/busca) também vê o botão.
    eh_espectador = espectador === true;
    atualizar_botao_sair();
    // Nova rodada/partida: rearma a rolagem do cliente.
    rolagem_pedida = false;
    rolagem_animada = false;
    cancelar_retry_rolagem();
    const tela_jogar_dados = document.getElementById('tela_jogar_dados')
    const container = document.createElement('div');
    tela_jogar_dados.innerHTML = ""

    if (espectador === false) {
        container.className = 'container my-2 p-2 mb-1 bg-black text-white border border-light rounded';
        container.style = '--bs-bg-opacity: .3;';

        // Criação do botão Jogar Dados
        const botao = document.createElement('button');
        botao.id = 'dadobotao';
        botao.className = 'btn btn-primary mt-2';
        botao.textContent = t('js.jogar_dados');
        botao.onclick = jogar_dados;  // Função que será chamada ao clicar

        // Adicionando o botão ao container principal
        container.appendChild(botao);

        // Criação da div interna container para organizar as colunas
        const containerInterno = document.createElement('div');
        containerInterno.className = 'container mt-3';

        // Criação da linha de dados
        const row = document.createElement('div');
        row.className = 'row d-flex justify-content-evenly';

        // Gerar um número aleatório entre 1 e 6 para a quantidade de dados
        const quantidadeDeDados = data.quantidade;

        // Loop para criar cada dado dinamicamente
        for (let i = 1; i <= quantidadeDeDados; i++) {
            const col = document.createElement('div');
            col.className = 'col-4 text-center';

            const img = document.createElement('img');
            img.id = `dado${i}`;
            img.src = `../static/imagens/dado/${i}.png`;  // Ajuste o caminho da imagem conforme necessário
            img.className = 'img-fluid mb-1';
            img.alt = `Imagem ${i}`;
            img.width = 75;
            img.height = 75;

            col.appendChild(img);
            row.appendChild(col);
        }

        // Adicionando a linha de dados ao container interno
        containerInterno.appendChild(row);

        // Adicionando o container interno ao container principal
        container.appendChild(containerInterno);

        // Adicionando o container principal à tela
        tela_jogar_dados.appendChild(container)

        // Fase 21: jogador ainda não rolou — começa o contador da jogada
        // automática da rolagem (para quando o tempo máximo expirar).
        // Fase 75: espectador não rola nada, então não ganha relógio.
        if (!eh_espectador) {
            iniciar_timer_jogada(data.tempo_max);
        }
    } else {
        // Cria a div principal
        const container = document.createElement('div');
        container.className = 'container my-2 p-2 mb-1 bg-black text-white border border-light rounded';
        container.style.setProperty('--bs-bg-opacity', '.3');

        // Cria o sub-container centralizado
        const subContainer = document.createElement('div');
        subContainer.className = 'container mt-3 d-flex justify-content-center align-items-center';

        // Cria o texto com badge
        const badge = document.createElement('span');
        badge.className = 'fs-3 badge text-bg-primary text-wrap mb-2';
        badge.style.width = 'auto';
        badge.style.maxWidth = '90%';
        badge.textContent = t('js.dados_rolando');

        // Adiciona o badge ao sub-container
        subContainer.appendChild(badge);

        // Cria o spinner
        const spinner = document.createElement('div');
        spinner.className = 'spinner-border text-primary';
        spinner.setAttribute('role', 'status');

        // Adiciona o texto acessível ao spinner
        const visuallyHidden = document.createElement('span');
        visuallyHidden.className = 'visually-hidden';
        visuallyHidden.textContent = t('js.carregando');
        spinner.appendChild(visuallyHidden);

        // Monta o DOM
        container.appendChild(subContainer);
        container.appendChild(spinner);

        // Adiciona o container ao body ou a outro container desejado
        tela_jogar_dados.appendChild(container);
    }

    // Fase 22: status de quem já rolou os dados (preenchido pelo `rolagem_status`).
    const status_rol = document.createElement('div');
    status_rol.id = 'rolagem_status';
    status_rol.className = 'mt-3 fs-6 text-white text-wrap mx-auto';
    status_rol.style.maxWidth = '40rem';
    tela_jogar_dados.appendChild(status_rol);
})

// Função para construir os cards (parte estática)
socket.on('construtor_html', function (data) {
    // Fase P3: primero marcador do snapshot de turnos — arma o mute de sons.
    if (data && data.reconstrucao === true) {
        reconstruindo_snapshot = true;
    }
    const principal = document.getElementById('cards');
    principal.innerHTML = '';

    // Fase 9: mostra "Rodada N" na tela de turnos (o payload rodada_n já existia).
    const rodada_txt = document.getElementById('rodada_atual_txt');
    if (rodada_txt && data.rodada_n) {
        rodada_txt.textContent = t('js.rodada', { n: data.rodada_n });
        rodada_txt.classList.remove('d-none');
    }

    // Girar a ordem dos cards para o próprio jogador ficar no centro da sua tela,
    // mantendo a ordem circular (de turno) entre os demais.
    let entradas = Object.entries(data.turnos_lista);
    const meu_indice = entradas.findIndex(([jogador]) => jogador === nome_jogador);
    if (meu_indice > -1) {
        const centro = Math.floor(entradas.length / 2);
        const desloc = meu_indice - centro;
        entradas = entradas.map((_, i) => entradas[(i + desloc + entradas.length) % entradas.length]);
    }

    entradas.forEach(([jogador, turnos]) => {
        // Criação do container principal (`g-1` do `#cards` já dá o gutter
        // vertical em linhas quebradas; sem `mb-1` para manter a simetria)
        const divCol = document.createElement('div');
        divCol.className = 'col-md-2 col-sm-4 col-6';

        // Criação do card
        const card = document.createElement('div');
        card.className = 'card border border-secondary border-1 text-bg-dark';
        // Fase 32 (P3) + Fase 34: o tamanho (fixo) do card vem da CSS
        // (`#cards .card`) — o nome do jogador não o altera; no cabeçalho o
        // nome longo é truncado com reticências (o `title` mostra o nome todo).
        card.id = `card_${jogador}`;

        // Criação do cabeçalho do card
        const cardHeader = document.createElement('div');
        if (jogador === nome_jogador) {
            cardHeader.className = 'card-header text-bg-primary';
            // window.alert(`${jogador} = ${nome_jogador}`);
        } else {
            cardHeader.className = 'card-header';
            // window.alert(`${jogador} =/= ${nome_jogador}`);
        }

        cardHeader.id = `card_hea_${jogador}`;
        montar_cabecalho_card(cardHeader, jogador, data.dados_tt);

        // Criação do corpo do card
        const cardBody = document.createElement('div');
        cardBody.className = 'card-body';
        cardBody.id = `card_bod_${jogador}`;

        // Criação da linha dentro do corpo do card
        const row = document.createElement('div');
        row.className = 'row d-flex justify-content-center align-items-center text-center';
        row.id = `card_row_${jogador}`;

        // Montando a estrutura do card
        cardBody.appendChild(row);
        card.appendChild(cardHeader);
        card.appendChild(cardBody);
        divCol.appendChild(card);

        principal.appendChild(divCol); // Adicionando tudo ao DOM
    })
})

// função para atualizar um turno
socket.on('atualizar_turno', function (dados) {
    tocar_som_variante('aposta', [1, 2]);
    const jogador = dados.jogador
    const lista_turnos = dados.lista_turnos
    const card_row = document.getElementById(`card_row_${jogador}`)
    // A última jogada da rodada ganha destaque; antes de marcar, limpa o antigo.
    const destacar_ultimo = dados.ultimo === true;
    if (destacar_ultimo) {
        document.querySelectorAll('#cards .jogada-destaque').forEach(function (el) {
            el.classList.remove('jogada-destaque');
        });
        document.querySelectorAll('#cards .card-header.card-ultima').forEach(function (el) {
            el.classList.remove('card-ultima');
            el.removeAttribute('data-rotulo');
        });
    }
    // A linha de dados vive no card do apelido; se o nome mudou depois do
    // construtor_html (o `🤖` da substituição, Fase 76), o card ainda é o do
    // nome antigo e este turno não tem onde desenhar. Mesmo mecanismo de
    // `reset_rodada`/`formatador_coletivo`: sem elemento, o próximo
    // `construtor_html` (nova rodada) reconstrói o card.
    if (card_row) {
        card_row.innerHTML = ""
        lista_turnos.forEach((sublista, index) => {
            const dado = sublista[0];
            const dado_qtd = sublista[1];
            let opacidade;

            // Definindo a opacidade com base no índice
            if (index === 0) {
                opacidade = 'opacity-100'; // Para o índice 0, opacidade 25%
            } else if (index === 1) {
                opacidade = 'opacity-50'; // Para o índice 1, opacidade 50%
            } else if (index === 2) {
                opacidade = 'opacity-25'; // Para o índice 2, opacidade 100%
            }
            card_row.appendChild(createDiceSection(`X${dado_qtd}`, opacidade, dado, destacar_ultimo && index === 0));
        })
    }
    // O selo "ÚLTIMA" ancora no cabeçalho (fora do container de rolagem do
    // corpo do card) para nunca ser cortado nem ficar atrás do card.
    if (destacar_ultimo) {
        const cabecalho = document.getElementById(`card_hea_${jogador}`);
        if (cabecalho) {
            cabecalho.classList.add('card-ultima');
            cabecalho.setAttribute('data-rotulo', t('js.jogada.ultima'));
        }
    }
});

// ---------------------------------------------------------------------------
// Jogada automática por tempo máximo (Fase 21).
// O servidor informa o tempo (`tempo_max` segundos) em `construtor_dados`
// (rolagem), `meu_turno` (aposta/desconfiança) e `espera_turno` (tempo
// restante do turno, exibido também para quem espera). O cliente da vez conta
// regressivo e, ao expirar, pede ao servidor para jogar pelo atrasado
// (`autojogar`) — o servidor confere o tempo decorrido antes de agir, então
// isto é só o gatilho. Quem apenas acompanha não emite `autojogar`.
// ---------------------------------------------------------------------------
let timer_autojogar = null;
let tempo_autojogar_seg = 0;
// Só quem realmente pode agir dispara `autojogar` ao zerar. Quem apenas
// acompanha o turno (recebeu `espera_turno`) vê o contador, mas não emite.
let timer_meu_autojogar = true;
let sou_da_vez = false;      // recebeu `meu_turno` (a vez atual é a minha)
let tempo_turno_max = 0;     // limite/restanto do turno (vem no `meu_turno`/`espera_turno`)
// Fase P3: enquanto o snapshot de reconexão reconstrói a tela, um burst de eventos
// (um por aposta, reset nova rodada, etc.) dispara sons em rajada. A flag é
// armada pelo primeiro evento de conteúdo que chega marcado `reconstrucao: True`
// e desarmada pelo `mudar_pagina` final — isto garante um só flip de página e
// silencia apenas os sons de reconstrução, sem tocar a bip da vez / virar_papel.
let reconstruindo_snapshot = false;
// Fase D2: apelido do jogador que o cliente acredita estar NA VEZ (vem de
// `meu_turno`/`espera_turno`/`formatador_coletivo`). Vai no heartbeat para o
// servidor detectar um indicador de vez perdido entre instâncias (refresh) e
// reenviar só o `meu_turno`/`espera_turno` — senão a tela fica sem o menu de
// jogada mesmo com a página correta.
let vez_atual_nome = '';
let tempo_conf_vit = 0;      // limite da conferência/vitória (vem no `cards_conferencia`/`vencedor_da_partida`, Fase 22)

// ---------------------------------------------------------------------------
// Bip da vez e bip de tempo acabando (Fase 76).
// Mesmo arquivo nos dois papéis (`beep.mp3`): uma vez quando a vez é minha e,
// depois, uma vez por segundo do contador regressivo de "jogada automática",
// mais forte e mais apertado conforme o relógio aperta. Só cliente — o servidor
// já manda os segundos restantes do relógio (`tempo_max`), que é o suficiente
// para graduar o bip sem evento novo.
// ---------------------------------------------------------------------------
// Trava do bip da vez: um por turno. `meu_turno` pode ser REEMITIDO pelo
// dispatcher quando o heartbeat percebe que o indicador de vez se perdeu entre
// instâncias (Fase D2, `emitir_dispatcher_turno`) — sem esta trava o jogador
// levaria dois bips no mesmo turno. Rearmada em `espera_turno` (a vez passou
// para outro) e no boot (para o `meu_turno` do snapshot pós-refresh bipar).
let bip_vez_pendente = true;
// Janela do bip de tempo: fração do relógio, com piso/teto para não comer o
// turno inteiro (tempo curto) nem ficar colado no `text-bg-danger` do contador
// (tempo longo). O teto de 20s faz a janela cobrir 1/3 do turno de 60s (o
// padrão) e 1/6 do de 120s. O piso de 9s importa: com a janela curta, os
// níveis esparsos (4s/3s) não encaixam nenhum bip e a rampa perde o degrau —
// no relógio mais curto que a sala oferece (15s) ainda é preciso caber a rampa
// inteira, e é o que o piso garante.
const FRACAO_JANELA_BIP = 0.45;
const JANELA_BIP_MIN = 9;
const JANELA_BIP_MAX = 20;
// A rampa desce até o último segundo: com o piso de 1s entre bips, o tom
// audível do `beep.mp3` (~0,4s) termina antes da jogada automática e não
// encavala com a explosão de sons do zero (era o que a rajada de 450ms fazia).
const BIP_MINIMO_RESTANTE = 1;
// Níveis do bip de tempo, do mais calmo ao mais apertado:
// [fração restante mínima da janela, intervalo entre bips (ms), volume].
// Quatro degraus (4s → 3s → 2s → 1s) para a aceleração ser CONTÍNUA e não
// dois saltos: os vãos entre bips encolhem de forma monótona e o trecho final
// fica em 1 bip por segundo.
// O relógio que manda é o do contador (passa de 1 em 1), então o intervalo
// precisa ser um múltiplo inteiro de 1000ms — 4000ms = bipa a cada 4 ticks,
// 1000ms = a cada tick. Bipa no MESMO tick que redesenha o número, então o
// som cai junto com a contagem da tela; um `setTimeout` próprio (o que era
// antes) derivava do contador e acabava bipando em cima do número errado.
// PISO DE 1 SEGUNDO: o tom audível dura ~0,4s e abaixo disso os avisos se
// fundem numa rajada contínua em vez de soar como bipes distintos.
const NIVEIS_BIP_TEMPO = [
    [0.80, 4000, 0.22],
    [0.60, 3000, 0.36],
    [0.30, 2000, 0.55],
    [0.00, 1000, 0.78],
];
let tempo_total_jogada = 0;   // duração do relógio atual, para derivar a janela
let ultimo_bip_seg = -1;     // contador no último bip (mede o vão, -1 = nenhum)

function janela_bip_tempo() {
    if (tempo_total_jogada <= 0) {
        return 0;
    }
    return Math.min(JANELA_BIP_MAX,
        Math.max(JANELA_BIP_MIN, Math.ceil(tempo_total_jogada * FRACAO_JANELA_BIP)));
}

// Nível do bip para `seg` segundos restantes, ou null fora da janela.
function nivel_bip_tempo(seg) {
    const janela = janela_bip_tempo();
    if (janela <= 0 || seg > janela || seg < BIP_MINIMO_RESTANTE) {
        return null;
    }
    const fracao = seg / janela;
    for (const [minimo, intervalo, volume] of NIVEIS_BIP_TEMPO) {
        if (fracao > minimo) {
            return { intervalo: intervalo, volume: volume };
        }
    }
    const ultimo = NIVEIS_BIP_TEMPO[NIVEIS_BIP_TEMPO.length - 1];
    return { intervalo: ultimo[1], volume: ultimo[2] };
}

// Bip do contador, chamado no MESMO tick que redesenha o número regressivo
// (`atualizar_contador_jogada`) — o bip é função do valor que está na tela.
// Só na página de turnos (2) e só para quem está na vez. A rolagem (1) tem
// `rolar_dados` a cada 1,2s e a conferência/vitória (3/4) estouram sons a cada
// confirmação — o bip intercalado com eles soava como travamento, e o relógio
// dessas telas é de quem já jogou (não é "o tempo dele" acabando). Quem só
// acompanha o turno (`meu === false`) e o espectador ficam mudos.
function bipar_contador_jogada(seg) {
    if (!timer_meu_autojogar || indiceAtual !== 2) {
        return;
    }
    const nivel = nivel_bip_tempo(seg);
    if (!nivel) {
        return;
    }
    // Espaçamento medido no PRÓPRIO contador, não por módulo: `seg` é inteiro e
    // cai de 1 em 1, então o vão real é `ultimo_bip_seg - seg`. Filtrar por
    // `seg % passos` era mais curto mas bipava no primeiro tick de cada nível —
    // o que encurtava o vão logo na virada (a 30s dava 3s > 1s > 2s) e a
    // aceleração voltava a andar para trás. Medindo o vão, a rampa encolhe de
    // forma monótona até 1 bip por segundo.
    const passos = nivel.intervalo / 1000;
    if (ultimo_bip_seg >= 0 && (ultimo_bip_seg - seg) < passos) {
        return;
    }
    ultimo_bip_seg = seg;
    tocar_som('beep', nivel.volume);
}

// Bip da vez: só na página de turnos (2), que é onde o jogador tem algo a
// decidir. No começo da rodada o servidor já emite `meu_turno` para quem abre
// a ordem (`Rodada.criar_rodada` -> `atualizar_front_pro_da_vez`) e a tela de
// jogar dados só vem DEPOIS (`mudar_pagina(1)`): sem esta trava o bip disparava
// enquanto a mesa ainda estava rolando os dados, e o jogador ouvia "sua vez"
// sem ter nada para fazer. Fora da página 2 a trava fica de pé e o bip sai no
// `mudar_pagina(2)`, quando a decisão aparece de fato.
function tocar_bip_sua_vez() {
    if (!bip_vez_pendente) {
        return;
    }
    bip_vez_pendente = false;
    tocar_som('beep');
}

function atualizar_contador_jogada() {
    const el = document.getElementById('contador_jogada');
    if (!el) {
        return;
    }
    if (tempo_autojogar_seg <= 0) {
        el.style.display = 'none';
        return;
    }
    el.textContent = t('js.autojogar_contagem', { n: tempo_autojogar_seg });
    el.classList.toggle('text-bg-danger', tempo_autojogar_seg <= 10);
    el.classList.toggle('text-bg-warning', tempo_autojogar_seg > 10);
    el.style.display = 'inline-block';
}

// Fase 75: o contador da jogada automática vive numa camada IRMÃ das telas
// (`#camada_contador`), fora do `#app-main`. Ele antes morava dentro de
// `#tela_partida`, que ganha `display:none` em toda troca de página — então nas
// páginas 1, 3 e 4 o badge ficava preso nesse ancestral invisível: o relógio
// corria, mas ninguém via, e o servidor auto-confirmava o "Ok" do jogador sem
// aviso. Aqui o elemento é MOVIDO no DOM conforme a página: na de turnos (2)
// volta para dentro de `#rodape_acao` (é o rodapé do layout de app do mobile,
// Fase 33/M3) e nas demais fica na camada, que nunca é escondida.
function posicionar_contador_jogada() {
    const el = document.getElementById('contador_jogada');
    if (!el) {
        return;
    }
    const destino = indiceAtual === 2
        ? document.getElementById('rodape_acao')
        : document.getElementById('camada_contador');
    // `display:none` do ancestral esconde o badge mesmo com `el.style.display`
    // = inline-block; a visibilidade depende de ESTE par de nós.
    if (destino && el.parentElement !== destino) {
        destino.appendChild(el);
    }
}

function iniciar_timer_jogada(segundos, meu) {
    parar_timer_jogada();
    // `meu` (default true) separa quem pode auto-jogar de quem só acompanha o
    // turno (`espera_turno`): o observador exibe o contador mas não emite.
    timer_meu_autojogar = meu !== false;
    tempo_autojogar_seg = Math.max(0, Math.floor(Number(segundos) || 0));
    tempo_total_jogada = tempo_autojogar_seg;
    if (tempo_autojogar_seg <= 0) {
        return;
    }
    atualizar_contador_jogada();
    // Fase 76: o bip acompanha o contador. Fica logo ao lado de cada
    // `atualizar_contador_jogada` do relógio, então o som e o número da tela
    // mudam no mesmo tick e não há como derivarem um do outro. `-1` dá o bip
    // logo no primeiro tick, sem esperar o intervalo do nível.
    ultimo_bip_seg = -1;
    bipar_contador_jogada(tempo_autojogar_seg);
    timer_autojogar = setInterval(function () {
        tempo_autojogar_seg -= 1;
        atualizar_contador_jogada();
        if (tempo_autojogar_seg <= 0) {
            parar_timer_jogada();
            if (timer_meu_autojogar) {
                socket.emit('autojogar', { chave: chave_secreta });
            }
            return;
        }
        bipar_contador_jogada(tempo_autojogar_seg);
    }, 1000);
}

function parar_timer_jogada() {
    tempo_total_jogada = 0;
    ultimo_bip_seg = -1;
    if (timer_autojogar) {
        clearInterval(timer_autojogar);
        timer_autojogar = null;
    }
    const el = document.getElementById('contador_jogada');
    if (el) {
        el.style.display = 'none';
    }
}

// Função individual para verificar o jogador da vez no turno e construir formatação dinâmina para ele
socket.on('meu_turno', function (data) {
    let turno_num = data.turno_num;
    const painel_jogada = document.getElementById('painel_jogada');
    const painel_aguarde = document.getElementById('painel_aguarde');

    // Fase 21: marca que é a minha vez e guarda o limite. O contador só começa
    // de fato na página de turnos (2): na rolagem ele é substituído pelo
    // contador da rolagem (`construtor_dados`/`mudar_pagina`).
    sou_da_vez = true;
    tempo_turno_max = Number(data.tempo_max) || 0;
    // Bip da vez, uma vez por turno — só quando a decisão já está na tela
    // (`tocar_bip_sua_vez` cuida da trava e da página). O servidor emite
    // `atualizar_turno` (o "Piece Impact" do dado que acabou de ser apostado)
    // antes de `meu_turno` em `Rodada.apostar_turno` — então o bip cai DEPOIS
    // do impacto. A trava também segura o reemit do dispatcher (Fase D2), que
    // traria um segundo bip no mesmo turno.
    if (indiceAtual === 2) {
        tocar_bip_sua_vez();
    }
    // Fase D2: registro quem o cliente acredita estar na vez (o heartbeat usa
    // isso para pedir um `meu_turno` reenviado se o indicador se perder).
    vez_atual_nome = String(data.username || '');
    if (indiceAtual === 2) {
        iniciar_timer_jogada(tempo_turno_max, true);
    }

    if (painel_jogada && painel_aguarde) {
        painel_jogada.style.display = "block"; // Mostra o painel de jogada
        painel_aguarde.style.display = "none"; // Oculta painel aguarde
    }
    // Fase 57: o menu de jogada cresce o rodapé — o toast (se visível) sobe
    // para continuar na área vazia, sem cobrir os dados/Apostar/Desconfiar.
    posicionar_toast_mobile();

    if (turno_num > 0) {
        const botao = document.getElementById('desconfiar');
        if (botao) {
            botao.disabled = false; // Ativa o botão desconfiar
        }
    }

    // Mínimo legal da aposta: ajusta o input de quantidade automaticamente.
    contexto_min_aposta = {
        com_coringa: data.com_coringa === true,
        coringa_atual_qtd: Number(data.coringa_atual_qtd) || 0,
        ultima_aposta: data.ultima_aposta || null
    };
    // F2: nova vez = nova escolha de face (a do turno anterior não vale mais).
    limpar_selecao_dado();
    ajustar_quantidade_minima(true);
})

// Função coletiva para os jogadores que não estão na vez e construir formatação dinâmina para eles
socket.on('espera_turno', function (data) {
    const painel_jogada = document.getElementById('painel_jogada');
    const painel_aguarde = document.getElementById('painel_aguarde');
    sou_da_vez = false; // Fase 21: não é mais a minha vez.
    // A vez saiu daqui: o próximo `meu_turno` (turno novo) volta a ter direito
    // ao bip da vez. Sem isto o bip tocaria só uma vez na partida inteira.
    bip_vez_pendente = true;
    // Fase 21: o contador do turno agora aparece para todos — quem espera vê o
    // mesmo relógio do da vez, mas sem emitir `autojogar` ao zerar.
    tempo_turno_max = Number(data.tempo_max) || 0;
    if (indiceAtual === 2 && tempo_turno_max > 0) {
        iniciar_timer_jogada(tempo_turno_max, false);
    } else {
        parar_timer_jogada();
    }
    // Fase D2: registro quem o cliente acredita estar na vez (o heartbeat usa
    // isso para pedir um `espera_turno` reenviado se o indicador se perder).
    vez_atual_nome = String(data.username || '');
    // F2: fora da vez a seleção antiga não pode vazar para o próximo turno.
    limpar_selecao_dado();
    painel_jogada.style.display = "none"; // Oculta o painel de jogada
    painel_aguarde.style.display = "block"; // Mostra painel aguarde
    // Fase 57: sem o menu de jogada o rodapé encolhe — o toast desce para
    // ficar onde antes ficava o rodapé alto.
    posicionar_toast_mobile();
})

// Função que atualiza cada rodada, executa a cada inicio de rodada
socket.on('reset_rodada', function (data) {
    tocar_som_variante('nova_rodada', [1, 2]);
    const jogadores = data.jogadores_nomes;
    const jogadores_dados = data.jogadores_dados_qtd;
    const botao = document.getElementById('bot_confe_fim');
    const botao_desc = document.getElementById('desconfiar');
    rearmar_ok('bot_confe_fim'); // Fase A: nova rodada, "Ok" volta ao estado inicial.
    botao.disabled = false; // Reativa o input
    botao_desc.disabled = true; // Desativa o input
    // F2: rodada nova = face anterior não vale mais para a próxima aposta.
    limpar_selecao_dado();

    jogadores.forEach((jogador, index) => {
        const card = document.getElementById(`card_hea_${jogador}`);
        const c_row = document.getElementById(`card_row_${jogador}`);

        if (card) {  // Verifica se o elemento existe
            montar_cabecalho_card(card, jogador, jogadores_dados[index]);
        }
        if (c_row) {  // Verifica se o elemento existe
            c_row.innerHTML = '';
        }
    });
});

// Função que atualiza cada partida, executa a cada inicio de partida
socket.on('reset_partida', function () {
    const botao_fogos = document.getElementById('comemorar');
    const bot_vencedor_fim = document.getElementById('bot_vencedor_fim');
    const bot_confe_fim = document.getElementById('bot_confe_fim');
    // Fase A: partida nova, "Ok" da conferência/vitória volta ao estado inicial.
    rearmar_ok('bot_vencedor_fim');
    rearmar_ok('bot_confe_fim');
    bot_vencedor_fim.disabled = false; // Reativa o input
    bot_vencedor_fim.style.display = 'block' // Reativa o input
    bot_confe_fim.disabled = false; // Reativa o input
    bot_confe_fim.style.display = 'block'; // Reativa o input
    botao_fogos.style.display = 'none'; // Desativa o input
    // Limpa resíduos da partida anterior (vitória/conferência) no DOM.
    const h1_vencedor = document.getElementById('h1_vencedor');
    if (h1_vencedor) {
        h1_vencedor.innerHTML = '';
    }
    const texto_v_d = document.getElementById("texto_vitoria_derrota");
    if (texto_v_d) {
        texto_v_d.innerText = '';
    }
    // Some com a auditoria da partida anterior.
    const painel_aud = document.getElementById('painel_auditoria');
    if (painel_aud) {
        painel_aud.style.display = 'none';
    }
    parar_celebracao();
    limpar_narrador();
});

// Função coletiva para construir formatação dinâmina para todos os os jogadores da partida (broadcast)
socket.on('formatador_coletivo', function (data) {
    const jogadores = data.jogadores_nomes;
    const jog_da_vez = data.jogador_inicial_nome;
    // Fase D2: registro quem o cliente acredita estar na vez (o heartbeat usa
    // isso para pedir o dispatcher reenviado se o indicador se perder).
    vez_atual_nome = String(jog_da_vez || '');

    jogadores.forEach((jogador) => {
        const card = document.getElementById(`card_${jogador}`);

        if (!card) {
            return;
        }

        // Fase 32 (P4): indicador de vez para TODOS — borda verde pulsante
        // (classe `card-da-vez`) no card de quem está na vez. Reseta o card
        // para o estado base e aplica o marcador só no da vez.
        card.className = 'card border border-secondary border-1 text-bg-dark';
        if (jogador === jog_da_vez) {
            card.classList.add('card-da-vez');
        }
    });
})

socket.on('botao_vencedor_ativ', function () {
    const botao_fogos = document.getElementById('comemorar');
    botao_fogos.style.display = 'block';
})

socket.on('vencedor_da_partida', function (data) {
    // Fase P3: marca o snapshot antes da fanfarra/celebração da vitória.
    if (data && data.reconstrucao === true) {
        reconstruindo_snapshot = true;
    }
    tocar_som_variante('aposta', [1, 2]);
    tocar_som('mover_peca');
    const h1_vencedor = document.getElementById('h1_vencedor');
    // Fase E + P5: o template tem <br> (por isso innerHTML); o nome interpolado
    // é escapado dentro de `t()` (`_interpolar` no i18n.js), sem dupla codificação.
    h1_vencedor.innerHTML = t('js.vitoria_texto', { nome: data.nome });
    iniciar_celebracao();
    // Fase 22: contador da jogada automática da tela de vitória (auto-confirma
    // o reset se o jogador ficar away from keyboard). Fase 75: espectador não
    // confirma nada, então não ganha relógio.
    tempo_conf_vit = Number(data.tempo_max) || 0;
    if (!eh_espectador) {
        iniciar_timer_jogada(tempo_conf_vit);
    }
})

socket.on('soltar_fogos', function () {
    soltar_fogos();
})

// Monta o texto da conferência no idioma do jogador. O servidor manda campos
// estruturados (quem ganhou/perdeu, quantidade apostada e real); se não vierem,
// cai para o texto pt-BR legado.
function texto_conferencia(data) {
    if (!data) {
        return '';
    }
    if (data.verdadeira === undefined) {
        return data.texto || '';
    }
    const qtd = data.dado_qtd;
    const face = data.dado_apostado_face;
    const saiu_txt = data.saiu_da_partida
        ? t('msg.conf.saiu', { nome: data.perdedor })
        : '';
    if (data.verdadeira) {
        const chave = Number(qtd) > 1 ? 'msg.conf.verdadeira.plural' : 'msg.conf.verdadeira.sing';
        return t(chave, { vencedor: data.ganhador, perdedor: data.perdedor, qtd: qtd, face: face, saiu: saiu_txt });
    }
    const real = Number(data.quantidade_real) || 0;
    const qchave = real <= 0 ? 'msg.conf.qtd.zero' : (real === 1 ? 'msg.conf.qtd.um' : 'msg.conf.qtd.muitos');
    const quantidade = t(qchave, { qtd: real });
    return t('msg.conf.mentirosa', {
        vencedor: data.ganhador, perdedor: data.perdedor,
        qtd: qtd, face: face, quantidade: quantidade, saiu: saiu_txt,
    });
}

// Função para construir os cards na página conferência
socket.on('cards_conferencia', function (data) {
    // Fase P3: marca o snapshot antes de tocar os sons de abertura da conferência.
    if (data && data.reconstrucao === true) {
        reconstruindo_snapshot = true;
    }
    tocar_som_variante('aposta', [1, 2]);
    tocar_som('virar_papel');
    const nomes = data.nomes;
    const dados = data.dados;
    const ganhador = data.ganhador;
    const perdedor = data.perdedor;
    const saiu_da_partida = data.saiu_da_partida;
    const dado_apostado = data.dado_apostado_face;
    const coringa = data.com_coringa;


    const cardContainer = document.getElementById("cards_conferencia");
    const texto_v_d = document.getElementById("texto_vitoria_derrota")
    cardContainer.innerHTML = ''
    const texto_conf = texto_conferencia(data);
    texto_v_d.innerText = texto_conf;
    if (texto_conf) {
        narrador_linha(texto_conf);
    }

    nomes.forEach((nome, index) => {
        // Criação do card
        const card = document.createElement("div");
        card.classList.add("col-sm-3", "mb-3");

        const cardInner = document.createElement("div");
        if (nome === ganhador) {
            cardInner.classList.add("card", "text-bg-secondary", "border-success", "rounded", "border-3");
        } else if (nome === perdedor && nome != saiu_da_partida) {
            cardInner.classList.add("card", "text-bg-secondary", "border-warning", "rounded", "border-3");
        } else if (nome === saiu_da_partida) {
            cardInner.classList.add("card", "text-bg-secondary", "border-danger", "rounded", "border-3");
        } else {
            cardInner.classList.add("card", "text-bg-secondary", "border-secondary", "rounded");
        }

        const cardBody = document.createElement("div");
        cardBody.classList.add("card-body");

        const cardTitle = document.createElement("h5");
        cardTitle.classList.add("card-title");
        cardTitle.textContent = nome;

        const hr = document.createElement("hr");

        const rowOuter = document.createElement("div");
        rowOuter.classList.add("row", "d-flex", "justify-content-evenly");

        const rowContainer = document.createElement("div");
        rowContainer.classList.add("row", "container", "text-center");

        // Adicionar colunas com imagem de dados no container
        for (let i = 0; i < dados[index].length; i++) {
            const diceCol = document.createElement("div");
            diceCol.classList.add("col", "g-1");

            const diceImg = document.createElement("img");
            diceImg.src = `../static/imagens/dado/${dados[index][i]}.png`;
            if ((dados[index][i] === dado_apostado) || (dados[index][i] === 1 && coringa)) {
                diceImg.classList.add("img-fluid", "px-1", "border", "border-danger", "shadow-lg", "rounded");
            } else {
                diceImg.classList.add("img-fluid", "px-1");
            }
            diceImg.classList.add("img-fluid", "px-1");
            diceImg.alt = `Imagem ${i + 1}`;
            diceImg.width = 40;
            diceImg.height = 40;

            diceCol.appendChild(diceImg);
            rowContainer.appendChild(diceCol);
        }

        // Estruturação dos elementos no card
        rowOuter.appendChild(rowContainer);
        cardBody.appendChild(cardTitle);
        cardBody.appendChild(hr);
        cardBody.appendChild(rowOuter);
        cardInner.appendChild(cardBody);
        card.appendChild(cardInner);
        cardContainer.appendChild(card);
    });

    // Fase 22: contador da jogada automática da conferência (auto-confirma o
    // "Ok" se o jogador ficar away from keyboard). Fase 75: espectador não
    // confirma nada, então não ganha relógio.
    tempo_conf_vit = Number(data.tempo_max) || 0;
    if (!eh_espectador) {
        iniciar_timer_jogada(tempo_conf_vit);
    }
})

// Fase 22: status em tempo real de quem já clicou no "Ok" (ou já rolou), por
// jogador, nas telas de rolagem (1), conferência (3) e vitória (4). O servidor
// emite `confirmados`/`pendentes` com apelidos; o cliente monta as fichas.
function renderizar_status_confirmacao(elId, data) {
    const el = document.getElementById(elId);
    if (!el) {
        return;
    }
    const confirmados = Array.isArray(data.confirmados) ? data.confirmados : [];
    const pendentes = Array.isArray(data.pendentes) ? data.pendentes : [];
    const total = Number(data.total) || 0;
    el.innerHTML = '';
    if (total <= 0) {
        return;
    }

    const chips = document.createElement('div');
    chips.className = 'd-flex flex-wrap justify-content-center gap-1 mb-1';
    confirmados.forEach(nome => {
        const b = document.createElement('span');
        b.className = 'badge text-bg-success';
        b.textContent = `✓ ${nome}`;
        chips.appendChild(b);
    });
    pendentes.forEach(nome => {
        const b = document.createElement('span');
        b.className = 'badge text-bg-secondary';
        b.textContent = `⏳ ${nome}`;
        chips.appendChild(b);
    });

    const msg = document.createElement('div');
    if (pendentes.length === 0) {
        msg.textContent = t('js.todos_confirmaram');
    } else if (pendentes.includes(nome_jogador)) {
        msg.textContent = t('js.aguardando_voce');
    } else {
        msg.textContent = t('js.aguardando_outros', { n: pendentes.length });
    }

    el.appendChild(chips);
    el.appendChild(msg);
}

socket.on('rolagem_status', function (data) {
    renderizar_status_confirmacao('rolagem_status', data);
});

socket.on('conferencia_status', function (data) {
    renderizar_status_confirmacao('status_conferencia', data);
});

socket.on('vitoria_status', function (data) {
    renderizar_status_confirmacao('status_vitoria', data);
})

// Ações a aplicar no jogador que virou espectador, broadcast=False
socket.on('espectador', function (data) {
    // Fase P3: no snapshot o espectador é o primeiro evento — arma o mute de sons
    // (o "pegar_dados" do evento vivo ainda soa, só o do snapshot é mudo).
    if (data && data.reconstrucao === true) {
        reconstruindo_snapshot = true;
    }
    tocar_som_variante('pegar_dados', [1, 2]);
    // Fase 30: quem virou espectador (perdeu todos os dados) ganha o botão de sair.
    eh_espectador = true;
    atualizar_botao_sair();
    const painel_jogada = document.getElementById('painel_jogada');
    const bot_confe_fim = document.getElementById('bot_confe_fim');
    const painel_aguarde = document.getElementById('painel_aguarde');
    const meus_dados = document.getElementById('meus_dados');
    meus_dados.innerHTML = "";
    const span = document.createElement('span');
    span.className = "fs-5 text-white me-2";
    span.innerText = t('js.espectador');
    meus_dados.appendChild(span);
    bot_confe_fim.style.display = 'none';
    painel_aguarde.style.display = 'none';
    painel_jogada.style.display = 'none';
    // Fase 75: espectador não tem botão de "Ok" nem é da vez, então o contador
    // da jogada automática não descreve nada que ele possa fazer — e o
    // `autojogar` que ele emitiria seria recusado pelo servidor (ele não está
    // em `rodada.jogadores`). Encerra para não mostrar um relógio que não
    // termina em nada.
    parar_timer_jogada();
    posicionar_toast_mobile();
    // Fase 69: quem vira espectador numa partida só de IAs passa a pagar o
    // ritmo — agenda o primeiro poll já (o `narracao` reagenda os seguintes).
    agendar_poll_espectador(POLL_ESPECTADOR_PADRAO);

})

// Lógica para enviar a aposta (chamada pelo botão e pela tecla Enter).
function apostar() {
    // Fase D: identidade ainda não confirmada (retomada em andamento) — o
    // servidor rejeitaria a chave placeholder. Não para o timer: o `autojogar`
    // (sem guarda) continua como rede de segurança.
    if (!chave_confirmada) {
        return;
    }
    parar_timer_jogada(); // Fase 21: agiu dentro do tempo, encerra o contador.
    const quantidade = document.getElementById('quantidade').value;

    if (selectedImageValue && quantidade) {
        const data = {
            chave: chave_secreta,
            dado: selectedImageValue,
            quantidade: quantidade
        };

        // Enviar para o backend (exemplo usando fetch)
        socket.emit('apostar', { dados: data });
    } else {
        mostrar_alerta(t('msg.selecione_dado'), 'aviso');
    }
}

document.getElementById('apostar').addEventListener('click', apostar);

// Lógica para enviar a desconfiança (chamada pelo botão e pela tecla Enter).
function desconfiar() {
    // Fase D: mesma guarda de `apostar` (ver lá).
    if (!chave_confirmada) {
        return;
    }
    parar_timer_jogada(); // Fase 21: agiu dentro do tempo, encerra o contador.
    const data = {
        chave: chave_secreta,
        acao: 'desconfiar'
    };
    // Enviar para o backend
    socket.emit('desconfiar', { dados: data });
}

document.getElementById('desconfiar').addEventListener('click', desconfiar);

// Funções após conectar
let retomar_enviado = false;
socket.on("connect_start", function (data) {
    // Fase D3: registra a conexão atendida — o `connect` local pode chegar
    // depois (ver a guarda no handler de `connect`).
    sid_ultimo_connect_start = socket.id;
    // Fase 73: o handshake desta conexão andou — desarma o watchdog (o
    // contador só zera quando a identidade é confirmada, abaixo).
    _watchdog_connect_start = _cancelar_watchdog(_watchdog_connect_start);
    // Facilidade: nova conexão, a config salva pode ser reaplicada numa sala nova.
    _config_local_aplicada = false;
    // Fase 18: na home (sem sala) o servidor não devolve chave — mantém a atual
    // para não apagar a identidade de uma sala anterior.
    // Fase D: guarda a chave no storage por sala só quando não há uma sessão
    // anterior para retomar (senão o placeholder sobrescreveria a identidade).
    if (data && data.chave_secreta) {
        chave_secreta = data.chave_secreta;
        if (!chave_resumo) {
            gravar_chave_resumo(chave_secreta);
        }
    }
    sou_master = !!(data && data.is_master);
    if (data && data.sala) {
        sala_atual = data.sala;
        modo_home = false;
        const badge = document.getElementById('sala_atual');
        if (badge) {
            badge.textContent = '#' + data.sala;
        }
    } else {
        // Home: sem sala definida o jogador escolhe criar ou buscar.
        sala_atual = '';
        modo_home = true;
    }
    aplicar_modo_home();
    // Fase 30: entrou numa sala (espera) — o botão de sair fica visível na
    // página 0; na home (sem sala) ele some.
    atualizar_botao_sair();
    if (data && data.username) {
        // Reconexão retomada: o servidor já tem o apelido deste jogador, então
        // o botão entra no lápis direto (sem depender do prefill do storage).
        // Numa sala nova `username` vem None e o "ok" continua de pé.
        nome_jogador = data.username;
        confirmar_apelido(data.username);
    }
    // Fase D: com uma sessão anterior guardada, retoma a identidade logo após
    // o connect (uma vez por conexão). O servidor troca o placeholder pela
    // identidade real e reemite o connect_start + snapshot.
    if (retomar_enviado) {
        // Segundo connect_start (pós-retomada): chave_secreta já é a real.
        chave_confirmada = true;
        // Fase 73: identidade confirmada — zera as tentativas do watchdog.
        _watchdog_connect_tentativas = 0;
    } else if (chave_resumo && data && data.sala) {
        retomar_enviado = true;
        // Placeholder: chave_secreta é temporária, ação mutável agora falharia.
        chave_confirmada = false;
        socket.emit('retomar_identidade', { chave: chave_resumo });
        // Fase 73: o primeiro `connect_start` é do placeholder — a identidade
        // real e o snapshot só vêm no segundo. Se a retomada abortar em silêncio,
        // o watchdog reabre a conexão (o contador NÃO zera aqui, senão o loop
        // placeholder→aborto nunca atingiria o teto).
        _armar_watchdog_connect_start();
    } else {
        // Sem retomada (sala nova / home): a chave já corresponde ao servidor.
        chave_confirmada = true;
        _watchdog_connect_tentativas = 0;
    }
    // Destrava o apelido para todos, incluindo o master (o `update_user_list`
    // seguinte é quem trava de novo, conforme status/pronto).
    apelido_travado = false;
    atualizar_botao_apelido();
    aplicar_master();
});

// A chave guardada não pertence a esta sala (ex.: sessão de outra sala, ou a
// identidade expirou): adota o placeholder como identidade nova e persiste a
// chave dele no sessionStorage — senão a chave stale ficaria para sempre.
// Fase D2: `chave_resumo` passa a apontar para a chave do placeholder, para um
// reconnect com sid novo (morte de instância) retomar a identidade correta.
socket.on('retomar_negado', function (data) {
    // Fase 73: o servidor já reemitiu o snapshot do placeholder — a tela monta,
    // não precisa reabrir a conexão.
    _watchdog_connect_start = _cancelar_watchdog(_watchdog_connect_start);
    _watchdog_connect_tentativas = 0;
    // Fase 30: o motivo explica por que a retomada falhou (vaga perdida por
    // inatividade nesta sala vs. sessão de outra sala).
    const motivo = (data && data.motivo && data.motivo.chave)
        ? t(data.motivo.chave, data.motivo.params)
        : t('msg.retomar_outra_sala');
    mostrar_alerta(motivo, 'aviso');
    if (chave_secreta) {
        // O placeholder vira a identidade definitiva: chave_secreta volta a
        // corresponder ao servidor, então as ações mutáveis já podem fluir.
        chave_confirmada = true;
        chave_resumo = chave_secreta;
        gravar_chave_resumo(chave_secreta);
    }
});

// Indicadores de conexão/reconexão (heartbeat visual).
function _atualizar_status_conexao(chave, classe) {
    const status = document.getElementById('status_conexao');
    if (status) {
        status.textContent = t(chave);
        status.className = 'd-block mb-2 ' + classe;
    }
}

// Fase 73: watchdog do handshake da sala. `handle_connect` e
// `retomar_identidade` abortam em SILÊNCIO quando o lock distribuído está tomado
// (`TravaIndisponivel`) ou o save fica stale (`ConflitoDeEstado`): o socket segue
// CONECTADO, mas o `connect_start` nunca chega e a sala não monta. Sem isto, a
// recuperação dependia do ping timeout do socket.io (~20s+) ou de um reload
// manual — era a lentidão percebida ao dar refresh numa sala. Aqui, se o
// `connect_start` não chega em `TEMPO_LIMITE_CONNECT_MS`, a conexão é derrubada e
// reaberta (mesmo efeito de um F5, sem a espera). Limitado a
// `MAX_TENTATIVAS_WATCHDOG_CONNECT` para não martelar o servidor; depois disso o
// status vira "sem conexão" (reabrir a aba/voltar do background reconecta).
const TEMPO_LIMITE_CONNECT_MS = 9000;
const MAX_TENTATIVAS_WATCHDOG_CONNECT = 4;
let _watchdog_connect_start = null;
let _watchdog_connect_tentativas = 0;

function _armar_watchdog_connect_start() {
    _watchdog_connect_start = _cancelar_watchdog(_watchdog_connect_start);
    _watchdog_connect_start = setTimeout(function () {
        _watchdog_connect_start = null;
        if (_conexao_recusada || !socket.connected) {
            return;
        }
        if (_watchdog_connect_tentativas >= MAX_TENTATIVAS_WATCHDOG_CONNECT) {
            socket.disconnect();
            _atualizar_status_conexao('js.sem_conexao', 'text-danger');
            return;
        }
        _watchdog_connect_tentativas += 1;
        _atualizar_status_conexao('js.reconectando', 'text-warning');
        socket.disconnect();
        socket.connect();
    }, TEMPO_LIMITE_CONNECT_MS);
}

socket.on('connect', function () {
    _tentativas_reconexao = 0;
    _conexao_recusada = false;
    _atualizar_status_conexao('js.conectado', 'text-success');
    // Fase D2: reconnect com sid novo (morte de instância) ainda tem a chave
    // guardada — o placeholder foi criado com snapshot ADIADO (`tem_chave=1`);
    // rearmar `retomar_enviado` faz o `connect_start` seguinte reemitir a
    // `retomar_identidade` e destravar o snapshot pra este cliente.
    //
    // Fase D3: o `connect` local pode disparar DEPOIS do `connect_start` da
    // MESMA conexão (o socket.io processa a primeira mensagem do servidor antes
    // de emitir o `connect`). Só rearmamos o estado de retomada quando a
    // conexão é realmente nova (sid ainda não atendido por um `connect_start`) —
    // senão o `connect` clobberaria a decisão do `connect_start` (identidade já
    // confirmada voltaria a false e nenhum botão mutável responderia).
    if (sid_ultimo_connect_start !== socket.id) {
        retomar_enviado = false;
        // Segura ações mutáveis até o connect_start seguinte validar a chave.
        chave_confirmada = false;
        // Fase 73: conexão nova — se o `connect_start` não chegar (connect
        // abortado no servidor), o watchdog derruba/reabre a conexão.
        _armar_watchdog_connect_start();
    }
});

socket.on('disconnect', function () {
    _atualizar_status_conexao('js.reconectando', 'text-warning');
});

// Fase 68 (mobile): o Android suspende timers e o WebSocket quando a aba vai
// para segundo plano ou a rede troca (wifi <-> dados). Ao voltar para a aba
// (`visibilitychange`) ou recuperar a conexão (`online`), não espere o ping
// timeout do socket.io (~35s): reconecta na hora se caiu, ou bate um heartbeat
// para o servidor devolver o snapshot fresco (mesmo caminho do re-sync da
// espera). É o que evita a tela "desatualizada/demorando a conectar" depois de
// tirar o celular do bolso. Nunca reconecta após recusa intencional do servidor.
function _resync_apos_background() {
    if (_conexao_recusada) {
        return;
    }
    if (!socket.connected) {
        socket.connect();
        return;
    }
    if (chave_secreta) {
        try {
            socket.emit('heartbeat', {
                chave: chave_secreta,
                pagina: indiceAtual,
                vez: vez_atual_nome,
            });
        } catch (erro) {
            console.error('Erro no resync ao voltar do background', erro);
        }
    }
}

document.addEventListener('visibilitychange', function () {
    if (!document.hidden) {
        _resync_apos_background();
    }
});
window.addEventListener('online', _resync_apos_background);

socket.on("update_username", function (data) {
    nome_jogador = data.nome_jogador;
    // Confirmação (e eventual sufixo de colisão) do apelido: fecha o editor e
    // deixa o botão no lápis, com o input exibindo o valor que o servidor aceitou.
    confirmar_apelido(data.nome_jogador);
})

socket.on("jogar_dados_resultado", function (data) {
    parar_timer_jogada(); // Fase 21: já rolou (manual ou automático), zera o contador.
    cancelar_retry_rolagem(); // Fase 72: resultado chegou, desarma o watchdog.
    // A rolagem já foi feita (manual, `autojogar` ou reenvio idempotente):
    // trava o botão "Jogar dados" desta rodada para o jogador não clicar de novo.
    desativar_botao_dados();
    // Fase 55: reenvio idempotente do servidor (segundo clique perdido, rede)
    // não reinicia a animação desta rodada — só o primeiro recebimento anima.
    if (rolagem_animada) {
        return;
    }
    rolagem_animada = true;
    const dados_lista = data.dados_jogador;
    const dados_qtd = dados_lista.length;

    const dados = [];

    // Loop para adicionar os elementos restantes
    for (let i = 1; i <= dados_qtd; i++) {
        const dadoElement = document.getElementById(`dado${i}`);
        if (dadoElement) {
            dados.push(dadoElement);
        }
    }

    const rollInterval = 100; // Intervalo de troca de imagens em milissegundos
    const rollTime = Math.floor(Math.random() * (6000 - 3000 + 1)) + 3000; // Tempo total da rolagem

    // Inicia o som de rolagem, repetido enquanto a animação rola
    const som_rolagem = setInterval(() => tocar_som('rolar_dados'), 1200);
    tocar_som('rolar_dados');

    // Inicia a animação de rolagem para todos os dados
    const animation = setInterval(() => {
        dados.forEach(dado => {
            // Gera um índice aleatório para cada dado
            const randomIndex = Math.floor(Math.random() * diceImages.length);
            dado.src = diceImages[randomIndex];
        });
    }, rollInterval);

    // Após o tempo total de rolagem, exibe o resultado final e para a animação
    setTimeout(() => {
        clearInterval(animation);
        clearInterval(som_rolagem);

        // Cria dinamicamente os resultados finais com base em "dados_lista"
        const finalResults = dados_lista.map(valor => `../static/imagens/dado/${valor}.png`);

        // Atualiza as imagens com os resultados finais
        dados.forEach((dado, index) => {
            dado.src = finalResults[index];
        });
        tocar_som_variante('dado_impacto', [1, 2]);

        // Mostra o resultado por ~2 seg antes de enviar a confirmação
        // e o servidor mudar de tela.
        setTimeout(() => {
            socket.emit('joguei_dados', { 'chave_secreta': chave_secreta });
        }, 2000);
    }, rollTime);
});

// Alerta de jogada inválida: o servidor envia o motivo explicado (Fase 13).
socket.on('jogada_invalida', function (data) {
    let motivo;
    if (data && data.txtchave) {
        motivo = t(data.txtchave, data.txtparams || {});
    } else {
        motivo = (data && data.txtadd) ? data.txtadd : t('msg.jogada_invalida_padrao');
    }
    mostrar_alerta(motivo, 'erro');
})

// Fase 9: alguém caiu no meio da partida. Agenda um pedido ao servidor para
// expurgar a desconexão após a janela de graça — se o jogador voltar antes
// (chave_secreta no reconnect), o servidor limpa o marcador e nada é removido.
socket.on('jogador_desconectado', function (data) {
    const grace_ms = (Math.max(1, Number(data.grace) || 30) * 1000) + 500;
    setTimeout(() => socket.emit('verificar_desconectados', { chave: chave_secreta }), grace_ms);
});

// ---------------------------------------------------------------------------
// Apelido: o input e o botão de confirmação dividem a mesma linha
// (`.apelido-linha` no template) e o botão é o próprio estado da edição:
//
//   sem apelido  → input editável, botão "ok" (salva)
//   confirmado   → input em `readonly` só exibindo o valor, botão lápis
//                  (clicar/tocar no input reabre a edição e vira "ok")
//
// O apelido continua trocável quantas vezes quiser na espera; o travamento
// (jogando ou com o "ficar pronto" marcado) vem do `update_user_list`.
// ---------------------------------------------------------------------------
const ICONE_LAPIS = '✏️';
let apelido_confirmado = false;
let apelido_editando = false;
let apelido_travado = false;
// Último valor confirmado — o que o servidor respondeu, que pode vir sufixado em
// colisão ("Nome_1"). É o que o input exibe e o que o `blur` compara para saber
// se a edição pode fechar sozinha.
let apelido_confirmado_texto = '';

function atualizar_botao_apelido() {
    const input = document.getElementById('apelido');
    const botao = document.getElementById('botapel');
    if (!input || !botao) {
        return;
    }
    const editando = !apelido_confirmado || apelido_editando;
    input.readOnly = !editando;
    input.disabled = apelido_travado;
    botao.disabled = apelido_travado;
    botao.classList.toggle('papel', !editando);
    const rotulo = editando ? t('ui.apelido_ok') : ICONE_LAPIS;
    const dica = editando ? t('ui.apelido_ok') : t('ui.apelido_editar');
    botao.textContent = rotulo;
    botao.title = dica;
    botao.setAttribute('aria-label', dica);
}

function abrir_edicao_apelido() {
    const input = document.getElementById('apelido');
    if (!input || apelido_travado) {
        return;
    }
    apelido_editando = true;
    atualizar_botao_apelido();
    input.focus();
    input.select();
}

// Confirmação do servidor: o apelido salvo (já com o sufixo de colisão, se
// houve) vira o valor exibido e fecha o editor. Não mexe no localStorage — ali
// fica o que o jogador digitou, senão a próxima sessão já nasceria com o
// "Nome_1" e o servidor empilharia outro sufixo em cima.
function confirmar_apelido(texto) {
    apelido_confirmado = true;
    apelido_confirmado_texto = texto || '';
    const input = document.getElementById('apelido');
    // Digitação em curso (reabriu a edição antes da resposta chegar): não
    // sobrescreve nem trava o campo no meio da palavra — o próximo "ok" ou o
    // blur fecham a edição com o valor novo.
    if (!input || document.activeElement !== input) {
        if (input) {
            input.value = apelido_confirmado_texto;
        }
        apelido_editando = false;
    } else if (input.value.trim() === apelido_confirmado_texto) {
        apelido_editando = false;
    }
    atualizar_botao_apelido();
}

// Função para enviar apelido ao servidor
function enviar_apelido() {
    const input = document.getElementById("apelido");
    if (!input || apelido_travado) {
        return;
    }
    if (apelido_confirmado && !apelido_editando) {
        // O input está em `readonly` exibindo o apelido confirmado: não há o que
        // salvar, é preciso abrir a edição antes.
        return;
    }
    const apelido = input.value.trim();
    if (!apelido) {
        mostrar_alerta(t('msg.preencha_nome'), 'aviso');
        return;
    }
    localStorage.setItem('dadinho_apelido', apelido); // Lembra entre sessões
    sessionStorage.setItem('dadinho_apelido', apelido); // Mantém entre trocas de sala
    // Vai trimmed: o servidor valida o texto cru e cairia em 'NOME_BUGADO'.
    socket.emit('apelido', { apelido_msg: apelido });
    // O input não é desativado aqui: o apelido pode ser trocado quantas vezes
    // quiser na espera; o travamento acontece ao ficar pronto. Quem fecha o
    // editor é o `update_username` de confirmação — se o servidor recusar, o
    // input segue editável e o botão segue em "ok".
}

// Clique no botão: "ok" salva, o lápis abre a edição.
function alternar_apelido() {
    if (apelido_travado) {
        return;
    }
    if (!apelido_confirmado || apelido_editando) {
        enviar_apelido();
        return;
    }
    abrir_edicao_apelido();
}

const input_apelido = document.getElementById('apelido');
if (input_apelido) {
    // Tocar no input em modo leitura também abre a edição (o lápis é o atalho
    // explícito, mas o campo continua sendo clicável).
    input_apelido.addEventListener('focus', function () {
        if (apelido_confirmado && !apelido_editando && !apelido_travado) {
            apelido_editando = true;
            atualizar_botao_apelido();
            input_apelido.select();
        }
    });
    // Sair com o valor intacto fecha o editor; com valor diferente, fica em
    // edição esperando o "ok" para não perder o que foi digitado.
    input_apelido.addEventListener('blur', function () {
        if (apelido_confirmado && input_apelido.value.trim() === apelido_confirmado_texto) {
            apelido_editando = false;
        }
        atualizar_botao_apelido();
    });
}

// Facilidade: o apelido é lembrado entre sessões (localStorage) e entre abas
// da mesma sessão (sessionStorage, fallback para sessões antigas). O texto vem
// pré-preenchido, mas o botão só vira lápis quando o SERVIDOR confirma o
// apelido (`update_username`/`connect_start`) — marcar como confirmado aqui
// deixaria quem entra numa sala nova sem nunca apertar o "ok", e o servidor
// ficaria sem apelido (`pode_iniciar` preso em `sem_apelido`).
const apelidoSalvo = localStorage.getItem('dadinho_apelido') || sessionStorage.getItem('dadinho_apelido');
if (apelidoSalvo && input_apelido) {
    input_apelido.value = apelidoSalvo.trim();
}
atualizar_botao_apelido();

function iniciar_partida() {
    tocar_som_variante('embaralhar', [1, 2]);
    const dados_qtd = document.getElementById('config_dados').value;
    socket.emit('iniciar_partida', { chave: chave_secreta, dados_qtd: dados_qtd });
}

let contexto_audio = null;
let promessa_resume_audio = null;

function contexto_audio_rodando() {
    return !!contexto_audio && contexto_audio.state === 'running';
}

// Espera o `resume` em curso, mas no máximo este prazo: um resume preso não
// pode travar o início da música (o próximo gesto refaz a tentativa). Nunca
// rejeita.
const ESPERA_RESUME_MS = 1200;

function esperar_resume_audio() {
    const atual = promessa_resume_audio;
    if (!atual) {
        return Promise.resolve();
    }
    return Promise.race([
        atual.then(() => {}, () => {}),
        new Promise((resolve) => { setTimeout(resolve, ESPERA_RESUME_MS); }),
    ]);
}

// `gesto=true` só para quem está num gesto do usuário (`desbloquear_audio`).
// A função também roda fora de gesto (os efeitos de `tocar_som` vêm de
// socket.on), e um `resume()` aberto sem gesto fica pendente indefinidamente em
// alguns navegadores — sem resolver no clique seguinte. O guard de
// `promessa_resume_audio` evita duplicar o `resume`, mas ele NÃO pode valer
// para quem está num gesto: assim o `resume` é refeito a cada toque/tecla até
// o contexto ficar de fato 'running' (era o que impedia a música de ligar).
function garantir_contexto_audio(gesto) {
    if (typeof (window.AudioContext) === 'undefined' && typeof (window.webkitAudioContext) === 'undefined') {
        return false;
    }
    if (!contexto_audio) {
        contexto_audio = new (window.AudioContext || window.webkitAudioContext)();
        promessa_resume_audio = null;
    }
    // Retoma o contexto e guarda a promessa: o `resume` é assíncrono, e
    // começar uma fonte com o contexto ainda 'suspended' engole o som de
    // forma intermitente (iOS em especial). Quem for tocar aguarda a promessa.
    if (contexto_audio.state === 'suspended' && (gesto || !promessa_resume_audio)) {
        // A identidade da promessa importa: com `gesto=true` o `resume` é
        // reencaminhado a cada toque, e sem esta comparação a promessa antiga,
        // ao resolver, apagaria a flag da nova e o `resume` em voo deixaria de
        // ser aguardado por quem vai tocar.
        const em_voo = contexto_audio.resume();
        promessa_resume_audio = em_voo;
        const encerrar = () => {
            if (promessa_resume_audio === em_voo) {
                promessa_resume_audio = null;
            }
        };
        em_voo.then(encerrar, encerrar);
    }
    return true;
}

// Sons do jogo, carregados sob demanda a partir de static/sons/.
const sons_disponiveis = {
    rolar_dados: 'rolar_dados.mp3',
    pegar_dados_1: 'pegar_dados_1.mp3',
    pegar_dados_2: 'pegar_dados_2.mp3',
    pegar_dados_3: 'pegar_dados_3.mp3',
    aposta_1: 'aposta_1.mp3',
    aposta_2: 'aposta_2.mp3',
    virar_papel: 'virar_papel.mp3',
    virar_papel_2: 'virar_papel_2.mp3',
    mover_peca: 'mover_peca.mp3',
    mover_peca_2: 'mover_peca_2.mp3',
    embaralhar_1: 'embaralhar_1.mp3',
    embaralhar_2: 'embaralhar_2.mp3',
    dado_impacto_1: 'dado_impacto_1.mp3',
    dado_impacto_2: 'dado_impacto_2.mp3',
    nova_rodada_1: 'nova_rodada_1.mp3',
    nova_rodada_2: 'nova_rodada_2.mp3',
    distribuir_1: 'distribuir_1.mp3',
    distribuir_2: 'distribuir_2.mp3',
    beep: 'beep.mp3',
};
const sons = {};

// Preferência de som do jogador, persistida entre sessões. Valor padrão: ligado.
const som_salvo = localStorage.getItem('dadinho_som');
let som_ativado = som_salvo === null ? PADROES_CLIENTE.som_ativado : som_salvo !== 'off';
const botao_som = document.getElementById('botao_som');
// Fase 33 (M1): o drawer do mobile tem o próprio botão de som — ambos
// compartilham o mesmo estado via `alternar_som`/`atualizar_icones_som`.
const botao_menu_som = document.getElementById('menu_botao_som');

function atualizar_icones_som() {
    const icone = som_ativado ? '🔊' : '🔇';
    if (botao_som) {
        botao_som.textContent = icone;
    }
    if (botao_menu_som) {
        botao_menu_som.textContent = icone;
    }
}

function alternar_som() {
    som_ativado = !som_ativado;
    localStorage.setItem('dadinho_som', som_ativado ? 'on' : 'off');
    atualizar_icones_som();
}

if (botao_som) {
    atualizar_icones_som();
    botao_som.addEventListener('click', alternar_som);
}
if (botao_menu_som) {
    botao_menu_som.addEventListener('click', alternar_som);
}

// Volume dos efeitos sonoros (0 a 100), persistido entre sessões.
let volume_som = Number(localStorage.getItem('dadinho_volume_som') || PADROES_CLIENTE.volume_som);
const slider_volume_som = document.getElementById('volume_som');
const slider_menu_volume_som = document.getElementById('menu_volume_som');

function sincronizar_sliders_volume_som() {
    if (slider_volume_som) {
        slider_volume_som.value = volume_som;
    }
    if (slider_menu_volume_som) {
        slider_menu_volume_som.value = volume_som;
    }
}

function ao_mudar_volume_som(valor) {
    volume_som = Number(valor) || 0;
    localStorage.setItem('dadinho_volume_som', String(volume_som));
    sincronizar_sliders_volume_som();
    aplicar_volume_som();
}

if (slider_volume_som) {
    slider_volume_som.addEventListener('input', (event) => {
        ao_mudar_volume_som(event.target.value);
    });
}
if (slider_menu_volume_som) {
    slider_menu_volume_som.addEventListener('input', (event) => {
        ao_mudar_volume_som(event.target.value);
    });
}
// Aplica o volume persistido nos sliders (desktop + drawer) já no load.
sincronizar_sliders_volume_som();

// --- Sistema de ajuda: tutorial + dicas durante a partida ---
// Preferência de dicas do jogador, persistida entre sessões. Valor padrão: ligado.
const dicas_salvas = localStorage.getItem('dadinho_dicas');
let dicas_ativadas = dicas_salvas === null ? PADROES_CLIENTE.dicas : dicas_salvas !== 'off';

// Dicas contextuais mostradas conforme a página da partida (0 a 4). São chaves
// de tradução; o texto é resolvido no idioma do jogador em mostrar_dica().
const dicas_por_pagina = {
    0: ['js.dica.0.0', 'js.dica.0.1', 'js.dica.0.2', 'js.dica.0.3', 'js.dica.0.4', 'js.dica.0.5',
        'js.dica.0.6', 'js.dica.0.7', 'js.dica.0.8', 'js.dica.0.9', 'js.dica.0.10', 'js.dica.0.11',
        'js.dica.0.12'],
    1: ['js.dica.1.0', 'js.dica.1.1', 'js.dica.1.2', 'js.dica.1.3', 'js.dica.1.4', 'js.dica.1.5',
        'js.dica.1.6'],
    2: ['js.dica.2.0', 'js.dica.2.1', 'js.dica.2.2', 'js.dica.2.3', 'js.dica.2.4', 'js.dica.2.5',
        'js.dica.2.6', 'js.dica.2.7', 'js.dica.2.8', 'js.dica.2.9', 'js.dica.2.10', 'js.dica.2.11',
        'js.dica.2.12', 'js.dica.2.13', 'js.dica.2.14', 'js.dica.2.15'],
    3: ['js.dica.3.0', 'js.dica.3.1', 'js.dica.3.2', 'js.dica.3.3', 'js.dica.3.4', 'js.dica.3.5'],
    4: ['js.dica.4.0', 'js.dica.4.1', 'js.dica.4.2', 'js.dica.4.3', 'js.dica.4.4'],
};

// Última chave sorteada em mostrar_dica(): usada para não repetir a mesma dica
// na transição seguinte (refaz o sorteio uma vez quando cai a repetida).
let ultima_dica = null;

const botao_tutorial = document.getElementById('botao_tutorial');
const botao_dicas = document.getElementById('botao_dicas');
const overlay_tutorial = document.getElementById('tutorial_overlay');
const painel_dicas = document.getElementById('painel_dicas');
const switch_tutorial = document.getElementById('tutorial_dicas_switch');

// Modal de alerta reutilizável (substitui window.alert/confirm): evita o padrão
// do navegador e mantém a identidade visual do app. Retorna uma Promise que
// resolve com `true`/`false` quando o jogador fecha — com tipo `confirmar`, o
// modal ganha os botões Confirmar/Cancelar para servir de confirmação.
const alerta_overlay = document.getElementById('alerta_overlay');
const alerta_icone = document.getElementById('alerta_icone');
const alerta_titulo = document.getElementById('alerta_titulo');
const alerta_mensagem = document.getElementById('alerta_mensagem');
// F1: fila de alertas — `_alerta_ativo` é o alerta aberto agora; `_fila_alertas`
// guarda os que chegaram por cima dele. Antes, um resolver único era
// sobrescrito quando um 2º alerta abria sobre o 1º, e a promise do 1º nunca
// resolvia (cadeias `.then()` morriam — ex.: `sala_cheia -> criar_sala`).
let _alerta_ativo = null;
let _fila_alertas = [];

const ALERTA_ESTILOS = {
    aviso: { icone: '⚠️', titulo: 'alerta.aviso' },
    erro: { icone: '⛔', titulo: 'alerta.erro' },
    info: { icone: 'ℹ️', titulo: 'alerta.info' },
    sucesso: { icone: '✅', titulo: 'alerta.sucesso' },
    confirmar: { icone: '❓', titulo: 'alerta.confirmar' },
};

function mostrar_alerta(mensagem, tipo) {
    const chave = ALERTA_ESTILOS[tipo] ? tipo : 'aviso';
    if (!alerta_overlay) {
        return Promise.resolve(true);
    }
    return new Promise(function (resolve) {
        const alerta = { mensagem, tipo: chave, resolver: resolve };
        if (_alerta_ativo) {
            _fila_alertas.push(alerta);
        } else {
            _abrir_alerta(alerta);
        }
    });
}

function _abrir_alerta(alerta) {
    _alerta_ativo = alerta;
    const estilo = ALERTA_ESTILOS[alerta.tipo];
    const confirmar = alerta.tipo === 'confirmar';
    alerta_icone.textContent = estilo.icone;
    alerta_titulo.textContent = t(estilo.titulo);
    alerta_mensagem.textContent = alerta.mensagem;
    alerta_overlay.dataset.tipo = alerta.tipo;
    const botao_cancelar = document.getElementById('alerta_cancelar');
    if (botao_cancelar) {
        botao_cancelar.style.display = confirmar ? '' : 'none';
    }
    alerta_overlay.style.display = 'flex';
    const botao = confirmar && botao_cancelar ? botao_cancelar : document.getElementById('alerta_ok');
    if (botao) {
        botao.focus();
    }
}

function fechar_alerta(resultado) {
    if (!alerta_overlay || !_alerta_ativo) {
        return;
    }
    const atual = _alerta_ativo;
    _alerta_ativo = null;
    atual.resolver(!!resultado);
    const proximo = _fila_alertas.shift();
    if (proximo) {
        _abrir_alerta(proximo);
    } else {
        alerta_overlay.style.display = 'none';
    }
}

if (alerta_overlay) {
    alerta_overlay.addEventListener('click', (event) => {
        if (event.target === alerta_overlay) {
            fechar_alerta(false);
        }
    });
}

function aplicar_estado_dicas() {
    // Fase 33 (M1): o drawer do mobile tem o próprio switch de dicas.
    const menu_dicas_switch = document.getElementById('menu_dicas_switch');
    if (botao_dicas) {
        botao_dicas.classList.toggle('btn-outline-warning', dicas_ativadas);
        botao_dicas.classList.toggle('btn-outline-secondary', !dicas_ativadas);
    }
    if (menu_dicas_switch) {
        menu_dicas_switch.checked = dicas_ativadas;
        menu_dicas_switch.setAttribute('aria-checked', dicas_ativadas ? 'true' : 'false');
    }
    if (switch_tutorial) {
        switch_tutorial.checked = dicas_ativadas;
    }
}

function mostrar_dica(pag_numero) {
    if (!dicas_ativadas) {
        return;
    }
    const dicas = dicas_por_pagina[pag_numero] || [];
    if (dicas.length === 0) {
        return;
    }
    let chave = dicas[Math.floor(Math.random() * dicas.length)];
    if (chave === ultima_dica && dicas.length > 1) {
        chave = dicas[Math.floor(Math.random() * dicas.length)];
    }
    ultima_dica = chave;
    const texto = t(chave);
    if (eh_mobile()) {
        mostrar_toast_mobile(texto);
        return;
    }
    if (!painel_dicas) {
        return;
    }
    document.getElementById('dicas_texto').textContent = texto;
    painel_dicas.style.display = 'flex';
}

function fechar_dica() {
    if (painel_dicas) {
        painel_dicas.style.display = 'none';
    }
}

function definir_dicas(ativadas) {
    dicas_ativadas = ativadas;
    localStorage.setItem('dadinho_dicas', dicas_ativadas ? 'on' : 'off');
    aplicar_estado_dicas();
    aplicar_estado_narrador();
    if (dicas_ativadas) {
        mostrar_dica(indiceAtual);
    } else {
        fechar_dica();
    }
}

function alternar_dicas() {
    definir_dicas(!dicas_ativadas);
}

function abrir_tutorial() {
    if (overlay_tutorial) {
        overlay_tutorial.style.display = 'flex';
    }
}

function fechar_tutorial() {
    if (overlay_tutorial) {
        overlay_tutorial.style.display = 'none';
    }
}

if (botao_tutorial) {
    botao_tutorial.addEventListener('click', abrir_tutorial);
}
if (botao_dicas) {
    botao_dicas.addEventListener('click', alternar_dicas);
}
const botao_narrador = document.getElementById('botao_narrador');
if (botao_narrador) {
    botao_narrador.addEventListener('click', alternar_narrador);
}
if (switch_tutorial) {
    switch_tutorial.addEventListener('change', function () {
        definir_dicas(this.checked);
    });
}
if (overlay_tutorial) {
    overlay_tutorial.addEventListener('click', (event) => {
        if (event.target === overlay_tutorial) {
            fechar_tutorial();
        }
    });
}

// ---------------------------------------------------------------------------
// Fase 33 (M1): menu sandwich (drawer) do mobile.
// O ☰ abre um drawer com as 6 ferramentas (Tutorial, Dicas, Narrador, Idioma,
// Sons, Música); fecha no toque fora, no Esc, no ✖ ou arrastando para a
// esquerda. Abre também por swipe da borda direita da tela. Desktop não usa
// (o ☰ fica `display:none`).
// ---------------------------------------------------------------------------
const botao_menu = document.getElementById('botao_menu');
const menu_drawer = document.getElementById('menu_drawer');

function abrir_menu() {
    if (!menu_drawer) {
        return;
    }
    menu_drawer.classList.add('aberto', 'abrir');
    menu_drawer.setAttribute('aria-hidden', 'false');
    // A animação é pontual (classe `abrir`): sem ela o drawer não "pula" ao
    // abrir por swipe (que posiciona o drawer seguindo o dedo).
    window.setTimeout(function () {
        menu_drawer.classList.remove('abrir');
    }, 300);
    const fechar = document.getElementById('botao_fechar_menu');
    if (fechar) {
        fechar.focus();
    }
}

function fechar_menu() {
    if (!menu_drawer) {
        return;
    }
    menu_drawer.classList.remove('aberto', 'abrir', 'arrastando');
    menu_drawer.style.transform = '';
    menu_drawer.setAttribute('aria-hidden', 'true');
    if (botao_menu) {
        botao_menu.focus();
    }
}

if (botao_menu && menu_drawer) {
    botao_menu.addEventListener('click', abrir_menu);
    const botao_fechar_menu = document.getElementById('botao_fechar_menu');
    if (botao_fechar_menu) {
        botao_fechar_menu.addEventListener('click', fechar_menu);
    }
    // Toque/clique fora do drawer (e fora do ☰) fecha.
    document.addEventListener('pointerdown', function (event) {
        if (menu_drawer.classList.contains('aberto') &&
            !menu_drawer.contains(event.target) && event.target !== botao_menu) {
            fechar_menu();
        }
    });
    // Esc fecha o drawer.
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && menu_drawer.classList.contains('aberto')) {
            fechar_menu();
        }
    });
    // -----------------------------------------------------------------------
    // Swipe do drawer: arrastar para a esquerda fecha; um gesto começando na
    // borda direita da tela abre. Botões (☰/✖/toque fora) seguem como fallback.
    // Só existe no mobile (a media query que mostra o ☰ é max-width: 768px).
    // -----------------------------------------------------------------------
    const gesto_mobile = window.matchMedia('(max-width: 768px)');
    const NAO_ARRASTAVEIS = 'input, select, button, textarea, a, label';
    let arrasto_menu = null;

    // Gestos de abertura interrompidos (scroll/cancel) voltam ao estado
    // fechado — o drawer só fica aberto quando o dedo passa o limiar.
    function reverter_abertura_menu() {
        if (arrasto_menu && arrasto_menu.abrindo) {
            menu_drawer.classList.remove('aberto');
            menu_drawer.setAttribute('aria-hidden', 'true');
        }
    }

    function limpar_arrasto_menu() {
        arrasto_menu = null;
        menu_drawer.classList.remove('arrastando');
        menu_drawer.style.transform = '';
    }

    document.addEventListener('pointerdown', function (event) {
        if (!gesto_mobile.matches) {
            return;
        }
        const aberto = menu_drawer.classList.contains('aberto');
        if (aberto) {
            // Só arrasta se o toque começou dentro do drawer em área não
            // interativa (não rouba o gesto dos sliders, switchs e selects).
            if (!menu_drawer.contains(event.target) ||
                (event.target instanceof Element && event.target.closest(NAO_ARRASTAVEIS))) {
                return;
            }
        } else if (event.clientX <= window.innerWidth - 28) {
            // Fora da zona da borda direita: não é um gesto de abertura.
            return;
        }
        arrasto_menu = {
            inicioX: event.clientX,
            inicioY: event.clientY,
            dx: 0,
            abrindo: !aberto,
            definido: false
        };
        // Interrompe a animação de abertura por botão, se ainda estiver rodando.
        menu_drawer.classList.remove('abrir');
        if (arrasto_menu.abrindo) {
            menu_drawer.classList.add('aberto', 'arrastando');
            // Lê a largura depois de mostrar (display:none tem 0).
            menu_drawer.style.transform = 'translateX(' + menu_drawer.offsetWidth + 'px)';
        } else {
            menu_drawer.classList.add('arrastando');
        }
        try {
            menu_drawer.setPointerCapture(event.pointerId);
        } catch (e) { /* captura falha em poucos browsers; ouvintes no document bastam */ }
    });

    document.addEventListener('pointermove', function (event) {
        if (!arrasto_menu) {
            return;
        }
        const dx = event.clientX - arrasto_menu.inicioX;
        const dy = event.clientY - arrasto_menu.inicioY;
        if (!arrasto_menu.definido) {
            // Só vira gesto depois de cruzar o limiar; arrasto vertical (scroll
            // do corpo do drawer) é ignorado.
            if (Math.abs(dx) < 8 && Math.abs(dy) < 8) {
                return;
            }
            if (Math.abs(dy) > Math.abs(dx)) {
                reverter_abertura_menu();
                limpar_arrasto_menu();
                return;
            }
            arrasto_menu.definido = true;
        }
        arrasto_menu.dx = dx;
        if (arrasto_menu.abrindo) {
            // Só entra (dx negativo): acompanha o dedo, limitado à largura.
            const deslocar = Math.min(0, Math.max(-menu_drawer.offsetWidth, dx));
            menu_drawer.style.transform = 'translateX(' + deslocar + 'px)';
        } else {
            // Fechando: segue o dedo para a esquerda, nunca passa do 0.
            const deslocar = Math.min(0, dx);
            menu_drawer.style.transform = 'translateX(' + deslocar + 'px)';
        }
    });

    document.addEventListener('pointerup', function () {
        if (!arrasto_menu) {
            return;
        }
        const limiar = Math.round(menu_drawer.offsetWidth * 0.25);
        if (arrasto_menu.abrindo) {
            if (arrasto_menu.dx < -limiar) {
                menu_drawer.setAttribute('aria-hidden', 'false');
                const fechar = document.getElementById('botao_fechar_menu');
                if (fechar) {
                    fechar.focus();
                }
            } else {
                fechar_menu();
            }
        } else if (arrasto_menu.dx < -limiar) {
            fechar_menu();
        }
        limpar_arrasto_menu();
    });
    document.addEventListener('pointercancel', function () {
        reverter_abertura_menu();
        limpar_arrasto_menu();
    });
}

// Liga os botões do drawer às funções existentes.
const menu_tutorial = document.getElementById('menu_tutorial');
if (menu_tutorial) {
    menu_tutorial.addEventListener('click', function () {
        fechar_menu();
        abrir_tutorial();
    });
}
const menu_dicas_switch = document.getElementById('menu_dicas_switch');
if (menu_dicas_switch) {
    menu_dicas_switch.addEventListener('change', function () {
        definir_dicas(this.checked);
    });
}
const menu_narrador = document.getElementById('menu_narrador');
if (menu_narrador) {
    menu_narrador.addEventListener('click', function () {
        alternar_narrador();
        fechar_menu();
    });
}

// ---------------------------------------------------------------------------
// Menu de sala: drawer lateral esquerdo (Configurações + Jogadores IA).
// Abre pelo ⚙️ do card Jogadores e deixa a lista visível ao lado; fecha no ✖,
// Esc, clique fora, ao lotar a sala ou ao trocar de página.
// ---------------------------------------------------------------------------
function abrir_config_sala() {
    const drawer = document.getElementById('menu_sala');
    if (!drawer) {
        return;
    }
    drawer.classList.add('aberto');
    drawer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('sala-config-aberta');
}

function fechar_config_sala() {
    const drawer = document.getElementById('menu_sala');
    if (!drawer || !drawer.classList.contains('aberto')) {
        return;
    }
    drawer.classList.remove('aberto');
    drawer.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('sala-config-aberta');
}

// Clique fora do drawer (e fora do botão que o abre) fecha o menu de sala, sem
// bloquear a lista de jogadores que fica visível atrás.
document.addEventListener('click', function (evento) {
    const drawer = document.getElementById('menu_sala');
    if (!drawer || !drawer.classList.contains('aberto') || !evento.target || typeof evento.target.closest !== 'function') {
        return;
    }
    if (drawer.contains(evento.target)) {
        return;
    }
    const botao = document.getElementById('bot_abrir_config');
    if (botao && botao.contains(evento.target)) {
        return;
    }
    fechar_config_sala();
});

// Dropdown desktop de som + idioma: abre pelo ⚙️ do topo direito, fecha em
// clique fora, Esc ou novo clique no próprio ⚙️. Só existe no desktop (o ☰
// do mobile tem os mesmos controles no drawer).
const botao_config_desktop = document.getElementById('botao_config_desktop');
const dropdown_config_desktop = document.getElementById('dropdown_config_desktop');

function abrir_config_desktop() {
    if (!dropdown_config_desktop) {
        return;
    }
    dropdown_config_desktop.parentElement.classList.add('aberto');
    dropdown_config_desktop.setAttribute('aria-hidden', 'false');
}

function fechar_config_desktop() {
    if (!dropdown_config_desktop) {
        return;
    }
    dropdown_config_desktop.parentElement.classList.remove('aberto');
    dropdown_config_desktop.setAttribute('aria-hidden', 'true');
}

if (botao_config_desktop && dropdown_config_desktop) {
    botao_config_desktop.addEventListener('click', function (evento) {
        evento.stopPropagation();
        const aberto = dropdown_config_desktop.parentElement.classList.contains('aberto');
        if (aberto) {
            fechar_config_desktop();
        } else {
            abrir_config_desktop();
        }
    });

    document.addEventListener('click', function (evento) {
        const wrapper = dropdown_config_desktop.parentElement;
        if (!wrapper.classList.contains('aberto')) {
            return;
        }
        if (!evento.target || typeof evento.target.closest !== 'function') {
            return;
        }
        if (wrapper.contains(evento.target)) {
            return;
        }
        fechar_config_desktop();
    });
}

// Facilidade (teclado): Enter confirma a ação do contexto e Esc fecha o que
// estiver aberto (alerta, tutorial, busca, dica, menu de sala). O Enter em um
// input dispara a ação correspondente; em modais, confirma/fecha.
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        fechar_alerta();
        fechar_tutorial();
        fechar_busca();
        fechar_dica();
        fechar_config_sala();
        fechar_config_desktop();
        return;
    }
    if (event.key !== 'Enter') {
        return;
    }
    if (_alerta_ativo) {
        // F4: só o alerta de "Ok" (aviso/erro/info/sucesso) confirma com Enter.
        // No alerta de confirmação o Enter ativa o botão em foco (o padrão é o
        // Cancelar → false) em vez de forçar `true`; Escape resolve false.
        if (_alerta_ativo.tipo !== 'confirmar') {
            fechar_alerta(true);
        }
        return;
    }
    if (overlay_tutorial && overlay_tutorial.style.display === 'flex') {
        fechar_tutorial();
        return;
    }
    const alvo = event.target;
    if (alvo && (alvo.tagName === 'INPUT' || alvo.tagName === 'SELECT')) {
        const acoes = {
            apelido: enviar_apelido,
            config_nome: enviar_config,
            filtro_busca: buscar_partidas,
            quantidade: apostar,
        };
        const acao = acoes[alvo.id];
        if (acao) {
            event.preventDefault();
            acao();
        }
    }
});

aplicar_estado_dicas();

// Aplica o volume escolhido a todos os efeitos já carregados.
function aplicar_volume_som() {
    const ganho = volume_som / 100;
    Object.values(sons).forEach((audio) => {
        audio.volume = ganho;
    });
}

// Toca um efeito sonoro do jogo a partir de static/sons/. Os arquivos são
// carregados sob demanda e reutilizados (cache em 'sons'). `ganho_relativo`
// (padrão 1) é um multiplicador sobre o volume escolhido pelo jogador: o bip
// de tempo usa isso para subir de intensidade conforme o relógio aperta, sem
// sair da preferência de volume.
function tocar_som(nome, ganho_relativo) {
    if (!som_ativado || reconstruindo_snapshot) {
        return;
    }
    const arquivo = sons_disponiveis[nome];
    if (!arquivo) {
        return;
    }
    if (!sons[nome]) {
        sons[nome] = new Audio(`../static/sons/${arquivo}`);
        sons[nome].load();
    }
    const audio = sons[nome];
    const ganho = ganho_relativo === undefined ? 1 : ganho_relativo;
    audio.volume = Math.min(1, (volume_som / 100) * ganho);
    audio.currentTime = 0;
    audio.play().catch(() => {});
}

// Toca uma das variantes de um som (ex.: pegar_dados_1 / pegar_dados_2).
function tocar_som_variante(base, variantes) {
    const escolha = variantes[Math.floor(Math.random() * variantes.length)];
    tocar_som(`${base}_${escolha}`);
}

// Fanfarra de vitória sintetizada (Web Audio), sem depender de arquivo externo.
function tocar_fanfarra() {
    if (!som_ativado || reconstruindo_snapshot || !garantir_contexto_audio()) {
        return;
    }
    const agora = contexto_audio.currentTime;
    const notas = [523.25, 659.25, 783.99, 1046.5];
    const ganho_relativo = volume_som / 100;
    notas.forEach((freq, i) => {
        const osc = contexto_audio.createOscillator();
        const ganho = contexto_audio.createGain();
        osc.type = 'triangle';
        osc.frequency.value = freq;
        const inicio = agora + i * 0.14;
        ganho.gain.setValueAtTime(0.0001, inicio);
        ganho.gain.exponentialRampToValueAtTime(0.22 * ganho_relativo, inicio + 0.03);
        ganho.gain.exponentialRampToValueAtTime(0.0001, inicio + 0.55);
        osc.connect(ganho).connect(contexto_audio.destination);
        osc.start(inicio);
        osc.stop(inicio + 0.6);
    });
}

// Estouro/chiado dos fogos, sintetizado (ruído filtrado com decaimento).
function tocar_estouro() {
    if (!som_ativado || !garantir_contexto_audio()) {
        return;
    }
    const agora = contexto_audio.currentTime;
    const tamanho = Math.floor(contexto_audio.sampleRate * 0.28);
    const buffer = contexto_audio.createBuffer(1, tamanho, contexto_audio.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < tamanho; i++) {
        data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / tamanho, 2.5);
    }
    const fonte = contexto_audio.createBufferSource();
    fonte.buffer = buffer;
    const filtro = contexto_audio.createBiquadFilter();
    filtro.type = 'lowpass';
    filtro.frequency.value = 2000;
    const ganho = contexto_audio.createGain();
    ganho.gain.value = 0.22 * (volume_som / 100);
    fonte.connect(filtro).connect(ganho).connect(contexto_audio.destination);
    fonte.start(agora);
}

// ---------------------------------------------------------------------------
// Música de fundo oficial: tema orquestral/ambiental em MIDI (rota /tema.mid,
// que troca a composição a cada 12h — ver tema.py). O navegador não toca MIDI
// nativamente, então o arquivo é lido, interpretado e sintetizado via Web Audio
// em loop: cada programa General MIDI vira um timbre aproximado (cordas, coro,
// flautas, sinos, harpa, baixo acústico), com reverb de sala e largura estéreo.
// A composição é original, inspirada no clima animado e orquestral de Donkey
// Kong Country.
// O som da música é controlado por um botão próprio, independente dos efeitos.
// ---------------------------------------------------------------------------
const musica_salva = localStorage.getItem('dadinho_musica');
let musica_ativada = musica_salva === null ? PADROES_CLIENTE.musica_ativada : musica_salva === 'on';

// Volume da música (0 a 100), persistido entre sessões. Padrão: 40.
// Fase 33 (M1): o slider do drawer é sincronizado em `ao_mudar_volume_musica`
// (logo abaixo de `alternar_musica`), então o wiring fica concentrado ali.
let volume_musica = Number(localStorage.getItem('dadinho_volume_musica') || PADROES_CLIENTE.volume_musica);

// Lê um inteiro em 'variable-length quantity' do MIDI.
function ler_varint(view, estado) {
    let valor = 0;
    while (true) {
        const byte = view.getUint8(estado.pos++);
        valor = (valor << 7) | (byte & 0x7f);
        if (!(byte & 0x80)) {
            return valor;
        }
    }
}

function ler_texto(view, pos, tamanho) {
    let texto = '';
    for (let i = 0; i < tamanho; i++) {
        texto += String.fromCharCode(view.getUint8(pos + i));
    }
    return texto;
}

// Converte um tick (pulsos) em segundos, respeitando a mapa de andamento.
function tick_para_segundos(tick, tempos, ppq) {
    let total = 0;
    let tick_base = 0;
    let us_por_batida = tempos[0].us;
    for (let i = 0; i < tempos.length; i++) {
        const ponto = tempos[i];
        if (ponto.tick >= tick) {
            break;
        }
        total += ((ponto.tick - tick_base) / ppq) * (us_por_batida / 1e6);
        tick_base = ponto.tick;
        us_por_batida = ponto.us;
    }
    total += ((tick - tick_base) / ppq) * (us_por_batida / 1e6);
    return total;
}

// Interpreta um arquivo MIDI (formatos 0 e 1) e devolve as notas em segundos.
function parsear_midi(buffer) {
    const view = new DataView(buffer);
    if (buffer.byteLength < 14 || ler_texto(view, 0, 4) !== 'MThd') {
        throw new Error('Arquivo MIDI inválido');
    }
    const tamanho_cabecalho = view.getUint32(4);
    const total_trilhas = view.getUint16(10);
    const ppq = view.getUint16(12) || 480;
    const estado = { pos: 8 + tamanho_cabecalho };
    const eventos = [];
    const tempos = [{ tick: 0, us: 500000 }];

    for (let t = 0; t < total_trilhas && estado.pos + 8 <= buffer.byteLength; t++) {
        if (ler_texto(view, estado.pos, 4) !== 'MTrk') {
            break;
        }
        const tamanho = view.getUint32(estado.pos + 4);
        estado.pos += 8;
        const fim = estado.pos + tamanho;
        let tick = 0;
        let status = 0;
        while (estado.pos < fim) {
            tick += ler_varint(view, estado);
            let byte = view.getUint8(estado.pos);
            if (byte & 0x80) {
                if (byte >= 0x80 && byte <= 0xef) {
                    status = byte;
                }
                estado.pos++;
            } else {
                byte = status; // running status
            }
            if (byte === 0xff) {
                const tipo = view.getUint8(estado.pos++);
                const len = ler_varint(view, estado);
                if (tipo === 0x51 && len === 3) {
                    const us = (view.getUint8(estado.pos) << 16) |
                        (view.getUint8(estado.pos + 1) << 8) |
                        view.getUint8(estado.pos + 2);
                    tempos.push({ tick: tick, us: us });
                }
                estado.pos += len;
            } else if (byte === 0xf0 || byte === 0xf7) {
                estado.pos += ler_varint(view, estado);
            } else if (byte >= 0x80 && byte <= 0xef) {
                const tipo = byte & 0xf0;
                const canal = byte & 0x0f;
                if (tipo === 0x90 || tipo === 0x80) {
                    const altura = view.getUint8(estado.pos++);
                    const velocidade = view.getUint8(estado.pos++);
                    eventos.push({
                        tick: tick, canal: canal, altura: altura, velocidade: velocidade,
                        liga: tipo === 0x90 && velocidade > 0
                    });
                } else if (tipo === 0xc0) {
                    eventos.push({ tick: tick, canal: canal, programa: view.getUint8(estado.pos++) });
                } else if (tipo === 0xd0) {
                    estado.pos += 1;
                } else {
                    estado.pos += 2;
                }
            } else {
                break; // evento desconhecido: evita laço infinito
            }
        }
        estado.pos = fim;
    }

    tempos.sort(function (a, b) { return a.tick - b.tick; });
    const pendentes = new Map();
    const programas = new Map();
    const notas = [];
    let fim_tick = 0;

    eventos.forEach(function (ev) {
        if (ev.programa !== undefined) {
            programas.set(ev.canal, ev.programa);
            return;
        }
        const chave = ev.canal + ':' + ev.altura;
        if (ev.liga) {
            if (!pendentes.has(chave)) {
                pendentes.set(chave, []);
            }
            pendentes.get(chave).push({
                tick: ev.tick, velocidade: ev.velocidade,
                programa: programas.has(ev.canal) ? programas.get(ev.canal) : 0
            });
        } else {
            const pilha = pendentes.get(chave);
            if (pilha && pilha.length) {
                const inicio = pilha.shift();
                const inicio_s = tick_para_segundos(inicio.tick, tempos, ppq);
                notas.push({
                    inicio: inicio_s,
                    dur: Math.max(0.03, tick_para_segundos(ev.tick, tempos, ppq) - inicio_s),
                    altura: ev.altura,
                    velocidade: inicio.velocidade,
                    canal: ev.canal,
                    programa: inicio.programa
                });
                fim_tick = Math.max(fim_tick, ev.tick);
            }
        }
    });

    // Ordena por início: o sequenciador em tempo real percorre a lista com um
    // índice só (notas passadas nunca voltam), o que só vale se `inicio` for
    // crescente. A ordem original é a de note-off. O sort é estável, então notas
    // simultâneas mantêm a ordem de encerramento (não muda o que se ouve).
    notas.sort(function (a, b) { return a.inicio - b.inicio; });
    return { notas: notas, duracao: tick_para_segundos(fim_tick, tempos, ppq) };
}

// Perfil de timbre orquestral (aproximação no Web Audio) a partir do programa
// General MIDI. Traz as ondas, o envelope, o ganho, o filtro, o vibrato, o
// envio de reverb e o "coro" de osciladores levemente desafinados.
function perfil_do_programa(programa) {
    // Percussão cromática (celesta/vibrafone/marimba/xilofone/campanas).
    if (programa >= 8 && programa <= 15) {
        return { ondas: ['sine', 'triangle'], ataque: 0.006, decaimento: 1.1,
                 sustain: 0.12, liberacao: 0.6, detune: 7, ganho: 0.14,
                 corte: 6500, vibrato: 0, envio_reverb: 1.1, percussivo: true };
    }
    if (programa === 46) { // harpa
        return { ondas: ['triangle', 'sine'], ataque: 0.004, decaimento: 1.4,
                 sustain: 0.08, liberacao: 0.7, detune: 5, ganho: 0.13,
                 corte: 7000, vibrato: 0, envio_reverb: 1.2, percussivo: true };
    }
    if (programa <= 7) { // piano e teclas
        return { ondas: ['triangle', 'sine'], ataque: 0.004, decaimento: 1.0,
                 sustain: 0.2, liberacao: 0.5, detune: 2, ganho: 0.15,
                 corte: 5200, vibrato: 0, envio_reverb: 0.9, percussivo: true };
    }
    if (programa >= 32 && programa <= 39) { // baixos
        return { ondas: ['triangle', 'sine'], ataque: 0.02, decaimento: 0.5,
                 sustain: 0.7, liberacao: 0.35, detune: 0, ganho: 0.3,
                 corte: 850, vibrato: 0, envio_reverb: 0.4 };
    }
    if (programa === 43) { // contrabaixo orquestral
        return { ondas: ['triangle'], ataque: 0.03, decaimento: 0.6,
                 sustain: 0.7, liberacao: 0.4, detune: 0, ganho: 0.34,
                 corte: 650, vibrato: 0, envio_reverb: 0.5 };
    }
    // Cordas, ensembles, coro e pads: ataque macio e cauda presente.
    if ((programa >= 40 && programa <= 55) || (programa >= 88 && programa <= 95)) {
        return { ondas: ['sawtooth', 'sawtooth'], ataque: 0.35, decaimento: 0.4,
                 sustain: 0.8, liberacao: 1.1, detune: 11, ganho: 0.09,
                 corte: 2400, vibrato: 0.12, envio_reverb: 1.3 };
    }
    // Metais e trompa.
    if (programa >= 56 && programa <= 63) {
        return { ondas: ['sawtooth', 'triangle'], ataque: 0.14, decaimento: 0.3,
                 sustain: 0.8, liberacao: 0.6, detune: 6, ganho: 0.1,
                 corte: 1700, vibrato: 0.08, envio_reverb: 1.1 };
    }
    // Sopros (madeiras e flautas): vibrato suave, sopro macio.
    if (programa >= 64 && programa <= 79) {
        return { ondas: ['sine', 'triangle'], ataque: 0.09, decaimento: 0.25,
                 sustain: 0.82, liberacao: 0.45, detune: 3, ganho: 0.12,
                 corte: 3600, vibrato: 0.35, envio_reverb: 1.0 };
    }
    // Fallback: synth lead simples.
    return { ondas: ['square'], ataque: 0.03, decaimento: 0.3, sustain: 0.7,
             liberacao: 0.4, detune: 0, ganho: 0.07, corte: 3000, vibrato: 0.15,
             envio_reverb: 1.0 };
}

// Panorâmica fixa por canal dá largura orquestral sem precisar de CC no MIDI.
// (0 = melodia, 1 = sinos, 2 = colchão, 3 = baixo, 4 = contracanto.)
function pan_do_canal(canal) {
    if (canal === 1) {
        return 0.28;
    }
    if (canal === 2) {
        return -0.18;
    }
    if (canal === 4) {
        return -0.32;
    }
    return 0.0;
}

// Resposta ao impulso sintética para o reverb de sala (sem samples externos).
function criar_impulso_reverb(ctx, segundos, decaimento) {
    const tamanho = Math.floor(ctx.sampleRate * segundos);
    const buffer = ctx.createBuffer(2, tamanho, ctx.sampleRate);
    for (let canal = 0; canal < 2; canal++) {
        const dados = buffer.getChannelData(canal);
        for (let i = 0; i < tamanho; i++) {
            dados[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / tamanho, decaimento);
        }
    }
    return buffer;
}

function criar_buffer_ruido(ctx, segundos) {
    const tamanho = Math.floor(ctx.sampleRate * segundos);
    const buffer = ctx.createBuffer(1, tamanho, ctx.sampleRate);
    const dados = buffer.getChannelData(0);
    for (let i = 0; i < tamanho; i++) {
        dados[i] = Math.random() * 2 - 1;
    }
    return buffer;
}

// Desliga uma voz: desconecta todos os nós que ela criou. No motor antigo
// (render offline) isso não importava porque o grafo inteiro era descartado a
// cada tema; em tempo real as vozes se acumulariam a cada volta (2.7k gains
// por ciclo) e o `parar_musica` precisa cortar o som imediatamente.
function desligar_voz(nos) {
    return function () {
        for (let i = 0; i < nos.length; i++) {
            try {
                nos[i].disconnect();
            } catch (erro) {
                // já desconectado
            }
        }
    };
}

// Ancora o fim da voz: para todas as fontes em `fim` e, quando a primeira
// delas termina, tira os nós do grafo. Sem isso as vozes se acumulariam a cada
// volta do tema (2.7k gains por ciclo) e o `parar_musica` não cortaria o som.
function agendar_voz(fontes, fim, nos) {
    const desligar = desligar_voz(nos);
    let primeira = null;
    for (let i = 0; i < fontes.length; i++) {
        const fonte = fontes[i];
        if (!primeira) {
            primeira = fonte;
            fonte.onended = function () {
                desligar();
                vozes_musica.delete(desligar);
            };
        }
        try {
            fonte.stop(fim);
        } catch (erro) {
            // fonte já parada
        }
    }
    vozes_musica.add(desligar);
    return desligar;
}

// Percussão animada (tímpano/tom e bongôs/congas senoidais; caixa/chimbais com ruído).
function agendar_percussao(ctx, seco, reverb, altura, velocidade, t0, ruido) {
    const vel = Math.max(0.2, velocidade / 127);
    const envio = ctx.createGain();
    envio.gain.value = 0.8;
    envio.connect(reverb);
    if (altura >= 60 && altura <= 68) { // bongôs, congas, timbales e agogôs
        const osc = ctx.createOscillator();
        const ganho = ctx.createGain();
        const metalico = altura >= 67;
        const frequencia = 210 + (altura - 60) * 22;
        osc.type = metalico ? 'triangle' : 'sine';
        osc.frequency.setValueAtTime(frequencia, t0);
        osc.frequency.exponentialRampToValueAtTime(frequencia * 0.62, t0 + 0.14);
        ganho.gain.setValueAtTime(0.26 * vel, t0);
        ganho.gain.exponentialRampToValueAtTime(0.001, t0 + 0.22);
        osc.connect(ganho);
        ganho.connect(seco);
        ganho.connect(envio);
        osc.start(t0);
        return agendar_voz([osc], t0 + 0.26, [envio, osc, ganho]);
    }
    if (altura === 47 || altura === 35 || altura === 36 || altura === 41 || altura === 43) {
        const osc = ctx.createOscillator();
        const ganho = ctx.createGain();
        const grave = altura === 47 || altura === 35 || altura === 36;
        osc.type = 'sine';
        osc.frequency.setValueAtTime(grave ? 150 : 110, t0);
        osc.frequency.exponentialRampToValueAtTime(grave ? 45 : 58, t0 + (grave ? 0.5 : 0.3));
        ganho.gain.setValueAtTime((grave ? 0.38 : 0.28) * vel, t0);
        ganho.gain.exponentialRampToValueAtTime(0.001, t0 + (grave ? 1.1 : 0.6));
        osc.connect(ganho);
        ganho.connect(seco);
        ganho.connect(envio);
        osc.start(t0);
        return agendar_voz([osc], t0 + (grave ? 1.2 : 0.7), [envio, osc, ganho]);
    }
    const fonte = ctx.createBufferSource();
    fonte.buffer = ruido;
    const filtro = ctx.createBiquadFilter();
    const ganho = ctx.createGain();
    let duracao = 0.06;
    if (altura === 38 || altura === 40) { // caixa
        filtro.type = 'bandpass';
        filtro.frequency.value = 1800;
        filtro.Q.value = 0.9;
        ganho.gain.setValueAtTime(0.24 * vel, t0);
        duracao = 0.16;
    } else if (altura === 46 || altura === 44) { // chimbal aberto
        filtro.type = 'highpass';
        filtro.frequency.value = 6000;
        ganho.gain.setValueAtTime(0.12 * vel, t0);
        duracao = 0.26;
    } else if (altura === 49 || altura === 51 || altura === 57) { // prato
        filtro.type = 'highpass';
        filtro.frequency.value = 4000;
        ganho.gain.setValueAtTime(0.16 * vel, t0);
        duracao = 0.9;
    } else { // chimbal fechado
        filtro.type = 'highpass';
        filtro.frequency.value = 7000;
        ganho.gain.setValueAtTime(0.1 * vel, t0);
        duracao = 0.06;
    }
    ganho.gain.exponentialRampToValueAtTime(0.001, t0 + duracao);
    fonte.connect(filtro).connect(ganho);
    ganho.connect(seco);
    ganho.connect(envio);
    fonte.start(t0);
    return agendar_voz([fonte], t0 + duracao + 0.02, [envio, fonte, filtro, ganho]);
}

function agendar_nota(ctx, seco, reverb, nota_midi, ruido, quando) {
    const t0 = quando;
    const dur = nota_midi.dur;
    const t1 = t0 + dur;
    if (nota_midi.canal === 9) {
        return agendar_percussao(ctx, seco, reverb, nota_midi.altura, nota_midi.velocidade, t0, ruido);
    }
    const perfil = perfil_do_programa(nota_midi.programa);
    const ataque = Math.min(perfil.ataque, Math.max(0.01, dur * 0.6));
    const pico = Math.max(0.0002, perfil.ganho * (nota_midi.velocidade / 127));

    const filtro = ctx.createBiquadFilter();
    filtro.type = 'lowpass';
    filtro.frequency.value = perfil.corte;
    filtro.Q.value = 0.7;

    const ganho = ctx.createGain();
    let parada;
    if (perfil.percussivo) {
        const fim = Math.max(t1, t0 + perfil.decaimento);
        ganho.gain.setValueAtTime(0.0001, t0);
        ganho.gain.exponentialRampToValueAtTime(pico, t0 + ataque);
        ganho.gain.exponentialRampToValueAtTime(0.0001, fim);
        parada = fim + 0.05;
    } else {
        const inicio_liberacao = Math.max(t0 + ataque + 0.01, t1 - perfil.liberacao);
        ganho.gain.setValueAtTime(0.0001, t0);
        ganho.gain.exponentialRampToValueAtTime(pico, t0 + ataque);
        ganho.gain.setValueAtTime(pico, inicio_liberacao);
        ganho.gain.exponentialRampToValueAtTime(0.0001, t1);
        parada = t1 + 0.05;
    }

    const mistura = ctx.createGain();
    mistura.gain.value = 1 / perfil.ondas.length;
    mistura.connect(filtro);
    const frequencia = 440 * Math.pow(2, (nota_midi.altura - 69) / 12);
    let lfo = null;
    let lfo_ganho = null;
    if (perfil.vibrato > 0) {
        lfo = ctx.createOscillator();
        lfo.frequency.value = 5.2;
        lfo_ganho = ctx.createGain();
        lfo_ganho.gain.value = perfil.vibrato * 6;
        lfo.connect(lfo_ganho);
    }
    const nos = [filtro, ganho, mistura];
    const fontes = [];
    perfil.ondas.forEach(function (onda, indice) {
        const osc = ctx.createOscillator();
        osc.type = onda;
        osc.frequency.value = frequencia;
        if (perfil.detune) {
            osc.detune.value = indice === 0 ? -perfil.detune : perfil.detune;
        }
        if (lfo_ganho) {
            lfo_ganho.connect(osc.detune);
        }
        osc.connect(mistura);
        osc.start(t0);
        fontes.push(osc);
    });
    if (lfo) {
        lfo.start(t0);
        fontes.push(lfo);
    }
    // Tudo que a voz criou entra em `nos`, senão sobra GainNode vivo a cada
    // nota com vibrato (o gain do LFO é o esquecido clássico).
    nos.push.apply(nos, fontes);
    if (lfo_ganho) {
        nos.push(lfo_ganho);
    }
    filtro.connect(ganho);

    let saida = ganho;
    if (ctx.createStereoPanner) {
        const pan = ctx.createStereoPanner();
        pan.pan.value = pan_do_canal(nota_midi.canal);
        ganho.connect(pan);
        saida = pan;
        nos.push(pan);
    }
    saida.connect(seco);
    if (perfil.envio_reverb > 0) {
        const envio = ctx.createGain();
        envio.gain.value = perfil.envio_reverb;
        saida.connect(envio);
        envio.connect(reverb);
        nos.push(envio);
    }
    return agendar_voz(fontes, parada, nos);
}

// --- Motor de música em tempo real -----------------------------------------
// Antes (Fase 33): o MIDI inteiro era renderizado num `OfflineAudioContext` e
// reproduzido como um `AudioBuffer` em loop. O render dos 48,4s do tema
// consumia ~30s de CPU bloqueante, então a música só começava dezenas de
// segundos depois do clique. Agora o MIDI é só parseado (~ms) e as notas são
// agendadas uma a uma no `AudioContext` vivo, como um sequenciador: o primeiro
// som sai em poucos milissegundos e o custo acompanha as notas que tocam.

const VOLUME_CICLO_MUSICA = 0.85; // ganho da cadeia mestra, igual ao render antigo
const FADE_ENTRADA_MUSICA = 0.06; // some/vem suave no início de cada volta
const FADE_SAIDA_MUSICA = 0.3; // e no fim, para o loop não estalar
const ANTECEDENCIA_MUSICA = 0.6; // até onde à frente as vozes são criadas
const ANTECEDENCIA_OCULTA_MUSICA = 15; // aba oculta: o setInterval é estrangulado
const INTERVALO_BOMBA_MUSICA = 120; // de quanto em quanto tempo a bomba agenda
const TOLERANCIA_NOTA_MUSICA = 0.05; // nota mais atrasada que ainda vale a pena tocar
const TROCA_TEMA_MUSICA = 0.3; // fade para trocar o tema sem estalar

// Monta a cadeia mestra uma vez por contexto: seco -> mestre (fade do loop) ->
// compressor -> ganho (volume) -> destino, com o reverb em paralelo no mestre.
function montar_cadeia_musica() {
    if (cadeia_musica) {
        return cadeia_musica;
    }
    const mestre = contexto_audio.createGain();
    mestre.gain.value = 0.0001;
    const compressor = contexto_audio.createDynamicsCompressor();
    compressor.threshold.value = -18;
    compressor.knee.value = 30;
    compressor.ratio.value = 2.5;
    compressor.attack.value = 0.006;
    compressor.release.value = 0.25;
    const ganho = contexto_audio.createGain();
    ganho.gain.value = volume_musica / 100;
    mestre.connect(compressor);
    compressor.connect(ganho);
    ganho.connect(contexto_audio.destination);

    // Reverb de sala: bus wet alimentado pelo envio de cada timbre.
    const reverb = contexto_audio.createConvolver();
    reverb.buffer = criar_impulso_reverb(contexto_audio, 2.8, 3.0);
    const retorno_reverb = contexto_audio.createGain();
    retorno_reverb.gain.value = 0.32;
    reverb.connect(retorno_reverb);
    retorno_reverb.connect(mestre);
    const seco = contexto_audio.createGain();
    seco.gain.value = 0.85;
    seco.connect(mestre);

    cadeia_musica = {
        mestre: mestre,
        seco: seco,
        reverb: reverb,
        ruido: criar_buffer_ruido(contexto_audio, 1.2)
    };
    ganho_musica = ganho;
    return cadeia_musica;
}

// Ancora um ciclo em `base` (tempo do AudioContext) e programa o fade da
// virada. `imediato` reanora sem esperar o ciclo recomeçar (recuperação de
// atraso): o envelope começa em `currentTime` em vez de `base`, senão a
// rampa nasceria no passado. `saindo` entra com fade em vez de degrau — usado
// na troca de tema, para não cortar o que já estava tocando.
function ancorar_ciclo_musica(base, imediato, saindo) {
    const ganho = cadeia_musica.mestre.gain;
    const agora = contexto_audio.currentTime;
    const inicio = imediato ? agora : Math.max(base, agora + 0.02);
    // O cancelamento é em `inicio + epsilon` de propósito: `inicio` é
    // exatamente onde o fade-out do ciclo anterior termina, e cancelar a partir
    // dele apagaria a rampa (o ganho cairia de 0,85 para 0 num sample, que é o
    // estalo que o fade existe para evitar).
    ganho.cancelScheduledValues(inicio + 0.0005);
    if (saindo) {
        ganho.linearRampToValueAtTime(0.0001, inicio);
    } else {
        ganho.setValueAtTime(0.0001, inicio);
    }
    ganho.exponentialRampToValueAtTime(VOLUME_CICLO_MUSICA, inicio + FADE_ENTRADA_MUSICA);
    const corte = base + tema_musica.duracao - FADE_SAIDA_MUSICA;
    if (corte > inicio + FADE_ENTRADA_MUSICA) {
        ganho.setValueAtTime(VOLUME_CICLO_MUSICA, corte);
        ganho.exponentialRampToValueAtTime(0.0001, base + tema_musica.duracao);
    }
    sequencia_musica = { base: base, indice: 0 };
}

// Sequenciador: agenda as notas do ciclo atual que estão dentro da janela de
// antecedência e, ao fechar o ciclo, ancora o próximo com o fade da virada.
function bombear_musica() {
    if (!musica_rodando || !tema_musica || !cadeia_musica || !contexto_audio_rodando()) {
        return;
    }
    const agora = contexto_audio.currentTime;
    const notas = tema_musica.notas;
    // A janela é sempre finita. Com a aba oculta o `setInterval` é estrangulado
    // (chama no máximo 1x/s e, em aba congelada, para) enquanto a thread de
    // áudio continua: um horizonte maior que isso evita que a música cale, mas
    // um horizonte até o fim do ciclo drenaria a lista inteira a cada disparo e
    // ancoraria ciclos sem parar (milhões de nós). A recuperação de atraso abaixo
    // cobre o que o estrangulamento deixou passar.
    const horizonte = Math.min(
        sequencia_musica.base + tema_musica.duracao,
        agora + (document.hidden ? ANTECEDENCIA_OCULTA_MUSICA : ANTECEDENCIA_MUSICA)
    );
    // Recuperação de atraso: aba em segundo plano, GC longo ou travada do
    // relógio limitam o `setInterval`, mas o áudio (que roda na thread de
    // áudio) segue. Reancorar a linha do tempo é melhor que despejar de uma
    // vez as notas que passaram — senão voltam todas juntas, atrasadas.
    if (agora > sequencia_musica.base + tema_musica.duracao) {
        const atraso = agora - sequencia_musica.base;
        const ciclos = Math.floor(atraso / tema_musica.duracao);
        ancorar_ciclo_musica(sequencia_musica.base + ciclos * tema_musica.duracao, true);
    }
    while (sequencia_musica.indice < notas.length) {
        const nota = notas[sequencia_musica.indice];
        const quando = sequencia_musica.base + nota.inicio;
        if (quando > horizonte) {
            break;
        }
        sequencia_musica.indice++;
        if (quando < agora - TOLERANCIA_NOTA_MUSICA) {
            continue; // já passou: descarta em vez de atrasar a voze
        }
        agendar_nota(
            contexto_audio, cadeia_musica.seco, cadeia_musica.reverb,
            nota, cadeia_musica.ruido, Math.max(quando, agora)
        );
    }
    if (sequencia_musica.indice >= notas.length) {
        ancorar_ciclo_musica(sequencia_musica.base + tema_musica.duracao, false);
    }
}

// Aplica o volume escolhido à música em reprodução (ou guarda para a próxima).
function aplicar_volume_musica() {
    if (ganho_musica) {
        ganho_musica.gain.value = volume_musica / 100;
    }
}

let ganho_musica = null;
let cadeia_musica = null;
let tema_musica = null; // { notas, duracao } do parsear_midi (não é mais AudioBuffer)
let sequencia_musica = { base: 0, indice: 0 };
let vozes_musica = new Set(); // limpezas das vozes vivas (corte imediato ao parar)
let musica_rodando = false;
let relogio_musica = null;
let promessa_musica = null;
let promessa_inicio_musica = null;
let falha_musica_em = 0;
let seed_musica = null;
let relogio_tema = null;

// Não martela /tema.mid a cada clique quando o fetch está falhando: a próxima
// tentativa só sai depois desta janela (o preload não é afetado).
const ESPERA_RECARGA_MUSICA_MS = 15000;

// Lê os segundos de `public, max-age=N` devolvidos pela rota /tema.mid.
function segundos_ate_cache(cc) {
    const parte = /max-age=(\d+)/.exec(cc || '');
    return parte ? Number(parte[1]) : 0;
}

// Agenda o próximo re-check do tema logo após a expiração do Cache-Control
// (a virada da janela de 12h). Sem header, recheca a cada meia hora.
function agendar_verificacao_tema(cc) {
    if (relogio_tema) {
        clearTimeout(relogio_tema);
    }
    const espera = segundos_ate_cache(cc) || 30 * 60;
    relogio_tema = setTimeout(verificar_tema_atual, (espera + 5) * 1000);
}

// Aplica o tema novo em `tema_musica`. Caminho único do preload e do re-check
// da virada de 12h: se a música está tocando, reanora o ciclo com fade (parar e
// reiniciar abriria um estalo no meio da troca); se não está, quem manda é o
// gesto — `iniciar_musica` só liga sozinho com o contexto já rodando.
function aplicar_tema_musica(tema_novo) {
    tema_musica = tema_novo;
    if (musica_rodando && cadeia_musica) {
        ancorar_ciclo_musica(contexto_audio.currentTime + TROCA_TEMA_MUSICA, false, true);
    } else if (musica_ativada && contexto_audio_rodando()) {
        iniciar_musica();
    }
}

// Busca o MIDI vigente, parseia e guarda o seed do tema. A concorrência é
// deduplicada por `promessa_musica`; roda no preload (para o clique ligar a
// música na hora) e no re-check da virada de 12h.
async function carregar_musica() {
    if (promessa_musica) {
        return promessa_musica;
    }
    promessa_musica = (async function () {
        try {
            const resposta = await fetch('/tema.mid');
            if (!resposta.ok) {
                throw new Error('HTTP ' + resposta.status);
            }
            const tema_novo = parsear_midi(await resposta.arrayBuffer());
            if (!tema_novo || !tema_novo.notas.length || tema_novo.duracao <= 0) {
                throw new Error('MIDI vazio');
            }
            falha_musica_em = 0;
            const seed_novo = resposta.headers.get('X-Dadinho-Tema-Seed');
            if (seed_novo) {
                seed_musica = seed_novo;
            }
            agendar_verificacao_tema(resposta.headers.get('Cache-Control') || '');
            // O clique no botão pode ter vindo antes do parse terminar. Como
            // aqui não existe gesto, `aplicar_tema_musica` só inicia sozinho se
            // o contexto já estiver rodando; senão quem começa é o próximo
            // clique/tecla (`desbloquear_audio`), sem novo clique no botão.
            aplicar_tema_musica(tema_novo);
        } catch (erro) {
            console.error('Falha ao carregar a música:', erro);
            falha_musica_em = Date.now();
            agendar_verificacao_tema('');
        }
    })();
    try {
        await promessa_musica;
    } finally {
        promessa_musica = null;
    }
}

// Deduplica por `promessa_inicio_musica`: o botão, o desbloqueio por gesto e o
// fim do preload podem pedir o início ao mesmo tempo, e cada pedido criaria a
// sua própria fonte (música dobrada).
async function iniciar_musica() {
    if (promessa_inicio_musica) {
        return promessa_inicio_musica;
    }
    promessa_inicio_musica = iniciar_musica_agora();
    try {
        await promessa_inicio_musica;
    } finally {
        promessa_inicio_musica = null;
    }
}

async function iniciar_musica_agora() {
    if (!musica_ativada || musica_rodando || !garantir_contexto_audio()) {
        return;
    }
    if (!tema_musica) {
        if (falha_musica_em && (Date.now() - falha_musica_em) < ESPERA_RECARGA_MUSICA_MS) {
            return;
        }
        await carregar_musica();
    }
    if (!tema_musica || !musica_ativada || musica_rodando) {
        return;
    }
    // Só agenda as vozes depois de o contexto estar de fato 'running' — senão
    // o start() cai no contexto suspenso e some (problema intermitente, iOS).
    if (promessa_resume_audio) {
        await esperar_resume_audio();
    }
    if (!musica_ativada || musica_rodando) {
        return;
    }
    if (!contexto_audio_rodando()) {
        // O `resume` não resolveu (foi aberto fora de gesto). Em vez de tocar
        // no vazio, deixa o pedido para o próximo clique/tecla, que reabre o
        // `resume` dentro do gesto (`gesto=true` em `garantir_contexto_audio`).
        return;
    }
    montar_cadeia_musica();
    vozes_musica.clear();
    // 50ms de folga: o primeiro som entra praticamente junto com o clique.
    ancorar_ciclo_musica(contexto_audio.currentTime + 0.05, false);
    musica_rodando = true;
    bombear_musica();
    if (!relogio_musica) {
        relogio_musica = setInterval(bombear_musica, INTERVALO_BOMBA_MUSICA);
    }
}

// Quando o Cache-Control expira, a janela de 12h pode ter virado: revalida o
// tema e, se o seed mudou, troca a composição sem reload.
async function verificar_tema_atual() {
    relogio_tema = null;
    try {
        const resposta = await fetch('/tema.mid');
        if (!resposta.ok) {
            throw new Error('HTTP ' + resposta.status);
        }
        const seed_novo = resposta.headers.get('X-Dadinho-Tema-Seed');
        if (seed_novo && seed_musica && seed_novo !== seed_musica) {
            const tema_novo = parsear_midi(await resposta.arrayBuffer());
            if (tema_novo && tema_novo.notas.length) {
                seed_musica = seed_novo;
                aplicar_tema_musica(tema_novo);
            }
        }
        agendar_verificacao_tema(resposta.headers.get('Cache-Control') || '');
    } catch (erro) {
        console.error('Falha ao verificar o tema:', erro);
        agendar_verificacao_tema('');
    }
}

function parar_musica() {
    if (relogio_musica) {
        clearInterval(relogio_musica);
        relogio_musica = null;
    }
    if (!musica_rodando) {
        return;
    }
    musica_rodando = false;
    // Sem `stop()` collective (o motor agora é nota a nota): cada voz se
    // desconecta na hora, o que corta o som como o `fonte_musica.stop()` fazia.
    vozes_musica.forEach(function (desligar) { desligar(); });
    vozes_musica.clear();
    if (cadeia_musica) {
        // Rede de segurança: corta o mestre em 20ms (e não num degrau) caso
        // alguma voz tenha sobrevivido ao desligamento das vozes.
        const ganho = cadeia_musica.mestre.gain;
        const agora = contexto_audio.currentTime;
        ganho.cancelScheduledValues(agora);
        ganho.linearRampToValueAtTime(0.0001, agora + 0.02);
    }
}

// Botão próprio da música: liga/desliga sem afetar os efeitos sonoros.
// Fase 33 (M1): o drawer do mobile tem o próprio botão de música.
const botao_musica = document.getElementById('botao_musica');
const botao_menu_musica = document.getElementById('menu_botao_musica');

function aplicar_estado_musica() {
    if (botao_musica) {
        botao_musica.textContent = '🎵';
        botao_musica.classList.toggle('btn-outline-light', musica_ativada);
        botao_musica.classList.toggle('btn-outline-secondary', !musica_ativada);
        botao_musica.title = musica_ativada
            ? t('js.musica.on')
            : t('js.musica.off');
    }
    if (botao_menu_musica) {
        botao_menu_musica.textContent = '🎵';
        botao_menu_musica.classList.toggle('btn-outline-light', musica_ativada);
        botao_menu_musica.classList.toggle('btn-outline-secondary', !musica_ativada);
        botao_menu_musica.title = musica_ativada
            ? t('js.musica.on')
            : t('js.musica.off');
    }
}

function alternar_musica() {
    musica_ativada = !musica_ativada;
    aplicar_estado_musica();
    try {
        localStorage.setItem('dadinho_musica', musica_ativada ? 'on' : 'off');
    } catch (erro) {
        // armazenamento indisponível (privado/iframe): o toggle não pode falhar
    }
    if (musica_ativada) {
        iniciar_musica();
    } else {
        parar_musica();
    }
}

if (botao_musica) {
    aplicar_estado_musica();
    botao_musica.addEventListener('click', alternar_musica);
}
if (botao_menu_musica) {
    botao_menu_musica.addEventListener('click', alternar_musica);
}

// Pré-carrega e parseia o tema em segundo plano para o clique ligar a música na
// hora, sem depender do fetch + parse do MIDI no primeiro toque. O AudioContext
// só é criado/retomado no gesto (`garantir_contexto_audio` em `iniciar_musica`).
carregar_musica();

// Volume da música (0 a 100), persistido entre sessões — sliders do topo e do
// drawer (M1) compartilham o mesmo estado.
const slider_volume_musica = document.getElementById('volume_musica');
const slider_menu_volume_musica = document.getElementById('menu_volume_musica');

function sincronizar_sliders_volume_musica() {
    if (slider_volume_musica) {
        slider_volume_musica.value = volume_musica;
    }
    if (slider_menu_volume_musica) {
        slider_menu_volume_musica.value = volume_musica;
    }
}

function ao_mudar_volume_musica(valor) {
    volume_musica = Number(valor) || 0;
    localStorage.setItem('dadinho_volume_musica', String(volume_musica));
    sincronizar_sliders_volume_musica();
    aplicar_volume_musica();
}

if (slider_volume_musica) {
    slider_volume_musica.addEventListener('input', (event) => {
        ao_mudar_volume_musica(event.target.value);
    });
}
if (slider_menu_volume_musica) {
    slider_menu_volume_musica.addEventListener('input', (event) => {
        ao_mudar_volume_musica(event.target.value);
    });
}
// Aplica o volume persistido nos sliders (desktop + drawer) já no load.
sincronizar_sliders_volume_musica();

// A política de autoplay dos navegadores exige um gesto do usuário: a música
// começa no primeiro clique/toque/tecla e segue em loop até ser desligada.
// O listener NÃO é `{once:true}`: ele também é a rede de segurança para o
// pedido de início que ficou pendente (tema ainda baixando/parseando, ou
// `resume` preso fora de gesto — o clique no botão só resolve o que já está
// pronto).
function desbloquear_audio() {
    garantir_contexto_audio(true);
    if (musica_ativada) {
        iniciar_musica();
    }
}
window.addEventListener('pointerdown', desbloquear_audio);
window.addEventListener('keydown', desbloquear_audio);

function jogar_dados() {
    // Fase D: identidade ainda não confirmada (retomada em andamento) — o
    // emit cairia na chave placeholder. Sem tocar em `rolagem_pedida`/botão,
    // pra não travar o re-clique quando a retomada completar.
    if (!chave_confirmada) {
        return;
    }
    // Fase 55: trava o emit no cliente para ESTA rodada — um segundo clique
    // não re-dispara o `jogar_dados` (que parecia rolar de novo). O servidor
    // continua idempotente para o caso de o evento se perder (cooldown/rede);
    // o `construtor_dados` rearma a flag a cada rodada e o watchdog da Fase 72
    // destrava o botão se o resultado não chegar.
    if (rolagem_pedida) {
        return;
    }
    rolagem_pedida = true;
    desativar_botao_dados();
    socket.emit('jogar_dados', { chave: chave_secreta });
    // Fase 72: se o resultado não chegar, devolve o botão para o jogador
    // reenviar — o servidor deduplica e reentrega dados + pill.
    armar_retry_rolagem();
    garantir_contexto_audio();
}

// Desativa o botão "Jogar dados" após a jogada da rodada. O botão é
// recriado (habilitado) pelo `construtor_dados` a cada rodada, então não
// precisa de rearmar aqui — só impedir cliques extras durante a rolagem.
function desativar_botao_dados() {
    const botao = document.getElementById('dadobotao');
    if (botao) {
        botao.disabled = true;
    }
}

// Fase 22: marca visualmente que o jogador já clicou no "Ok" (as fichas de
// status e o próprio botão mostram o confirmado). Sem `disabled`: o servidor
// deduplica pela flag `confirmou_*`, e travar o botão aqui deixaria o jogador
// preso se o evento fosse perdido (cooldown, rede) — ele precisa poder tentar
// de novo. O contador da jogada automática também segue como rede de segurança.
function marcar_ok_clicado(botaoId) {
    const botao = document.getElementById(botaoId);
    if (!botao || botao.dataset.confirmado) {
        return;
    }
    botao.dataset.confirmado = '1';
    botao.textContent = t('js.ok_confirmado');
    botao.classList.remove('btn-primary');
    botao.classList.add('btn-success');
}

// Rearma o botão de "Ok" para a próxima rodada/partida: apaga a marca de
// confirmação e devolve o texto/estilo padrão (o botão tem data-i18n="ui.ok").
function rearmar_ok(botaoId) {
    const botao = document.getElementById(botaoId);
    if (!botao) {
        return;
    }
    delete botao.dataset.confirmado;
    botao.textContent = t('ui.ok');
    botao.classList.remove('btn-success');
    botao.classList.add('btn-primary');
}

function conferencia_final() {
    marcar_ok_clicado('bot_confe_fim');
    socket.emit('conferencia_final', { chave: chave_secreta });
}

function vencedor_final() {
    marcar_ok_clicado('bot_vencedor_fim');
    socket.emit('vencedor_final', { chave: chave_secreta });
}

document.getElementById('comemorar').addEventListener('click', () => {
    socket.emit('foguetear_click', { chave: chave_secreta });
});

// Seleciona os elementos
const inputQuantidade = document.getElementById("quantidade");
const btnIncrease = document.getElementById("increase");
const btnDecrease = document.getElementById("decrease");

// Incrementa o valor (F3: capado no total de dados da mesa, senão o servidor
// rebate com `jogada_invalida`).
btnIncrease.addEventListener("click", () => {
    const currentValue = parseInt(inputQuantidade.value) || 1;
    if (!total_dados_mesa || currentValue < total_dados_mesa) {
        inputQuantidade.value = currentValue + 1;
    }
});

// Decrementa o valor (não permitindo valores menores que o mínimo)
btnDecrease.addEventListener("click", () => {
    const currentValue = parseInt(inputQuantidade.value) || 1;
    if (currentValue > parseInt(inputQuantidade.min)) {
        inputQuantidade.value = currentValue - 1;
    }
});

let selectedImageValue = null; // Para armazenar o valor da imagem selecionada

// F2: a seleção de dado vale só para o turno corrente — limpa a face escolhida
// (`selectedImageValue` e o destaque `.selected`) a cada turno/rodada, senão a
// aposta reutiliza a face do turno anterior quando o jogador não clica de novo.
function limpar_selecao_dado() {
    selectedImageValue = null;
    document.querySelectorAll('.image-button').forEach(btn => {
        btn.classList.remove('selected');
    });
}

// Menor quantidade legal para apostar uma face, espelhando Rodada.explicar_jogada.
function minimo_quantidade(face) {
    const ctx = contexto_min_aposta;
    if (!ctx || !ctx.ultima_aposta) {
        return 1;
    }
    const face_ant = Number(ctx.ultima_aposta.face);
    const qtd_ant = Number(ctx.ultima_aposta.qtd);
    const f = Number(face) || 1;
    if (ctx.com_coringa) {
        if (face_ant === 1) {
            // O coringa acabou de ser apostado.
            if (f === 1) {
                return qtd_ant + 1;
            }
            return Math.max(1, 2 * (Number(ctx.coringa_atual_qtd) || qtd_ant));
        }
        if (f === 1) {
            // Apostar o coringa exige superar o último coringa da mesa.
            return Math.max(1, (Number(ctx.coringa_atual_qtd) || 0) + 1);
        }
        // Face maior com a mesma quantidade; senão, quantidade maior.
        return f > face_ant ? qtd_ant : qtd_ant + 1;
    }
    return f > face_ant ? qtd_ant : qtd_ant + 1;
}

// Menor quantidade legal considerando qualquer face (usada antes da escolha).
function minimo_quantidade_global() {
    if (!contexto_min_aposta || !contexto_min_aposta.ultima_aposta) {
        return 1;
    }
    let minimo = Infinity;
    for (let f = 1; f <= 6; f++) {
        minimo = Math.min(minimo, minimo_quantidade(f));
    }
    return Number.isFinite(minimo) ? minimo : 1;
}

// Atualiza o input de quantidade para o mínimo legal. Com `forcar_valor`,
// substitui o valor atual (usado ao começar a vez); senão, só sobe se estiver
// abaixo do mínimo da face escolhida.
function ajustar_quantidade_minima(forcar_valor) {
    const input = document.getElementById('quantidade');
    if (!input) {
        return;
    }
    const face = selectedImageValue ? Number(selectedImageValue) : null;
    const minimo = face ? minimo_quantidade(face) : minimo_quantidade_global();
    input.min = String(minimo);
    const atual = parseInt(input.value, 10);
    if (forcar_valor || !atual || atual < minimo) {
        input.value = String(minimo);
    }
}

// Adiciona evento para cada imagem
document.querySelectorAll('.image-button').forEach(button => {
    button.addEventListener('click', () => {
        // Desmarca todos os botões
        document.querySelectorAll('.image-button').forEach(btn => {
            btn.classList.remove('selected');
        });
        // Marca o botão clicado
        button.classList.add('selected');
        selectedImageValue = button.getAttribute('data-value');
        ajustar_quantidade_minima(false);
    });
});

// ---------------------------------------------------------------------------
// Fogos de artifício + confetes na comemoração.
// ---------------------------------------------------------------------------
const canvas = document.getElementById('fireworks');
const ctx = canvas.getContext('2d');
let largura_canvas = window.innerWidth;
let altura_canvas = window.innerHeight;

// Mobile tem GPU/CPU limitados: reduzimos resolução e quantidade de partículas.
const eh_celular = window.matchMedia('(max-width: 768px)').matches;

function ajustar_canvas() {
    largura_canvas = window.innerWidth;
    altura_canvas = window.innerHeight;
    // Fase 57: sub-amostragem 0.75x no celular — fogos/confetes não precisam de
    // nitidez e o fill do canvas cai ~44% (o clearRect/viewport é o custo fixo
    // de cada frame). No desktop mantém até 2x.
    const escala = eh_celular ? 0.75 : Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(largura_canvas * escala);
    canvas.height = Math.floor(altura_canvas * escala);
    canvas.style.width = largura_canvas + 'px';
    canvas.style.height = altura_canvas + 'px';
    ctx.setTransform(escala, 0, 0, escala, 0, 0);
}

ajustar_canvas();
window.addEventListener('resize', ajustar_canvas);

let particles = [];
let confetes = [];
let celebrando = false;
let intervalo_fogos = null;

const CORES_FOGOS = ['#ff5733', '#33ff57', '#3357ff', '#f3ff33', '#ff33a8', '#00e5ff', '#ffffff'];

function createFirework(x, y, cor) {
    const base = cor || CORES_FOGOS[Math.floor(Math.random() * CORES_FOGOS.length)];
    // Fase 55 (P7): no celular os fogos ficam mais enxutos (menos partículas e
    // menor velocidade) — a tela de comemoração travava em aparelhos de CPU/GPU
    // limitados com o render de centenas de partículas a 60fps.
    const quantidade = eh_celular ? 22 + Math.floor(Math.random() * 13) : 90 + Math.floor(Math.random() * 70);
    const preenchido = Math.random() < 0.35;
    for (let i = 0; i < quantidade; i++) {
        const angulo = (Math.PI * 2 * i) / quantidade + (Math.random() - 0.5) * 0.25;
        let velocidade = eh_celular ? 1.0 + Math.random() * 2.6 : 1.6 + Math.random() * 4.6;
        if (preenchido) {
            velocidade *= 0.35 + Math.random() * 0.65;
        }
        particles.push({
            x: x,
            y: y,
            px: x,
            py: y,
            vx: Math.cos(angulo) * velocidade,
            vy: Math.sin(angulo) * velocidade,
            vida: 1,
            decaimento: 0.008 + Math.random() * 0.014,
            cor: Math.random() < 0.22 ? '#ffffff' : base,
            tamanho: (eh_celular ? 1.0 : 1.4) + Math.random() * (eh_celular ? 1.2 : 1.8)
        });
    }
}

function criar_confete(no_topo) {
    return {
        x: Math.random() * largura_canvas,
        y: no_topo ? -20 - Math.random() * 60 : Math.random() * altura_canvas,
        vx: (Math.random() - 0.5) * 1.6,
        vy: 1.8 + Math.random() * 3.4,
        w: eh_celular ? 3 + Math.random() * 3 : 6 + Math.random() * 7,
        h: eh_celular ? 5 + Math.random() * 4 : 9 + Math.random() * 10,
        rot: Math.random() * Math.PI * 2,
        vrot: (Math.random() - 0.5) * 0.35,
        cor: CORES_FOGOS[Math.floor(Math.random() * CORES_FOGOS.length)],
        balanco: Math.random() * Math.PI * 2,
        balanco_vel: 0.02 + Math.random() * 0.045
    };
}

function iniciar_celebracao() {
    // Fase P3: no snapshot de reconexão a vitória não recomeça os fogos (o flag
    // `reconstruindo_snapshot` ainda está ativo); o OK do vencedor reenvia o
    // `comemorar` caso queira os fogos manualmente.
    if (reconstruindo_snapshot) {
        return;
    }
    celebrando = true;
    if (confetes.length === 0) {
        // Fase 55 (P7): menos confetes no celular — 70 ~ 35 (cada um paga um
        // save/translate/rotate/fillRect/restore por frame no canvas).
        const quantidade = eh_celular ? 35 : 180;
        for (let i = 0; i < quantidade; i++) {
            confetes.push(criar_confete(true));
        }
    }
    garantir_loop_animacao(); // P1: liga o loop de animação (parado ocioso).
    if (!intervalo_fogos) {
        disparar_fogos(eh_celular ? 1 : 3);
        intervalo_fogos = setInterval(function () {
            if (celebrando) {
                disparar_fogos(eh_celular ? 1 : 2);
            }
        }, eh_celular ? 1800 : 900);
    }
    // Evita fogos/confetes rodando sem parar caso o jogador não clique em Ok.
    clearTimeout(iniciar_celebracao._timer);
    iniciar_celebracao._timer = setTimeout(parar_celebracao, 30000);
}

function parar_celebracao() {
    celebrando = false;
    confetes = [];
    clearTimeout(iniciar_celebracao._timer);
    if (intervalo_fogos) {
        clearInterval(intervalo_fogos);
        intervalo_fogos = null;
    }
}

function disparar_fogos(quantidade) {
    if (eh_celular) {
        quantidade = Math.min(quantidade, 2);
    }
    for (let i = 0; i < quantidade; i++) {
        const x = largura_canvas * (0.15 + Math.random() * 0.7);
        const y = altura_canvas * (0.12 + Math.random() * 0.45);
        createFirework(x, y);
    }
    tocar_estouro();
}

function soltar_fogos() {
    garantir_loop_animacao(); // P1: fogos avulsos também ligam o loop.
    disparar_fogos(2 + Math.floor(Math.random() * 3));
}

function updateParticles() {
    particles.forEach(function (p) {
        p.px = p.x;
        p.py = p.y;
        p.vy += 0.055; // gravidade
        p.vx *= 0.99;
        p.vy *= 0.99;
        p.x += p.vx;
        p.y += p.vy;
        p.vida -= p.decaimento;
    });
    particles = particles.filter(function (p) {
        return p.vida > 0 && p.y < altura_canvas + 40;
    });
}

function drawParticles() {
    ctx.clearRect(0, 0, largura_canvas, altura_canvas);

    // Fogos com rastro (blend aditivo).
    ctx.globalCompositeOperation = 'lighter';
    particles.forEach(function (p) {
        ctx.globalAlpha = Math.max(0, p.vida);
        ctx.strokeStyle = p.cor;
        ctx.lineWidth = p.tamanho;
        ctx.beginPath();
        ctx.moveTo(p.px, p.py);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
    });
    ctx.globalAlpha = 1;

    // Confetes caindo de cima da tela.
    ctx.globalCompositeOperation = 'source-over';
    confetes.forEach(function (c) {
        c.balanco += c.balanco_vel;
        c.x += c.vx + Math.sin(c.balanco) * 0.9;
        c.y += c.vy;
        c.rot += c.vrot;
        if (c.y > altura_canvas + 30) {
            Object.assign(c, criar_confete(true));
        }
        ctx.save();
        ctx.translate(c.x, c.y);
        ctx.rotate(c.rot);
        ctx.fillStyle = c.cor;
        ctx.globalAlpha = 0.95;
        ctx.fillRect(-c.w / 2, -c.h / 2, c.w, c.h);
        ctx.restore();
    });
    ctx.globalAlpha = 1;
}

let _loop_animacao_ativo = false;
// Fase 57: intervalo mínimo entre desenhos — 30fps no celular, 60 no desktop.
const INTV_FRAME = eh_celular ? 33.33 : 16.67;
let _ultimo_frame_ts = 0;

// P1: liga o loop de animação sob demanda. Antes, `animate()` rodava para
// sempre e `drawParticles` fazia `clearRect` do viewport inteiro a cada frame
// mesmo sem partículas/confetes — custo ocioso de CPU no mobile.
function garantir_loop_animacao() {
    if (!_loop_animacao_ativo) {
        _loop_animacao_ativo = true;
        // Fase 57: traz o canvas de volta (ocioso fica display:none no CSS).
        canvas.style.display = 'block';
        requestAnimationFrame(animate);
    }
}

function animate(agora) {
    const ativo = celebrando || particles.length > 0 || confetes.length > 0;
    if (ativo) {
        // Fase 57: trava a 30fps no celular — o rAF pode pedir 60+, e cada
        // frame paga física + fill do canvas. Só desenha quando passa INTV_FRAME;
        // frames pulados não rodam update/draw.
        if (!_ultimo_frame_ts) {
            _ultimo_frame_ts = agora;
        }
        const atraso = agora - _ultimo_frame_ts;
        if (atraso >= INTV_FRAME) {
            _ultimo_frame_ts = agora - (atraso % INTV_FRAME); // sem deriva acumulada
            updateParticles();
            drawParticles();
        }
        requestAnimationFrame(animate);
    } else {
        // Sem festa: para o loop (a próxima celebração o religa).
        _loop_animacao_ativo = false;
        _ultimo_frame_ts = 0;
        ctx.clearRect(0, 0, largura_canvas, altura_canvas);
        // Fase 57: esconde o canvas ocioso (remove a camada de composição).
        canvas.style.display = 'none';
    }
}

// ---------------------------------------------------------------------------
// Verificação de integridade (provably fair) — espelha seed.py no cliente.
// O nonce é gerado aqui (nunca no servidor) e o compromisso é publicado.
// ---------------------------------------------------------------------------
let seed_estado = null;
let nonce_local = null;
let compromisso_local = null;
let seed_commit_enviado = null;
let seed_revelacao_enviada = null;
// Nonces revelados publicamente nesta partida (client_id -> nonce), usados na
// auditoria para não depender do que o servidor diz ter usado na seed.
let revelacoes_publicas = {};

const CHAVE_NONCE = 'dadinho_seed_nonce';
const CHAVE_SEED_CTX = 'dadinho_seed_ctx';

function bytesParaHex(bytes) {
    return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
}

function hexParaBytes(hex) {
    const bytes = new Uint8Array(hex.length / 2);
    for (let i = 0; i < bytes.length; i++) {
        bytes[i] = parseInt(hex.substr(i * 2, 2), 16);
    }
    return bytes;
}

function compararUtf8(a, b) {
    const ea = new TextEncoder().encode(a);
    const eb = new TextEncoder().encode(b);
    const n = Math.min(ea.length, eb.length);
    for (let i = 0; i < n; i++) {
        if (ea[i] !== eb[i]) {
            return ea[i] - eb[i];
        }
    }
    return ea.length - eb.length;
}

async function sha256Hex(texto) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(texto));
    return bytesParaHex(new Uint8Array(digest));
}

async function hmacHex(keyBytes, msg) {
    const key = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(msg));
    return bytesParaHex(new Uint8Array(sig));
}

function gerarNonceHex() {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    return bytesParaHex(bytes);
}

function reset_seed_local() {
    nonce_local = null;
    compromisso_local = null;
    seed_commit_enviado = null;
    seed_revelacao_enviada = null;
    revelacoes_publicas = {};
    sessionStorage.removeItem(CHAVE_NONCE);
    sessionStorage.removeItem(CHAVE_SEED_CTX);
}

// Gera (uma vez por partida) o nonce local e publica o compromisso dele.
async function garantir_compromisso_seed() {
    if (!seed_estado || !crypto.subtle || !chave_secreta) {
        return;
    }
    // O servidor precisa ter comprometido a entropia dele ANTES de aceitar o
    // nonce do jogador; sem compromisso publicado, não compromete.
    if (!seed_estado.compromisso_servidor) {
        return;
    }
    const ctx = `${sala_atual}|${seed_estado.compromisso_servidor}`;
    if (seed_commit_enviado === ctx) {
        return; // já comprometido nesta partida
    }
    if (sessionStorage.getItem(CHAVE_SEED_CTX) !== ctx) {
        reset_seed_local();
    }
    if (!nonce_local) {
        nonce_local = sessionStorage.getItem(CHAVE_NONCE);
    }
    if (!nonce_local) {
        nonce_local = gerarNonceHex();
        sessionStorage.setItem(CHAVE_NONCE, nonce_local);
        sessionStorage.setItem(CHAVE_SEED_CTX, ctx);
    }
    compromisso_local = await sha256Hex('dadinho:v1:commit|' + nonce_local);
    // Fase de compromisso: só o hash vai para o servidor; o nonce fica local
    // até a fase de revelação ('seed_revelar').
    socket.emit('comprometer_seed', { chave: chave_secreta, compromisso: compromisso_local });
    seed_commit_enviado = ctx;
}

socket.on('seed_compromissos', function (data) {
    seed_estado = data;
    garantir_compromisso_seed();
});

// O servidor pediu a revelação (todos já comprometeram): envia o nonce local.
socket.on('seed_revelar', function () {
    if (!seed_estado || !nonce_local || !chave_secreta) {
        return;
    }
    const ctx = `${sala_atual}|${seed_estado.compromisso_servidor}`;
    if (seed_revelacao_enviada === ctx) {
        return; // já revelou nesta partida
    }
    socket.emit('revelar_seed', { chave: chave_secreta, nonce: nonce_local });
    seed_revelacao_enviada = ctx;
});

// Revelação pública de um jogador: guardada para a auditoria recalcular a seed
// com os nonces que realmente foram revelados (e não com o que o servidor diz).
socket.on('seed_revelacao', function (data) {
    if (data && data.client_id) {
        revelacoes_publicas[data.client_id] = data.nonce;
    }
});

// Valor derivado (1-6) de um dado — mesma fórmula do servidor.
async function valorDerivado(seedHex, sala, partida, rodada, clientId, indice) {
    const digestHex = await hmacHex(hexParaBytes(seedHex), `dadinho:v1:roll|${sala}|${partida}|${rodada}|${clientId}|${indice}`);
    return Number(BigInt('0x' + digestHex) % 6n) + 1;
}

// Confere a auditoria inteira sem confiar no servidor.
async function verificar_auditoria(data) {
    const itens = [];
    if (!crypto.subtle) {
        return [[t('js.audit.webcrypto'), false]];
    }
    if (data.compromisso_servidor && data.nonce_servidor) {
        const hSrv = await sha256Hex('dadinho:v1:commit|' + data.nonce_servidor);
        itens.push([t('js.audit.servidor_ok'), hSrv === data.compromisso_servidor]);
    }
    for (const p of (data.participantes || [])) {
        // Prefere o nonce que foi revelado publicamente na partida; se o
        // servidor tiver usado outro valor na seed, a conferência abaixo falha.
        const revelado = revelacoes_publicas[p.client_id];
        const nonce = revelado || (p.sem_reveal ? null : p.nonce);
        if (p.compromisso && nonce) {
            const h = await sha256Hex('dadinho:v1:commit|' + nonce);
            itens.push([t('js.audit.participante', { nome: p.nome || p.client_id }), h === p.compromisso]);
        }
    }
    const nonces = {};
    for (const p of (data.participantes || [])) {
        // Usa a revelação pública quando existir; só cai no fallback do
        // compromisso para quem realmente não revelou.
        if (revelacoes_publicas[p.client_id]) {
            nonces[p.client_id] = revelacoes_publicas[p.client_id];
        } else if (p.nonce) {
            nonces[p.client_id] = p.nonce;
        }
    }
    const ordem = Object.keys(nonces).sort(compararUtf8);
    const partes = [data.fonte, data.entropia_externa, ...ordem.map(c => nonces[c])];
    const seedCalc = await sha256Hex('dadinho:v1:seed|' + partes.join('|'));
    itens.push([t('js.audit.seed_ok'), seedCalc === data.seed_final]);

    if (data.fonte === 'beacon' && data.beacon && data.beacon.round) {
        try {
            const resp = await fetch(`https://api.drand.sh/${data.beacon.chain}/public/${data.beacon.round}`);
            const json = await resp.json();
            const mesmo = String(json.randomness || '').toLowerCase() === String(data.entropia_externa || '').toLowerCase();
            itens.push([t('js.audit.beacon_ok'), mesmo]);
        } catch (e) {
            itens.push([t('js.audit.beacon_erro'), false]);
        }
    }

    let total = 0;
    let iguais = 0;
    for (const rodada of (data.rodadas || [])) {
        const dadosRodada = rodada.dados_por_jogador || {};
        for (const cid of Object.keys(dadosRodada)) {
            const valores = dadosRodada[cid] || [];
            for (let i = 0; i < valores.length; i++) {
                const v = await valorDerivado(data.seed_final, data.sala, data.partida_num, rodada.rodada_num, cid, i);
                total += 1;
                if (v === valores[i]) {
                    iguais += 1;
                }
            }
        }
    }
    itens.push([t('js.audit.dados_ok', { iguais: iguais, total: total }), total > 0 && iguais === total]);

    if (nonce_local) {
        const meu = (data.participantes || []).find(p => p.nonce === nonce_local);
        const publico = Object.values(revelacoes_publicas).includes(nonce_local);
        itens.push([t('js.audit.nonce_ok'), !!meu || publico]);
    }
    return itens;
}

async function render_auditoria(data) {
    const painel = document.getElementById('painel_auditoria');
    const alvo = document.getElementById('auditoria_resultado');
    if (!painel || !alvo) {
        return;
    }
    painel.style.display = 'block';
    alvo.innerHTML = '<div class="spinner-border spinner-border-sm text-info" role="status"></div> ' + t('js.conf.conferindo');
    const itens = await verificar_auditoria(data);
    alvo.innerHTML = '';
    const ul = document.createElement('ul');
    ul.className = 'list-unstyled mb-2 text-start';
    itens.forEach(([texto, ok]) => {
        const li = document.createElement('li');
        li.textContent = `${ok ? '✅' : '❌'} ${texto}`;
        li.className = ok ? 'text-success' : 'text-danger';
        ul.appendChild(li);
    });
    alvo.appendChild(ul);

    const detalhes = document.createElement('details');
    const sumario = document.createElement('summary');
    sumario.textContent = t('js.conf.detalhes');
    detalhes.appendChild(sumario);
    const pre = document.createElement('pre');
    pre.className = 'small text-start';
    pre.style.whiteSpace = 'pre-wrap';
    pre.style.wordBreak = 'break-all';
    pre.textContent = JSON.stringify({
        versao: data.versao,
        fonte: data.fonte,
        seed_final: data.seed_final,
        compromisso_servidor: data.compromisso_servidor,
        nonce_servidor: data.nonce_servidor,
        entropia_externa: data.entropia_externa,
        beacon: data.beacon,
        participantes: data.participantes,
    }, null, 2);
    detalhes.appendChild(pre);
    alvo.appendChild(detalhes);
}

socket.on('auditoria_partida', function (data) {
    render_auditoria(data);
});

// Fase 44 (S5): delegação de cliques — o HTML usa `data-acao` em vez de
// `onclick` inline (que o CSP estrito sem 'unsafe-inline' bloquearia). As ações
// são expostas em `window.Dadinho` (Fase 53); `fechar_alerta` lê o
// `data-resultado`.
document.addEventListener('click', function (evento) {
    if (!evento.target || typeof evento.target.closest !== 'function') return;
    const alvo = evento.target.closest('[data-acao]');
    if (!alvo) return;
    const acao = alvo.dataset.acao;
    if (acao === 'fechar_alerta') {
        fechar_alerta(alvo.dataset.resultado === 'true');
        return;
    }
    // Ações de leitura/UI caem direto; as mutáveis esperam a identidade ser
    // confirmada (senão o servidor rejeita a chave placeholder silenciosamente).
    const acoes_nao_mutaveis = ['abrir_busca', 'fechar_busca', 'buscar_partidas',
        'copiar_link_sala', 'fechar_tutorial', 'fechar_dica', 'criar_sala',
        'abrir_config_sala', 'fechar_config_sala'];
    if (!chave_confirmada && !acoes_nao_mutaveis.includes(acao)) {
        return;
    }
    const funcao = window.Dadinho[acao];
    if (typeof funcao === 'function') funcao();
});

// Fase 53: expõe as ações do `data-acao` sob um único global (nada mais vaza do
// IIFE). Se adicionar um novo `data-acao` em `jogo.html`, exportar a função
// aqui também — senão o clique não faz nada.
window.Dadinho = {
    sair_da_sala, criar_sala, abrir_busca, copiar_link_sala,
    alternar_apelido, alternar_pronto, iniciar_partida,
    adicionar_ia, completar_com_ias, remover_ias,
    buscar_partidas, fechar_busca,
    conferencia_final, vencedor_final,
    fechar_tutorial, fechar_alerta, fechar_dica,
    abrir_config_sala, fechar_config_sala,
};
})();
