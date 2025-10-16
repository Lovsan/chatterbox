class ChatTabs {
    constructor(rootElement) {
        this.rootElement = rootElement;
        this.currentUser = rootElement ? rootElement.dataset.currentUser : null;
        this.tabList = document.getElementById("chat-tabs");
        this.tabContent = document.getElementById("chat-tab-content");
        this.emptyState = document.getElementById("chat-empty-state");
        this.tabs = new Map();
        this.storageKey = "activeChatTab";
        this.storageMetadataKey = "chatTabMetadata";
        this.activeTabKey = null;
    }

    getCurrentUser() {
        return this.currentUser;
    }

    getConversationKey(conversation) {
        return `${conversation.type}:${conversation.id}`;
    }

    getDirectConversationKey(id) {
        return `direct:${id}`;
    }

    parseConversationKey(key) {
        if (!key) {
            return null;
        }
        const [type, id] = key.split(":");
        return { type, id: Number(id) };
    }

    updateEmptyState() {
        if (!this.emptyState) {
            return;
        }
        const shouldShow = this.tabs.size === 0;
        this.emptyState.classList.toggle("d-none", !shouldShow);
    }

    ensureConversation(conversation, { activate = false } = {}) {
        if (!conversation) {
            return null;
        }
        const key = this.getConversationKey(conversation);
        if (this.tabs.has(key)) {
            this.persistConversationMetadata(key, conversation);
            if (activate) {
                this.activateTab(key);
            }
            return this.tabs.get(key);
        }

        const tabElement = this.createTabElement(conversation, key);
        const paneElement = this.createPaneElement(conversation, key);

        const tabEntry = {
            conversation,
            tabElement,
            paneElement,
            messagesLoaded: false
        };

        this.tabs.set(key, tabEntry);
        this.persistConversationMetadata(key, conversation);
        if (this.tabList) {
            this.tabList.appendChild(tabElement);
        }
        if (this.tabContent) {
            this.tabContent.appendChild(paneElement);
        }
        this.updateEmptyState();

        if (activate || this.tabs.size === 1) {
            this.activateTab(key);
        }

        return tabEntry;
    }

    createTabElement(conversation, key) {
        const listItem = document.createElement("li");
        listItem.className = "nav-item";
        listItem.setAttribute("role", "presentation");

        const button = document.createElement("button");
        button.type = "button";
        button.className = "nav-link";
        button.textContent = conversation.display_name || conversation.name;
        button.dataset.conversationKey = key;
        button.addEventListener("click", () => this.activateTab(key));

        listItem.appendChild(button);
        return listItem;
    }

    createPaneElement(conversation, key) {
        const pane = document.createElement("div");
        pane.className = "tab-pane fade";
        pane.id = `chat-pane-${key.replace(/[:]/g, "-")}`;
        pane.setAttribute("role", "tabpanel");

        const messagesContainer = document.createElement("div");
        messagesContainer.className = "chat-messages mb-3 overflow-auto";
        messagesContainer.dataset.messagesContainer = key;
        messagesContainer.style.maxHeight = "55vh";

        const form = document.createElement("form");
        form.className = "message-form";
        form.dataset.username = this.currentUser || "";
        form.dataset.recipient = conversation.name;
        form.dataset.conversationKey = key;

        const inputGroup = document.createElement("div");
        inputGroup.className = "input-group";

        const input = document.createElement("input");
        input.type = "text";
        input.name = "message";
        input.required = true;
        input.placeholder = "Type your message...";
        input.className = "form-control";

        const buttonWrapper = document.createElement("button");
        buttonWrapper.type = "submit";
        buttonWrapper.className = "btn btn-primary";
        buttonWrapper.textContent = "Send";

        inputGroup.append(input, buttonWrapper);
        form.appendChild(inputGroup);

        pane.append(messagesContainer, form);
        return pane;
    }

    async activateTab(key) {
        if (!this.tabs.has(key)) {
            return;
        }

        this.tabList.querySelectorAll(".nav-link").forEach(link => {
            link.classList.toggle("active", link.dataset.conversationKey === key);
        });

        this.tabContent.querySelectorAll(".tab-pane").forEach(pane => {
            const isActive = pane.id === `chat-pane-${key.replace(/[:]/g, "-")}`;
            pane.classList.toggle("show", isActive);
            pane.classList.toggle("active", isActive);
        });

        this.activeTabKey = key;
        sessionStorage.setItem(this.storageKey, key);

        const tabEntry = this.tabs.get(key);
        if (!tabEntry.messagesLoaded) {
            await this.loadMessagesForConversation(tabEntry.conversation, key);
        }
    }

    async loadMessagesForConversation(conversation, key) {
        if (conversation.type !== "direct") {
            return;
        }

        try {
            const response = await fetch(`/chat/conversation/${conversation.id}/messages`);
            if (!response.ok) {
                throw new Error("Failed to load messages");
            }
            const data = await response.json();
            const messages = data.messages || [];
            const entry = this.tabs.get(key);
            if (!entry) {
                return;
            }

            const target = entry.paneElement.querySelector(`[data-messages-container="${key}"]`);
            if (target) {
                target.innerHTML = "";
            }

            messages.forEach(message => {
                this.appendMessage(key, {
                    username: message.sender.username,
                    message: message.text,
                    timestamp: message.timestamp
                });
            });

            entry.messagesLoaded = true;
        } catch (error) {
            console.error("Error loading messages:", error);
        }
    }

    appendMessage(key, { username, message, timestamp }) {
        const entry = this.tabs.get(key);
        if (!entry) {
            return;
        }

        const target = entry.paneElement.querySelector(`[data-messages-container="${key}"]`);

        if (!target) {
            return;
        }

        const messageElement = document.createElement("div");
        messageElement.className = "mb-2";

        const sender = document.createElement("strong");
        sender.className = username === this.currentUser ? "text-primary" : "text-secondary";
        sender.textContent = `${username === this.currentUser ? "You" : username}:`;

        const textNode = document.createElement("span");
        textNode.className = "ms-2";
        textNode.textContent = message;

        messageElement.title = this.formatTimestamp(timestamp);
        messageElement.append(sender, textNode);

        target.appendChild(messageElement);
        target.scrollTop = target.scrollHeight;
    }

    formatTimestamp(timestamp) {
        if (!timestamp) {
            return new Date().toLocaleString();
        }
        try {
            return new Date(timestamp).toLocaleString();
        } catch (error) {
            return timestamp;
        }
    }

    getActiveConversationKey() {
        return this.activeTabKey;
    }

    persistConversationMetadata(key, conversation) {
        if (!key || !conversation) {
            return;
        }
        const metadata = this.readConversationMetadata();
        metadata[key] = conversation;
        sessionStorage.setItem(this.storageMetadataKey, JSON.stringify(metadata));
    }

    readConversationMetadata() {
        try {
            const raw = sessionStorage.getItem(this.storageMetadataKey);
            return raw ? JSON.parse(raw) : {};
        } catch (error) {
            console.error("Unable to read chat metadata from storage:", error);
            return {};
        }
    }

    async hydrateFromServer() {
        if (!this.rootElement) {
            return;
        }

        try {
            const response = await fetch("/chat/open-conversations");
            if (!response.ok) {
                throw new Error("Failed to load open conversations");
            }

            const data = await response.json();
            const conversations = data.conversations || [];
            conversations.forEach(conversation => {
                this.ensureConversation(conversation);
            });

            const storedKey = sessionStorage.getItem(this.storageKey);
            if (storedKey && this.tabs.has(storedKey)) {
                this.activateTab(storedKey);
            } else if (storedKey) {
                const metadata = this.readConversationMetadata()[storedKey];
                if (metadata) {
                    this.ensureConversation(metadata, { activate: true });
                }
            } else if (this.rootElement.dataset.initialRecipientId) {
                const id = Number(this.rootElement.dataset.initialRecipientId);
                const username = this.rootElement.dataset.initialRecipientUsername;
                const key = this.getDirectConversationKey(id);
                this.ensureConversation({
                    id,
                    name: username,
                    display_name: username,
                    type: "direct"
                }, { activate: true });
            }
        } catch (error) {
            console.error("Error hydrating conversations:", error);
        }
    }
}

const chatTabs = new ChatTabs(document.getElementById("chat-app"));
window.chatTabs = chatTabs;

document.addEventListener("DOMContentLoaded", () => {
    const userList = document.getElementById("user-list");
    if (userList) {
        userList.addEventListener("click", event => {
            const trigger = event.target.closest("[data-open-conversation]");
            if (!trigger) {
                return;
            }
            event.preventDefault();
            const userId = Number(trigger.dataset.userId);
            const username = trigger.dataset.username;
            if (!Number.isNaN(userId)) {
                chatTabs.ensureConversation({
                    id: userId,
                    name: username,
                    display_name: username,
                    type: "direct"
                }, { activate: true });
            }
        });

        const refresh = () => refreshUserList(chatTabs.getActiveConversationKey());
        refresh();
        setInterval(refresh, 5000);
    }

    const startChatForm = document.getElementById("start-chat-form");
    if (startChatForm) {
        startChatForm.addEventListener("submit", async event => {
            event.preventDefault();
            const formData = new FormData(startChatForm);
            const username = (formData.get("username") || "").trim();
            if (!username) {
                return;
            }

            try {
                const response = await fetch("/chat/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username })
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({ message: "Unable to start chat." }));
                    alert(errorData.message || "Unable to start chat.");
                    return;
                }

                const data = await response.json();
                const conversation = data.conversation;
                if (conversation) {
                    chatTabs.ensureConversation(conversation, { activate: true });
                    startChatForm.reset();
                }
            } catch (error) {
                console.error("Error starting chat:", error);
            }
        });
    }

    chatTabs.hydrateFromServer();
});

function refreshUserList(activeKey) {
    fetch("/chat/user-list")
        .then(response => response.json())
        .then(data => {
            const userList = document.getElementById("user-list");
            if (!userList) {
                return;
            }

            userList.innerHTML = "";
            const ulElement = document.createElement("ul");
            ulElement.className = "list-group";

            const activeConversation = chatTabs.parseConversationKey(activeKey);

            data.users.forEach(user => {
                const liElement = document.createElement("li");
                liElement.className = "list-group-item d-flex justify-content-between align-items-center";

                const button = document.createElement("button");
                button.type = "button";
                button.className = "btn btn-link p-0 text-decoration-none";
                button.dataset.openConversation = "true";
                button.dataset.userId = user.id;
                button.dataset.username = user.username;
                button.textContent = user.username;

                if (activeConversation && activeConversation.id === Number(user.id)) {
                    button.classList.add("fw-bold");
                }

                liElement.appendChild(button);
                ulElement.appendChild(liElement);
            });

            userList.appendChild(ulElement);
        })
        .catch(error => console.error("Error fetching user list:", error));
}
