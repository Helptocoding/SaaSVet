import api from "./client";

// Caja / turno (ADR p28). URLs por public_id.
export const getCurrentSession = () =>
    api.get("cash/sessions/current/").then(r => r.data);

export const listSessions = (params = {}) =>
    api.get("cash/sessions/", { params }).then(r => r.data);

export const openSession = ({ openingFloat = 0, notes = "" } = {}) =>
    api.post("cash/sessions/open/", { opening_float: String(openingFloat), notes }).then(r => r.data);

export const closeSession = (publicId, { countedCash, notes = "", force = false } = {}) =>
    api.post(`cash/sessions/${publicId}/close/`, {
        counted_cash: String(countedCash), notes, force,
    }).then(r => r.data);
