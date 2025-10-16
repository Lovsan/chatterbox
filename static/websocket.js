// This script handles the WebSocket communication between the client and the server

document.addEventListener("DOMContentLoaded", () => {
    const chatApp = document.getElementById("chat-app");
    if (!chatApp || !window.chatTabs) {
        return;
    }

    const socket = io();
    const currentUsername = window.chatTabs.getCurrentUser();

    document.addEventListener("submit", event => {
        const form = event.target;
        if (!form.classList.contains("message-form")) {
            return;
        }

        event.preventDefault();
        const input = form.querySelector("input[name='message']");
        const message = input ? input.value.trim() : "";
        if (!message) {
            return;
        }

        socket.emit("send_message", {
            username: form.dataset.username,
            recipient: form.dataset.recipient,
            message
        });

        input.value = "";
    });

    socket.on("receive_message", data => {
        const chatTabs = window.chatTabs;
        if (!chatTabs) {
            return;
        }

        const isSender = data.username === currentUsername;
        const otherParticipantId = isSender ? data.recipient_id : data.sender_id;
        const otherParticipantUsername = isSender ? data.recipient : data.username;
        const key = chatTabs.getDirectConversationKey(otherParticipantId);

        chatTabs.ensureConversation({
            id: otherParticipantId,
            name: otherParticipantUsername,
            display_name: otherParticipantUsername,
            type: "direct"
        }, { activate: false });

        chatTabs.appendMessage(key, {
            username: data.username,
            message: data.message,
            timestamp: data.timestamp
        });
    });
});
