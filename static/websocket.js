// This script handles the WebSocket communication between the client and the server

document.addEventListener("DOMContentLoaded", () => {
    const socket = io();
    const messageForm = document.getElementById("message-form");
    const messageInput = document.getElementById("message-input");

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

            const message = messageInput.value.trim();
            if (!message) {
                return;
            }

            const chatType = messageForm.dataset.chatType;
            if (chatType === "group") {
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

            messageInput.value = "";
        });
    }

    socket.on("receive_message", (data) => {
        if (!messageForm || messageForm.dataset.chatType !== "direct") {
            return;
        }
        const currentUsername = messageForm.dataset.username;
        const activeRecipient = messageForm.dataset.recipient;
        if (
            (data.recipient === currentUsername && data.username === activeRecipient) ||
            (data.username === currentUsername && data.recipient === activeRecipient)
        ) {
            appendMessage(data.username, currentUsername, data.message, data.timestamp);
        }
    });

    socket.on("receive_group_message", (data) => {
        if (!messageForm || messageForm.dataset.chatType !== "group") {
            return;
        }
        if (String(data.group_id) !== String(messageForm.dataset.groupId)) {
            return;
        }
        appendMessage(data.alias, messageForm.dataset.alias, data.message, data.timestamp);
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

    // ---------------------------------------------------------------------
    // WebRTC call handling
    // ---------------------------------------------------------------------
    const callStartButton = document.getElementById("call-start-btn");
    const callAcceptButton = document.getElementById("call-accept-btn");
    const callHangupButton = document.getElementById("call-hangup-btn");
    const callStatusBanner = document.getElementById("call-status-banner");
    const callVideoContainer = document.getElementById("call-video-container");
    const localVideo = document.getElementById("local-video");
    const remoteVideo = document.getElementById("remote-video");
    const incomingModalElement = document.getElementById("incomingCallModal");
    const incomingModal = incomingModalElement ? new bootstrap.Modal(incomingModalElement) : null;
    const incomingCallFrom = document.getElementById("incoming-call-from");
    const incomingAcceptButton = document.getElementById("incoming-call-accept");
    const incomingDeclineButton = document.getElementById("incoming-call-decline");
    const callStatusModalElement = document.getElementById("callStatusModal");
    const callStatusModal = callStatusModalElement ? new bootstrap.Modal(callStatusModalElement) : null;
    const callStatusMessage = document.getElementById("call-status-message");

    const rtcConfig = {
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    };

    let peerConnection = null;
    let localStream = null;
    let remoteStream = null;
    let callState = "idle";
    let currentCall = null;

    function isDirectChat() {
        return messageForm && messageForm.dataset.chatType === "direct";
    }

    function setBanner(message) {
        if (!callStatusBanner) {
            return;
        }
        if (!message) {
            callStatusBanner.hidden = true;
            callStatusBanner.textContent = "";
            return;
        }
        callStatusBanner.hidden = false;
        callStatusBanner.textContent = message;
    }

    function showStatus(message) {
        if (callStatusModal && callStatusMessage) {
            callStatusMessage.textContent = message;
            callStatusModal.show();
        } else {
            setBanner(message);
        }
    }

    function hideStatus() {
        if (callStatusModal) {
            callStatusModal.hide();
        }
        setBanner("");
    }

    function updateControls() {
        if (!callStartButton || !callHangupButton || !callAcceptButton) {
            return;
        }

        const acceptVisible = callState === "ringing";
        const hangupVisible = ["calling", "active", "ringing"].includes(callState);
        const startVisible = callState === "idle";

        callStartButton.classList.toggle("d-none", !startVisible);
        callHangupButton.classList.toggle("d-none", !hangupVisible);
        callAcceptButton.classList.toggle("d-none", !acceptVisible);
    }

    function resetVideo() {
        if (callVideoContainer) {
            callVideoContainer.classList.add("d-none");
        }
        if (localVideo) {
            localVideo.srcObject = null;
        }
        if (remoteVideo) {
            remoteVideo.srcObject = null;
        }
        remoteStream = null;
    }

    function showVideo() {
        if (callVideoContainer) {
            callVideoContainer.classList.remove("d-none");
        }
    }

    async function ensureLocalStream() {
        if (localStream) {
            return localStream;
        }
        try {
            localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
            if (localVideo) {
                localVideo.srcObject = localStream;
            }
            showVideo();
            return localStream;
        } catch (error) {
            console.error("Media capture failed", error);
            showStatus("Microphone or camera access was denied.");
            throw error;
        }
    }

    function createPeerConnection() {
        if (peerConnection) {
            peerConnection.close();
        }
        peerConnection = new RTCPeerConnection(rtcConfig);
        peerConnection.onicecandidate = (event) => {
            if (event.candidate && currentCall) {
                socket.emit("ice_candidate", {
                    sessionId: currentCall.id,
                    candidate: event.candidate,
                });
            }
        };
        peerConnection.ontrack = (event) => {
            if (!remoteStream) {
                remoteStream = new MediaStream();
                if (remoteVideo) {
                    remoteVideo.srcObject = remoteStream;
                }
            }
            event.streams[0].getTracks().forEach((track) => {
                remoteStream.addTrack(track);
            });
            showVideo();
        };

        if (localStream) {
            localStream.getTracks().forEach((track) => {
                peerConnection.addTrack(track, localStream);
            });
        }

        return peerConnection;
    }

    function cleanupCall(message) {
        if (peerConnection) {
            peerConnection.ontrack = null;
            peerConnection.onicecandidate = null;
            peerConnection.close();
            peerConnection = null;
        }
        if (localStream) {
            localStream.getTracks().forEach((track) => track.stop());
            localStream = null;
        }
        resetVideo();
        callState = "idle";
        currentCall = null;
        updateControls();
        hideStatus();
        if (incomingModal) {
            incomingModal.hide();
        }
        if (message) {
            setBanner(message);
        }
    }

    async function startOutgoingCall() {
        if (!isDirectChat() || callState !== "idle" || !callStartButton) {
            return;
        }
        const recipient = callStartButton.dataset.recipient;
        if (!recipient) {
            return;
        }

        try {
            await ensureLocalStream();
        } catch (error) {
            return;
        }

        createPeerConnection();
        callState = "calling";
        currentCall = {
            id: null,
            roomId: null,
            partner: recipient,
            role: "caller",
        };
        updateControls();
        showStatus(`Calling ${recipient}…`);

        try {
            const offer = await peerConnection.createOffer();
            await peerConnection.setLocalDescription(offer);
            socket.emit("call_request", {
                target: recipient,
                offer: offer,
            });
        } catch (error) {
            console.error("Failed to start call", error);
            cleanupCall("Could not start the call.");
        }
    }

    async function acceptIncomingCall() {
        if (!currentCall || currentCall.role !== "callee") {
            return;
        }
        try {
            await ensureLocalStream();
        } catch (error) {
            declineIncomingCall();
            return;
        }

        createPeerConnection();
        updateControls();

        try {
            await peerConnection.setRemoteDescription(new RTCSessionDescription(currentCall.offer));
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);
            callState = "active";
            showStatus("Call connected.");
            socket.emit("call_answer", {
                sessionId: currentCall.id,
                accepted: true,
                answer: answer,
            });
        } catch (error) {
            console.error("Failed to accept call", error);
            cleanupCall("Call could not be connected.");
            socket.emit("call_answer", {
                sessionId: currentCall.id,
                accepted: false,
            });
        }
    }

    function declineIncomingCall() {
        if (!currentCall) {
            return;
        }
        socket.emit("call_answer", {
            sessionId: currentCall.id,
            accepted: false,
        });
        cleanupCall("Call declined.");
    }

    function hangupCall() {
        if (!currentCall) {
            cleanupCall();
            return;
        }
        socket.emit("call_hangup", { sessionId: currentCall.id });
        cleanupCall("Call ended.");
    }

    if (callStartButton) {
        callStartButton.addEventListener("click", startOutgoingCall);
    }
    if (callAcceptButton) {
        callAcceptButton.addEventListener("click", acceptIncomingCall);
    }
    if (callHangupButton) {
        callHangupButton.addEventListener("click", hangupCall);
    }
    if (incomingAcceptButton) {
        incomingAcceptButton.addEventListener("click", () => {
            if (incomingModal) {
                incomingModal.hide();
            }
            acceptIncomingCall();
        });
    }
    if (incomingDeclineButton) {
        incomingDeclineButton.addEventListener("click", () => {
            declineIncomingCall();
        });
    }

    function handleIncomingCall(data) {
        if (callState !== "idle") {
            socket.emit("call_answer", { sessionId: data.sessionId, accepted: false });
            return;
        }
        if (!isDirectChat()) {
            showStatus(`Incoming call from ${data.caller}. Open their chat to answer.`);
            return;
        }
        if (messageForm.dataset.recipient !== data.caller) {
            showStatus(`Incoming call from ${data.caller}. Switch chats to respond.`);
            return;
        }

        currentCall = {
            id: data.sessionId,
            roomId: data.roomId,
            partner: data.caller,
            offer: data.offer,
            role: "callee",
        };
        callState = "ringing";
        updateControls();
        setBanner(`Incoming call from ${data.caller}`);
        if (incomingCallFrom) {
            incomingCallFrom.textContent = data.caller;
        }
        if (incomingModal) {
            incomingModal.show();
        }
    }

    socket.on("call_outgoing", (data) => {
        if (!currentCall || currentCall.role !== "caller") {
            return;
        }
        currentCall.id = data.sessionId;
        currentCall.roomId = data.roomId;
        callState = "calling";
        updateControls();
        setBanner(`Calling ${currentCall.partner}…`);
    });

    socket.on("call_incoming", (data) => {
        handleIncomingCall(data);
    });

    socket.on("call_answered", async (data) => {
        if (!currentCall || data.sessionId !== currentCall.id) {
            return;
        }
        if (currentCall.role === "caller" && peerConnection) {
            try {
                await peerConnection.setRemoteDescription(new RTCSessionDescription(data.answer));
                callState = "active";
                setBanner("Call connected.");
                showVideo();
            } catch (error) {
                console.error("Failed to process answer", error);
                cleanupCall("Call failed to connect.");
            }
        }
    });

    socket.on("call_declined", (data) => {
        if (!currentCall || data.sessionId !== currentCall.id) {
            return;
        }
        cleanupCall("Call was declined.");
    });

    socket.on("call_ended", (data) => {
        if (!currentCall || data.sessionId !== currentCall.id) {
            cleanupCall("Call ended.");
            return;
        }
        const endedBy = data.endedBy ? ` by ${data.endedBy}` : "";
        cleanupCall(`Call ended${endedBy}.`);
    });

    socket.on("ice_candidate", async (data) => {
        if (!currentCall || data.sessionId !== currentCall.id || !peerConnection) {
            return;
        }
        try {
            await peerConnection.addIceCandidate(new RTCIceCandidate(data.candidate));
        } catch (error) {
            console.error("Error adding ICE candidate", error);
        }
    });

    socket.on("call_error", (data) => {
        const message = data && data.error ? data.error : "Call error";
        console.warn("Call error:", message);
        cleanupCall(message);
    });
});
