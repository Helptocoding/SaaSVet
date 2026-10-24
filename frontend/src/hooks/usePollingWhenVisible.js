import { useEffect } from "react";

// The callback owns its request/error handling. Keep it stable with useCallback;
// changing it starts a new cycle (e.g. a different Inbox filter or thread).
export default function usePollingWhenVisible(callback, intervalMs, enabled = true) {
    useEffect(() => {
        if (!enabled) return;
        let timer = null;
        let initial = true;
        const stop = () => {
            if (timer !== null) clearInterval(timer);
            timer = null;
        };
        const poll = () => {
            // Also guard a tick already queued when visibility changed.
            if (document.hidden) return;
            callback({ initial });
            initial = false;
        };
        const syncVisibility = () => {
            if (document.hidden) {
                stop();
            } else if (timer === null) {
                poll();
                timer = setInterval(poll, intervalMs);
            }
        };
        document.addEventListener("visibilitychange", syncVisibility);
        syncVisibility();
        return () => {
            stop();
            document.removeEventListener("visibilitychange", syncVisibility);
        };
    }, [callback, intervalMs, enabled]);
}
