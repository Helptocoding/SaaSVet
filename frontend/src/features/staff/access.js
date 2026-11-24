// Presentación del estado de acceso de un integrante (Fase 1 Equipo).
//
// El estado lo calcula el backend (`apps/users/access.py`); aquí solo se
// traduce a texto. Fechas en la zona de la clínica, con las utilidades de
// `utils/datetime`. El último acceso tiene precisión de una hora: se registra al
// iniciar sesión y al renovarla, como máximo una vez por hora.
import { dayLabelOrg, formatDateTime, relativeTimeOrg } from "../../utils/datetime";

export const ACCESS_LABELS = {
    active: "Activo",
    inactive: "Inactivo",
    pending_first_login: "Pendiente de primer ingreso",
    password_change_pending: "Debe cambiar su contraseña",
    temp_password_active: "Contraseña temporal",
    temp_password_expired: "Contraseña temporal vencida",
};

// Integrantes activos que todavía no completan su acceso.
export const PENDING_ACCESS = new Set([
    "pending_first_login",
    "password_change_pending",
    "temp_password_active",
    "temp_password_expired",
]);

const DAY_MS = 86400000;

const lowerFirst = (text) => (text ? text.charAt(0).toLowerCase() + text.slice(1) : text);

export function lastAccessLabel(lastLogin, tz, now = new Date()) {
    if (!lastLogin) return "Sin accesos registrados";
    const elapsed = now.getTime() - new Date(lastLogin).getTime();
    const when = elapsed < DAY_MS
        ? relativeTimeOrg(lastLogin, tz, now)
        : lowerFirst(dayLabelOrg(lastLogin, tz, now));
    return `Último acceso: ${when}`;
}

/**
 * `access` = { status, last_login, temp_password_expires_at } del backend.
 * Devuelve { label, detail, title, attention }: `detail` es la segunda línea y
 * `title` la fecha completa para el tooltip; `attention` marca lo único que pide
 * una acción del administrador (una temporal vencida: hay que restablecerla).
 */
export function describeAccess(access, tz, now = new Date()) {
    const status = access?.status;
    const label = ACCESS_LABELS[status] || "—";
    if (status === "temp_password_active" || status === "temp_password_expired") {
        const expires = access.temp_password_expires_at;
        const relative = expires ? relativeTimeOrg(expires, tz, now) : "";
        return {
            label,
            detail: !expires ? "" : status === "temp_password_active" ? `Vence ${relative}` : `Venció ${relative}`,
            title: expires ? formatDateTime(expires, tz, "es-MX") : "",
            attention: status === "temp_password_expired",
        };
    }
    return {
        label,
        detail: lastAccessLabel(access?.last_login, tz, now),
        title: access?.last_login ? formatDateTime(access.last_login, tz, "es-MX") : "",
        attention: false,
    };
}
