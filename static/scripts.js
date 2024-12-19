// Ensure that the document is fully loaded before running the script
document.addEventListener("DOMContentLoaded", function() {
    // Get the chat box element
    const chatBox = document.getElementById("chat-box");

    // Check if the chat box exists
    if (chatBox) {
        // Scroll to the bottom of the chat box
        chatBox.scrollTop = chatBox.scrollHeight;
    }
});


/**
 * Function to create and append a message element to the chat box
 * @param {string} username - The username of the sender
 * @param {string} currentUsername - The current user's username
 * @param {string} message - The message text
 */
function appendMessage(username, currentUsername, message) {
    // Get the chat box element
    const chatBox = document.getElementById("chat-box");

    if (chatBox) {
        // Create a new message element
        const messageElement = document.createElement("div");
        messageElement.classList.add("mb-2");
        messageElement.innerHTML = `
            <strong class="${username === currentUsername ? 'text-primary' : 'text-secondary'}">
                ${username === currentUsername ? 'You' : username}: 
            </strong>
            ${message}
            <small class="text-muted">${new Date().toLocaleString()}</small>
        `;
        
        // Append the message to the chat box and scroll to the bottom
        chatBox.appendChild(messageElement);
        chatBox.scrollTop = chatBox.scrollHeight;
    }
}