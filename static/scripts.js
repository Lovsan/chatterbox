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
// Ensure that the document is fully loaded before running the script
document.addEventListener("DOMContentLoaded", function() {
    const chatBox = document.getElementById("chat-box");
    if (chatBox) {
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    if (document.getElementById("user-list")) {
        refreshUserList();
        setInterval(refreshUserList, 5000);
    }

    if (document.getElementById("group-list")) {
        refreshGroupList();
        setInterval(refreshGroupList, 10000);
    }

    initializeSecurityLock();
    initializeMediaControls();
});

function refreshUserList() {
    fetch('/chat/user-list')
        .then(response => response.json())
        .then(data => {
            const userList = document.getElementById("user-list");
            if (!userList) {
                return;
            }
            userList.innerHTML = '';
            if (!data.users.length) {
                userList.innerHTML = '<p class="text-muted small">Start a chat to see contacts here.</p>';
                return;
            }

            const ulElement = document.createElement("ul");
            ulElement.classList.add("list-group");

            const params = new URLSearchParams(window.location.search);
            const recipientId = params.get("recipient_id");

            data.users.forEach(user => {
                const liElement = document.createElement("li");
                liElement.classList.add("list-group-item");

                const aElement = document.createElement("a");
                aElement.href = `/chat?recipient_id=${user.id}`;
                aElement.classList.add("text-decoration-none", "d-flex", "justify-content-between", "align-items-center");
                aElement.innerHTML = `<span>${user.username}</span>`;

                if (user.id == recipientId) {
                    aElement.classList.add("active");
                }

                liElement.appendChild(aElement);
                ulElement.appendChild(liElement);
            });

            userList.appendChild(ulElement);
        })
        .catch(error => console.error('Error fetching user list:', error));
}

function refreshGroupList() {
    fetch('/groups/list')
        .then(response => response.json())
        .then(data => {
            const groupList = document.getElementById("group-list");
            if (!groupList) {
                return;
            }
            groupList.innerHTML = '';
            if (!data.groups.length) {
                groupList.innerHTML = '<p class="text-muted small">No hidden groups yet. Create or join one above.</p>';
                return;
            }

            const params = new URLSearchParams(window.location.search);
            const activeGroupId = params.get("group_id");

            const ulElement = document.createElement("ul");
            ulElement.classList.add("list-group");

            data.groups.forEach(group => {
                const liElement = document.createElement("li");
                liElement.classList.add("list-group-item");

                const link = document.createElement("a");
                link.href = `/chat?group_id=${group.id}`;
                link.classList.add("text-decoration-none", "w-100");

                if (group.id == activeGroupId) {
                    link.classList.add("active");
                }

                const expiresText = group.expires_at ? ` • expires ${formatExpiry(group.expires_at)}` : '';
                const codeText = group.is_owner && group.code ? `<span class="badge text-bg-secondary ms-2">${group.code}</span>` : '';

                link.innerHTML = `
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <strong>${group.name}</strong>
                            <div class="small text-muted">You as ${group.alias}${expiresText}</div>
                        </div>
                        ${codeText}
                    </div>
                `;

                liElement.appendChild(link);
                ulElement.appendChild(liElement);
            });

            groupList.appendChild(ulElement);
        })
        .catch(error => console.error('Error fetching group list:', error));
}

function formatExpiry(isoString) {
    try {
        const date = new Date(isoString);
        return date.toLocaleString();
    } catch (error) {
        return 'soon';
    }
}

function appendMessage(senderLabel, currentLabel, message, timestamp, attachments = []) {
    const chatBox = document.getElementById("chat-box");
    if (!chatBox) {
        return;
    }

    const label = senderLabel === currentLabel ? 'You' : senderLabel;
    const titleDate = timestamp ? new Date(timestamp) : new Date();

    const messageElement = document.createElement("div");
    messageElement.classList.add("chat-message", "mb-3");
    messageElement.setAttribute("title", titleDate.toLocaleString());

    const headerElement = document.createElement("div");
    headerElement.classList.add("chat-message-header");
    headerElement.innerHTML = `<strong class="${label === 'You' ? 'text-primary' : 'text-secondary'}">${label}:</strong>`;
    messageElement.appendChild(headerElement);

    if (message) {
        const bodyElement = document.createElement("div");
        bodyElement.classList.add("chat-message-body");
        bodyElement.textContent = message;
        messageElement.appendChild(bodyElement);
    }

    if (attachments && attachments.length) {
        const attachmentsContainer = document.createElement("div");
        attachmentsContainer.classList.add("chat-attachments");

        attachments.forEach(attachment => {
            const card = document.createElement("div");
            card.classList.add("chat-media-card");
            const mediaElement = createMediaElement(attachment);
            if (mediaElement) {
                card.appendChild(mediaElement);
                if (attachment.duration_seconds) {
                    const duration = document.createElement("div");
                    duration.classList.add("chat-media-meta", "small", "text-muted");
                    duration.textContent = formatDuration(attachment.duration_seconds);
                    card.appendChild(duration);
                }
                attachmentsContainer.appendChild(card);
            }
        });

        if (attachmentsContainer.childElementCount) {
            messageElement.appendChild(attachmentsContainer);
        }
    }

    chatBox.appendChild(messageElement);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function updateProgressDisplay(progress) {
    if (!progress) {
        return;
    }
    const levelElement = document.getElementById('progress-level');
    const badgeElement = document.getElementById('progress-badge');
    if (levelElement) {
        levelElement.textContent = `Level ${progress.level}`;
    }
    if (badgeElement) {
        badgeElement.textContent = progress.badge;
    }
}

window.appendMessage = appendMessage;
window.updateProgressDisplay = updateProgressDisplay;

function formatDuration(seconds) {
    const totalSeconds = Math.max(0, Math.round(Number(seconds) || 0));
    const minutes = Math.floor(totalSeconds / 60);
    const remaining = totalSeconds % 60;
    if (minutes > 0) {
        return `${minutes}:${remaining.toString().padStart(2, '0')}`;
    }
    return `${remaining}s`;
}

function createMediaElement(attachment) {
    if (!attachment) {
        return null;
    }
    const source = attachment.url || (attachment.storage_path ? `/uploads/${attachment.storage_path}` : null);
    if (!source) {
        return null;
    }

    const mediaType = (attachment.media_type || '').toLowerCase();
    if (mediaType === 'image') {
        const img = document.createElement('img');
        img.classList.add('chat-media', 'chat-media-image');
        img.src = source;
        img.alt = 'Shared image';
        return img;
    }
    if (mediaType === 'audio') {
        const audio = document.createElement('audio');
        audio.classList.add('chat-media');
        audio.controls = true;
        audio.src = source;
        return audio;
    }
    if (mediaType === 'video') {
        const video = document.createElement('video');
        video.classList.add('chat-media');
        video.controls = true;
        video.src = source;
        return video;
    }

    const link = document.createElement('a');
    link.href = source;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = 'Download attachment';
    return link;
}

function initializeMediaControls() {
    const messageForm = document.getElementById('message-form');
    const previewContainer = document.getElementById('attachment-preview');
    const uploadButton = document.getElementById('attachment-upload-btn');
    const voiceButton = document.getElementById('voice-record-btn');
    const videoButton = document.getElementById('video-record-btn');
    const clearButton = document.getElementById('attachment-clear-btn');
    const fileInput = document.getElementById('attachment-file-input');

    if (!messageForm) {
        window.chatAttachmentState = {
            pendingUpload: null,
            clearPendingUpload: () => {},
        };
        return;
    }

    const state = {
        pendingUpload: null,
        mediaRecorder: null,
        mediaStream: null,
        recordingStart: null,
        setPendingUpload(upload) {
            this.pendingUpload = upload;
            if (!previewContainer) {
                return;
            }
            previewContainer.innerHTML = '';
            const element = createMediaElement(upload);
            if (element) {
                previewContainer.appendChild(element);
                previewContainer.classList.remove('d-none');
            }
            if (clearButton) {
                clearButton.classList.remove('d-none');
            }
        },
        clearPendingUpload() {
            this.pendingUpload = null;
            if (previewContainer) {
                previewContainer.innerHTML = '';
                previewContainer.classList.add('d-none');
            }
            if (clearButton) {
                clearButton.classList.add('d-none');
            }
            if (fileInput) {
                fileInput.value = '';
            }
        },
    };

    window.chatAttachmentState = state;

    const setUploading = (isUploading) => {
        messageForm.classList.toggle('is-uploading', Boolean(isUploading));
        [uploadButton, voiceButton, videoButton].forEach((btn) => {
            if (btn) {
                btn.disabled = Boolean(isUploading);
            }
        });
    };

    const cleanupRecorder = () => {
        if (state.mediaStream) {
            state.mediaStream.getTracks().forEach((track) => track.stop());
        }
        state.mediaStream = null;
        state.mediaRecorder = null;
        state.recordingStart = null;
        if (voiceButton) {
            voiceButton.textContent = voiceButton.dataset.defaultLabel || 'Voice Clip';
            voiceButton.classList.remove('btn-danger');
            voiceButton.dataset.state = 'idle';
        }
        if (videoButton) {
            videoButton.textContent = videoButton.dataset.defaultLabel || 'Video Clip';
            videoButton.classList.remove('btn-danger');
            videoButton.dataset.state = 'idle';
        }
    };

    const uploadBlob = (blob, mimeType, durationSeconds) => {
        if (!blob) {
            return;
        }
        state.clearPendingUpload();
        const formData = new FormData();
        const extension = (mimeType && mimeType.includes('/')) ? mimeType.split('/')[1] : 'bin';
        formData.append('file', blob, `upload.${extension}`);
        if (mimeType) {
            formData.append('mime_type', mimeType);
        }
        if (typeof durationSeconds === 'number' && !Number.isNaN(durationSeconds)) {
            formData.append('duration', String(durationSeconds));
        }

        setUploading(true);
        fetch('/api/uploads', {
            method: 'POST',
            body: formData,
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error('Upload failed');
                }
                return response.json();
            })
            .then((payload) => {
                state.setPendingUpload(payload);
            })
            .catch((error) => {
                console.error('Upload error:', error);
                alert('Failed to upload media. Please try again.');
            })
            .finally(() => {
                setUploading(false);
            });
    };

    if (clearButton) {
        clearButton.addEventListener('click', () => {
            state.clearPendingUpload();
        });
    }

    if (uploadButton && fileInput) {
        uploadButton.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (event) => {
            const file = event.target.files ? event.target.files[0] : null;
            if (!file) {
                return;
            }
            uploadBlob(file, file.type, null);
        });
    }

    const beginRecording = async (mode) => {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert('Media recording is not supported in this browser.');
            return;
        }

        const isAudio = mode === 'audio';
        const triggerButton = isAudio ? voiceButton : videoButton;
        if (!triggerButton) {
            return;
        }

        if (state.mediaRecorder && state.mediaRecorder.state !== 'inactive') {
            state.mediaRecorder.stop();
            return;
        }

        try {
            const constraints = isAudio ? { audio: true } : { audio: true, video: true };
            const stream = await navigator.mediaDevices.getUserMedia(constraints);
            state.mediaStream = stream;
            const recorder = new MediaRecorder(stream);
            const chunks = [];
            state.mediaRecorder = recorder;
            state.recordingStart = Date.now();

            triggerButton.dataset.defaultLabel = triggerButton.dataset.defaultLabel || triggerButton.textContent.trim();
            triggerButton.textContent = 'Stop Recording';
            triggerButton.classList.add('btn-danger');
            triggerButton.dataset.state = 'recording';

            recorder.ondataavailable = (event) => {
                if (event.data && event.data.size > 0) {
                    chunks.push(event.data);
                }
            };

            recorder.onstop = () => {
                const mimeType = recorder.mimeType || (isAudio ? 'audio/webm' : 'video/webm');
                const blob = new Blob(chunks, { type: mimeType });
                const durationSeconds = state.recordingStart
                    ? (Date.now() - state.recordingStart) / 1000
                    : undefined;
                cleanupRecorder();
                uploadBlob(blob, mimeType, durationSeconds);
            };

            recorder.onerror = (event) => {
                console.error('Recorder error:', event);
                cleanupRecorder();
                alert('Recording failed. Please try again.');
            };

            recorder.start();
        } catch (error) {
            console.error('Unable to start recording:', error);
            cleanupRecorder();
            alert('Unable to access the required media devices.');
        }
    };

    if (voiceButton) {
        voiceButton.addEventListener('click', () => beginRecording('audio'));
        voiceButton.dataset.defaultLabel = voiceButton.textContent.trim() || 'Voice Clip';
    }

    if (videoButton) {
        videoButton.addEventListener('click', () => beginRecording('video'));
        videoButton.dataset.defaultLabel = videoButton.textContent.trim() || 'Video Clip';
    }
}

function initializeSecurityLock() {
    const body = document.body;
    if (!body) {
        return;
    }

    const overlay = document.getElementById("security-lock-overlay");
    if (!overlay) {
        return;
    }

    const hasPin = body.dataset.hasPin === "1";
    const lockTimeoutMinutes = parseInt(body.dataset.lockTimeout || "0", 10);
    if (!hasPin || !lockTimeoutMinutes) {
        return;
    }

    const lockTimeoutMs = lockTimeoutMinutes * 60 * 1000;
    const form = overlay.querySelector("#security-lock-form");
    const pinInput = overlay.querySelector("#security-lock-pin");
    const messageElement = overlay.querySelector("#security-lock-message");
    const errorElement = overlay.querySelector("#security-lock-error");

    let lockTimerId = null;

    const scheduleLock = () => {
        if (document.hidden) {
            triggerLock();
            return;
        }
        if (lockTimerId) {
            clearTimeout(lockTimerId);
        }
        lockTimerId = window.setTimeout(triggerLock, lockTimeoutMs);
    };

    const hideOverlay = () => {
        overlay.classList.remove("active");
        body.classList.remove("locked");
        if (errorElement) {
            errorElement.textContent = "";
            errorElement.classList.add("d-none");
        }
        scheduleLock();
    };

    const showError = (message) => {
        if (!errorElement) {
            alert(message);
            return;
        }
        errorElement.textContent = message;
        errorElement.classList.remove("d-none");
    };

    const triggerLock = () => {
        overlay.classList.add("active");
        body.classList.add("locked");
        if (pinInput) {
            pinInput.value = "";
            pinInput.focus();
        }
        if (messageElement) {
            messageElement.textContent = `Enter your 4-digit security PIN to continue. (Auto-lock after ${lockTimeoutMinutes} minutes of inactivity.)`;
        }
        if (errorElement) {
            errorElement.textContent = "";
            errorElement.classList.add("d-none");
        }
    };

    if (form && pinInput) {
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const pin = pinInput.value.trim();
            if (pin.length !== 4 || /\D/.test(pin)) {
                showError("Enter your 4-digit PIN.");
                pinInput.focus();
                return;
            }
            form.classList.add("is-submitting");
            fetch("/security/verify-pin", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ pin })
            })
                .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
                .then(({ ok, data }) => {
                    if (ok && data.success) {
                        hideOverlay();
                    } else {
                        showError((data && data.message) || "Incorrect PIN.");
                    }
                })
                .catch(() => {
                    showError("Unable to verify PIN. Please try again.");
                })
                .finally(() => {
                    form.classList.remove("is-submitting");
                    pinInput.focus();
                    pinInput.select();
                });
        });
    }

    ["mousemove", "keydown", "click", "scroll", "touchstart"].forEach((eventName) => {
        document.addEventListener(eventName, scheduleLock, { passive: true });
    });

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            triggerLock();
        } else {
            scheduleLock();
        }
    });

    scheduleLock();
}
