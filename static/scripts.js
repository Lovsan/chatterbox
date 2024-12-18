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
