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

/**
 * Cambia el rol (y, en ADMIN, si atiende pacientes) de un integrante (ADR p66).
 * Devuelve el integrante actualizado. No cierra sus sesiones.
 */
export const changeStaffRole = async (publicId, { role, attendsPatients } = {}) => {
    const body = { role };
    if (attendsPatients !== undefined) body.attends_patients = attendsPatients;
    const res = await api.post(`staff/${publicId}/role/`, body);
    return res.data;
};

/** Pendientes del integrante: { upcoming_appointments, open_medical_records, open_cash_session }. */
export const getStaffImpact = async (publicId) => {
    const res = await api.get(`staff/${publicId}/impact/`);
    return res.data;
};

/** Historial de accesos (últimos 50, del más reciente al más antiguo). */
export const getStaffHistory = async (publicId) => {
    const res = await api.get(`staff/${publicId}/history/`);
    return res.data;
};

// ── Ficha, ausencias y citas del integrante (ADR p67) ───────────────────────

/** Datos del integrante para su ficha (también si está inactivo). */
export const getStaffProfile = async (publicId) => {
    const res = await api.get(`staff/${publicId}/profile/`);
    return res.data;
};

/**
 * Citas por atender del integrante (programadas o confirmadas, aún no
 * empezadas). Cada una trae su `expected_state` para reasignarla (INV-A).
 */
export const getStaffAppointments = async (publicId, { from, to } = {}) => {
    const params = {};
    if (from) params.from = from;
    if (to) params.to = to;
    const res = await api.get(`staff/${publicId}/appointments/`, { params });
    return res.data;
};

/**
 * Ausencias vigentes que se cruzan con el rango (por defecto, de hoy en
 * adelante). `member` = public_id para las de un solo integrante.
 */
export const getAbsences = async ({ from, to, member } = {}) => {
    const params = {};
    if (from) params.from = from;
    if (to) params.to = to;
    if (member) params.member = member;
    const res = await api.get("staff/absences/", { params });
    return res.data;
};

/**
 * Registra una ausencia por días completos. Devuelve
 * `{ absence, affected_appointments }`: las citas NO se mueven solas.
 */
export const createAbsence = async (publicId, { startDate, endDate, kind }) => {
    const res = await api.post(`staff/${publicId}/absences/`, {
        start_date: startDate,
        end_date: endDate,
        kind,
    });
    return res.data;
};

/** Cancela una ausencia (queda registrada quién y cuándo). */
export const cancelAbsence = async (absencePublicId) => {
    const res = await api.delete(`staff/absences/${absencePublicId}/`);
    return res.data;
};
