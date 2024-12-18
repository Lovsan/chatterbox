// This script handles the WebSocket communication between the client and the server

// Ensure that the document is fully loaded before running the script
document.addEventListener("DOMContentLoaded", function() {
    // Initialize SocketIO
    const socket = io();

    // Handle message form submission
    const messageForm = document.getElementById("message-form");
    if (messageForm) {
        messageForm.addEventListener("submit", function(event) {
            // Prevent the default form submission behavior
            event.preventDefault();
            
            // Get the message input element and its value
            const messageInput = document.getElementById("message-input");
            const message = messageInput.value.trim();
            
            // Check if the message is not empty
            if (message) {
                // Emit the "send_message" event with the message data
                socket.emit("send_message", {
                    username: messageForm.dataset.username, // Sender's username
                    recipient: messageForm.dataset.recipient, // Recipient's username
                    message: message // Message text
                });
                
                // Clear the message input field
                messageInput.value = "";
            }
        });
    }

    // Handle receiving messages
    socket.on("receive_message", function(data) {
        // Get the current username from the form's data attributes
        const currentUsername = messageForm.dataset.username;
        
        // Get the chat box element
        const chatBox = document.getElementById("chat-box");

        // Check if the received message is for the current chat
        if ((data.recipient === currentUsername && data.username === messageForm.dataset.recipient) ||
            (data.username === currentUsername && data.recipient === messageForm.dataset.recipient)) {
            // Create a new message element
            const messageElement = document.createElement("div");
            messageElement.classList.add("mb-2");
            messageElement.innerHTML = `
                <strong class="${data.username === currentUsername ? 'text-primary' : 'text-secondary'}">
                    ${data.username === currentUsername ? 'You' : data.username}: 
                </strong>
                ${data.message}
                <small class="text-muted">${new Date().toLocaleString()}</small>
            `;
            
            // Append the message to the chat box and scroll to the bottom
            chatBox.appendChild(messageElement);
            chatBox.scrollTop = chatBox.scrollHeight;
        }
    });
});