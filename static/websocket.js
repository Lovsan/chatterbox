// This script handles the WebSocket communication between the client and the server

document.addEventListener("DOMContentLoaded", () => {
    const chatApp = document.getElementById("chat-app");
    if (!chatApp || !window.chatTabs) {
        return;
    }

    const socket = io();
    const currentUsername = window.chatTabs.getCurrentUser();

    document.addEventListener("submit", event => {
        const form = event.target;
        if (!form.classList.contains("message-form")) {
            return;
        }

        event.preventDefault();
        const input = form.querySelector("input[name='message']");
        const message = input ? input.value.trim() : "";
        if (!message) {
            return;
        }

        socket.emit("send_message", {
            username: form.dataset.username,
            recipient: form.dataset.recipient,
            message
document.addEventListener("DOMContentLoaded", function() {
    const socket = io();
    const messageForm = document.getElementById("message-form");
    const messageInput = document.getElementById("message-input");
    const attachmentState = window.chatAttachmentState || { pendingUpload: null, clearPendingUpload: () => {} };
    const translationToggle = document.getElementById("translation-toggle");
    const translationLanguage = document.getElementById("translation-language");
    const translationSourceLanguage = document.getElementById("translation-source-language");
    const captionsContainer = document.getElementById("translated-captions");
    const callId = messageForm ? messageForm.dataset.callId : (translationToggle ? translationToggle.dataset.callId : null);

    const translationState = {
        enabled: false,
        mediaRecorder: null,
        mediaStream: null,
        callId,
    };

    if (callId) {
        socket.emit("join_call_room", { call_id: callId });
    }

    function filterCaptionsByLanguage() {
        if (!captionsContainer) {
            return;
        }
        const selected = translationLanguage ? translationLanguage.value.toLowerCase() : "";
        const lines = captionsContainer.querySelectorAll(".caption-line");
        lines.forEach((line) => {
            const lang = (line.dataset.language || "").toLowerCase();
            if (!selected || !lang || lang === selected) {
                line.classList.remove("d-none");
            } else {
                line.classList.add("d-none");
            }
        });
    }

    function appendCaption(payload) {
        if (!captionsContainer) {
            return;
        }
        if (payload.call_id && translationState.callId && payload.call_id !== translationState.callId) {
            return;
        }
        const placeholder = captionsContainer.querySelector('[data-caption-placeholder="true"]');
        if (placeholder) {
            placeholder.remove();
        }
        const captionLine = document.createElement("div");
        captionLine.classList.add("caption-line", "mb-1", "small");
        captionLine.dataset.language = (payload.target_language || "").toLowerCase();
        const badge = document.createElement("span");
        badge.classList.add("badge", "bg-secondary", "me-2");
        badge.textContent = (payload.target_language || "?").toUpperCase();
        const textSpan = document.createElement("span");
        textSpan.textContent = payload.translation || payload.transcript || "";
        captionLine.appendChild(badge);
        captionLine.appendChild(textSpan);
        captionsContainer.appendChild(captionLine);
        filterCaptionsByLanguage();
        captionsContainer.scrollTop = captionsContainer.scrollHeight;
    }

    function stopTranslationStream() {
        if (translationState.mediaRecorder) {
            translationState.mediaRecorder.stop();
            translationState.mediaRecorder = null;
        }
        if (translationState.mediaStream) {
            translationState.mediaStream.getTracks().forEach((track) => track.stop());
            translationState.mediaStream = null;
        }
        translationState.enabled = false;
    }

    async function startTranslationStream() {
        if (!callId) {
            console.warn("No call identifier available for translation.");
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            translationState.mediaStream = stream;
            const options = { mimeType: "audio/webm;codecs=opus" };
            const recorder = new MediaRecorder(stream, options);
            recorder.addEventListener("dataavailable", (event) => {
                if (!event.data || event.data.size === 0 || !translationState.enabled) {
                    return;
                }
                const reader = new FileReader();
                reader.onloadend = function() {
                    const base64Data = (reader.result || "").split(",")[1];
                    if (!base64Data) {
                        return;
                    }
                    socket.emit("call_transcription_chunk", {
                        call_id: callId,
                        audio_chunk: base64Data,
                        source_language: translationSourceLanguage ? translationSourceLanguage.value : undefined,
                    });
                };
                reader.readAsDataURL(event.data);
            });
            recorder.start(1000);
            translationState.mediaRecorder = recorder;
            translationState.enabled = true;
            socket.emit("join_call_room", { call_id: callId });
            socket.emit("set_translation_preferences", {
                call_id: callId,
                enabled: true,
                target_language: translationLanguage ? translationLanguage.value : "en",
                source_language: translationSourceLanguage ? translationSourceLanguage.value : undefined,
            });
        } catch (error) {
            console.error("Unable to start translation stream", error);
            stopTranslationStream();
            alert("Unable to access microphone for live translation.");
        }
    }

    function updateTranslationPreferences() {
        if (!callId) {
            return;
        }
        socket.emit("set_translation_preferences", {
            call_id: callId,
            enabled: translationState.enabled,
            target_language: translationLanguage ? translationLanguage.value : "en",
            source_language: translationSourceLanguage ? translationSourceLanguage.value : undefined,
        });
    }

    // ---------------------------------------------------------------------
    // chat messaging
    // ---------------------------------------------------------------------
    if (messageForm && messageForm.dataset.chatType === "group") {
        socket.emit("join_group_room", { group_id: messageForm.dataset.groupId });
    }

    if (messageForm) {
        messageForm.addEventListener("submit", (event) => {
            event.preventDefault();

            if (!messageInput) {
                return;
            }

            const message = messageInput ? messageInput.value.trim() : "";
            const pendingUpload = attachmentState.pendingUpload;

            if (!message && !pendingUpload) {
                return;
            }

            const chatType = messageForm.dataset.chatType;
            if (pendingUpload) {
                const payload = {
                    chat_type: chatType,
                    caption: message,
                    upload_token: pendingUpload.token,
                };

                if (chatType === "group") {
                    payload.group_id = messageForm.dataset.groupId;
                    payload.alias = messageForm.dataset.alias;
                } else {
                    payload.username = messageForm.dataset.username;
                    payload.recipient = messageForm.dataset.recipient;
                }

                socket.emit("send_media_message", payload);
            } else if (chatType === "group") {
                socket.emit("send_group_message", {
                    group_id: messageForm.dataset.groupId,
                    alias: messageForm.dataset.alias,
                    message: message,
                });
            } else {
                socket.emit("send_message", {
                    username: messageForm.dataset.username,
                    recipient: messageForm.dataset.recipient,
                    message: message,
                });
            }

            if (messageInput) {
                messageInput.value = "";
            }
            if (attachmentState && typeof attachmentState.clearPendingUpload === 'function') {
                attachmentState.clearPendingUpload();
            }
        });
    }

    if (translationToggle) {
        translationToggle.addEventListener("change", function(event) {
            if (event.target.checked) {
                startTranslationStream();
            } else {
                stopTranslationStream();
                updateTranslationPreferences();
            }
        });
    }

    if (translationLanguage) {
        translationLanguage.addEventListener("change", function() {
            updateTranslationPreferences();
            filterCaptionsByLanguage();
        });
        filterCaptionsByLanguage();
    }

    if (translationSourceLanguage) {
        translationSourceLanguage.addEventListener("change", function() {
            updateTranslationPreferences();
        });

        input.value = "";
    });

    socket.on("receive_message", data => {
        const chatTabs = window.chatTabs;
        if (!chatTabs) {
            return;
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
            appendMessage(
                data.username,
                currentUsername,
                data.message,
                data.timestamp,
                data.attachments || []
            );
        }
    });

    socket.on("receive_group_message", (data) => {
        if (!messageForm || messageForm.dataset.chatType !== "group") {
            return;
        }
        if (String(data.group_id) !== String(messageForm.dataset.groupId)) {
            return;
        }
        appendMessage(
            data.alias,
            messageForm.dataset.alias,
            data.message,
            data.timestamp,
            data.attachments || []
        );
    });

    socket.on("progress_update", (data) => {
        updateProgressDisplay(data);
    });

    socket.on("error", (data) => {
        if (data && data.error) {
            console.warn("Chat error:", data.error);
            alert(data.error);
        }
    });

    socket.on("translated_caption", function(payload) {
        appendCaption(payload || {});
    });

    socket.on("translation_error", function(payload) {
        if (!payload || !payload.message) {
            return;
        }
        console.warn("Translation error:", payload.message);
        if (captionsContainer) {
            const errorLine = document.createElement("div");
            errorLine.classList.add("text-danger", "small", "mb-1");
            errorLine.textContent = payload.message;
            captionsContainer.appendChild(errorLine);
            captionsContainer.scrollTop = captionsContainer.scrollHeight;
        }

        const isSender = data.username === currentUsername;
        const otherParticipantId = isSender ? data.recipient_id : data.sender_id;
        const otherParticipantUsername = isSender ? data.recipient : data.username;
        const key = chatTabs.getDirectConversationKey(otherParticipantId);

        chatTabs.ensureConversation({
            id: otherParticipantId,
            name: otherParticipantUsername,
            display_name: otherParticipantUsername,
            type: "direct"
        }, { activate: false });

        chatTabs.appendMessage(key, {
            username: data.username,
            message: data.message,
            timestamp: data.timestamp
        });
    });
});
