import api from "./client";

export const getStaff = async (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    const url = qs ? `staff/?${qs}` : "staff/";
    const res = await api.get(url);
    return res.data;
};

export const createStaff = async (data) => {
    const res = await api.post("staff/create/", data);
    return res.data;
};

/**
 * Edita nombre, apellido, correo (plan Equipo A1), especialidad y cédula
 * profesional (M01, orden 7). Enviar solo lo que cambió: el backend rechaza
 * cualquier otra clave.
 */
export const updateStaff = async (publicId, data) => {
    const res = await api.patch(`staff/${publicId}/`, data);
    return res.data;
};

export const deactivateStaff = async (publicId) => {
    const res = await api.delete(`staff/${publicId}/`);
    return res.data;
};

/**
 * Admin-initiated password reset for a staff member (ADR p21).
 *
 * Returns once: { temp_password, request_id, duration_ms,
 * expires_in_seconds, must_change_on_first_login }. The temp password
 * must be surfaced to the admin in a modal that does not persist —
 * losing it requires another reset.
 */
const newRequestId = () =>
    typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2);

export const resetStaffPassword = async (publicId) => {
    const res = await api.post(
        `staff/${publicId}/reset-password/`,
        {},
        { headers: { "X-Request-ID": newRequestId() } },
    );
    return res.data;
};

/**
 * Reactiva a un integrante desactivado (plan Equipo A2). Misma forma que el
 * restablecimiento más `member`; 409 `already_active` si ya está activo. La
 * contraseña temporal se muestra una sola vez.
 */
export const reactivateStaff = async (publicId) => {
    const res = await api.post(
        `staff/${publicId}/reactivate/`,
        {},
        { headers: { "X-Request-ID": newRequestId() } },
    );
    return res.data;
};
