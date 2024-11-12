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
        } else {
            // logo.style.display = "block"; // Exibe o logotipo
            logodiv.style.height = '50vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '45%';
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
        } else {
            // logo.style.display = "block"; // Exibe o logotipo
            logodiv.style.height = '50vh';
            logo.src = "../static/imagens/titulo.png";
            logo.style.width = '45%';
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
    span.innerHTML = `Temos <b>${data}</b> dados na mesa`
    dados_mesa.appendChild(span)
});

// Função pra preencher o coringa
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
        cardHeader.id = `card_hea_${jogador}`

        // Criação do corpo do card
        const cardBody = document.createElement('div');
        cardBody.className = 'card-body';

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
    const jog_painel = document.getElementById('painel_jogada');
    const painel_aguarde = document.getElementById('painel_aguarde');
    jog_painel.style.display = "block"; // Mostra o painel
    painel_aguarde.style.display = "none"; // Oculta painel aguarde
    // window.alert('meu_turno');
})

// Função coletiva para os jogadores que não estão na vez e construir formatação dinâmina para eles
socket.on('espera_turno', function (data) {
    const jog_painel = document.getElementById('painel_jogada');
    const painel_aguarde = document.getElementById('painel_aguarde');
    jog_painel.style.display = "none"; // Oculta o painel
    painel_aguarde.style.display = "block"; // Mostra painel aguarde
    // window.alert('espera_turno');
})

// Função coletiva para construir formatação dinâmina para todos os os jogadores da partida (broadcast)
socket.on('formatador_coletivo', function (data) {
    jogadores = data.jogadores_nomes;
    jog_da_vez = data.jogador_inicial_nome;
    eu = nome_jogador

    jogadores.forEach(jogador => {
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

let selectedImageValue = null; // Para armazenar o valor da imagem selecionada

// Adiciona evento para cada imagem
document.querySelectorAll('.img-button').forEach(button => {
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

    // Loop para atualizar as imagens de dado no inicio da partida
    for (let i = 1; i <= 3; i++) {
        const randomIndex = Math.floor(Math.random() * diceImages.length); // Escolhe um índice aleatório
        const randomImage = diceImages[randomIndex]; // Seleciona a imagem correspondente

        document.getElementById(`dado${i}`).src = randomImage; // Atualiza o src da tag <img>
    }
}
