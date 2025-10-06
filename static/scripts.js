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

function appendMessage(senderLabel, currentLabel, message, timestamp) {
    const chatBox = document.getElementById("chat-box");
    if (!chatBox) {
        return;
    }

    const messageElement = document.createElement("div");
    messageElement.classList.add("mb-2");

    const label = senderLabel === currentLabel ? 'You' : senderLabel;
    const titleDate = timestamp ? new Date(timestamp) : new Date();
    messageElement.innerHTML = `
        <strong class="${label === 'You' ? 'text-primary' : 'text-secondary'}">${label}:</strong>
        ${message}
    `;
    messageElement.setAttribute("title", titleDate.toLocaleString());

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
