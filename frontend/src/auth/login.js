import api from "../api/client";

export const loginRequest = async (username, password) => {
    const res = await api.post("token/", { username, password });
    return res.data;
};

/**
 * Segundo paso del login con verificación en dos pasos (ADR p68): el reto que
 * devolvió `token/` y un código de la app o de respaldo.
 */
export const loginMfaRequest = async (mfaToken, code) => {
    const res = await api.post("token/mfa/", { mfa_token: mfaToken, code });
    return res.data;
};

export const getMe = async (token) => {
    const res = await api.get("me/", {
        headers: { Authorization: `Bearer ${token}` },
    });
    return res.data;
};

export const refreshTokenRequest = async (refreshToken) => {
    const res = await api.post("token/refresh/", { refresh: refreshToken });
    return res.data;
};
