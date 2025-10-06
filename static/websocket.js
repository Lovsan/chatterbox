// This script handles the WebSocket communication between the client and the server

document.addEventListener("DOMContentLoaded", function() {
    const socket = io();
    const messageForm = document.getElementById("message-form");
    const messageInput = document.getElementById("message-input");

    if (messageForm && messageForm.dataset.chatType === "group") {
        socket.emit("join_group_room", { group_id: messageForm.dataset.groupId });
    }

    if (messageForm) {
        messageForm.addEventListener("submit", function(event) {
            event.preventDefault();

            if (!messageInput) {
                return;
            }

            const message = messageInput.value.trim();
            if (!message) {
                return;
            }

            const chatType = messageForm.dataset.chatType;
            if (chatType === "group") {
                socket.emit("send_group_message", {
                    group_id: messageForm.dataset.groupId,
                    alias: messageForm.dataset.alias,
                    message: message
                });
            } else {
                socket.emit("send_message", {
                    username: messageForm.dataset.username,
                    recipient: messageForm.dataset.recipient,
                    message: message
                });
            }

            messageInput.value = "";
        });
    }

    socket.on("receive_message", function(data) {
        if (!messageForm || messageForm.dataset.chatType !== "direct") {
            return;
        }
        const currentUsername = messageForm.dataset.username;
        const activeRecipient = messageForm.dataset.recipient;
        if (
            (data.recipient === currentUsername && data.username === activeRecipient) ||
            (data.username === currentUsername && data.recipient === activeRecipient)
        ) {
            appendMessage(data.username, currentUsername, data.message, data.timestamp);
        }
    });

    socket.on("receive_group_message", function(data) {
        if (!messageForm || messageForm.dataset.chatType !== "group") {
            return;
        }
        if (String(data.group_id) !== String(messageForm.dataset.groupId)) {
            return;
        }
        appendMessage(data.alias, messageForm.dataset.alias, data.message, data.timestamp);
    });

    socket.on("progress_update", function(data) {
        updateProgressDisplay(data);
    });

    socket.on("error", function(data) {
        if (data && data.error) {
            console.warn('Chat error:', data.error);
            alert(data.error);
        }
    });
});
