// Definindo uma constante para a tecla "K"
const TECLA_K = 'k';
let indiceAtual = 0;
// Função para capturar a tecla "K"
document.addEventListener('keydown', function (event) {
    // Verifica se a tecla pressionada é "K" (minúscula ou maiúscula)
    if (event.key === TECLA_K || event.key === TECLA_K.toUpperCase()) {
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
    }
});

// embaralhar os dados ao iniciar
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
socket.on("mudar_pagina", function (num) {
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
        indiceAtual = num.numero % paginas.length; // Ciclo entre 0 e o número de páginas
        // Mostra a próxima página
        paginas[indiceAtual].style.display = "block";
    }
});

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
        alert('Preencha o seu nome(pelo menos uma letra fi)')
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

// // Função para enviar gatilho ao servidor
// function iniciarpartida() {
//     socket.emit('jogar_dados'); // Emite apenas o evento sem dados adicionais
// }
