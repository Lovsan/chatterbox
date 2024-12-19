// This script handles the WebSocket communication between the client and the server

// Ensure that the document is fully loaded before running the script
document.addEventListener("DOMContentLoaded", function() {
    // Initialize SocketIO
    const socket = io();

    // Get the message form element
    const messageForm = document.getElementById("message-form");

    // Check if the message form exists
    if (messageForm) {
        // Add an event listener for the form submission
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

        // Check if the received message is for the current chat
        if ((data.recipient === currentUsername && data.username === messageForm.dataset.recipient) ||
            (data.username === currentUsername && data.recipient === messageForm.dataset.recipient)) {
            // Use the appendMessage function to create and append the message element
            appendMessage(data.username, currentUsername, data.message);
        }
    });
});