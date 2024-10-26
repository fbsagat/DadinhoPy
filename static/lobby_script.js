const socket = io();
let username = "";

document.getElementById("setUsernameButton").onclick = () => {
    const usernameInput = document.getElementById("usernameInput");
    username = usernameInput.value.trim();

    if (username) {
        usernameInput.disabled = true; // Desabilita o campo de nome após definir
        document.getElementById("sendButton").disabled = false; // Habilita o botão de enviar
        usernameInput.value = ""; // Limpa o campo de entrada
    }
};

document.getElementById("sendButton").onclick = () => {
    const messageInput = document.getElementById("messageInput");
    const message = messageInput.value;

    if (message && username) {
        socket.emit("send_message", { username, message });
        messageInput.value = ""; // Limpa o campo de entrada
    }
};

// Recebe mensagens do servidor
socket.on("receive_message", (data) => {
    const messagesDiv = document.getElementById("messages");
    messagesDiv.innerHTML += `<div><strong>${data.username}:</strong> ${data.message}</div>`;
    messagesDiv.scrollTop = messagesDiv.scrollHeight; // Rolagem automática para a parte inferior
});
