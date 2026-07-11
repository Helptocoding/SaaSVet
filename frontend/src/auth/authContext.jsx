import { createContext, useContext, useState, useEffect, useRef, useCallback } from "react";
import { getItem, setTokens, setAccessToken, setRefreshToken, setUser as storeUser, clearTokens, isLoggingOut } from "./tokenStorage";

const AuthContext = createContext();

const rawBase = import.meta.env.VITE_API_URL || "";
const API_BASE = rawBase.endsWith("/") ? rawBase : rawBase + "/";

const REFRESH_BEFORE_EXPIRY_MS = 5 * 60 * 1000; // refrescar 5 min antes de expirar

function getTokenExp(token) {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return payload.exp * 1000; // exp en segundos → ms
    } catch {
        return null;
    }
}

export const AuthProvider = ({ children }) => {
    const [token, setToken] = useState(null);
    const [user, setUser] = useState(null);
    const [initializing, setInitializing] = useState(true);
    const [permissions, setPermissions] = useState(() => new Set());
    const refreshTimerRef = useRef(null);

    const logout = useCallback(() => {
        if (refreshTimerRef.current) {
            clearTimeout(refreshTimerRef.current);
            refreshTimerRef.current = null;
        }
        clearTokens();
        setToken(null);
        setUser(null);
        setPermissions(new Set());
    }, []);

    const scheduleTokenRefresh = useCallback((accessToken) => {
        if (refreshTimerRef.current) {
            clearTimeout(refreshTimerRef.current);
        }

        const exp = getTokenExp(accessToken);
        if (!exp) return;

        const delay = Math.max(exp - Date.now() - REFRESH_BEFORE_EXPIRY_MS, 0);

        refreshTimerRef.current = setTimeout(async () => {
            const storedRefresh = getItem("refresh_token");
            if (!storedRefresh) {
                logout();
                return;
            }

            try {
                const res = await fetch(`${API_BASE}token/refresh/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ refresh: storedRefresh }),
                });

                // Guard against zombie revival: if the user logged out while
                // this fetch was in flight, drop the response. Without this
                // check, a late 200 would re-seed tokens and restore the
                // session the user just terminated.
                if (isLoggingOut()) {
                    return;
                }

                if (res.ok) {
                    const data = await res.json();
                    setAccessToken(data.access);
                    setRefreshToken(data.refresh);
                    setToken(data.access);
                    scheduleTokenRefresh(data.access);
                } else {
                    logout();
                }
            } catch (err) {
                if (isLoggingOut()) return;
                console.error("[Auth] Token refresh failed", err);
                logout();
            }
        }, delay);
    }, [logout]);

    // ── Shared: persist tokens + update React state + schedule next refresh ──
    // Used by login() and by the session-restore path inside the init effect.
    const applyTokensAndScheduleRefresh = useCallback((access, refresh, remember) => {
        setTokens({ access, refresh, remember });
        setToken(access);
        scheduleTokenRefresh(access);
    }, [scheduleTokenRefresh]);

    // ── Init state machine ────────────────────────────────────────────────
    // States: UNKNOWN → LOGIN | FETCH_USER | RESTORING_SESSION
    //
    // UNKNOWN            no access_token in storage        → LOGIN
    // UNKNOWN            access_token valid (exp > now)    → FETCH_USER
    // UNKNOWN            access_token expired              → RESTORING_SESSION
    // RESTORING_SESSION  refresh ok                        → FETCH_USER
    // RESTORING_SESSION  refresh fail / no refresh token   → LOGIN
    // FETCH_USER         /me/ ok                           → AUTHENTICATED
    // FETCH_USER         /me/ fail                         → LOGIN
    //
    // Critical invariant: `initializing` stays true across the entire
    // RESTORING_SESSION → FETCH_USER chain. It only becomes false when the
    // chain reaches a terminal state (LOGIN or AUTHENTICATED). This prevents
    // PrivateRoute from mounting protected routes with a stale/expired token.
    useEffect(() => {
        const storedToken = getItem("access_token");

        // ── UNKNOWN → LOGIN: no token at all ──────────────────────────
        if (!storedToken) {
            setInitializing(false);
            return;
        }

        const exp = getTokenExp(storedToken);
        const isValid = exp && exp > Date.now();

        // ── UNKNOWN → FETCH_USER: token is still valid ────────────────
        if (isValid) {
            setToken(storedToken);
            scheduleTokenRefresh(storedToken);

            fetch(`${API_BASE}me/`, {
                headers: { Authorization: `Bearer ${storedToken}` },
            })
                .then(res => res.ok ? res.json() : null)
                .then(data => {
                    if (data) {
                        storeUser(data);
                        setUser(data);
                        setPermissions(Object.freeze(new Set(data.permissions || [])));
                    } else {
                        // Valid token but /me/ rejected → force clean login
                        logout();
                    }
                })
                .catch(() => {
                    logout();
                })
                .finally(() => setInitializing(false));

            return;
        }

        // ── UNKNOWN → RESTORING_SESSION: token expired ────────────────

        const storedRefresh = getItem("refresh_token");

        if (!storedRefresh) {
            clearTokens();
            setInitializing(false);
            return;
        }

        // Reconstruct `remember` from the explicit flag written by
        // setTokens() at login time — never inferred from store choice.
        const remember = getItem("auth_persist") !== "0";

        // Async session restoration. No React state is mutated until
        // the refresh succeeds AND /me/ validates the new token.
        (async () => {
            try {
                // Step 1 — Refresh (T4/T5/T6)
                const refreshRes = await fetch(`${API_BASE}token/refresh/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ refresh: storedRefresh }),
                });

                if (!refreshRes.ok) {
                    clearTokens();
                    setInitializing(false);
                    return;
                }

                const tokens = await refreshRes.json();

                // Persist both tokens, update React state, schedule next
                // periodic refresh — reuses the same helper as login().
                applyTokensAndScheduleRefresh(tokens.access, tokens.refresh, remember);

                // Step 2 — Validate with backend (T7/T8)
                const meRes = await fetch(`${API_BASE}me/`, {
                    headers: { Authorization: `Bearer ${tokens.access}` },
                });

                if (meRes.ok) {
                    const userData = await meRes.json();
                    storeUser(userData);
                    setUser(userData);
                    setPermissions(Object.freeze(new Set(userData.permissions || [])));
                } else {
                    // Refresh succeeded but the backend rejects this user.
                    // Do NOT fall back to cached data — the session is invalid.
                    logout();
                }
            } catch (err) {
                console.error("[Auth] Session restoration failed", err);
                logout();
            } finally {
                setInitializing(false);
            }
        })();

        return () => {
            if (refreshTimerRef.current) {
                clearTimeout(refreshTimerRef.current);
            }
        };
    }, [applyTokensAndScheduleRefresh, scheduleTokenRefresh]);

    const login = (accessToken, refreshToken, remember = true) => {
        applyTokensAndScheduleRefresh(accessToken, refreshToken, remember);
    };

    const setUserData = (userData) => {
        storeUser(userData);
        setUser(userData);
        setPermissions(Object.freeze(new Set(userData.permissions || [])));
    };

    // Re-lee /me/ con el access token vigente y refresca user + permisos en React
    // state. Necesario cuando un flag del usuario cambió server-side pero el token
    // que ya tenía el cliente no lo reflejaba (p.ej. tras cambiar la contraseña
    // temporal: el backend limpia must_change_password, pero login() solo intercambia
    // tokens — sin esto, el gate seguiría rebotando a /change-password). Devuelve el
    // user fresco o null si falla.
    const refreshUser = useCallback(async () => {
        const access = getItem("access_token");
        if (!access) return null;
        try {
            const res = await fetch(`${API_BASE}me/`, {
                headers: { Authorization: `Bearer ${access}` },
            });
            if (!res.ok) return null;
            const data = await res.json();
            storeUser(data);
            setUser(data);
            setPermissions(Object.freeze(new Set(data.permissions || [])));
            return data;
        } catch {
            return null;
        }
    }, []);

    const isAuthenticated = !!token && !!user;

    const can = useCallback(
        (permCode) => permissions.has(permCode),
        [permissions]
    );

    const canAny = useCallback(
        (codes) => codes.some(code => permissions.has(code)),
        [permissions]
    );

    const canAll = useCallback(
        (codes) => codes.every(code => permissions.has(code)),
        [permissions]
    );

    return (
        <AuthContext.Provider
            value={{
                token,
                user,
                initializing,
                login,
                logout,
                setUserData,
                refreshUser,
                isAuthenticated,
                permissions,
                can,
                canAny,
                canAll,
            }}
        >
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);
