document.addEventListener("DOMContentLoaded", function() {
    const chatBox = document.getElementById("chat-box");
    if (chatBox) {
        // Scroll to the bottom of the chat box
        chatBox.scrollTop = chatBox.scrollHeight;
    }
});
