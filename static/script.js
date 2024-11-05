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
            logo.style.display = "none"; // Esconde o logotipo pra abrir espaço
            logodiv.style.height = '5vh';
        } else {
            logo.style.display = "block"; // Exibe o logotipo
            logodiv.style.height = '50vh';
        }
    }
});

// Embaralhar os dados ao iniciar
window.onload = escolherImagemAleatoria;

const socket = io({ autoConnect: true });
socket.connect();

// Atualiza a lista de jogadores
socket.on("update_user_list", (data) => {
    const userListItems = document.getElementById("lista_de_jogadores");
    userListItems.innerHTML = ""; // Limpa a lista existente

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
});

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
            logo.style.display = "none"; // Apaga o logotipo pra abrir espaço
            logodiv.style.display = "none";
            logodiv.style.height = '5vh';
        } else {
            logo.style.display = "block"; // Exibe o logotipo
            logodiv.style.display = "block";
            logodiv.style.height = '50vh';
        }
    }
});

// Função para preencher os dados do jogador na página de partida
socket.on('meus_dados', function (data, index) {
    const meus_dados = document.getElementById('meus_dados')
    const span = document.createElement('span')
    span.className = "fs-5 text-white me-2"
    span.innerText = "Seus dados: "
    meus_dados.appendChild(span);

    data.dados.forEach(dados => {
        const col_dado = document.createElement('div')
        col_dado.className = "col-auto"

        const img_dado = document.createElement('img')
        img_dado.className = "img-fluid me-2"
        img_dado.alt = `imagem ${index}`;
        img_dado.width = 30
        img_dado.height = 30
        img_dado.src = `../static/imagens/dado/${dados}.png`

        meus_dados.appendChild(col_dado);
        col_dado.appendChild(img_dado);
    });

});

// Função para preencher os dados na mesa
socket.on('dados_mesa', function (data) {
    dados_mesa = document.getElementById('dados_mesa')
    data = data.total
    span = document.createElement('span')
    span.className = 'fs-5 text-white me-2'
    span.innerText = `${data} dados na mesa`
    dados_mesa.appendChild(span)
});

// Função pra preencher o coringa
socket.on('rodada_info', function (data) {
    const coringa_n = Number(data.coringa_atual)
    const coringa_j = String(data.ultimo_coringa)
    const corin_atual = document.getElementById('corin_atual')
    corin_atual.innerHTML = ""

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
})

// Função individual para verificar o jogador da vez no turno                 TERMINEI AQUI !!!
socket.on('meu_turno', function () {
    let jog_painel = document.getElementById('painel_jogada');
    // if (jog_painel) { // Verifique se o elemento foi encontrado
    //     if (jogador === o_da_vez) {
    //         card.className = 'card border-primary border-4 text-bg-dark';
    //         jog_painel.style.display = "block"; // Mostra o painel
    //     } else {
    //         card.className = 'card border-secondary border-1 text-bg-dark';
    //         jog_painel.style.display = "none"; // Oculta o painel
    //     }
    // } else {
    //     console.error("Elemento 'painel_jogada' não encontrado.");
    // }

})

// função para preencher os cards
socket.on('rodada_info', function (data) {
    const principal = document.getElementById('cards');

    const o_da_vez = data.vez_atual;
    principal.innerHTML = '';

    Object.entries(data.turnos_lista).forEach(([jogador, turnos]) => {
        // Criação do container principal
        const divCol = document.createElement('div');
        divCol.className = 'col-md-2 col-sm-4 col-6 mb-1';

        // Criação do card
        const card = document.createElement('div');
        card.className = 'card border-primary border-4 text-bg-dark';

        

        // Criação do cabeçalho do card
        const cardHeader = document.createElement('div');
        cardHeader.className = 'card-header';
        cardHeader.textContent = jogador;

        // Criação do corpo do card
        const cardBody = document.createElement('div');
        cardBody.className = 'card-body';

        // Criação da linha dentro do corpo do card
        const row = document.createElement('div');
        row.className = 'row d-flex justify-content-center align-items-center text-center';

        // Percorrendo a lista de dois em dois
        if (data.rodada_n != 0) {
            for (let i = 0; i < turnos.length; i++) {
                // Verifica se o próximo índice existe para evitar erros
                row.appendChild(createDiceSection(`X${turnos[i][0]}`, 'opacity-25', turnos[i][1]));
            }
        }

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

        // Montando a estrutura do card
        cardBody.appendChild(row);
        card.appendChild(cardHeader);
        card.appendChild(cardBody);
        divCol.appendChild(card);

        principal.appendChild(divCol); // Adicionando tudo ao DOM
    })
})

// Funções após conectar
socket.on("connect_start", function (data) {
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

socket.on("jogar_dados_resultado", function (data) {
    const diceImages = [
        "../static/imagens/dado/1.png",
        "../static/imagens/dado/2.png",
        "../static/imagens/dado/3.png",
        "../static/imagens/dado/4.png",
        "../static/imagens/dado/5.png",
        "../static/imagens/dado/6.png"
    ];

    const dados = [
        document.getElementById('dado1'),
        document.getElementById('dado2'),
        document.getElementById('dado3')
    ];
    const rollSound = document.getElementById('rollSound');

    let currentIndex = 0;
    const rollInterval = 100; // Intervalo de troca de imagens em milissegundos
    let valor = Math.floor(Math.random() * (6000 - 3000 + 1)) + 3000;
    const rollTime = valor; // Tempo total da rolagem em milissegundos

    // Inicia o som de rolagem
    rollSound.currentTime = 0;
    rollSound.play();

    // Inicia a animação de rolagem para todos os dados
    const animation = setInterval(() => {
        dados.forEach(dado => {
            dado.src = diceImages[currentIndex];
        });
        currentIndex = (currentIndex + 1) % diceImages.length;
    }, rollInterval);

    // Após o tempo total de rolagem, exibe o resultado final e para a animação
    setTimeout(() => {
        clearInterval(animation);

        // Recebe os resultados finais para cada dado (simulado aqui)
        const finalResults = [
            `../static/imagens/dado/${data.dados_jogador[0]}.png`, // Exemplo de resultado final do dado 1
            `../static/imagens/dado/${data.dados_jogador[1]}.png`, // Exemplo de resultado final do dado 1
            `../static/imagens/dado/${data.dados_jogador[2]}.png`, // Exemplo de resultado final do dado 1
        ];

        // Atualiza as imagens com os resultados finais
        dados.forEach((dado, index) => {
            dado.src = finalResults[index];
        });

        // Para o som
        rollSound.pause();
        rollSound.currentTime = 0;
        socket.emit('joguei_dados', data.jogador);
    }, rollTime);
});

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
        alert('Preencha o seu nome!')
    }
}

function ir_jogar_dados() {
    const bot_iniciar = document.getElementById('ir_jogar_dados')
    socket.emit('ir_jogar_dados')
}

function jogar_dados() {
    socket.emit('jogar_dados')
    const bot_iniciar = document.getElementById('jogar_dados')
    constant = dadobt = document.getElementById('dadobotao')
    dadobt.disabled = true; // Desativa o input
}


function verificr_enter(event, button) {
    if (event.key === 'Enter' && button === 'button') {
        enviar_apelido()
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

    // Loop para atualizar as imagens de dado
    for (let i = 1; i <= 3; i++) {
        const randomIndex = Math.floor(Math.random() * diceImages.length); // Escolhe um índice aleatório
        const randomImage = diceImages[randomIndex]; // Seleciona a imagem correspondente

        document.getElementById(`dado${i}`).src = randomImage; // Atualiza o src da tag <img>
    }
}
