// Validación previa del horario (plan F1.3): las mismas reglas y los mismos
// mensajes que `OrganizationScheduleItemSerializer`. El servidor sigue siendo
// la garantía; esto solo evita un viaje para un error evidente.
export const SCHEDULE_MESSAGES = {
    hoursRequired: "Indica la hora de apertura y la de cierre.",
    hoursOrder: "La hora de apertura debe ser anterior a la de cierre.",
    breakRequired: "Indica el inicio y el fin del descanso.",
    breakInside: "El descanso debe quedar dentro del horario de apertura.",
};

const hm = (value) => (value ? String(value).slice(0, 5) : "");

/** Mensaje del primer problema del día, o null. */
export function validateDay(day) {
    if (!day || day.is_closed) return null;
    const opens = hm(day.opens_at);
    const closes = hm(day.closes_at);
    if (!opens || !closes) return SCHEDULE_MESSAGES.hoursRequired;
    if (opens >= closes) return SCHEDULE_MESSAGES.hoursOrder;
    if (day.has_break) {
        const start = hm(day.break_start);
        const end = hm(day.break_end);
        if (!start || !end) return SCHEDULE_MESSAGES.breakRequired;
        if (!(opens < start && start < end && end < closes)) return SCHEDULE_MESSAGES.breakInside;
    }
    return null;
}

/** `{weekday: mensaje}` de los días con problema. */
export function validateWeek(days) {
    const errors = {};
    for (const day of days || []) {
        const message = validateDay(day);
        if (message) errors[day.weekday] = message;
    }
    return errors;
}
