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
 * Edita especialidad y cédula profesional de un miembro (M01, orden 7).
 * El backend rechaza cualquier otra clave.
 */
export const updateStaff = async (publicId, data) => {
    const res = await api.patch(`staff/${publicId}/`, data);
    return res.data;
};

export const deactivateStaff = async (id) => {
    const res = await api.delete(`staff/${id}/`);
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
export const resetStaffPassword = async (publicId) => {
    const requestId =
        typeof crypto !== "undefined" && crypto.randomUUID
            ? crypto.randomUUID()
            : Math.random().toString(36).slice(2);
    const res = await api.post(
        `staff/${publicId}/reset-password/`,
        {},
        { headers: { "X-Request-ID": requestId } },
    );
    return res.data;
};
