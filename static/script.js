let indiceAtual = 0;
let chave_secreta = '';
let nome_jogador = '';
let sala_atual = getParamSala();
let sou_master = false;

// Envia a chave guardada anteriormente (via sessionStorage) para o servidor
// reconhecer um refresh/reconexão e retomar a identidade (Fase 4).
const chave_resumo = sessionStorage.getItem('dadinho_chave') || '';
const socket = io({ autoConnect: true, query: { sala: sala_atual, chave_secreta: chave_resumo } });
socket.connect();

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

function narrador_linha(texto) {
    const log = document.getElementById('narrador_log');
    if (!log) {
        return;
    }
    const linha = document.createElement('div');
    linha.className = 'narrador-linha';
    linha.textContent = texto;
    log.appendChild(linha);
    while (log.children.length > 40) {
        log.removeChild(log.firstChild);
    }
    log.scrollTop = log.scrollHeight;
}

function mostrar_pensando(nome, ms) {
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
    el.appendChild(document.createTextNode(`${nome || 'Bot'} está pensando...`));
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
    if (data && data.texto) {
        narrador_linha(data.texto);
    }
    if (data && data.tipo === 'vitoria') {
        tocar_fanfarra();
    }
});

function getParamSala() {
    const params = new URLSearchParams(window.location.search);
    return (params.get('sala') || 'padrao').trim() || 'padrao';
}

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

function entrar_sala() {
    const input = document.getElementById('input_sala');
    const codigo = input.value.trim();
    if (!codigo) {
        alert('Digite o código da sala!');
        return;
    }
    ir_para_sala(codigo);
}

function copiar_link_sala() {
    const url = new URL(window.location.href);
    url.searchParams.set('sala', sala_atual);
    navigator.clipboard.writeText(url.toString());
}

// --- Busca de partidas (tela client-side) ---
function abrir_busca() {
    document.getElementById('tela_jogadores').style.display = 'none';
    document.getElementById('tela_busca').style.display = 'block';
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
    socket.emit('listar_partidas', { filtros: filtros, sala_atual: sala_atual });
}

function entrar_partida(codigo) {
    tocar_som_variante('pegar_dados', [1, 2]);
    ir_para_sala(codigo);
}

socket.on('partidas_listadas', function (data) {
    const lista = document.getElementById('lista_partidas');
    lista.innerHTML = '';
    const partidas = data.partidas || [];

    if (partidas.length === 0) {
        lista.innerHTML = '<small class="text-muted">Nenhuma partida encontrada com esses filtros.</small>';
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
            `🎲 ${partida.dados_qtd} dado(s)`,
            partida.com_coringa ? 'coringa ativo' : 'sem coringa',
            `master: ${partida.master || '?'}`,
            jogando ? '🕹 em andamento' : `${partida.prontos}/${partida.jogadores} prontos`,
        ];
        detalhes.textContent = detalhes_parts.join(' · ');

        info.appendChild(nome);
        info.appendChild(detalhes);

        const botao = document.createElement('button');
        if (jogando) {
            // Fase 9: assistir partidas em andamento pela busca é liberado; quem
            // entra vira espectador (a sala em jogo não trava mais a entrada).
            botao.className = 'btn btn-sm btn-outline-info';
            botao.textContent = '👁 Assistir';
            botao.title = 'Entrar na partida como espectador';
            botao.onclick = () => entrar_partida(partida.sala);
        } else if (partida.pode_entrar) {
            botao.className = 'btn btn-sm btn-success';
            botao.textContent = 'Entrar';
            botao.onclick = () => entrar_partida(partida.sala);
        } else {
            botao.className = 'btn btn-sm btn-outline-secondary';
            botao.textContent = 'Lotada';
            botao.disabled = true;
        }

        div.appendChild(info);
        div.appendChild(botao);
        lista.appendChild(div);
    });
});

socket.on('sala_cheia', function () {
    alert('Esta sala está cheia (limite de jogadores atingido).');
    ir_para_sala('padrao');
});

socket.on('iniciar_negado', function (data) {
    alert(`Não é possível iniciar: ${data.motivo}`);
});

const apelidoSalvo = sessionStorage.getItem('dadinho_apelido');
if (apelidoSalvo) {
    const apelidoInput = document.getElementById('apelido');
    if (apelidoInput) {
        apelidoInput.value = apelidoSalvo;
    }
}

// Atualiza a lista de jogadores e o estado da sala de espera
socket.on("update_user_list", (data) => {
    const userListItems = document.getElementById("lista_de_jogadores");
    userListItems.innerHTML = ""; // Limpa a lista existente

    // Nome, status e prontidão da partida.
    const nome_partida = document.getElementById('nome_partida');
    if (nome_partida) {
        nome_partida.textContent = data.nome || 'Partida';
    }
    const status_partida = document.getElementById('status_partida');
    if (status_partida) {
        const jogando = data.status === 'jogando';
        status_partida.textContent = jogando ? '🕹 Em andamento' : '⏳ Aguardando jogadores';
        status_partida.className = 'badge ' + (jogando ? 'text-bg-success' : 'text-bg-secondary');
    }
    const prontidao_partida = document.getElementById('prontidao_partida');
    if (prontidao_partida) {
        const prontos = data.prontos.filter(Boolean).length;
        prontidao_partida.textContent = `${prontos}/${data.users.length} prontos`;
    }
    const motivo_iniciar = document.getElementById('motivo_iniciar');
    if (motivo_iniciar) {
        if (data.users.length >= 2 && data.status === 'espera') {
            motivo_iniciar.textContent = data.pode_iniciar ? 'Tudo pronto! Pode iniciar.' : data.motivo || '';
        } else {
            motivo_iniciar.textContent = '';
        }
    }

    // Aplica a configuração da partida (read-only para não-master).
    aplicar_config(data.config);

    // Verificação ativa na sala de espera: guarda o compromisso do servidor e
    // envia o nonce/compromisso deste cliente (provably fair).
    if (data.config && data.config.verificacao_ativa && data.seed && data.status === 'espera') {
        seed_estado = data.seed;
        garantir_compromisso_seed();
    }

    if (data.users.length === 0) {
        userListItems.innerHTML = "<small>Aguardando jogadores...</small>";
    } else {
        const rowDiv = document.createElement("div");
        rowDiv.className = "row border-bottom";

        const jogadoresDiv = document.createElement("div");
        jogadoresDiv.className = "col-md-6 font-weight-bold";
        jogadoresDiv.textContent = "Jogadores conectados";

        const pontuacaoDiv = document.createElement("div");
        pontuacaoDiv.className = "col-md-6 font-weight-bold";
        pontuacaoDiv.textContent = "Pontuação";

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
        if (bot_pronto) {
            const meu_indice = data.users.indexOf(nome_jogador);
            const eu_pronto = meu_indice !== -1 && data.prontos[meu_indice] === true;
            bot_pronto.textContent = eu_pronto ? '✅ Pronto (clique para desfazer)' : 'Ficar pronto';
            bot_pronto.disabled = data.status === 'jogando';
        }

        const iniciar_jogo = document.getElementById('iniciar_jogo');
        if (iniciar_jogo) {
            iniciar_jogo.disabled = !data.pode_iniciar; // Ativa o botão de iniciar partida
            iniciar_jogo.style.display = sou_master ? 'block' : 'none';
        }
    }
});

socket.on('atualizar_pontos', function (data) {
    data.nomes.forEach((nome, index) => {
        const pontos = document.getElementById(`pontos_${nome}`);
        pontos.textContent = data.pontos[index];
    })
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
    };
    socket.emit('configurar_partida', { chave: chave_secreta, config: config });
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
        painel.textContent = `${data.nome} caiu e foi substituído por uma IA.`;
    }
});

// Alterna a prontidão do jogador na sala de espera.
function alternar_pronto() {
    socket.emit('ficar_pronto', { chave: chave_secreta });
}

// O master aplica as configurações ao alterar qualquer campo da sala de espera.
['config_nome', 'config_dados', 'config_max', 'config_coringa', 'config_publica', 'config_substituir_ia', 'config_verificacao', 'ia_nivel'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
        el.addEventListener('change', enviar_config);
    }
});

// Funções para mudança de página
socket.on("mudar_pagina", function (data) {
    tocar_som('virar_papel');
    const tela_busca = document.getElementById('tela_busca');
    if (tela_busca) {
        tela_busca.style.display = 'none'; // Fecha a busca caso esteja aberta (navegação do servidor)
    }
    const painel_narrador = document.getElementById('narrador');
    if (painel_narrador) {
        painel_narrador.style.display = data.pag_numero === 0 ? 'none' : 'flex';
    }
    const logo = document.getElementById('titulo_img');
    const logodiv = document.getElementById('div_titulo_img');
    if (data.pag_numero === 0) {
        const painel_aud = document.getElementById('painel_auditoria');
        if (painel_aud) {
            painel_aud.style.display = 'none';
        }
        limpar_narrador();
        parar_celebracao();
    }
    {
        const paginas = [
            document.getElementById('tela_jogadores'),
            document.getElementById('tela_jogar_dados'),
            document.getElementById('tela_partida'),
            document.getElementById('tela_conferencia'),
            document.getElementById('tela_vitoria')
        ]
        let indicie_atual = 0;
        paginas[indiceAtual].style.display = "none";
        // Atualiza o índice para a próxima página
        indiceAtual = data.pag_numero % paginas.length; // Ciclo entre 0 e o número de páginas
        // Mostra a próxima página
        paginas[indiceAtual].style.display = "block";
        if (data.pag_numero === 2) {
            // logo.style.display = "none"; // Escondekk o logotipo pra abrir espaço
            logodiv.style.height = '10vh';
            logo.src = "../static/imagens/titulo_p.png";
            logo.style.width = '25%';
        } else if (data.pag_numero === 3) {
            // logo.style.display = "none"; // Escondekk o logotipo pra abrir espaço
            logodiv.style.height = '26vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '34%';
        } else {
            // logo.style.display = "block"; // Exibe o logotipo
            logodiv.style.height = '24vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '34%';
        }
    }
    mostrar_dica(data.pag_numero);
});

// Função para preencher os dados do jogador na página de partida
socket.on('meus_dados', function (data) {
    const meus_dados = document.getElementById('meus_dados');
    meus_dados.innerHTML = "";
    const span = document.createElement('span');
    span.className = "fs-5 text-white me-2";
    span.innerText = "Seus dados: ";
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

// Função para preencher a info sobre os dados na mesa
socket.on('dados_mesa', function (data) {
    const dados_mesa = document.getElementById('dados_mesa')
    const total = data.total
    dados_mesa.innerHTML = ""
    const span = document.createElement('span')
    span.className = 'fs-5 text-white me-2'
    span.innerHTML = `Temos <b>${total}</b> dados na mesa`
    dados_mesa.appendChild(span)
});

// Função pra preencher a info sobre o coringa
socket.on('atualizar_coringa', function (data) {
    const coringa_n = Number(data.coringa_atual)
    const coringa_j = String(data.ultimo_coringa)
    const conringa_cancelado = data.coringa_cancelado
    const corin_atual = document.getElementById('corin_atual')
    corin_atual.innerHTML = ""

    if (conringa_cancelado) {
        const span3 = document.createElement('span')
        span3.className = 'fs-5 text-danger me-2'
        span3.innerText = 'O coringa foi cancelado!'
        corin_atual.appendChild(span3)
    } else {
        if (coringa_n === 0) {
            const span3 = document.createElement('span')
            span3.className = 'fs-6 text-white me-2'
            span3.innerText = 'O coringa ainda não foi jogado'
            corin_atual.appendChild(span3)
        } else {
            const span1 = document.createElement('span')
            span1.className = 'fs-5 text-white me-2'
            span1.innerText = `Coringa atual:`
            const img1 = document.createElement('img')
            img1.className = "img-fluid"
            img1.alt = 'imagem coringa';
            img1.width = 30
            img1.height = 30
            img1.src = '../static/imagens/dado/1.png'
            const span2 = document.createElement('span')
            span2.className = 'fs-5 text-white me-2'
            span2.innerText = `X${coringa_n} (${coringa_j})`
            corin_atual.appendChild(span1)
            corin_atual.appendChild(img1)
            corin_atual.appendChild(span2)
        }
    }
})

// Função para criar cada seção de dados
function createDiceSection(text, opacityClass, imageIndex) {
    const col = document.createElement('div');
    col.className = `col-md-12 mb-1 ${opacityClass}`;

    const diceDiv = document.createElement('div');
    diceDiv.className = 'd-flex align-items-center justify-content-evenly border rounded';

    const imgDiv = document.createElement('div');
    const img = document.createElement('img');
    img.src = `../static/imagens/dado/${imageIndex}.png`;
    img.className = 'diceImage img-fluid ms-4';
    img.alt = 'Imagem 1';
    img.width = 40;
    img.height = 40;
    imgDiv.appendChild(img);

    const textDiv = document.createElement('div');
    textDiv.className = 'mt-2';
    const heading = document.createElement('h1');
    heading.className = 'fs-3';
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
    const tela_jogar_dados = document.getElementById('tela_jogar_dados')
    const container = document.createElement('div');
    tela_jogar_dados.innerHTML = ""

    if (espectador === false) {
        container.className = 'container my-4 p-3 mb-2 bg-black text-white border border-light rounded';
        container.style = '--bs-bg-opacity: .3;';

        // Criação do botão Jogar Dados
        const botao = document.createElement('button');
        botao.id = 'dadobotao';
        botao.className = 'btn btn-primary mt-2';
        botao.textContent = 'Jogar dados';
        botao.onclick = jogar_dados;  // Função que será chamada ao clicar

        // Adicionando o botão ao container principal
        container.appendChild(botao);

        // Criação da div interna container para organizar as colunas
        const containerInterno = document.createElement('div');
        containerInterno.className = 'container mt-5';

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
    } else {
        // Cria a div principal
        const container = document.createElement('div');
        container.className = 'container my-4 p-3 mb-2 bg-black text-white border border-light rounded';
        container.style.setProperty('--bs-bg-opacity', '.3');

        // Cria o sub-container centralizado
        const subContainer = document.createElement('div');
        subContainer.className = 'container mt-5 d-flex justify-content-center align-items-center';

        // Cria o texto com badge
        const badge = document.createElement('span');
        badge.className = 'fs-3 badge text-bg-primary text-wrap mb-2';
        badge.style.width = 'auto';
        badge.style.maxWidth = '90%';
        badge.textContent = 'Aguarde, os dados estão rolando';

        // Adiciona o badge ao sub-container
        subContainer.appendChild(badge);

        // Cria o spinner
        const spinner = document.createElement('div');
        spinner.className = 'spinner-border text-primary';
        spinner.setAttribute('role', 'status');

        // Adiciona o texto acessível ao spinner
        const visuallyHidden = document.createElement('span');
        visuallyHidden.className = 'visually-hidden';
        visuallyHidden.textContent = 'Loading...';
        spinner.appendChild(visuallyHidden);

        // Monta o DOM
        container.appendChild(subContainer);
        container.appendChild(spinner);

        // Adiciona o container ao body ou a outro container desejado
        tela_jogar_dados.appendChild(container);
    }
})

// Função para construir os cards (parte estática)
socket.on('construtor_html', function (data) {
    const principal = document.getElementById('cards');
    principal.innerHTML = '';

    // Fase 9: mostra "Rodada N" na tela de turnos (o payload rodada_n já existia).
    const rodada_txt = document.getElementById('rodada_atual_txt');
    if (rodada_txt && data.rodada_n) {
        rodada_txt.textContent = `Rodada ${data.rodada_n}`;
        rodada_txt.classList.remove('d-none');
    }

    Object.entries(data.turnos_lista).forEach(([jogador, turnos]) => {
        // Criação do container principal
        const divCol = document.createElement('div');
        divCol.className = 'col-md-2 col-sm-4 col-6 mb-1';

        // Criação do card
        const card = document.createElement('div');
        card.className = 'card border border-secondary border-1 text-bg-dark';
        card.style.minHeight = '200px'; // Altura mínima do card; cresce com o conteúdo no mobile.
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
        card_row.appendChild(createDiceSection(`X${dado_qtd}`, opacidade, dado));
    })
});

// Função individual para verificar o jogador da vez no turno e construir formatação dinâmina para ele
socket.on('meu_turno', function (data) {
    let turno_num = data.turno_num;
    const painel_jogada = document.getElementById('painel_jogada');
    const painel_aguarde = document.getElementById('painel_aguarde');

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
})

// Função coletiva para os jogadores que não estão na vez e construir formatação dinâmina para eles
socket.on('espera_turno', function (data) {
    const painel_jogada = document.getElementById('painel_jogada');
    const painel_aguarde = document.getElementById('painel_aguarde');
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
    botao.disabled = false; // Reativa o input
    botao_desc.disabled = true; // Desativa o input

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
    const eu = nome_jogador;

    jogadores.forEach((jogador, index) => {
        const card = document.getElementById(`card_${jogador}`);

        if (!card) {
            return;
        }

        if (jogador === eu) {
            if (jogador === jog_da_vez) {
                // // Aqui para o jogador na própria vez, card dele
                card.className = 'card border border-primary border-4 text-bg-dark';
            } else {
                // Aqui para o jogador na espera da vez, card dele
                card.className = 'card border border-secondary border-1 text-bg-dark';
            }
            // Aqui para todos os jogadores sendo eu o da vez
        } else {
            if (jogador === jog_da_vez) {
                // Aqui para o jogador na espera da vez, card do da vez
                card.className = 'card border border-warning border-2 text-bg-dark';
            } else {
                // Aqui para o jogador na própria vez, card do(s) jogaor(es) aguardando
                card.className = 'card border border-secondary border-1 text-bg-dark';
            }
            // Aqui para todos os jogadores não sendo eu o da vez
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
    h1_vencedor.innerHTML = `Vitória de ${data.nome}<br> Nessa bagaça!!!`;
    iniciar_celebracao();
})

socket.on('soltar_fogos', function () {
    soltar_fogos();
})

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
    texto_v_d.innerText = data.texto;

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
})

// Ações a aplicar no jogador que virou espectador, broadcast=False
socket.on('espectador', function (data) {
    tocar_som_variante('pegar_dados', [1, 2]);
    const painel_jogada = document.getElementById('painel_jogada');
    const bot_confe_fim = document.getElementById('bot_confe_fim');
    const painel_aguarde = document.getElementById('painel_aguarde');
    const meus_dados = document.getElementById('meus_dados');
    meus_dados.innerHTML = "";
    const span = document.createElement('span');
    span.className = "fs-5 text-white me-2";
    span.innerText = "ESPECTADOR";
    meus_dados.appendChild(span);
    bot_confe_fim.style.display = 'none';
    painel_aguarde.style.display = 'none';
    painel_jogada.style.display = 'none';

})

// Lógica para enviar a aposta
document.getElementById('apostar').addEventListener('click', () => {
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
        alert('Selecione um dado e informe a quantidade!');
    }
});

// Lógica para enviar a desconfiança
document.getElementById('desconfiar').addEventListener('click', () => {
    const data = {
        chave: chave_secreta,
        acao: 'desconfiar'
    };
    // Enviar para o backend
    socket.emit('desconfiar', { dados: data });
});

// Funções após conectar
socket.on("connect_start", function (data) {
    chave_secreta = data.chave_secreta;
    sessionStorage.setItem('dadinho_chave', chave_secreta);
    sou_master = data.is_master === true;
    if (data.sala) {
        sala_atual = data.sala;
        const badge = document.getElementById('sala_atual');
        if (badge) {
            badge.textContent = '#' + data.sala;
        }
    }
    if (data.username) {
        // Reconexão retomada: devolve o apelido pro jogador.
        nome_jogador = data.username;
        const apelidoInput = document.getElementById('apelido');
        if (apelidoInput && !apelidoInput.value) {
            apelidoInput.value = data.username;
        }
    }
    const textInput = document.getElementById("apelido");
    const botaapelido = document.getElementById('botapel');
    textInput.disabled = false; // Habilita o input de apelido para todos, incluindo o master
    botaapelido.disabled = false;
    aplicar_master();
});

// Indicadores de conexão/reconexão (heartbeat visual).
socket.on('connect', function () {
    const status = document.getElementById('status_conexao');
    if (status) {
        status.textContent = '● Conectado';
        status.className = 'd-block mb-2 text-success';
    }
});

socket.on('disconnect', function () {
    const status = document.getElementById('status_conexao');
    if (status) {
        status.textContent = '⚠ Reconectando...';
        status.className = 'd-block mb-2 text-warning';
    }
});

socket.on("update_username", function (data) {
    nome_jogador = data.nome_jogador;
})

socket.on("jogar_dados_resultado", function (data) {
    const dados_lista = data.dados_jogador;
    const dados_qtd = dados_lista.length;

    const diceImages = [
        "../static/imagens/dado/1.png",
        "../static/imagens/dado/2.png",
        "../static/imagens/dado/3.png",
        "../static/imagens/dado/4.png",
        "../static/imagens/dado/5.png",
        "../static/imagens/dado/6.png"
    ];

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

        // Envia confirmação para o servidor
        socket.emit('joguei_dados', { 'chave_secreta': chave_secreta });
    }, rollTime);
});

// Alerta de jogada inválida
socket.on('jogada_invalida', function (data) {
    const txt = data.txtadd
    window.alert(`Esta jogada é inválida, ${txt}`);
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
    const botaapelido = document.getElementById('botapel');
    let apelido = textInput.value.trim();
    if (apelido) {
        sessionStorage.setItem('dadinho_apelido', apelido); // Mantém o apelido entre trocas de sala (recarregar página)
        socket.emit('apelido', { apelido_msg: textInput.value });
        textInput.disabled = true; // Desativa o input
        botaapelido.disabled = true; // Desativa o input
    } else {
        alert('Preencha o seu nome!');
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

// --- Sistema de ajuda: tutorial + dicas durante a partida ---
// Preferência de dicas do jogador, persistida entre sessões. Valor padrão: ligado.
let dicas_ativadas = localStorage.getItem('dadinho_dicas') !== 'off';

// Dicas contextuais mostradas conforme a página da partida (0 a 4).
const dicas_por_pagina = {
    0: [
        'Escolha um apelido e clique em "Pronto" para entrar na partida.',
        'O master define nome, dados por jogador, coringa e se a partida é pública.',
        'A partida só começa com 2+ jogadores, todos com apelido e prontos.',
        'Os pontos são acumulados no lobby a cada vitória.',
    ],
    1: [
        'Clique em "Jogar dados" para rolar os seus dados.',
        'Você só vê os seus dados; os outros jogadores veem apenas os deles.',
        'Quando todos rolarem, começam os turnos de aposta.',
    ],
    2: [
        'Na sua vez, aposte uma quantidade e um número (face do dado).',
        'Você também pode desconfiar da aposta anterior em vez de apostar.',
        'A aposta deve aumentar: quantidade maior, ou mesma quantidade com número maior.',
        'O 1 é coringa: conta como qualquer número, mas voltar pra número exige o dobro.',
        'Desconfiou certo? Quem apostou perde um dado. Errou? Você perde um dado.',
        'Quem perde todos os dados vira espectador da partida.',
    ],
    3: [
        'Veja quem ganhou e quem perdeu um dado na rodada.',
        'Os dados destacados em vermelho mostram a aposta conferida.',
        'Clique em Ok para começar a próxima rodada.',
    ],
    4: [
        'Parabéns ao vencedor! Clique em Ok para voltar ao lobby.',
        'O vencedor ganha 1 ponto na pontuação da sala.',
    ],
};

const botao_tutorial = document.getElementById('botao_tutorial');
const botao_dicas = document.getElementById('botao_dicas');
const overlay_tutorial = document.getElementById('tutorial_overlay');
const painel_dicas = document.getElementById('painel_dicas');
const switch_tutorial = document.getElementById('tutorial_dicas_switch');

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
    document.getElementById('dicas_texto').textContent = dicas[Math.floor(Math.random() * dicas.length)];
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

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        fechar_tutorial();
    }
});

aplicar_estado_dicas();

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
    notas.forEach((freq, i) => {
        const osc = contexto_audio.createOscillator();
        const ganho = contexto_audio.createGain();
        osc.type = 'triangle';
        osc.frequency.value = freq;
        const inicio = agora + i * 0.14;
        ganho.gain.setValueAtTime(0.0001, inicio);
        ganho.gain.exponentialRampToValueAtTime(0.22, inicio + 0.03);
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
    ganho.gain.value = 0.22;
    fonte.connect(filtro).connect(ganho).connect(contexto_audio.destination);
    fonte.start(agora);
}

// ---------------------------------------------------------------------------
// Música de fundo oficial: tema chiptune em MIDI (rota /tema.mid, que troca a
// composição a cada 12h — ver tema.py). O navegador não toca MIDI nativamente,
// então o arquivo é lido, interpretado e sintetizado via Web Audio
// (onda quadrada/serra/triângulo e ruído) em loop.
// A composição é original, inspirada em jogos de tabuleiro de SNES/Mega Drive.
// O som da música é controlado por um botão próprio, independente dos efeitos.
// ---------------------------------------------------------------------------
let musica_ativada = localStorage.getItem('dadinho_musica') !== 'off';

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

// Escolhe a forma de onda do Web Audio a partir do programa General MIDI.
function onda_do_programa(programa) {
    if (programa === 81) {
        return 'sawtooth'; // arpejo estilo Mega Drive
    }
    if (programa === 38 || programa === 32 || programa === 33) {
        return 'triangle'; // baixo
    }
    if (programa >= 88 && programa <= 95) {
        return 'sine';
    }
    return 'square'; // melodia estilo SNES
}

function volume_do_programa(programa) {
    if (programa === 38 || programa === 32 || programa === 33) {
        return 0.26;
    }
    if (programa === 81) {
        return 0.055;
    }
    if (programa === 82) {
        return 0.085;
    }
    return 0.12;
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

// Percussão sintetizada (bumbo senoidal; caixa/chimbais/pratos com ruído).
function agendar_percussao(ctx, destino, altura, t0, ruido) {
    if (altura === 35 || altura === 36) {
        const osc = ctx.createOscillator();
        const ganho = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(150, t0);
        osc.frequency.exponentialRampToValueAtTime(45, t0 + 0.12);
        ganho.gain.setValueAtTime(0.55, t0);
        ganho.gain.exponentialRampToValueAtTime(0.001, t0 + 0.18);
        osc.connect(ganho).connect(destino);
        osc.start(t0);
        osc.stop(t0 + 0.2);
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
        ganho.gain.setValueAtTime(0.32, t0);
        duracao = 0.16;
    } else if (altura === 46 || altura === 44) { // chimbal aberto
        filtro.type = 'highpass';
        filtro.frequency.value = 6000;
        ganho.gain.setValueAtTime(0.16, t0);
        duracao = 0.26;
    } else if (altura === 49 || altura === 51 || altura === 57) { // prato
        filtro.type = 'highpass';
        filtro.frequency.value = 4000;
        ganho.gain.setValueAtTime(0.22, t0);
        duracao = 0.9;
    } else { // chimbal fechado
        filtro.type = 'highpass';
        filtro.frequency.value = 7000;
        ganho.gain.setValueAtTime(0.12, t0);
        duracao = 0.06;
    }
    ganho.gain.exponentialRampToValueAtTime(0.001, t0 + duracao);
    fonte.connect(filtro).connect(ganho).connect(destino);
    fonte.start(t0);
    fonte.stop(t0 + duracao + 0.02);
}

function agendar_nota(ctx, destino, nota_midi, ruido) {
    const t0 = nota_midi.inicio;
    const t1 = nota_midi.inicio + nota_midi.dur;
    if (nota_midi.canal === 9) {
        agendar_percussao(ctx, destino, nota_midi.altura, t0, ruido);
        return;
    }
    const osc = ctx.createOscillator();
    const ganho = ctx.createGain();
    osc.type = onda_do_programa(nota_midi.programa);
    osc.frequency.value = 440 * Math.pow(2, (nota_midi.altura - 69) / 12);
    const volume = volume_do_programa(nota_midi.programa) * (nota_midi.velocidade / 127);
    const fim_ataque = t0 + 0.012;
    ganho.gain.setValueAtTime(0.0001, t0);
    ganho.gain.exponentialRampToValueAtTime(Math.max(0.0002, volume), fim_ataque);
    ganho.gain.setValueAtTime(Math.max(0.0002, volume), Math.max(fim_ataque, t1 - 0.03));
    ganho.gain.exponentialRampToValueAtTime(0.0001, t1);
    osc.connect(ganho).connect(destino);
    osc.start(t0);
    osc.stop(t1 + 0.02);
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
    mestre.gain.value = 0.9;
    const compressor = offline.createDynamicsCompressor();
    compressor.threshold.value = -16;
    compressor.knee.value = 24;
    compressor.ratio.value = 4;
    compressor.attack.value = 0.004;
    compressor.release.value = 0.18;
    mestre.connect(compressor).connect(offline.destination);
    const ruido = criar_buffer_ruido(offline, 1.2);
    dados.notas.forEach(function (n) {
        agendar_nota(offline, mestre, n, ruido);
    });
    return await offline.startRendering();
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
        ganho_musica.gain.value = 0.5;
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
        ? 'Música ligada (clique para desligar)'
        : 'Música desligada (clique para ligar)';
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
    socket.emit('jogar_dados', { chave: chave_secreta });
    garantir_contexto_audio();
    const dadobt = document.getElementById('dadobotao');
    dadobt.disabled = true; // Desativa o input
}

function conferencia_final() {
    const botao = document.getElementById('bot_confe_fim');
    socket.emit('conferencia_final', { chave: chave_secreta });
    botao.disabled = true; // Desativa o input
}

function vencedor_final() {
    const botao = document.getElementById('bot_vencedor_fim');
    socket.emit('vencedor_final', { chave: chave_secreta });
    botao.disabled = true; // Desativa o input
}

document.getElementById('comemorar').addEventListener('click', () => {
    socket.emit('foguetear_click', { chave: chave_secreta });
});

function verificar_enter(event, button) {
    if (event.key !== 'Enter') {
        return;
    }
    if (button === 'button') {
        enviar_apelido();
    } else if (button === 'sala') {
        entrar_sala();
    }
}

// Seleciona os elementos
const inputQuantidade = document.getElementById("quantidade");
const btnIncrease = document.getElementById("increase");
const btnDecrease = document.getElementById("decrease");

// Incrementa o valor
btnIncrease.addEventListener("click", () => {
    const currentValue = parseInt(inputQuantidade.value) || 1;
    inputQuantidade.value = currentValue + 1;
});

// Decrementa o valor (não permitindo valores menores que o mínimo)
btnDecrease.addEventListener("click", () => {
    const currentValue = parseInt(inputQuantidade.value) || 1;
    if (currentValue > parseInt(inputQuantidade.min)) {
        inputQuantidade.value = currentValue - 1;
    }
});

let selectedImageValue = null; // Para armazenar o valor da imagem selecionada

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

function animate() {
    updateParticles();
    drawParticles();
    requestAnimationFrame(animate);
}

animate();

// ---------------------------------------------------------------------------
// Verificação de integridade (provably fair) — espelha seed.py no cliente.
// O nonce é gerado aqui (nunca no servidor) e o compromisso é publicado.
// ---------------------------------------------------------------------------
let seed_estado = null;
let nonce_local = null;
let compromisso_local = null;
let seed_commit_enviado = null;

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
    sessionStorage.removeItem(CHAVE_NONCE);
    sessionStorage.removeItem(CHAVE_SEED_CTX);
}

// Gera (uma vez por partida) o nonce local e publica o compromisso dele.
async function garantir_compromisso_seed() {
    if (!seed_estado || !crypto.subtle || !chave_secreta) {
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
    socket.emit('comprometer_seed', { chave: chave_secreta, nonce: nonce_local, compromisso: compromisso_local });
    seed_commit_enviado = ctx;
}

socket.on('seed_compromissos', function (data) {
    seed_estado = data;
    garantir_compromisso_seed();
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
        return [['Web Crypto indisponível (use HTTPS ou localhost).', false]];
    }
    if (data.compromisso_servidor && data.nonce_servidor) {
        const hSrv = await sha256Hex('dadinho:v1:commit|' + data.nonce_servidor);
        itens.push(['Compromisso do servidor confere', hSrv === data.compromisso_servidor]);
    }
    for (const p of (data.participantes || [])) {
        if (p.compromisso && p.nonce && !p.sem_reveal) {
            const h = await sha256Hex('dadinho:v1:commit|' + p.nonce);
            itens.push([`Compromisso de ${p.nome || p.client_id} confere`, h === p.compromisso]);
        }
    }
    const nonces = {};
    for (const p of (data.participantes || [])) {
        if (p.nonce) {
            nonces[p.client_id] = p.nonce;
        }
    }
    const ordem = Object.keys(nonces).sort(compararUtf8);
    const partes = [data.fonte, data.entropia_externa, ...ordem.map(c => nonces[c])];
    const seedCalc = await sha256Hex('dadinho:v1:seed|' + partes.join('|'));
    itens.push(['Seed final bate com a fórmula', seedCalc === data.seed_final]);

    if (data.fonte === 'beacon' && data.beacon && data.beacon.round) {
        try {
            const resp = await fetch(`https://api.drand.sh/${data.beacon.chain}/public/${data.beacon.round}`);
            const json = await resp.json();
            const mesmo = String(json.randomness || '').toLowerCase() === String(data.entropia_externa || '').toLowerCase();
            itens.push(['Beacon drand confere (consulta independente)', mesmo]);
        } catch (e) {
            itens.push(['Beacon drand: não foi possível consultar', false]);
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
    itens.push([`Dados derivados conferem (${iguais}/${total})`, total > 0 && iguais === total]);

    if (nonce_local) {
        const meu = (data.participantes || []).find(p => p.nonce === nonce_local);
        itens.push(['Meu nonce está incluído na seed', !!meu]);
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
    alvo.innerHTML = '<div class="spinner-border spinner-border-sm text-info" role="status"></div> conferindo...';
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
    sumario.textContent = 'Ver dados técnicos (seed, compromissos, beacon)';
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
