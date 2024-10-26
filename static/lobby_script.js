const socket = io();
let username = "";

document.getElementById("setUsernameButton").onclick = () => {
    const usernameInput = document.getElementById("usernameInput");
    username = usernameInput.value.trim();

    if (username) {
        socket.emit("set_username", { username });  // Envia o nome ao servidor
        usernameInput.disabled = true; // Desabilita o campo de nome após definir
        document.getElementById("sendButton").disabled = false; // Habilita o botão de enviar
        usernameInput.value = ""; // Limpa o campo de entrada
    }
};

// Recebe o status de "mestre" do servidor
socket.on("user_role", (data) => {
    if (data.is_master) {
        document.getElementById("specialButton").style.display = "block";  // Mostra o botão especial
    }
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
