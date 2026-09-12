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
    const caracteres = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let codigo = '';
    for (let i = 0; i < 5; i++) {
        codigo += caracteres[Math.floor(Math.random() * caracteres.length)];
    }
    ir_para_sala(codigo);
}

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
            botao.className = 'btn btn-sm btn-outline-secondary';
            botao.textContent = 'Assistir';
            botao.disabled = true; // Entrar no meio de uma partida só pelo link direto
            botao.title = 'Partidas em andamento só aceitam espectadores pelo link direto';
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
    document.querySelectorAll('#painel_config input, #painel_config select').forEach(el => {
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
    };
    socket.emit('configurar_partida', { chave: chave_secreta, config: config });
}

// Alterna a prontidão do jogador na sala de espera.
function alternar_pronto() {
    socket.emit('ficar_pronto', { chave: chave_secreta });
}

// O master aplica as configurações ao alterar qualquer campo da sala de espera.
['config_nome', 'config_dados', 'config_max', 'config_coringa', 'config_publica'].forEach((id) => {
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
    const logo = document.getElementById('titulo_img');
    const logodiv = document.getElementById('div_titulo_img');
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
            logodiv.style.height = '45vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '40%';
        } else {
            // logo.style.display = "block"; // Exibe o logotipo
            logodiv.style.height = '45vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '40%';
        }
    }
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
    tocar_som_variante('pegar_dados', [1, 2]);
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
})

socket.on('soltar_fogos', function () {
    const x = Math.random() * canvas.width;
    const y = Math.random() * canvas.height / 2;
    createFirework(x, y);
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

        // Envia confirmação para o servidor
        socket.emit('joguei_dados', { 'chave_secreta': chave_secreta });
    }, rollTime);
});

// Alerta de jogada inválida
socket.on('jogada_invalida', function (data) {
    const txt = data.txtadd
    window.alert(`Esta jogada é inválida, ${txt}`);
})

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
    socket.emit('iniciar_partida', { dados_qtd: dados_qtd });
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
    aposta_1: 'aposta_1.mp3',
    aposta_2: 'aposta_2.mp3',
    virar_papel: 'virar_papel.mp3',
    mover_peca: 'mover_peca.mp3',
    embaralhar_1: 'embaralhar_1.mp3',
    embaralhar_2: 'embaralhar_2.mp3',
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

function jogar_dados() {
    socket.emit('jogar_dados');
    garantir_contexto_audio();
    const dadobt = document.getElementById('dadobotao');
    dadobt.disabled = true; // Desativa o input
}

function conferencia_final() {
    const botao = document.getElementById('bot_confe_fim');
    socket.emit('conferencia_final');
    botao.disabled = true; // Desativa o input
}

function vencedor_final() {
    const botao = document.getElementById('bot_vencedor_fim');
    socket.emit('vencedor_final');
    botao.disabled = true; // Desativa o input
}

document.getElementById('comemorar').addEventListener('click', () => {
    socket.emit('foguetear_click');
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

const canvas = document.getElementById('fireworks');
const ctx = canvas.getContext('2d');
canvas.width = window.innerWidth;
canvas.height = window.innerHeight;

let particles = [];

function createFirework(x, y) {
    const colors = ['#FF5733', '#33FF57', '#3357FF', '#F3FF33', '#FF33A8'];
    const numParticles = 50;

    for (let i = 0; i < numParticles; i++) {
        particles.push({
            x: x,
            y: y,
            angle: Math.random() * 2 * Math.PI,
            speed: Math.random() * 5 + 2,
            radius: Math.random() * 2 + 1,
            color: colors[Math.floor(Math.random() * colors.length)],
            life: 100
        });
    }
}

function updateParticles() {
    particles = particles.filter(p => p.life > 0);
    particles.forEach(p => {
        p.x += Math.cos(p.angle) * p.speed;
        p.y += Math.sin(p.angle) * p.speed;
        p.life -= 2;
        p.radius *= 0.98; // Decay the radius
    });
}

function drawParticles() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    particles.forEach(p => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.fill();
        ctx.closePath();
    });
}

function animate() {
    updateParticles();
    drawParticles();
    requestAnimationFrame(animate);
}

animate();
