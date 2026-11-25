// Verificación en dos pasos de la propia cuenta (ADR p68). Solo ADMIN, opcional.
import api from "./client";

/** `{ available, enabled, enabled_at, recovery_codes_remaining }`. */
export const getMfaStatus = async () => (await api.get("users/mfa/")).data;

/** Pide la contraseña y devuelve `{ secret, otpauth_uri }` (vale 30 minutos). */
export const startMfaSetup = async (password) =>
    (await api.post("users/mfa/setup/", { password })).data;

/** Activa con el primer código de la app; devuelve los 10 códigos de respaldo. */
export const enableMfa = async (code) => (await api.post("users/mfa/enable/", { code })).data;

export const disableMfa = async ({ password, code }) =>
    (await api.post("users/mfa/disable/", { password, code })).data;

/** Devuelve 10 códigos nuevos; los anteriores dejan de servir. */
export const regenerateRecoveryCodes = async ({ password, code }) =>
    (await api.post("users/mfa/recovery-codes/", { password, code })).data;
