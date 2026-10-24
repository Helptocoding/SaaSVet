import { useCallback, useEffect, useState } from "react";
import { getInboxMedia } from "../../api/inbox";

// Only mounted consumers retain a blob. Refcounts deduplicate simultaneous views;
// the final release aborts pending I/O and revokes the URL on scroll/unmount/logout.
const cache = new Map();
const liveUrls = new Set();

export function acquireMediaUrl(publicId, scope) {
    const key = JSON.stringify([scope, publicId]);
    let entry = cache.get(key);
    if (!entry || entry.error) {
        entry = { refs: 0, controller: new AbortController(), url: null, error: null };
        const current = entry;
        current.promise = getInboxMedia(publicId, { signal: current.controller.signal }).then((blob) => {
            if (current.controller.signal.aborted || current.refs === 0) throw new DOMException("Aborted", "AbortError");
            if (!(blob instanceof Blob)) throw new Error("Invalid media response");
            current.url = URL.createObjectURL(blob);
            liveUrls.add(current.url);
            return current.url;
        }).catch((error) => { current.error = error; throw error; });
        cache.set(key, current);
    }
    entry.refs += 1;
    const owned = entry;
    let released = false;
    return { promise: owned.promise, release: () => {
        if (released) return;
        released = true;
        owned.refs -= 1;
        if (owned.refs === 0) {
            owned.controller.abort();
            if (owned.url) { liveUrls.delete(owned.url); URL.revokeObjectURL(owned.url); }
            if (cache.get(key) === owned) cache.delete(key);
        }
    } };
}

export default function useMediaUrl(publicId, { enabled = false, scope = "" } = {}) {
    const [attempt, setAttempt] = useState(0);
    const [snapshot, setSnapshot] = useState(null);
    const identity = JSON.stringify([scope, publicId, attempt]);
    useEffect(() => {
        if (!publicId || !enabled) return;
        let current = true;
        const handle = acquireMediaUrl(publicId, scope);
        handle.promise.then((url) => { if (current) setSnapshot({ identity, url, error: null }); })
            .catch((error) => { if (current && error.name !== "AbortError") setSnapshot({ identity, url: null, error }); });
        return () => { current = false; handle.release(); };
    }, [publicId, scope, enabled, identity]);
    const current = enabled && snapshot?.identity === identity
        && (snapshot.error || liveUrls.has(snapshot.url)) ? snapshot : null;
    const retry = useCallback(() => setAttempt((value) => value + 1), []);
    return { url: current?.url || null, error: current?.error || null,
        loading: Boolean(enabled && !current), retry };
}
