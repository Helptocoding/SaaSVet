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

// Movimientos manuales del cajón (ADR p39): deposit | withdrawal | expense.
export const registerCashMovement = ({ movementType, amount, reason }) =>
    api.post("cash/movements/", {
        movement_type: movementType, amount: String(amount), reason,
    }).then(r => r.data);

// Sin params → movimientos de la caja abierta del actor; { session } → por sesión.
export const listCashMovements = (params = {}) =>
    api.get("cash/movements/", { params }).then(r => r.data);
