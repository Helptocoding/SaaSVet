import axios from "axios";
import { getItem, clearTokens } from "../auth/tokenStorage";
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

api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401 && !isLoginAttempt(error.config)) {
            clearTokens();
            window.location.href = "/login";
        } else if (error.response?.status >= 500) {
            alert("Error del servidor. Intenta más tarde.");
        }
        return Promise.reject(error);
    }
);

export default api;