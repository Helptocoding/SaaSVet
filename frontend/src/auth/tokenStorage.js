/**
 * Token storage abstraction for the "Recordarme" flow.
 *
 * Two backing stores:
 *   - localStorage   → persists across browser restarts (remember=true)
 *   - sessionStorage → per-tab, cleared on tab/browser close (remember=false)
 *
 * INVARIANT: valid auth tokens MUST NOT coexist in localStorage and
 * sessionStorage simultaneously. `setTokens()` enforces this by wiping the
 * non-target store before writing. Any caller that bypasses this module and
 * writes raw storage keys violates the invariant and will produce ambiguous
 * session state.
 *
 * READ PRIORITY: sessionStorage > localStorage. A short-lived tab session must
 * win over a stale persistent session inside the same tab. Reversing this
 * priority leaks identities (persistent session impersonates a temp one).
 *
 * SOURCE OF TRUTH: presence of "access_token" in either store. The
 * `auth_persist` flag is METADATA ONLY — never read for store-selection
 * decisions. It can desync (browser crash, devtools edit, extension tampering)
 * and trusting it would corrupt session routing.
 *
 * LOGOUT FLAG: `clearTokens()` raises a module-level `loggingOut` flag.
 * `isLoggingOut()` lets in-flight async work (refresh callbacks, queued
 * requests) check before mutating auth state and avoid resurrecting a session
 * the user just terminated. `setTokens()` clears the flag — a fresh login
 * cancels the lockout. Any future shared `refreshPromise` singleton must also
 * be nulled inside `clearTokens()` for the same reason.
 *
 * All auth storage access in the app MUST go through this module. Direct
 * `localStorage.getItem("access_token")` / `sessionStorage.*` calls outside
 * here are bugs — they erode the invariant over time.
 */

const KEYS = ["access_token", "refresh_token", "user"];
const PERSIST_FLAG = "auth_persist"; // metadata only — never read as authority

let loggingOut = false;

function activeStore() {
    // Authority: presence of access_token. NOT the persist flag.
    if (sessionStorage.getItem("access_token")) return sessionStorage;
    if (localStorage.getItem("access_token")) return localStorage;
    return localStorage;
}

export function getItem(key) {
    const fromSession = sessionStorage.getItem(key);
    if (fromSession !== null) return fromSession;
    return localStorage.getItem(key);
}

export function setTokens({ access, refresh, remember }) {
    const target = remember ? localStorage : sessionStorage;
    const other = remember ? sessionStorage : localStorage;
    KEYS.forEach(k => other.removeItem(k));
    other.removeItem(PERSIST_FLAG);
    target.setItem("access_token", access);
    target.setItem("refresh_token", refresh);
    target.setItem(PERSIST_FLAG, remember ? "1" : "0");
    // Fresh login cancels any prior logout lockout.
    loggingOut = false;
}

export function setAccessToken(access) {
    activeStore().setItem("access_token", access);
}

export function setUser(user) {
    activeStore().setItem("user", JSON.stringify(user));
}

export function clearTokens() {
    loggingOut = true;
    KEYS.forEach(k => {
        localStorage.removeItem(k);
        sessionStorage.removeItem(k);
    });
    localStorage.removeItem(PERSIST_FLAG);
    sessionStorage.removeItem(PERSIST_FLAG);
}

export function isLoggingOut() {
    return loggingOut;
}
