document.addEventListener("DOMContentLoaded", function() {
    const socket = io();

    // Scroll to the bottom of the chat box
    const chatBox = document.getElementById("chat-box");
    if (chatBox) {
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // Handle message form submission
    const messageForm = document.getElementById("message-form");
    if (messageForm) {
        messageForm.addEventListener("submit", function(event) {
            event.preventDefault();
            const messageInput = document.getElementById("message-input");
            const recipientId = messageForm.dataset.recipientId;
            const message = messageInput.value.trim();
            if (message) {
                socket.emit("send_message", {
                    username: messageForm.dataset.username,
                    recipient: messageForm.dataset.recipient,
                    message: message
                });
                messageInput.value = "";
            }
        });
    }

    // Handle receiving messages
    socket.on("receive_message", function(data) {
        const currentRecipientId = messageForm.dataset.recipientId;
        const currentUsername = messageForm.dataset.username;
        const chatBox = document.getElementById("chat-box");

        if ((data.recipient === currentUsername && data.username === messageForm.dataset.recipient) ||
            (data.username === currentUsername && data.recipient === messageForm.dataset.recipient)) {
            const messageElement = document.createElement("div");
            messageElement.classList.add("mb-2");
            messageElement.innerHTML = `
                <strong class="${data.username === currentUsername ? 'text-primary' : 'text-secondary'}">
                    ${data.username === currentUsername ? 'You' : data.username}: 
                </strong>
                ${data.message}
                <small class="text-muted">${new Date().toLocaleString()}</small>
            `;
            chatBox.appendChild(messageElement);
            chatBox.scrollTop = chatBox.scrollHeight;
        }
    });
});