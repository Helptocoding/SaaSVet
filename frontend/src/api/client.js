import axios from "axios";
import { getItem, clearTokens, isLoggingOut } from "../auth/tokenStorage";
import { genRequestId } from "../utils/requestId";

const rawBase = import.meta.env.VITE_API_URL;
if (!rawBase) {
    throw new Error("VITE_API_URL no está definida");
}

const api = axios.create({
    baseURL: rawBase.endsWith('/') ? rawBase : rawBase + '/',
});

api.interceptors.request.use((config) => {
    const token = getItem("access_token");
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    // P1-5 A1: correlación end-to-end. No pisar un id ya seteado por el caller
    // (p.ej. ops sensibles que reusan el mismo id en un reintento).
    if (!config.headers["X-Request-ID"]) {
        config.headers["X-Request-ID"] = genRequestId();
    }
    return config;
});

const isLoginAttempt = (config) => {
    const url = config?.url || "";
    return url.endsWith("token/") || url.endsWith("token");
};

// Login, refresh y cierre de sesión: nunca se reintentan.
const AUTH_ENDPOINT = /(^|\/)token(\/(refresh|logout))?\/?$/;

// ADR p65 (D14): un 401 de una petición que viajó con un access token que ya no
// es el almacenado (se renovó mientras viajaba, p. ej. al cambiar la propia
// contraseña) se reintenta UNA vez con el vigente. Es seguro aunque sea un POST:
// DRF rechaza la autenticación antes de ejecutar la vista. Nunca llama al
// refresh, no comparte estado entre peticiones y compara tokens sin
// escribirlos en ningún lado.
const shouldRetryWithCurrentToken = (config) => {
    if (!config || config._sessionRetried) return false;
    if (AUTH_ENDPOINT.test(config.url || "")) return false;
    const sent = config.headers?.Authorization;
    if (typeof sent !== "string" || !sent.startsWith("Bearer ")) return false;
    if (isLoggingOut()) return false;
    const current = getItem("access_token");
    return Boolean(current) && sent !== `Bearer ${current}`;
};

api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401 && !isLoginAttempt(error.config)) {
            if (shouldRetryWithCurrentToken(error.config)) {
                // El interceptor de peticiones pone el token vigente.
                error.config._sessionRetried = true;
                return api(error.config);
            }
            clearTokens();
            window.location.href = "/login";
        } else if (error.response?.status >= 500) {
            alert("Error del servidor. Intenta más tarde.");
        }
        return Promise.reject(error);
    }
);

export default api;