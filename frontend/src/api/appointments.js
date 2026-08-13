import api from "./client";

/**
 * INV-A (ADR p57) — la precondición de estado, del lado del frontend.
 *
 * `expected_state` es la tupla que el usuario tenía **en pantalla** cuando
 * decidió mutar la cita. El dominio la compara contra la fila bloqueada,
 * dentro de la misma transacción que escribe, y responde `409
 * appointment_changed` si difiere. Es lo que impide que dos personas —o una
 * persona y el asistente de WhatsApp— se pisen en silencio: sin ella, gana
 * quien guarda último.
 *
 * Se construye a partir de la cita **ya cargada**, nunca releyéndola justo
 * antes de guardar: releer produciría el estado de *después* y la precondición
 * no diría nada.
 *
 * Devuelve `{}` si la cita no trae la tupla completa, para no fabricar una
 * precondición falsa (diría que la cita estaba como no la vimos). Desde la
 * Fase 3 la precondición es **obligatoria**: omitirla es `400
 * precondition_required` y `expected_state: null` es `400 validation_error`.
 * Los dos fallan a propósito — el llamador que no sabe cómo estaba la cita no
 * está autorizado a sobrescribirla (§1.2).
 */
export const expectedStateOf = (appt) => {
    if (!appt) return {};
    const { status, date, start_time: startTime } = appt;
    if (!status || !date || !startTime) return {};
    return {
        expected_state: {
            status,
            date,
            start_time: String(startTime).slice(0, 5),
        },
    };
};

export const getAppointments = async (token, filters = {}) => {
    const params = new URLSearchParams(filters).toString();
    const url = params ? `appointments/?${params}` : "appointments/";
    const res = await api.get(url);
    return res.data;
};

export const createAppointment = async (token, data) => {
    const res = await api.post("appointments/", data);
    return res.data;
};

/** `expected` = la cita tal como estaba en pantalla (ver `expectedStateOf`). */
export const updateAppointment = async (token, id, data, expected = null) => {
    const res = await api.patch(`appointments/${id}/`, {
        ...data,
        ...expectedStateOf(expected),
    });
    return res.data;
};

export const updateAppointmentStatus = async (token, id, status, expected = null) => {
    const res = await api.patch(`appointments/${id}/status/`, {
        status,
        ...expectedStateOf(expected),
    });
    return res.data;
};

// `deleteAppointment` se retiró (ADR p57 §3.3): `DELETE /appointments/<id>/`
// está DEPRECADO a favor de `PATCH /<id>/status/`, que es la vía con auditoría
// y precondición. No tenía ningún consumidor —el frontend ya cancelaba por
// `/status/`—, así que dejar la función viva solo invitaba a reintroducir la
// vía deprecada. El backend la mantiene con cabeceras `Deprecation`/`Sunset`
// hasta su retirada (Fase 3 del rollout de INV-A, pendiente de calendario).

export const walkInAppointment = async (token, data) => {
    const res = await api.post("appointments/walk-in/", data);
    return res.data;
};

export const getAppointmentHistory = async (id) => {
    const res = await api.get(`appointments/${id}/history/`);
    return res.data;
};

export const assignPatient = async (id, petId, expected = null) => {
    const res = await api.patch(`appointments/${id}/assign-patient/`, {
        pet: petId,
        ...expectedStateOf(expected),
    });
    return res.data;
};

export const createAppointmentWithPatient = async (data) => {
    const res = await api.post("appointments/create-with-patient/", data);
    return res.data;
};
