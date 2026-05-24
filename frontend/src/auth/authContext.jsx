import { createContext, useContext, useState, useEffect, useRef, useCallback } from "react";
import { getItem, setTokens, setAccessToken, setUser as storeUser, clearTokens, isLoggingOut } from "./tokenStorage";

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

    useEffect(() => {
        const storedToken = getItem("access_token");
        const storedUser = getItem("user");

        if (storedToken) {
            setToken(storedToken);
            scheduleTokenRefresh(storedToken);

            // Refresh user data from server to avoid stale org/role data in storage
            fetch(`${API_BASE}me/`, {
                headers: { Authorization: `Bearer ${storedToken}` },
            })
                .then(res => res.ok ? res.json() : null)
                .then(data => {
                    if (data) {
                        storeUser(data);
                        setUser(data);
                        setPermissions(Object.freeze(new Set(data.permissions || [])));
                    } else if (storedUser) {
                        const parsed = JSON.parse(storedUser);
                        setUser(parsed);
                        setPermissions(Object.freeze(new Set(parsed.permissions || [])));
                    }
                })
                .catch(() => {
                    if (storedUser) {
                        const parsed = JSON.parse(storedUser);
                        setUser(parsed);
                        setPermissions(Object.freeze(new Set(parsed.permissions || [])));
                    }
                })
                .finally(() => setInitializing(false));
        } else {
            if (storedUser) {
                const parsed = JSON.parse(storedUser);
                setUser(parsed);
                setPermissions(Object.freeze(new Set(parsed.permissions || [])));
            }
            setInitializing(false);
        }

        return () => {
            if (refreshTimerRef.current) {
                clearTimeout(refreshTimerRef.current);
            }
        };
    }, [scheduleTokenRefresh]);

    const login = (accessToken, refreshToken, remember = true) => {
        setTokens({ access: accessToken, refresh: refreshToken, remember });
        setToken(accessToken);
        scheduleTokenRefresh(accessToken);
    };

    const setUserData = (userData) => {
        storeUser(userData);
        setUser(userData);
        setPermissions(Object.freeze(new Set(userData.permissions || [])));
    };

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
