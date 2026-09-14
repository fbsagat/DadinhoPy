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

// Imagens dos dados (1-6): constante global reutilizada na animação de rolagem.
const diceImages = [
    "../static/imagens/dado/1.png",
    "../static/imagens/dado/2.png",
    "../static/imagens/dado/3.png",
    "../static/imagens/dado/4.png",
    "../static/imagens/dado/5.png",
    "../static/imagens/dado/6.png"
];

// Envia a chave guardada anteriormente (via sessionStorage) para o servidor
// reconhecer um refresh/reconexão e retomar a identidade (Fase 4).
// Fase D: a chave NÃO vai mais na query string do handshake (vazava em logs de
// acesso). O servidor cria um "placeholder" no connect e a identidade é
// retomada pela primeira mensagem (`retomar_identidade`). `tem_chave` é só um
// sinal booleano não-secreto para o servidor não barrar quem pode estar
// retomando (sala cheia/GC).
// Fase D2: vira `let` para `retomar_negado` adotar a chave do placeholder —
// reincidência (reconnect com sid novo) tenta retomar com a chave certa.
let chave_resumo = sessionStorage.getItem('dadinho_chave') || '';
// WebSocket primeiro: no serverless da Vercel o long-polling quebra (cada
// request de poll pode cair numa instância sem a sessão Engine.IO e o cliente
// entra em loop de reconexão). O polling fica só como fallback de rede.
const socket = io({
    autoConnect: true,
    transports: ['websocket', 'polling'],
    query: { sala: sala_atual, tem_chave: chave_resumo ? '1' : '0' },
});
socket.connect();

// Heartbeat de sala: renova o "visto_em" no servidor para a busca distinguir
// salas vivas das órfãs do serverless (instância que morreu sem disconnect).
// Na sala de espera o intervalo é curto: o servidor usa a batida como re-sync
// do lobby entre instâncias (ver `heartbeat` no app.py) — quem entrou/ficou
// pronto numa instância diferente não alcança o broadcast do host, então o
// servidor devolve o snapshot atual do lobby para cada cliente que bate.
// Só emite quando o socket está conectado e já temos a chave de uma sala.
const INTERVALO_HEARTBEAT_ESPERA = 20000;
const INTERVALO_HEARTBEAT_PARTIDA = 60000;

function agendar_heartbeat() {
    const intervalo = indiceAtual === 0 ? INTERVALO_HEARTBEAT_ESPERA : INTERVALO_HEARTBEAT_PARTIDA;
    setTimeout(function () {
        if (socket.connected && chave_secreta) {
            socket.emit('heartbeat', { chave: chave_secreta, pagina: indiceAtual, vez: vez_atual_nome });
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

function _processar_fila_eventos() {
    if (fila_eventos.length === 0) {
        processando_eventos = false;
        esconder_pensando();
        return;
    }
    const item = fila_eventos.shift();
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
    const ia_nome = (nome === 'narracao' && payload && payload.is_ia) ? (payload.jogador || 'Bot') : null;
    fila_eventos.push({ packet: packet, atraso: atraso, ia_nome: ia_nome });
    if (!processando_eventos) {
        processando_eventos = true;
        _processar_fila_eventos();
    }
};

// Modo de exibição do narrador, persistido entre sessões:
//   completo  -> histórico de falas (padrão)
//   ultima    -> mostra só a última fala
//   desligado -> painel escondido
const NARRADOR_MODOS = {
    completo: { icone: '🎙️', titulo: 'js.narrador.modo.completo', classe: 'btn-outline-info' },
    ultima: { icone: '💬', titulo: 'js.narrador.modo.ultima', classe: 'btn-outline-warning' },
    desligado: { icone: '🔕', titulo: 'js.narrador.modo.desligado', classe: 'btn-outline-secondary' },
};
const NARRADOR_CICLO = ['completo', 'ultima', 'desligado'];
let narrador_modo = localStorage.getItem('dadinho_narrador');
if (!NARRADOR_MODOS[narrador_modo]) {
    narrador_modo = 'completo';
}

function aplicar_estado_narrador() {
    const botao = document.getElementById('botao_narrador');
    const painel = document.getElementById('narrador');
    const cfg = NARRADOR_MODOS[narrador_modo];
    if (botao) {
        botao.textContent = cfg.icone;
        botao.title = t(cfg.titulo);
        Object.keys(NARRADOR_MODOS).forEach(function (chave) {
            botao.classList.remove(NARRADOR_MODOS[chave].classe);
        });
        botao.classList.add(cfg.classe);
    }
    if (painel) {
        painel.style.display = (narrador_modo === 'desligado' || indiceAtual === 0) ? 'none' : 'flex';
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
    const pos = NARRADOR_CICLO.indexOf(narrador_modo);
    narrador_modo = NARRADOR_CICLO[(pos + 1) % NARRADOR_CICLO.length];
    localStorage.setItem('dadinho_narrador', narrador_modo);
    aplicar_estado_narrador();
}

function narrador_linha(texto) {
    if (narrador_modo === 'desligado') {
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

function esconder_pensando() {
    const el = document.getElementById('narrador_pensando');
    if (el) {
        el.style.display = 'none';
    }
}

function limpar_narrador() {
    const log = document.getElementById('narrador_log');
    if (log) {
        log.innerHTML = '';
    }
    esconder_pensando();
}

socket.on('narracao', function (data) {
    esconder_pensando();
    const texto = traduzirSegmentos(data && data.segmentos, data && data.texto);
    if (texto) {
        narrador_linha(texto);
    }
    if (data && data.tipo === 'vitoria') {
        tocar_fanfarra();
    }
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

function criar_sala() {
    // Fase 9: o código é gerado no servidor (charset sem ambíguos + colisão);
    // ao receber 'sala_criada', o cliente navega para a sala criada.
    socket.emit('criar_sala');
}

socket.on('sala_criada', function (data) {
    if (data && data.sala) {
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
    document.getElementById('tela_busca').style.display = 'none';
    document.getElementById('tela_jogadores').style.display = 'block';
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
}

restaurar_filtros_busca();

function entrar_partida(codigo) {
    tocar_som_variante('pegar_dados', [1, 2]);
    ir_para_sala(codigo);
}

socket.on('partidas_listadas', function (data) {
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
    // Sala pedida lotada: em vez de travar no alerta, cria uma sala nova.
    mostrar_alerta(t('msg.sala_cheia'), 'aviso')
        .then(() => criar_sala());
});

socket.on('iniciar_negado', function (data) {
    const motivo = data && data.motivo;
    const texto = (motivo && motivo.chave) ? t(motivo.chave, motivo.params) : (motivo || '');
    mostrar_alerta(t('msg.iniciar_negado', { motivo: texto }), 'aviso');
});

// Facilidade: o apelido é lembrado entre sessões (localStorage) e entre abas
// da mesma sessão (sessionStorage, fallback para sessões antigas).
const apelidoSalvo = localStorage.getItem('dadinho_apelido') || sessionStorage.getItem('dadinho_apelido');
if (apelidoSalvo) {
    const apelidoInput = document.getElementById('apelido');
    if (apelidoInput) {
        apelidoInput.value = apelidoSalvo;
    }
}

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
        const rowDiv = document.createElement("div");
        rowDiv.className = "row border-bottom";

        const jogadoresDiv = document.createElement("div");
        jogadoresDiv.className = "col-md-6 font-weight-bold";
        jogadoresDiv.textContent = t('js.jogadores_conectados');

        const pontuacaoDiv = document.createElement("div");
        pontuacaoDiv.className = "col-md-6 font-weight-bold";
        pontuacaoDiv.textContent = t('js.pontuacao');

        userListItems.appendChild(rowDiv);
        rowDiv.appendChild(jogadoresDiv);
        rowDiv.appendChild(pontuacaoDiv);

        data.users.forEach((user, index) => {
            const headerRow = document.createElement("div");
            headerRow.className = "row border-bottom";

            const userItem = document.createElement("div");
            userItem.className = "col-md-6";

            let master = ''
            if (data.masters[index] === true) {
                master = '🏁'
            }
            const pronto = data.prontos[index] === true ? '✅' : '⏳';
            userItem.textContent = `${user} ${master} ${pronto}`;

            // Fase 19: o master pode expulsar qualquer jogador (humano ou IA),
            // exceto ele mesmo. O client_id vem no payload `ids` (mesmo índice).
            if (sou_master && user !== nome_jogador && data.ids && data.ids[index]) {
                const botao_expulsar = document.createElement("button");
                botao_expulsar.className = "btn btn-sm btn-outline-danger ms-2";
                botao_expulsar.textContent = t('js.expulsar');
                botao_expulsar.title = t('js.expulsar_titulo');
                botao_expulsar.onclick = function () {
                    expulsar_jogador(data.ids[index], user);
                };
                userItem.appendChild(botao_expulsar);
            }

            const pontuacaoDiv = document.createElement("div");
            pontuacaoDiv.className = "col-md-6";
            pontuacaoDiv.id = `pontos_${user}`;
            pontuacaoDiv.textContent = data.pontos[index];

            userListItems.appendChild(headerRow); // Adiciona cada row à lista
            headerRow.appendChild(userItem); // Adiciona cada usuário à headerRow
            headerRow.appendChild(pontuacaoDiv); // Adiciona cada pontuação à lista
        });

        // Botão "Ficar pronto" reflete o estado atual do próprio jogador.
        const bot_pronto = document.getElementById('bot_pronto');
        const meu_indice = data.users.indexOf(nome_jogador);
        const eu_pronto = meu_indice !== -1 && data.prontos[meu_indice] === true;
        if (bot_pronto) {
            bot_pronto.textContent = eu_pronto ? t('js.pronto_desfazer') : t('js.ficar_pronto');
            bot_pronto.disabled = data.status === 'jogando';
        }
        // Apelido editável na espera quantas vezes o jogador quiser, mas travado
        // ao ficar pronto (e destravado ao desfazer o pronto).
        const apelidoInput = document.getElementById('apelido');
        const botaapelido = document.getElementById('botapel');
        const apelido_travado = data.status === 'jogando' || eu_pronto;
        if (apelidoInput) {
            apelidoInput.disabled = apelido_travado;
        }
        if (botaapelido) {
            botaapelido.disabled = apelido_travado;
        }

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
// A configuração padrão espelha `Lobby.config_padrao` (modelos.py). Quando o
// master entra numa sala recém-criada (config ainda é a padrão), a preferência
// salva é aplicada e enviada de uma vez — não precisa reconfigurar toda vez.
const CONFIG_PADRAO_LOCAL = {
    dados_qtd: 1,
    max_jogadores: 6,
    com_coringa: true,
    publica: true,
    substituir_desconectado_por_ia: false,
    ia_nivel_padrao: 2,
    verificacao_ativa: false,
    tempo_max_jogada: 30,
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

socket.on('jogador_substituido_por_ia', function (data) {
    const painel = document.getElementById('motivo_iniciar');
    if (painel && data && data.nome) {
        painel.textContent = t('msg.substituido_ia', { nome: data.nome });
    }
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
    sessionStorage.removeItem('dadinho_chave');
    mostrar_alerta(t('msg.expulso_da_sala'), 'erro').then(function () {
        const url = new URL(window.location.href);
        url.searchParams.delete('sala');
        url.searchParams.delete('chave_secreta');
        window.location.href = url.toString();
    });
});

// Fase 30: botão de "Sair da sala" visível só para quem está assistindo
// (espectador) durante a partida — quem está jogando usa a janela de reconexão.
function atualizar_botao_sair() {
    const botao = document.getElementById('bot_sair_da_sala');
    if (botao) {
        botao.style.display = eh_espectador ? 'block' : 'none';
    }
}

// O espectador escolheu sair: o servidor confirma e voltamos ao menu.
socket.on('saiu_da_sala', function () {
    chave_secreta = '';
    sessionStorage.removeItem('dadinho_chave');
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
    // Fase 21: contador da jogada automática segue o ciclo de páginas.
    // - Entrou na rolagem (1): mantém o contador (a rolagem acabou de ser
    //   armada pelo `construtor_dados`).
    // - Entrou nos turnos (2): se for a minha vez, (re)começa o contador.
    // - Sair de uma tela de jogo: encerra o contador.
    if (data.pag_numero === 2 && sou_da_vez) {
        iniciar_timer_jogada(tempo_turno_max);
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
        // Fase 30: de volta ao lobby (reset/entrada), ninguém é espectador —
        // esconde o botão de sair.
        eh_espectador = false;
        atualizar_botao_sair();
        limpar_narrador();
        parar_celebracao();
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
    aplicar_estado_narrador();
    // Mostra a próxima página
    paginas[indiceAtual].style.display = "block";
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

    // Fase M1: resetar swipe ao voltar para lobby (0) ou partida (2)
    if (data.pag_numero === 0) {
        resetar_swipe_lobby();
    } else if (data.pag_numero === 2) {
        resetar_swipe_status();
    }
});

// ============================================================
// Fase M1: Navegação por swipe horizontal (mobile).
// Dots sincronizados com scroll-snap para lobby e painel de
// status. Desktop mantém layout original (sem swipe).
// ============================================================

let lobby_tab_ativo = 0;
let status_tab_ativo = 0;

// --- Lobby swipe ---
function init_swipe_lobby() {
    const wrapper = document.getElementById('lobby_panels_wrapper');
    const dots = document.querySelectorAll('.lobby-dot');

    if (!wrapper || !dots.length) return;

    dots.forEach((dot) => {
        dot.addEventListener('click', () => {
            const tab = Number(dot.getAttribute('data-tab'));
            lobby_tab_ativo = tab;
            atualizar_dots_lobby();
            wrapper.scrollTo({
                left: tab * wrapper.clientWidth,
                behavior: 'smooth'
            });
        });
    });

    wrapper.addEventListener('scroll', () => {
        const page = Math.round(wrapper.scrollLeft / wrapper.clientWidth);
        if (page !== lobby_tab_ativo) {
            lobby_tab_ativo = page;
            atualizar_dots_lobby();
        }
    });
}

function atualizar_dots_lobby() {
    document.querySelectorAll('.lobby-dot').forEach((dot, i) => {
        dot.classList.toggle('active', i === lobby_tab_ativo);
    });
}

function resetar_swipe_lobby() {
    const wrapper = document.getElementById('lobby_panels_wrapper');
    if (!wrapper) return;
    lobby_tab_ativo = 0;
    wrapper.scrollTo({ left: 0, behavior: 'smooth' });
    atualizar_dots_lobby();
}

// --- Status panels swipe (Tela 2) ---
function init_swipe_status() {
    const wrapper = document.getElementById('status_panels_wrap');
    const dots = document.querySelectorAll('.status-dot');

    if (!wrapper || !dots.length) return;

    dots.forEach((dot) => {
        dot.addEventListener('click', () => {
            const tab = Number(dot.getAttribute('data-dot'));
            status_tab_ativo = tab;
            atualizar_dots_status();
            wrapper.scrollTo({
                left: tab * wrapper.clientWidth,
                behavior: 'smooth'
            });
        });
    });

    wrapper.addEventListener('scroll', () => {
        const page = Math.round(wrapper.scrollLeft / wrapper.clientWidth);
        if (page !== status_tab_ativo) {
            status_tab_ativo = page;
            atualizar_dots_status();
        }
    });
}

function atualizar_dots_status() {
    document.querySelectorAll('.status-dot').forEach((dot, i) => {
        dot.classList.toggle('active', i === status_tab_ativo);
    });
}

function resetar_swipe_status() {
    const wrapper = document.getElementById('status_panels_wrap');
    if (!wrapper) return;
    status_tab_ativo = 0;
    wrapper.scrollTo({ left: 0, behavior: 'smooth' });
    atualizar_dots_status();
}

// Initialize swipe (script is at end of body, so DOM is ready)
init_swipe_lobby();
init_swipe_status();

// Re-evaluate master tab visibility on resize (mobile↔desktop)
window.addEventListener('resize', () => {
    if (typeof aplicar_master === 'function') aplicar_master();
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

// Função para criar cada seção de dados
function createDiceSection(text, opacityClass, imageIndex, destaque = false) {
    const col = document.createElement('div');
    col.className = `col-md-12 mb-1 ${opacityClass}`;

    const diceDiv = document.createElement('div');
    diceDiv.className = 'd-flex align-items-center justify-content-evenly border rounded';
    if (destaque) {
        diceDiv.classList.add('jogada-destaque');
        diceDiv.setAttribute('data-rotulo', t('js.jogada.ultima'));
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

// Função para construir a tela dos dados (1-6 dados em tela_jogar_dados).
socket.on('construtor_dados', function (data) {
    const espectador = data.espectador;
    // Fase 30: quem entra assistindo (vaga perdida/busca) também vê o botão.
    eh_espectador = espectador === true;
    atualizar_botao_sair();
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
        iniciar_timer_jogada(data.tempo_max);
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
        // Criação do container principal
        const divCol = document.createElement('div');
        divCol.className = 'col-md-2 col-sm-4 col-6 mb-1';

        // Criação do card
        const card = document.createElement('div');
        card.className = 'card border border-secondary border-1 text-bg-dark';
        // Fase 32 (P3): altura FIXA no desktop (o corpo rola se o histórico
        // passar de 3 jogadas) — todos os cards ficam do mesmo tamanho.
        card.style.minHeight = '148px';
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

        cardHeader.textContent = `${jogador} (🎲 x ${data.dados_tt})`;
        cardHeader.id = `card_hea_${jogador}`;

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
    }
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
});

// ---------------------------------------------------------------------------
// Jogada automática por tempo máximo (Fase 21).
// O servidor informa o limite (`tempo_max` segundos) em `construtor_dados`
// (rolagem) e `meu_turno` (aposta/desconfiança). O cliente conta regressivo e,
// ao expirar, pede ao servidor para jogar pelo atrasado (`autojogar`) — o
// servidor confere o tempo decorrido antes de agir, então isto é só o gatilho.
// ---------------------------------------------------------------------------
let timer_autojogar = null;
let tempo_autojogar_seg = 0;
let sou_da_vez = false;      // recebeu `meu_turno` (a vez atual é a minha)
let tempo_turno_max = 0;     // limite do turno (vem no `meu_turno`)
// Fase D2: apelido do jogador que o cliente acredita estar NA VEZ (vem de
// `meu_turno`/`espera_turno`/`formatador_coletivo`). Vai no heartbeat para o
// servidor detectar um indicador de vez perdido entre instâncias (refresh) e
// reenviar só o `meu_turno`/`espera_turno` — senão a tela fica sem o menu de
// jogada mesmo com a página correta.
let vez_atual_nome = '';
let tempo_conf_vit = 0;      // limite da conferência/vitória (vem no `cards_conferencia`/`vencedor_da_partida`, Fase 22)

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

function iniciar_timer_jogada(segundos) {
    parar_timer_jogada();
    tempo_autojogar_seg = Math.max(0, Math.floor(Number(segundos) || 0));
    if (tempo_autojogar_seg <= 0) {
        return;
    }
    atualizar_contador_jogada();
    timer_autojogar = setInterval(function () {
        tempo_autojogar_seg -= 1;
        atualizar_contador_jogada();
        if (tempo_autojogar_seg <= 0) {
            parar_timer_jogada();
            socket.emit('autojogar', { chave: chave_secreta });
        }
    }, 1000);
}

function parar_timer_jogada() {
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
    // Fase D2: registro quem o cliente acredita estar na vez (o heartbeat usa
    // isso para pedir um `meu_turno` reenviado se o indicador se perder).
    vez_atual_nome = String(data.username || '');
    if (indiceAtual === 2) {
        iniciar_timer_jogada(tempo_turno_max);
    }

    if (painel_jogada && painel_aguarde) {
        painel_jogada.style.display = "block"; // Mostra o painel de jogada
        painel_aguarde.style.display = "none"; // Oculta painel aguarde
    }

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
    sou_da_vez = false; // Fase 21: não é mais a minha vez, zera o contador.
    parar_timer_jogada();
    // Fase D2: registro quem o cliente acredita estar na vez (o heartbeat usa
    // isso para pedir um `espera_turno` reenviado se o indicador se perder).
    vez_atual_nome = String(data.username || '');
    // F2: fora da vez a seleção antiga não pode vazar para o próximo turno.
    limpar_selecao_dado();
    painel_jogada.style.display = "none"; // Oculta o painel de jogada
    painel_aguarde.style.display = "block"; // Mostra painel aguarde
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
            card.textContent = `${jogador} (🎲 x ${jogadores_dados[index]})`;
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
    tocar_som_variante('aposta', [1, 2]);
    tocar_som('mover_peca');
    const h1_vencedor = document.getElementById('h1_vencedor');
    // Fase E + P5: o template tem <br> (por isso innerHTML); o nome interpolado
    // é escapado dentro de `t()` (`_interpolar` no i18n.js), sem dupla codificação.
    h1_vencedor.innerHTML = t('js.vitoria_texto', { nome: data.nome });
    iniciar_celebracao();
    // Fase 22: contador da jogada automática da tela de vitória (auto-confirma
    // o reset se o jogador ficar away from keyboard).
    tempo_conf_vit = Number(data.tempo_max) || 0;
    iniciar_timer_jogada(tempo_conf_vit);
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
    texto_v_d.innerText = texto_conferencia(data);

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
    // "Ok" se o jogador ficar away from keyboard).
    tempo_conf_vit = Number(data.tempo_max) || 0;
    iniciar_timer_jogada(tempo_conf_vit);
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

})

// Lógica para enviar a aposta (chamada pelo botão e pela tecla Enter).
function apostar() {
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
    // Facilidade: nova conexão, a config salva pode ser reaplicada numa sala nova.
    _config_local_aplicada = false;
    // Fase 18: na home (sem sala) o servidor não devolve chave — mantém a atual
    // para não apagar a identidade de uma sala anterior.
    // Fase D: guarda a chave no sessionStorage só quando não há uma sessão
    // anterior para retomar (senão o placeholder sobrescreveria a identidade).
    if (data && data.chave_secreta) {
        chave_secreta = data.chave_secreta;
        if (!chave_resumo) {
            sessionStorage.setItem('dadinho_chave', chave_secreta);
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
    if (data && data.username) {
        // Reconexão retomada: devolve o apelido pro jogador.
        nome_jogador = data.username;
        const apelidoInput = document.getElementById('apelido');
        if (apelidoInput && !apelidoInput.value) {
            apelidoInput.value = data.username;
        }
    }
    // Fase D: com uma sessão anterior guardada, retoma a identidade logo após
    // o connect (uma vez por conexão). O servidor troca o placeholder pela
    // identidade real e reemite o connect_start + snapshot.
    if (chave_resumo && data && data.sala && !retomar_enviado) {
        retomar_enviado = true;
        socket.emit('retomar_identidade', { chave: chave_resumo });
    }
    const textInput = document.getElementById("apelido");
    const botaapelido = document.getElementById('botapel');
    if (textInput) {
        textInput.disabled = false; // Habilita o input de apelido para todos, incluindo o master
    }
    if (botaapelido) {
        botaapelido.disabled = false;
    }
    aplicar_master();
});

// A chave guardada não pertence a esta sala (ex.: sessão de outra sala, ou a
// identidade expirou): adota o placeholder como identidade nova e persiste a
// chave dele no sessionStorage — senão a chave stale ficaria para sempre.
// Fase D2: `chave_resumo` passa a apontar para a chave do placeholder, para um
// reconnect com sid novo (morte de instância) retomar a identidade correta.
socket.on('retomar_negado', function (data) {
    // Fase 30: o motivo explica por que a retomada falhou (vaga perdida por
    // inatividade nesta sala vs. sessão de outra sala).
    const motivo = (data && data.motivo && data.motivo.chave)
        ? t(data.motivo.chave, data.motivo.params)
        : t('msg.retomar_outra_sala');
    mostrar_alerta(motivo, 'aviso');
    if (chave_secreta) {
        chave_resumo = chave_secreta;
        sessionStorage.setItem('dadinho_chave', chave_secreta);
    }
});

// Indicadores de conexão/reconexão (heartbeat visual).
socket.on('connect', function () {
    const status = document.getElementById('status_conexao');
    if (status) {
        status.textContent = t('js.conectado');
        status.className = 'd-block mb-2 text-success';
    }
    // Fase D2: reconnect com sid novo (morte de instância) ainda tem a chave
    // guardada — o placeholder foi criado com snapshot ADIADO (`tem_chave=1`);
    // rearmar `retomar_enviado` faz o `connect_start` seguinte reemitir a
    // `retomar_identidade` e destravar o snapshot pra este cliente.
    retomar_enviado = false;
});

socket.on('disconnect', function () {
    const status = document.getElementById('status_conexao');
    if (status) {
        status.textContent = t('js.reconectando');
        status.className = 'd-block mb-2 text-warning';
    }
});

socket.on("update_username", function (data) {
    nome_jogador = data.nome_jogador;
})

socket.on("jogar_dados_resultado", function (data) {
    parar_timer_jogada(); // Fase 21: já rolou (manual ou automático), zera o contador.
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

// Função para enviar apelido ao servidor
function enviar_apelido() {
    const textInput = document.getElementById("apelido");
    let apelido = textInput.value.trim();
    if (apelido) {
        localStorage.setItem('dadinho_apelido', apelido); // Lembra entre sessões
        sessionStorage.setItem('dadinho_apelido', apelido); // Mantém entre trocas de sala
        socket.emit('apelido', { apelido_msg: textInput.value });
        // O input não é desativado aqui: o apelido pode ser trocado quantas
        // vezes quiser na espera; o travamento acontece ao ficar pronto.
    } else {
        mostrar_alerta(t('msg.preencha_nome'), 'aviso');
    }
}

function iniciar_partida() {
    tocar_som_variante('embaralhar', [1, 2]);
    const dados_qtd = document.getElementById('config_dados').value;
    socket.emit('iniciar_partida', { chave: chave_secreta, dados_qtd: dados_qtd });
}

let contexto_audio = null;

function garantir_contexto_audio() {
    if (typeof (window.AudioContext) === 'undefined' && typeof (window.webkitAudioContext) === 'undefined') {
        return false;
    }
    if (!contexto_audio) {
        contexto_audio = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (contexto_audio.state === 'suspended') {
        contexto_audio.resume();
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
};
const sons = {};

// Preferência de som do jogador, persistida entre sessões. Valor padrão: ligado.
let som_ativado = localStorage.getItem('dadinho_som') !== 'off';
const botao_som = document.getElementById('botao_som');
if (botao_som) {
    botao_som.textContent = som_ativado ? '🔊' : '🔇';
    botao_som.addEventListener('click', () => {
        som_ativado = !som_ativado;
        localStorage.setItem('dadinho_som', som_ativado ? 'on' : 'off');
        botao_som.textContent = som_ativado ? '🔊' : '🔇';
    });
}

// Volume dos efeitos sonoros (0 a 100), persistido entre sessões.
let volume_som = Number(localStorage.getItem('dadinho_volume_som') || '100');
const slider_volume_som = document.getElementById('volume_som');
if (slider_volume_som) {
    slider_volume_som.value = volume_som;
    slider_volume_som.addEventListener('input', () => {
        volume_som = Number(slider_volume_som.value);
        localStorage.setItem('dadinho_volume_som', String(volume_som));
        aplicar_volume_som();
    });
}

// --- Sistema de ajuda: tutorial + dicas durante a partida ---
// Preferência de dicas do jogador, persistida entre sessões. Valor padrão: ligado.
let dicas_ativadas = localStorage.getItem('dadinho_dicas') !== 'off';

// Dicas contextuais mostradas conforme a página da partida (0 a 4). São chaves
// de tradução; o texto é resolvido no idioma do jogador em mostrar_dica().
const dicas_por_pagina = {
    0: ['js.dica.0.0', 'js.dica.0.1', 'js.dica.0.2', 'js.dica.0.3'],
    1: ['js.dica.1.0', 'js.dica.1.1', 'js.dica.1.2'],
    2: ['js.dica.2.0', 'js.dica.2.1', 'js.dica.2.2', 'js.dica.2.3', 'js.dica.2.4', 'js.dica.2.5', 'js.dica.2.6'],
    3: ['js.dica.3.0', 'js.dica.3.1', 'js.dica.3.2'],
    4: ['js.dica.4.0', 'js.dica.4.1'],
};

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
    if (!botao_dicas) {
        return;
    }
    botao_dicas.classList.toggle('btn-outline-warning', dicas_ativadas);
    botao_dicas.classList.toggle('btn-outline-secondary', !dicas_ativadas);
    if (switch_tutorial) {
        switch_tutorial.checked = dicas_ativadas;
    }
}

function mostrar_dica(pag_numero) {
    if (!dicas_ativadas || !painel_dicas) {
        return;
    }
    const dicas = dicas_por_pagina[pag_numero] || [];
    if (dicas.length === 0) {
        return;
    }
    document.getElementById('dicas_texto').textContent = t(dicas[Math.floor(Math.random() * dicas.length)]);
    painel_dicas.style.display = 'flex';
}

function fechar_dica() {
    if (painel_dicas) {
        painel_dicas.style.display = 'none';
    }
}

function alternar_dicas() {
    dicas_ativadas = !dicas_ativadas;
    localStorage.setItem('dadinho_dicas', dicas_ativadas ? 'on' : 'off');
aplicar_estado_dicas();
aplicar_estado_narrador();
    if (dicas_ativadas) {
        mostrar_dica(indiceAtual);
    } else {
        fechar_dica();
    }
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
    switch_tutorial.addEventListener('change', alternar_dicas);
}
if (overlay_tutorial) {
    overlay_tutorial.addEventListener('click', (event) => {
        if (event.target === overlay_tutorial) {
            fechar_tutorial();
        }
    });
}

// Facilidade (teclado): Enter confirma a ação do contexto e Esc fecha o que
// estiver aberto (alerta, tutorial, busca, dica). O Enter em um input dispara a
// ação correspondente; em modais, confirma/fecha.
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        fechar_alerta();
        fechar_tutorial();
        fechar_busca();
        fechar_dica();
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
// carregados sob demanda e reutilizados (cache em 'sons').
function tocar_som(nome) {
    if (!som_ativado) {
        return;
    }
    const arquivo = sons_disponiveis[nome];
    if (!arquivo) {
        return;
    }
    if (!sons[nome]) {
        sons[nome] = new Audio(`../static/sons/${arquivo}`);
        sons[nome].volume = volume_som / 100;
        sons[nome].load();
    }
    const audio = sons[nome];
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
    if (!som_ativado || !garantir_contexto_audio()) {
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
let musica_ativada = localStorage.getItem('dadinho_musica') === 'on';

// Volume da música (0 a 100), persistido entre sessões. Padrão: 50 (metade).
let volume_musica = Number(localStorage.getItem('dadinho_volume_musica') || '50');
const slider_volume_musica = document.getElementById('volume_musica');
if (slider_volume_musica) {
    slider_volume_musica.value = volume_musica;
    slider_volume_musica.addEventListener('input', () => {
        volume_musica = Number(slider_volume_musica.value);
        localStorage.setItem('dadinho_volume_musica', String(volume_musica));
        aplicar_volume_musica();
    });
}

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
        osc.stop(t0 + 0.26);
        return;
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
        osc.stop(t0 + (grave ? 1.2 : 0.7));
        return;
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
    fonte.stop(t0 + duracao + 0.02);
}

function agendar_nota(ctx, seco, reverb, nota_midi, ruido) {
    const t0 = nota_midi.inicio;
    const t1 = nota_midi.inicio + nota_midi.dur;
    if (nota_midi.canal === 9) {
        agendar_percussao(ctx, seco, reverb, nota_midi.altura, nota_midi.velocidade, t0, ruido);
        return;
    }
    const perfil = perfil_do_programa(nota_midi.programa);
    const ataque = Math.min(perfil.ataque, Math.max(0.01, nota_midi.dur * 0.6));
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
        osc.stop(parada);
    });
    if (lfo) {
        lfo.start(t0);
        lfo.stop(parada);
    }
    filtro.connect(ganho);

    let saida = ganho;
    if (ctx.createStereoPanner) {
        const pan = ctx.createStereoPanner();
        pan.pan.value = pan_do_canal(nota_midi.canal);
        ganho.connect(pan);
        saida = pan;
    }
    saida.connect(seco);
    if (perfil.envio_reverb > 0) {
        const envio = ctx.createGain();
        envio.gain.value = perfil.envio_reverb;
        saida.connect(envio);
        envio.connect(reverb);
    }
}

// Renderiza o MIDI inteiro para um AudioBuffer (permite loop sem cliques).
async function renderizar_musica(buffer) {
    const dados = parsear_midi(buffer);
    if (!dados.notas.length || dados.duracao <= 0) {
        return null;
    }
    const OfflineCtx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!OfflineCtx) {
        return null;
    }
    const taxa = 44100;
    const offline = new OfflineCtx(2, Math.ceil(dados.duracao * taxa), taxa);
    const mestre = offline.createGain();
    mestre.gain.setValueAtTime(0.0001, 0);
    mestre.gain.exponentialRampToValueAtTime(0.85, 0.06);
    if (dados.duracao > 0.6) {
        mestre.gain.setValueAtTime(0.85, dados.duracao - 0.3);
        mestre.gain.exponentialRampToValueAtTime(0.0001, dados.duracao);
    }
    const compressor = offline.createDynamicsCompressor();
    compressor.threshold.value = -18;
    compressor.knee.value = 30;
    compressor.ratio.value = 2.5;
    compressor.attack.value = 0.006;
    compressor.release.value = 0.25;
    mestre.connect(compressor).connect(offline.destination);

    // Reverb de sala: bus wet alimentado por envio de cada timbre.
    const reverb = offline.createConvolver();
    reverb.buffer = criar_impulso_reverb(offline, 2.8, 3.0);
    const retorno_reverb = offline.createGain();
    retorno_reverb.gain.value = 0.32;
    reverb.connect(retorno_reverb).connect(mestre);
    const seco = offline.createGain();
    seco.gain.value = 0.85;
    seco.connect(mestre);

    const ruido = criar_buffer_ruido(offline, 1.2);
    dados.notas.forEach(function (n) {
        agendar_nota(offline, seco, reverb, n, ruido);
    });
    return await offline.startRendering();
}

// Aplica o volume escolhido à música em reprodução (ou guarda para a próxima).
function aplicar_volume_musica() {
    if (ganho_musica) {
        ganho_musica.gain.value = volume_musica / 100;
    }
}

let ganho_musica = null;
let fonte_musica = null;
let buffer_musica = null;
let promessa_musica = null;

async function iniciar_musica() {
    if (!musica_ativada || fonte_musica || !garantir_contexto_audio()) {
        return;
    }
    if (!buffer_musica) {
        if (!promessa_musica) {
            promessa_musica = (async function () {
                try {
                    const resposta = await fetch('/tema.mid');
                    if (!resposta.ok) {
                        throw new Error('HTTP ' + resposta.status);
                    }
                    buffer_musica = await renderizar_musica(await resposta.arrayBuffer());
                } catch (erro) {
                    console.error('Falha ao carregar a música:', erro);
                    buffer_musica = null;
                }
            })();
        }
        await promessa_musica;
        promessa_musica = null;
    }
    if (!buffer_musica || !musica_ativada || fonte_musica) {
        return;
    }
    if (!ganho_musica) {
        ganho_musica = contexto_audio.createGain();
        ganho_musica.gain.value = volume_musica / 100;
        ganho_musica.connect(contexto_audio.destination);
    }
    fonte_musica = contexto_audio.createBufferSource();
    fonte_musica.buffer = buffer_musica;
    fonte_musica.loop = true;
    fonte_musica.connect(ganho_musica);
    fonte_musica.start();
}

function parar_musica() {
    if (!fonte_musica) {
        return;
    }
    try {
        fonte_musica.stop();
    } catch (erro) {
        // fonte já finalizada
    }
    fonte_musica.disconnect();
    fonte_musica = null;
}

// Botão próprio da música: liga/desliga sem afetar os efeitos sonoros.
const botao_musica = document.getElementById('botao_musica');

function aplicar_estado_musica() {
    if (!botao_musica) {
        return;
    }
    botao_musica.textContent = '🎵';
    botao_musica.classList.toggle('btn-outline-light', musica_ativada);
    botao_musica.classList.toggle('btn-outline-secondary', !musica_ativada);
    botao_musica.title = musica_ativada
        ? t('js.musica.on')
        : t('js.musica.off');
}

if (botao_musica) {
    aplicar_estado_musica();
    botao_musica.addEventListener('click', function () {
        musica_ativada = !musica_ativada;
        localStorage.setItem('dadinho_musica', musica_ativada ? 'on' : 'off');
        aplicar_estado_musica();
        if (musica_ativada) {
            iniciar_musica();
        } else {
            parar_musica();
        }
    });
}

// A política de autoplay dos navegadores exige um gesto do usuário: a música
// começa no primeiro clique/toque/tecla e segue em loop até ser desligada.
function desbloquear_audio() {
    garantir_contexto_audio();
    if (musica_ativada) {
        iniciar_musica();
    }
}
window.addEventListener('pointerdown', desbloquear_audio, { once: true });
window.addEventListener('keydown', desbloquear_audio, { once: true });

function jogar_dados() {
    parar_timer_jogada(); // Fase 21: rolou manualmente, encerra o contador.
    socket.emit('jogar_dados', { chave: chave_secreta });
    garantir_contexto_audio();
    const dadobt = document.getElementById('dadobotao');
    dadobt.disabled = true; // Desativa o input
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

function ajustar_canvas() {
    largura_canvas = window.innerWidth;
    altura_canvas = window.innerHeight;
    const escala = Math.min(window.devicePixelRatio || 1, 2);
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
    const quantidade = 90 + Math.floor(Math.random() * 70);
    const preenchido = Math.random() < 0.35;
    for (let i = 0; i < quantidade; i++) {
        const angulo = (Math.PI * 2 * i) / quantidade + (Math.random() - 0.5) * 0.25;
        let velocidade = 1.6 + Math.random() * 4.6;
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
            tamanho: 1.4 + Math.random() * 1.8
        });
    }
}

function criar_confete(no_topo) {
    return {
        x: Math.random() * largura_canvas,
        y: no_topo ? -20 - Math.random() * 60 : Math.random() * altura_canvas,
        vx: (Math.random() - 0.5) * 1.6,
        vy: 1.8 + Math.random() * 3.4,
        w: 6 + Math.random() * 7,
        h: 9 + Math.random() * 10,
        rot: Math.random() * Math.PI * 2,
        vrot: (Math.random() - 0.5) * 0.35,
        cor: CORES_FOGOS[Math.floor(Math.random() * CORES_FOGOS.length)],
        balanco: Math.random() * Math.PI * 2,
        balanco_vel: 0.02 + Math.random() * 0.045
    };
}

function iniciar_celebracao() {
    celebrando = true;
    if (confetes.length === 0) {
        for (let i = 0; i < 180; i++) {
            confetes.push(criar_confete(true));
        }
    }
    garantir_loop_animacao(); // P1: liga o loop de animação (parado ocioso).
    if (!intervalo_fogos) {
        disparar_fogos(3);
        intervalo_fogos = setInterval(function () {
            if (celebrando) {
                disparar_fogos(2);
            }
        }, 900);
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

// P1: liga o loop de animação sob demanda. Antes, `animate()` rodava para
// sempre e `drawParticles` fazia `clearRect` do viewport inteiro a cada frame
// mesmo sem partículas/confetes — custo ocioso de CPU no mobile.
function garantir_loop_animacao() {
    if (!_loop_animacao_ativo) {
        _loop_animacao_ativo = true;
        requestAnimationFrame(animate);
    }
}

function animate() {
    if (celebrando || particles.length > 0 || confetes.length > 0) {
        updateParticles();
        drawParticles();
        requestAnimationFrame(animate);
    } else {
        // Sem festa: para o loop (a próxima celebração o religa).
        _loop_animacao_ativo = false;
        ctx.clearRect(0, 0, largura_canvas, altura_canvas);
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
