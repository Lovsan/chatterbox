class ConversationSecurity {
    constructor(defaultConversationId) {
        this.defaultConversationId = defaultConversationId || null;
        this.keys = new Map();
        this.supportsCrypto = Boolean(window.crypto && window.crypto.subtle);
        this.textDecoder = typeof TextDecoder !== "undefined" ? new TextDecoder() : null;
    }

    async ensureKey(conversationId) {
        const target = conversationId || this.defaultConversationId;
        if (!target || !this.supportsCrypto) {
            return null;
        }
        if (this.keys.has(target)) {
            return this.keys.get(target);
        }
        const response = await fetch(`/api/conversations/key?conversation=${encodeURIComponent(target)}`);
        if (!response.ok) {
            throw new Error("Unable to retrieve encryption key.");
        }
        const data = await response.json();
        if (!data.key) {
            throw new Error("Encryption key missing from response.");
        }
        const keyBytes = base64ToUint8Array(data.key);
        const cryptoKey = await window.crypto.subtle.importKey(
            "raw",
            keyBytes,
            { name: "AES-GCM" },
            false,
            ["decrypt"]
        );
        this.keys.set(target, cryptoKey);
        return cryptoKey;
    }

    async decryptMessage(conversationId, ciphertext, nonce) {
        if (!this.supportsCrypto) {
            throw new Error("Web Crypto API is not available.");
        }
        const key = await this.ensureKey(conversationId);
        if (!key) {
            throw new Error("Missing encryption key.");
        }
        const iv = base64ToUint8Array(nonce);
        const payload = base64ToUint8Array(ciphertext);
        const result = await window.crypto.subtle.decrypt(
            { name: "AES-GCM", iv, tagLength: 128 },
            key,
            payload
        );
        if (this.textDecoder) {
            return this.textDecoder.decode(result);
        }
        const view = new Uint8Array(result);
        let text = "";
        for (let i = 0; i < view.length; i += 1) {
            text += String.fromCharCode(view[i]);
        }
        return text;
    }

    async decryptPayload(payload, fallbackConversation) {
        if (!payload || !payload.is_encrypted || !payload.ciphertext || !payload.nonce) {
            return payload && typeof payload.message === "string" ? payload.message : "";
        }
        const conversationId = payload.conversation || fallbackConversation || this.defaultConversationId;
        if (!conversationId) {
            return "";
        }
        try {
            return await this.decryptMessage(conversationId, payload.ciphertext, payload.nonce);
        } catch (error) {
            console.warn("Unable to decrypt payload", error);
            if (typeof payload.message === "string") {
                return payload.message;
            }
            return "";
        }
    }

    async hydrateExistingMessages(container) {
        if (!container || !this.supportsCrypto) {
            return;
        }
        const encryptedMessages = container.querySelectorAll('[data-is-encrypted="1"]');
        for (const element of encryptedMessages) {
            const ciphertext = element.dataset.ciphertext;
            const nonce = element.dataset.nonce;
            const conversation = element.dataset.conversation || this.defaultConversationId;
            const content = element.querySelector("[data-message-content]");
            if (!ciphertext || !nonce || !content) {
                continue;
            }
            try {
                const message = await this.decryptMessage(conversation, ciphertext, nonce);
                if (message) {
                    content.textContent = message;
                    content.classList.remove("text-muted", "fst-italic");
                    element.dataset.isEncrypted = "0";
                }
            } catch (error) {
                console.warn("Unable to decrypt existing message", error);
            }
        }
    }
}

class Messenger {
    constructor({ socket, messageForm, chatBox, security, currentUsername, currentUserId }) {
        this.socket = socket;
        this.messageForm = messageForm;
        this.messageInput = messageForm ? messageForm.querySelector("input[name='message']") : null;
        this.chatBox = chatBox;
        this.security = security;
        this.chatType = messageForm ? (messageForm.dataset.chatType || "direct") : "direct";
        this.conversationId = messageForm ? (messageForm.dataset.conversation || null) : null;
        this.currentUsername = currentUsername || "";
        this.currentLabel = this.chatType === "group" ? (messageForm ? messageForm.dataset.alias : "") : this.currentUsername;
        this.currentUserId = typeof currentUserId === "number"
            ? currentUserId
            : (messageForm && messageForm.dataset.currentUserId
                ? Number(messageForm.dataset.currentUserId)
                : null);
        this.notificationPlayer = this.createNotificationPlayer();
    }

    init() {
        if (!this.socket) {
            return;
        }
        if (this.messageForm) {
            this.messageForm.addEventListener("submit", (event) => this.handleSubmit(event));
        }
        this.socket.on("receive_message", (payload) => {
            if (this.chatType !== "direct") {
                return;
            }
            this.handleIncoming(payload);
        });
        this.socket.on("receive_group_message", (payload) => {
            if (this.chatType !== "group") {
                return;
            }
            this.handleIncoming(payload);
        });
        this.socket.on("progress_update", (progress) => {
            if (window.updateProgressDisplay) {
                window.updateProgressDisplay(progress);
            }
        });
        this.socket.on("error", (payload) => {
            if (payload && payload.error) {
                alert(payload.error);
            }
        });
    }

    decorateAttachments(attachments) {
        if (!attachments || !attachments.length) {
            return [];
        }
        return attachments.map((attachment) => {
            if (attachment.url) {
                return attachment;
            }
            if (attachment.storage_path) {
                return {
                    ...attachment,
                    url: `/uploads/${attachment.storage_path}`,
                };
            }
            return attachment;
        });
    }

    async handleIncoming(payload) {
        if (!payload) {
            return;
        }
        const conversation = payload.conversation || null;
        if (this.conversationId && conversation && conversation !== this.conversationId) {
            return;
        }
        const messageText = await this.security.decryptPayload(payload, this.conversationId);
        const attachments = this.decorateAttachments(payload.attachments || []);
        const senderLabel = this.chatType === "group"
            ? (payload.alias || "Member")
            : (payload.username || payload.sender_username || payload.recipient || "User");
        if (window.appendMessage) {
            window.appendMessage(senderLabel, this.currentLabel, messageText, payload.timestamp, attachments);
        }
        const senderId = typeof payload.sender_id === "number" ? payload.sender_id : null;
        const isOwnMessage = (senderId && this.currentUserId && senderId === this.currentUserId)
            || (payload.username && payload.username === this.currentUsername)
            || (payload.alias && payload.alias === this.currentLabel);
        if (!isOwnMessage) {
            this.playNotification();
        }
        this.scrollToBottom();
    }

    scrollToBottom() {
        if (this.chatBox) {
            this.chatBox.scrollTop = this.chatBox.scrollHeight;
        }
    }

    handleSubmit(event) {
        event.preventDefault();
        if (!this.messageForm) {
            return;
        }
        const message = this.messageInput ? this.messageInput.value.trim() : "";
        const attachmentState = window.chatAttachmentState || { pendingUpload: null, clearPendingUpload: () => {} };
        const pendingUpload = attachmentState.pendingUpload;
        if (!message && !pendingUpload) {
            return;
        }
        if (pendingUpload) {
            const payload = {
                chat_type: this.chatType,
                caption: message,
                upload_token: pendingUpload.token,
            };
            if (this.chatType === "group") {
                payload.group_id = this.messageForm.dataset.groupId;
                payload.alias = this.messageForm.dataset.alias;
            } else {
                payload.username = this.messageForm.dataset.username;
                payload.recipient = this.messageForm.dataset.recipient;
            }
            this.socket.emit("send_media_message", payload);
            attachmentState.clearPendingUpload();
        } else if (this.chatType === "group") {
            this.socket.emit("send_group_message", {
                group_id: this.messageForm.dataset.groupId,
                alias: this.messageForm.dataset.alias,
                message,
            });
        } else {
            this.socket.emit("send_message", {
                username: this.messageForm.dataset.username,
                recipient: this.messageForm.dataset.recipient,
                message,
            });
        }
        if (this.messageInput) {
            this.messageInput.value = "";
        }
    }

    createNotificationPlayer() {
        const ContextClass = window.AudioContext || window.webkitAudioContext;
        if (!ContextClass) {
            return null;
        }
        const audioContext = new ContextClass();
        return () => {
            if (audioContext.state === "suspended") {
                audioContext.resume().catch(() => {});
            }
            const oscillator = audioContext.createOscillator();
            const gain = audioContext.createGain();
            oscillator.type = "triangle";
            oscillator.frequency.value = 880;
            gain.gain.setValueAtTime(0.0001, audioContext.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.08, audioContext.currentTime + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + 0.35);
            oscillator.connect(gain);
            gain.connect(audioContext.destination);
            oscillator.start();
            oscillator.stop(audioContext.currentTime + 0.4);
        };
    }

    playNotification() {
        if (typeof document === "undefined") {
            return;
        }
        if (document.hidden && this.notificationPlayer) {
            try {
                this.notificationPlayer();
            } catch (error) {
                console.warn("Unable to play notification", error);
            }
        } else if (this.notificationPlayer) {
            try {
                this.notificationPlayer();
            } catch (error) {
                console.warn("Unable to play notification", error);
            }
        }
    }
}

class TranslationController {
    constructor({ socket, toggle, languageSelect, sourceSelect, container, callId, voiceToggle }) {
        this.socket = socket;
        this.toggle = toggle;
        this.languageSelect = languageSelect;
        this.sourceSelect = sourceSelect;
        this.container = container;
        this.callId = callId;
        this.mediaRecorder = null;
        this.mediaStream = null;
        this.enabled = false;
        this.voiceToggle = voiceToggle || null;
        this.voiceEnabled = false;
        this.speechSynthesisSupported = typeof window !== 'undefined'
            && 'speechSynthesis' in window
            && typeof window.SpeechSynthesisUtterance !== 'undefined';
    }

    init() {
        if (!this.socket || !this.callId) {
            return;
        }
        this.socket.emit("join_call_room", { call_id: this.callId });
        if (this.toggle) {
            this.toggle.addEventListener("change", () => {
                if (this.toggle.checked) {
                    this.start();
                } else {
                    this.stop();
                }
            });
        }
        if (this.voiceToggle) {
            if (!this.speechSynthesisSupported) {
                this.voiceToggle.disabled = true;
                const wrapper = this.voiceToggle.closest('.form-check');
                if (wrapper) {
                    wrapper.classList.add('opacity-50');
                }
            } else {
                this.voiceEnabled = this.voiceToggle.checked;
                this.voiceToggle.addEventListener('change', () => {
                    this.voiceEnabled = this.voiceToggle.checked;
                });
            }
        }
        if (this.languageSelect) {
            this.languageSelect.addEventListener("change", () => this.updatePreferences());
        }
        if (this.sourceSelect) {
            this.sourceSelect.addEventListener("change", () => this.updatePreferences());
        }
        this.socket.on("translated_caption", (payload) => this.handleCaption(payload));
        this.socket.on("translation_error", (payload) => {
            if (!payload || payload.call_id !== this.callId) {
                return;
            }
            alert(payload.message || "Translation error occurred.");
        });
    }

    async start() {
        if (this.enabled) {
            return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert("Live translation requires microphone access.");
            this.toggle.checked = false;
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.mediaStream = stream;
            const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
            recorder.addEventListener("dataavailable", (event) => {
                if (!this.enabled || !event.data || !event.data.size) {
                    return;
                }
                const reader = new FileReader();
                reader.onloadend = () => {
                    const result = reader.result || "";
                    const parts = result.split(",");
                    if (parts.length < 2) {
                        return;
                    }
                    this.socket.emit("call_transcription_chunk", {
                        call_id: this.callId,
                        audio_chunk: parts[1],
                        source_language: this.sourceSelect ? this.sourceSelect.value : undefined,
                    });
                };
                reader.readAsDataURL(event.data);
            });
            recorder.start(1000);
            this.mediaRecorder = recorder;
            this.enabled = true;
            this.updatePreferences(true);
        } catch (error) {
            console.error("Unable to start translation stream", error);
            alert("Microphone access is required for live translation.");
            this.toggle.checked = false;
            this.stop();
        }
    }

    stop() {
        if (this.mediaRecorder) {
            this.mediaRecorder.stop();
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach((track) => track.stop());
        }
        this.mediaRecorder = null;
        this.mediaStream = null;
        this.enabled = false;
        this.updatePreferences(false);
    }

    updatePreferences(forceEnabled) {
        if (!this.socket || !this.callId) {
            return;
        }
        const enabled = typeof forceEnabled === "boolean" ? forceEnabled : this.enabled;
        this.socket.emit("set_translation_preferences", {
            call_id: this.callId,
            enabled,
            target_language: this.languageSelect ? this.languageSelect.value : "en",
            source_language: this.sourceSelect ? this.sourceSelect.value : undefined,
        });
    }

    handleCaption(payload) {
        if (!payload || payload.call_id !== this.callId || !this.container) {
            return;
        }
        const line = document.createElement("div");
        line.classList.add("caption-line", "mb-1", "small");
        line.dataset.language = (payload.target_language || "").toLowerCase();
        const badge = document.createElement("span");
        badge.classList.add("badge", "bg-secondary", "me-2");
        badge.textContent = (payload.target_language || "?").toUpperCase();
        const text = document.createElement("span");
        text.textContent = payload.translation || payload.transcript || "";
        line.appendChild(badge);
        line.appendChild(text);
        const placeholder = this.container.querySelector('[data-caption-placeholder="true"]');
        if (placeholder) {
            placeholder.remove();
        }
        this.container.appendChild(line);
        this.container.scrollTop = this.container.scrollHeight;
        if (this.voiceEnabled) {
            this.speakCaption(text.textContent || '', payload.target_language);
        }
    }

    speakCaption(text, language) {
        if (!this.speechSynthesisSupported || !text) {
            return;
        }
        try {
            if (window.speechSynthesis.speaking) {
                window.speechSynthesis.cancel();
            }
            const utterance = new window.SpeechSynthesisUtterance(text);
            if (language) {
                utterance.lang = language;
            }
            window.speechSynthesis.speak(utterance);
        } catch (error) {
            console.warn('Unable to speak translation', error);
        }
    }
}

class CallClient {
    constructor({
        socket,
        conversationId,
        callId,
        toolbar,
        startButtons,
        hangupButton,
        recipient,
        callContainer,
        localMedia,
        remoteMedia,
    }) {
        this.socket = socket;
        this.conversationId = conversationId || null;
        this.callId = callId || null;
        this.toolbar = toolbar || null;
        this.startButtons = Array.from(startButtons || []);
        this.hangupButton = hangupButton || null;
        this.recipient = recipient || null;
        this.callContainer = callContainer || null;
        this.localMedia = localMedia || null;
        this.remoteMedia = remoteMedia || null;
        this.muteSelfButton = this.toolbar ? this.toolbar.querySelector("[data-call-mute-self]") : null;
        this.muteRemoteButton = this.toolbar ? this.toolbar.querySelector("[data-call-mute-remote]") : null;
        this.sessionId = null;
        this.roomId = null;
        this.currentMode = "audio";
        this.isCaller = false;
        this.pc = null;
        this.localStream = null;
        this.remoteStream = null;
        this.pendingOffer = null;
        this.active = false;
        this.incomingModalElement = document.getElementById("incomingCallModal");
        this.incomingModal = this.incomingModalElement ? new bootstrap.Modal(this.incomingModalElement) : null;
        this.callStatusElement = document.getElementById("callStatusModal");
        this.callStatusModal = this.callStatusElement ? new bootstrap.Modal(this.callStatusElement) : null;
        this.incomingFromElement = document.getElementById("incoming-call-from");
        this.incomingAcceptButton = document.getElementById("incoming-call-accept");
        this.incomingDeclineButton = document.getElementById("incoming-call-decline");
        this.callStatusMessage = document.getElementById("call-status-message");
    }

    init() {
        if (!this.socket) {
            return;
        }
        this.startButtons.forEach((button) => {
            button.addEventListener("click", (event) => {
                const mode = event.currentTarget.dataset.callStart || "audio";
                this.startCall(mode);
            });
        });
        if (this.hangupButton) {
            this.hangupButton.addEventListener("click", () => this.hangup());
        }
        if (this.muteSelfButton) {
            this.muteSelfButton.addEventListener("click", () => this.toggleLocalMute());
        }
        if (this.muteRemoteButton) {
            this.muteRemoteButton.addEventListener("click", () => this.toggleRemoteMute());
        }
        if (this.incomingAcceptButton) {
            this.incomingAcceptButton.addEventListener("click", () => this.acceptIncomingCall());
        }
        if (this.incomingDeclineButton) {
            this.incomingDeclineButton.addEventListener("click", () => this.declineIncomingCall());
        }
        this.registerSocketEvents();
        window.addEventListener("beforeunload", () => {
            if (this.sessionId) {
                this.socket.emit("call_hangup", { sessionId: this.sessionId });
            }
        });
    }

    registerSocketEvents() {
        this.socket.on("call_outgoing", (payload) => this.handleOutgoing(payload));
        this.socket.on("call_incoming", (payload) => this.handleIncoming(payload));
        this.socket.on("call_answered", (payload) => this.handleAnswered(payload));
        this.socket.on("ice_candidate", (payload) => this.handleIceCandidate(payload));
        this.socket.on("call_ended", (payload) => this.handleEnded(payload));
        this.socket.on("call_declined", (payload) => this.handleDeclined(payload));
        this.socket.on("call_error", (payload) => this.handleCallError(payload));
    }

    async startCall(mode) {
        if (!this.recipient) {
            alert("Select a recipient before starting a call.");
            return;
        }
        if (this.active) {
            alert("You are already in a call.");
            return;
        }
        const normalizedMode = mode === "video" ? "video" : "audio";
        try {
            await this.prepareLocalStream(normalizedMode);
            this.currentMode = normalizedMode;
            this.isCaller = true;
            this.setupPeerConnection();
            this.addLocalTracks();
            const offer = await this.pc.createOffer();
            await this.pc.setLocalDescription(offer);
            this.showStatus(`Calling ${this.recipient}…`);
            this.updateUiState(true);
            this.socket.emit("call_request", {
                target: this.recipient,
                offer: this.pc.localDescription,
                mode: this.currentMode,
            });
        } catch (error) {
            console.error("Unable to start call", error);
            alert("Unable to access microphone or camera for the call.");
            this.cleanup();
        }
    }

    async prepareLocalStream(mode) {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            throw new Error("getUserMedia is not supported in this browser.");
        }
        const constraints = { audio: true, video: mode === "video" };
        this.localStream = await navigator.mediaDevices.getUserMedia(constraints);
        if (this.localMedia) {
            this.localMedia.srcObject = this.localStream;
            this.localMedia.classList.remove("d-none");
        }
        if (this.callContainer) {
            this.callContainer.classList.remove("d-none");
        }
        this.syncMuteControls();
    }

    setupPeerConnection() {
        if (this.pc) {
            this.pc.close();
        }
        this.pc = new RTCPeerConnection({
            iceServers: [
                { urls: "stun:stun.l.google.com:19302" },
            ],
        });
        this.pc.onicecandidate = (event) => {
            if (event.candidate && this.sessionId) {
                this.socket.emit("ice_candidate", {
                    sessionId: this.sessionId,
                    candidate: event.candidate,
                });
            }
        };
        this.pc.ontrack = (event) => {
            const [stream] = event.streams;
            if (stream) {
                this.attachRemoteStream(stream);
            }
        };
        this.pc.onconnectionstatechange = () => {
            if (!this.pc) {
                return;
            }
            if (["disconnected", "failed", "closed"].includes(this.pc.connectionState)) {
                this.cleanup();
            }
        };
    }

    addLocalTracks() {
        if (!this.pc || !this.localStream) {
            return;
        }
        this.localStream.getTracks().forEach((track) => {
            this.pc.addTrack(track, this.localStream);
        });
    }

    attachRemoteStream(stream) {
        this.remoteStream = stream;
        if (this.remoteMedia) {
            this.remoteMedia.srcObject = stream;
            this.remoteMedia.classList.remove("d-none");
        }
        if (this.callContainer) {
            this.callContainer.classList.remove("d-none");
        }
        this.syncMuteControls();
    }

    handleOutgoing(payload) {
        if (!payload || !this.isCaller) {
            return;
        }
        this.sessionId = payload.sessionId;
        this.roomId = payload.roomId;
        this.currentMode = payload.mode || this.currentMode;
    }

    handleIncoming(payload) {
        if (!payload) {
            return;
        }
        this.sessionId = payload.sessionId;
        this.roomId = payload.roomId;
        this.currentMode = payload.mode || "audio";
        this.pendingOffer = payload.offer;
        if (this.incomingFromElement) {
            this.incomingFromElement.textContent = payload.caller || "Unknown";
        }
        if (this.incomingModal) {
            this.incomingModal.show();
        }
        this.updateUiState(true);
    }

    async acceptIncomingCall() {
        if (!this.pendingOffer || !this.sessionId) {
            return;
        }
        try {
            await this.prepareLocalStream(this.currentMode);
            this.isCaller = false;
            this.setupPeerConnection();
            this.addLocalTracks();
            const remoteOffer = typeof RTCSessionDescription !== "undefined"
                ? new RTCSessionDescription(this.pendingOffer)
                : this.pendingOffer;
            await this.pc.setRemoteDescription(remoteOffer);
            const answer = await this.pc.createAnswer();
            await this.pc.setLocalDescription(answer);
            this.socket.emit("call_answer", {
                sessionId: this.sessionId,
                accepted: true,
                answer: this.pc.localDescription,
                mode: this.currentMode,
            });
            this.showStatus("Connecting…");
            if (this.incomingModal) {
                this.incomingModal.hide();
            }
            this.pendingOffer = null;
            this.active = true;
        } catch (error) {
            console.error("Unable to accept call", error);
            alert("Unable to connect to the call. Please check your microphone and camera permissions.");
            this.socket.emit("call_answer", {
                sessionId: this.sessionId,
                accepted: false,
            });
            this.cleanup();
        }
    }

    declineIncomingCall() {
        if (!this.sessionId) {
            return;
        }
        this.socket.emit("call_answer", {
            sessionId: this.sessionId,
            accepted: false,
        });
        if (this.incomingModal) {
            this.incomingModal.hide();
        }
        this.updateUiState(false);
        this.cleanup();
    }

    async handleAnswered(payload) {
        if (!payload || payload.sessionId !== this.sessionId || !this.pc) {
            return;
        }
        this.currentMode = payload.mode || this.currentMode;
        try {
            const remoteAnswer = typeof RTCSessionDescription !== "undefined"
                ? new RTCSessionDescription(payload.answer)
                : payload.answer;
            await this.pc.setRemoteDescription(remoteAnswer);
            this.hideStatus();
            this.active = true;
        } catch (error) {
            console.error("Failed to finalize call", error);
            this.cleanup();
        }
    }

    async handleIceCandidate(payload) {
        if (!payload || payload.sessionId !== this.sessionId || !this.pc) {
            return;
        }
        try {
            await this.pc.addIceCandidate(new RTCIceCandidate(payload.candidate));
        } catch (error) {
            console.warn("Unable to add ICE candidate", error);
        }
    }

    hangup() {
        if (!this.sessionId) {
            return;
        }
        this.socket.emit("call_hangup", { sessionId: this.sessionId });
        this.cleanup();
    }

    handleEnded(payload) {
        if (!payload || payload.sessionId !== this.sessionId) {
            return;
        }
        const endedBy = payload.endedBy ? `${payload.endedBy} ended the call.` : "Call ended.";
        this.showStatus(endedBy);
        setTimeout(() => this.hideStatus(), 1500);
        if (this.incomingModal) {
            this.incomingModal.hide();
        }
        this.cleanup();
    }

    handleDeclined(payload) {
        if (!payload || payload.sessionId !== this.sessionId) {
            return;
        }
        this.showStatus("The call was declined.");
        setTimeout(() => this.hideStatus(), 1500);
        if (this.incomingModal) {
            this.incomingModal.hide();
        }
        this.cleanup();
    }

    handleCallError(payload) {
        if (payload && payload.error) {
            alert(payload.error);
        }
        this.cleanup();
    }

    showStatus(message) {
        if (this.callStatusMessage) {
            this.callStatusMessage.textContent = message;
        }
        if (this.callStatusModal) {
            this.callStatusModal.show();
        }
    }

    hideStatus() {
        if (this.callStatusModal) {
            this.callStatusModal.hide();
        }
    }

    updateUiState(pending) {
        const inCall = Boolean(this.sessionId) || pending;
        this.startButtons.forEach((button) => {
            button.disabled = inCall;
        });
        if (this.hangupButton) {
            this.hangupButton.disabled = !inCall;
        }
        this.syncMuteControls();
    }

    cleanup() {
        this.active = false;
        this.pendingOffer = null;
        if (this.pc) {
            try {
                this.pc.close();
            } catch (error) {
                console.warn("Error closing peer connection", error);
            }
        }
        this.pc = null;
        if (this.localStream) {
            this.localStream.getTracks().forEach((track) => track.stop());
        }
        if (this.remoteStream) {
            this.remoteStream.getTracks().forEach((track) => track.stop());
        }
        this.localStream = null;
        this.remoteStream = null;
        if (this.localMedia) {
            this.localMedia.srcObject = null;
        }
        if (this.remoteMedia) {
            this.remoteMedia.srcObject = null;
            this.remoteMedia.muted = false;
        }
        if (this.callContainer) {
            this.callContainer.classList.add("d-none");
        }
        this.updateUiState(false);
        this.sessionId = null;
        this.roomId = null;
    }

    toggleLocalMute() {
        if (!this.localStream) {
            return;
        }
        const audioTracks = this.localStream.getAudioTracks();
        if (!audioTracks.length) {
            return;
        }
        const track = audioTracks[0];
        track.enabled = !track.enabled;
        this.syncMuteControls();
    }

    toggleRemoteMute() {
        if (!this.remoteMedia) {
            return;
        }
        this.remoteMedia.muted = !this.remoteMedia.muted;
        this.syncMuteControls();
    }

    syncMuteControls() {
        const hasLocal = Boolean(this.localStream);
        const localMuted = hasLocal ? this.localStream.getAudioTracks().some((track) => !track.enabled) : false;
        if (this.muteSelfButton) {
            this.muteSelfButton.disabled = !hasLocal;
            this.muteSelfButton.classList.toggle("active", localMuted);
            this.muteSelfButton.textContent = localMuted ? "Unmute Self" : "Mute Self";
        }
        const hasRemote = Boolean(this.remoteMedia && this.remoteMedia.srcObject);
        const remoteMuted = Boolean(this.remoteMedia && this.remoteMedia.muted);
        if (this.muteRemoteButton) {
            this.muteRemoteButton.disabled = !hasRemote;
            this.muteRemoteButton.classList.toggle("active", remoteMuted);
            this.muteRemoteButton.textContent = remoteMuted ? "Unmute Remote" : "Mute Remote";
        }
    }
}

function base64ToUint8Array(base64) {
    const normalized = base64.replace(/[^A-Za-z0-9+/=]/g, "");
    const binaryString = window.atob(normalized);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i += 1) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
}

document.addEventListener("DOMContentLoaded", async () => {
    const chatApp = document.getElementById("chat-app");
    if (!chatApp) {
        return;
    }
    const socket = io();
    const messageForm = document.getElementById("message-form");
    const chatBox = document.getElementById("chat-box");
    const translationToggle = document.getElementById("translation-toggle");
    const translationLanguage = document.getElementById("translation-language");
    const translationSource = document.getElementById("translation-source-language");
    const captionsContainer = document.getElementById("translated-captions");
    const translationVoiceToggle = document.getElementById("translation-voice");
    const currentUser = chatApp.dataset.currentUser || "";
    const conversationId = messageForm ? (messageForm.dataset.conversation || null) : null;
    const callId = messageForm ? (messageForm.dataset.callId || null) : null;

    const security = new ConversationSecurity(conversationId);
    await security.hydrateExistingMessages(chatBox);

    const currentUserId = chatApp.dataset.currentUserId ? Number(chatApp.dataset.currentUserId) : null;
    const messenger = new Messenger({
        socket,
        messageForm,
        chatBox,
        security,
        currentUsername: currentUser,
        currentUserId,
    });
    messenger.init();

    const translationController = new TranslationController({
        socket,
        toggle: translationToggle,
        languageSelect: translationLanguage,
        sourceSelect: translationSource,
        container: captionsContainer,
        callId,
        voiceToggle: translationVoiceToggle,
    });
    translationController.init();

    if (messageForm && messageForm.dataset.chatType === "group") {
        socket.emit("join_group_room", { group_id: messageForm.dataset.groupId });
    }

    const callToolbar = document.querySelector(".chat-call-toolbar");
    const callClient = new CallClient({
        socket,
        conversationId,
        callId,
        toolbar: callToolbar,
        startButtons: callToolbar ? callToolbar.querySelectorAll("[data-call-start]") : [],
        hangupButton: callToolbar ? callToolbar.querySelector("[data-call-hangup]") : null,
        recipient: messageForm ? messageForm.dataset.recipient : null,
        callContainer: document.querySelector("[data-call-container]") || null,
        localMedia: document.getElementById("local-media"),
        remoteMedia: document.getElementById("remote-media"),
    });
    callClient.init();
});
