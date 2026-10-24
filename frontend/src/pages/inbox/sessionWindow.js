const WARNING_MS = 12 * 60 * 60 * 1000;

// Server false always wins; the local clock can close a previously open window.
export function getSessionWindow(conversation, now = Date.now()) {
    if (!conversation || conversation.state === "closed") return { state: "inactive" };
    const expiresAt = Date.parse(conversation.session_window_expires_at);
    if (conversation.session_window_open === false) return { state: "closed", expiresAt };
    if (conversation.session_window_open !== true || !Number.isFinite(expiresAt)) {
        return { state: "unknown" };
    }
    const remaining = expiresAt - now;
    if (remaining < 0) return { state: "closed", expiresAt };
    return { state: remaining < WARNING_MS ? "closing" : "open", expiresAt,
        minutes: Math.ceil(remaining / 60000) };
}
