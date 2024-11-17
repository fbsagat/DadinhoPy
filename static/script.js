// Definindo uma constante para a tecla "K"
const TECLA_K = 'k';
let indiceAtual = 0;
// Função para capturar a tecla "K"
document.addEventListener('keydown', function (event) {
    // Verifica se a tecla pressionada é "K" (minúscula ou maiúscula)
    if (event.key === TECLA_K || event.key === TECLA_K.toUpperCase()) {
        const logo = document.getElementById('titulo_img');
        const logodiv = document.getElementById('div_titulo_img');
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
        indiceAtual = (indiceAtual + 1) % paginas.length; // Ciclo entre 0 e o número de páginas
        // Mostra a próxima página
        paginas[indiceAtual].style.display = "block";

        if (indiceAtual === 2) {
            // logo.style.display = "none"; // Escondekk o logotipo pra abrir espaço
            logodiv.style.height = '10vh';
            logo.src = "../static/imagens/titulo_p.png";
            logo.style.width = '20%';
        } else if (indiceAtual === 3) {
            // logo.style.display = "none"; // Escondekk o logotipo pra abrir espaço
            logodiv.style.height = '28vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '35%';
        } else {
            // logo.style.display = "block"; // Exibe o logotipo
            logodiv.style.height = '38vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '35%';
        }
    }
});

// Embaralhar os dados ao iniciar
window.onload = escolherImagemAleatoria;
let chave_secreta = '';
let nome_jogador = '';


const socket = io({ autoConnect: true });
socket.connect();

// Atualiza a lista de jogadores
socket.on("update_user_list", (data) => {
    const userListItems = document.getElementById("lista_de_jogadores");
    userListItems.innerHTML = ""; // Limpa a lista existente
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
            userItem.textContent = `${user} ${master}`;

            const pontuacaoDiv = document.createElement("div");
            pontuacaoDiv.className = "col-md-6";
            pontuacaoDiv.id = `pontos_${user}`;
            pontuacaoDiv.textContent = data.pontos[index];

            userListItems.appendChild(headerRow); // Adiciona cada row à lista
            headerRow.appendChild(userItem); // Adiciona cada usuário à headerRow
            headerRow.appendChild(pontuacaoDiv); // Adiciona cada pontuação à lista
        });

        if (data.users.length >= 2) {
            const iniciar_jogo = document.getElementById('iniciar_jogo');
            iniciar_jogo.disabled = false; // Ativa o botão de iniciar partida
        } else {
            iniciar_jogo.disabled = true; // Ativa o botão de iniciar partida
        }
    }
});

socket.on('atualizar_pontos', function (data) {
    data.nomes.forEach((nome, index) => {
        pontos = document.getElementById(`pontos_${nome}`);
        pontos.textContent = data.pontos[index];
    })
})

// Funções para o "master" do servidor
socket.on("master_def", function (data) {
    if (data.is_master) {
        const startGameButton = document.getElementById("iniciar_jogo");
        startGameButton.style.display = "inline-block"; // Exibe o botão "Iniciar Jogo" para o mestre
    }
});

// Funções para mudança de página
socket.on("mudar_pagina", function (data) {
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
            logo.style.width = '20%';
        } else if (data.pag_numero === 3) {
            // logo.style.display = "none"; // Escondekk o logotipo pra abrir espaço
            logodiv.style.height = '28vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '35%';
        } else {
            // logo.style.display = "block"; // Exibe o logotipo
            logodiv.style.height = '38vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '35%';
        }
    }
});

// Função para preencher os dados do jogador na página de partida
socket.on('meus_dados', function (data, index) {
    const meus_dados = document.getElementById('meus_dados');
    meus_dados.innerHTML = "";
    const span = document.createElement('span');
    span.className = "fs-5 text-white me-2";
    span.innerText = "Seus dados: ";
    meus_dados.appendChild(span);

    data.dados.forEach(dados => {
        const col_dado = document.createElement('div');
        col_dado.className = "col-auto";

        const img_dado = document.createElement('img');
        img_dado.className = "img-fluid me-2";
        img_dado.alt = `imagem ${index}`;
        img_dado.width = 30;
        img_dado.height = 30;
        img_dado.src = `../static/imagens/dado/${dados}.png`;

        meus_dados.appendChild(col_dado);
        col_dado.appendChild(img_dado);
    });

});

// Função para preencher a info sobre os dados na mesa
socket.on('dados_mesa', function (data) {
    dados_mesa = document.getElementById('dados_mesa')
    data = data.total
    dados_mesa.innerHTML = ""
    span = document.createElement('span')
    span.className = 'fs-5 text-white me-2'
    span.innerHTML = `Temos <b>${data}</b> dados na mesa`
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

        // Criação do elemento de áudio
        const audio = document.createElement('audio');
        audio.id = 'rollSound';
        audio.src = '../static/sounds/dice-roll.mp3';

        // Adicionando o elemento de áudio ao container principal
        container.appendChild(audio);

        // Adicionando o container principal ao corpo do documento
        document.body.appendChild(container);

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
        badge.style.width = '36rem';
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
        card.style.height = '240px'; // Tamanho do card, ajustar no futuro: 240px;
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

        if (data.rodada_n != 0) {

            let opacidade;
            // Definindo a opacidade com base no índice
            if (i === 0) {
                opacidade = 'opacity-25'; // Para o índice 0, opacidade 25%
            } else if (i === 1) {
                opacidade = 'opacity-50'; // Para o índice 1, opacidade 50%
            } else if (i === 2) {
                opacidade = 'opacity-100'; // Para o índice 2, opacidade 100%
            }
            for (let i = 0; i < turnos.length; i++) {
                row.appendChild(createDiceSection(`X${turnos[i][0]}`, opacidade, turnos[i][1]));
            }
        }
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
    const jogador = dados.jogador
    const lista_turnos = dados.lista_turnos
    card_row = document.getElementById(`card_row_${jogador}`)
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
    const jogadores = data.jogadores_nomes;
    const jogadores_dados = data.jogadores_dados_qtd;

    jogadores.forEach((jogador, index) => {
        const card = document.getElementById(`card_hea_${jogador}`);
        const c_row = document.getElementById(`card_row_${jogador}`);
        const botao = document.getElementById('bot_confe_fim');

        if (card) {  // Verifica se o elemento existe
            card.textContent = `${jogador} (🎲 x ${jogadores_dados[index]})`;
        }
        if (c_row) {  // Verifica se o elemento existe
            c_row.innerHTML = '';
        }
        botao.disabled = false; // Reativa o input
        const botao_desc = document.getElementById('desconfiar');
        botao_desc.disabled = true; // Desativa o input
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
});

// Função coletiva para construir formatação dinâmina para todos os os jogadores da partida (broadcast)
socket.on('formatador_coletivo', function (data) {
    const jogadores = data.jogadores_nomes;
    const jog_da_vez = data.jogador_inicial_nome;
    const eu = nome_jogador;

    jogadores.forEach((index, jogador) => {
        const card = document.getElementById(`card_${jogador}`);

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

document.querySelectorAll('.image-button').forEach(button => {
    button.addEventListener('click', () => {
        // Remove a classe 'selected' de todos os botões
        document.querySelectorAll('.image-button').forEach(btn => {
            btn.classList.remove('selected');
        });

        // Adiciona a classe 'selected' ao botão clicado
        button.classList.add('selected');
    });
});


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
    const textInput = document.getElementById("apelido");
    const botaapelido = document.getElementById('botapel');
    textInput.disabled = false; // Desativa o input
    botaapelido.disabled = false; // Desativa o input
    if (data.is_master) {
        startGameButton.style.display = "inline-block"; // Exibe o botão "Iniciar Jogo" para o mestre
        textInput.disabled = true; // Desativa o input
        botaapelido.disabled = true; // Desativa o input
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

    const rollSound = document.getElementById('rollSound');

    const rollInterval = 100; // Intervalo de troca de imagens em milissegundos
    const rollTime = Math.floor(Math.random() * (6000 - 3000 + 1)) + 3000; // Tempo total da rolagem

    // Inicia o som de rolagem
    rollSound.currentTime = 0;
    rollSound.play();

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

        // Cria dinamicamente os resultados finais com base em "dados_lista"
        const finalResults = dados_lista.map(valor => `../static/imagens/dado/${valor}.png`);

        // Atualiza as imagens com os resultados finais
        dados.forEach((dado, index) => {
            dado.src = finalResults[index];
        });

        // Para o som
        rollSound.pause();
        rollSound.currentTime = 0;

        // Envia confirmação para o servidor
        socket.emit('joguei_dados', { 'chave_secreta': chave_secreta });
    }, rollTime);
});

// Alerta de jogada inválida
socket.on('jogada_invalida', function (data) {
    txt = data.txtadd
    window.alert(`Esta jogada é inválida, ${txt}`);
})

// Função para enviar apelido ao servidor
function enviar_apelido() {
    const textInput = document.getElementById("apelido");
    const botaapelido = document.getElementById('botapel');
    let apelido = textInput.value.trim();
    if (apelido) {
        socket.emit('apelido', { apelido_msg: textInput.value });
        textInput.disabled = true; // Desativa o input
        botaapelido.disabled = true; // Desativa o input
    } else {
        alert('Preencha o seu nome!');
    }
}

function iniciar_partida() {
    const bot_iniciar = document.getElementById('iniciar_partida');
    socket.emit('iniciar_partida');
}

function jogar_dados() {
    socket.emit('jogar_dados');
    const bot_iniciar = document.getElementById('jogar_dados');
    constant = dadobt = document.getElementById('dadobotao');
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

function verificr_enter(event, button) {
    if (event.key === 'Enter' && button === 'button') {
        enviar_apelido();
    }
}

function escolherImagemAleatoria() {
    let diceImages = [
        "../static/imagens/dado/1.png",
        "../static/imagens/dado/2.png",
        "../static/imagens/dado/3.png",
        "../static/imagens/dado/4.png",
        "../static/imagens/dado/5.png",
        "../static/imagens/dado/6.png"
    ];

    // Loop para atualizar as imagens de dado no inicio da partida
    for (let i = 1; i <= 3; i++) {
        const randomIndex = Math.floor(Math.random() * diceImages.length); // Escolhe um índice aleatório
        const randomImage = diceImages[randomIndex]; // Seleciona a imagem correspondente

        document.getElementById(`dado${i}`).src = randomImage; // Atualiza o src da tag <img>
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
        document.querySelectorAll('.img-button').forEach(btn => {
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
