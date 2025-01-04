// Ensure that the document is fully loaded before running the script
document.addEventListener("DOMContentLoaded", function() {
    // Get the chat box element
    const chatBox = document.getElementById("chat-box");

    // Check if the chat box exists
    if (chatBox) {
        // Scroll to the bottom of the chat box
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // Check if the user list element exists
    const userList = document.getElementById("user-list");
    if (userList) {
        // Refresh the user list every 5 seconds
        setInterval(refreshUserList, 5000);

        // Initial call to populate the user list immediately
        refreshUserList();
    }
});


/**
 * Function to fetch and update the user list
 */
function refreshUserList() {
    fetch('/chat/user-list') // Fetch the user list from the server
        .then(response => response.json()) // Parse the JSON response
        .then(data => {
            const userList = document.getElementById("user-list");
            if (userList) {
                // Clear the current user list
                userList.innerHTML = '';
                // Create a new unordered list element
                const ulElement = document.createElement("ul");
                ulElement.classList.add("list-group");

                // Get the recipient_id from the URL query parameters
                const params = new URLSearchParams(window.location.search);
                const recipientId = params.get("recipient_id");

                // Populate the user list with the fetched data
                data.users.forEach(user => {
                    const liElement = document.createElement("li");
                    liElement.classList.add("list-group-item");

                    const aElement = document.createElement("a");
                    aElement.href = `/chat?recipient_id=${user.id}`;
                    aElement.classList.add("text-decoration-none");
                    aElement.textContent = user.username;

                    // Bold the username of the current recipient
                    if (user.id == recipientId) {
                        aElement.style.fontWeight = "bold";
                    }
                    
                    liElement.appendChild(aElement);
                    ulElement.appendChild(liElement);
                });

                // Append the unordered list to the user list container
                userList.appendChild(ulElement);
            }
        })
        .catch(error => console.error('Error fetching user list:', error)); // Handle any errors
}


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
        `;
        messageElement.setAttribute("title", `${new Date().toLocaleString("pl-PL")}`)
        
        // Append the message to the chat box and scroll to the bottom
        chatBox.appendChild(messageElement);
        chatBox.scrollTop = chatBox.scrollHeight;
    }
}
