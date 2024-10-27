var socket = io.connect('http://' + document.domain + ':' + location.port);

    // Recebe o status de "mestre" do servidor
socket.on("user_role", (data) => {
    if (data.is_master) {
        const startGameButton = document.getElementById("startGameButton");
        startGameButton.style.display = "block";  // Exibe o botão "Iniciar Jogo" para o mestre
    }
});

    // Função para enviar texto ao servidor
    function sendMessage() {
        const textInput = document.getElementById("apelido").value;
        socket.emit('apelido', {apelido_msg: textInput});
    }

    // Recebendo resposta do servidor para o evento personalizado
    socket.on('response', function(data) {
        document.getElementById("response").innerText = data.data;
    });

    // Atualiza a lista de usuários
socket.on("update_user_list", (data) => {
    const userListItems = document.getElementById("userListItems");
    userListItems.innerHTML = ""; // Limpa a lista existente

    data.users.forEach((user) => {
        const userItem = document.createElement("div");
        userItem.textContent = user;
        userListItems.appendChild(userItem); // Adiciona cada usuário à lista
    });
    });

    // Função para gatilho ao servidor
    function sendMessage() {
        const textInput = document.getElementById("apelido").value;
        socket.emit('apelido', {apelido_msg: textInput});
    }

    // Função para enviar gatilho ao servidor
function iniciarpartida() {
    socket.emit('jogar_dados'); // Emite apenas o evento sem dados adicionais
}

// Recebe o evento de redirecionamento e navega para a URL enviada pelo servidor
        socket.on('redirect_to_dice', function(data) {
            window.location.href = data.url;
        });