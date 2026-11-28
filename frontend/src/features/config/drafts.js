// Borradores de Configuración (ADR p70, plan F1.3): cada apartado compara lo
// que se está editando contra lo último guardado. De aquí salen el punto de
// «cambios sin guardar», el bloqueo al salir y lo que viaja en cada PATCH
// (solo lo que cambió, C16).
import { BILLING_RULES, CARE_RULES } from "./rules";

export const CLINIC_FIELDS = [
    "display_name", "phone", "whatsapp", "email", "website", "timezone",
    "address_line1", "address_line2", "district", "city", "state", "postal_code", "country",
    "google_maps_url", "arrival_instructions",
];

export const BILLING_FIELDS = [...BILLING_RULES.map((rule) => rule.key), "credit_default_days"];
// F2.3: la duración habitual de una cita vive en Atención.
export const CARE_FIELDS = [...CARE_RULES.map((rule) => rule.key), "default_appointment_duration_minutes"];

// Vacío y nulo son lo mismo para un campo de texto.
const normalize = (value) => (value === null || value === undefined ? "" : value);

/** Campos de `fields` cuyo borrador difiere de lo guardado, con su valor nuevo. */
export function changedFields(saved, draft, fields) {
    const changes = {};
    for (const field of fields) {
        if (normalize(saved?.[field]) !== normalize(draft?.[field])) changes[field] = draft?.[field] ?? "";
    }
    return changes;
}

const SCHEDULE_KEYS = ["is_closed", "opens_at", "closes_at", "has_break", "break_start", "break_end"];
const hm = (value) => (value ? String(value).slice(0, 5) : "");

const dayKey = (day) => SCHEDULE_KEYS.map((key) => (key.endsWith("_at") || key.startsWith("break_")
    ? hm(day?.[key]) : Boolean(day?.[key]))).join("|");

export function scheduleChanged(saved, draft) {
    const byDay = new Map((saved || []).map((day) => [day.weekday, dayKey(day)]));
    return (draft || []).some((day) => byDay.get(day.weekday) !== dayKey(day));
}

/** Apartados con cambios sin guardar. */
export function dirtySections(saved, draft) {
    const dirty = new Set();
    if (!saved || !draft) return dirty;
    if (Object.keys(changedFields(saved.org, draft.org, CLINIC_FIELDS)).length) dirty.add("clinic");
    if (scheduleChanged(saved.schedule, draft.schedule)) dirty.add("schedule");
    if (Object.keys(changedFields(saved.settings, draft.settings, BILLING_FIELDS)).length) dirty.add("billing");
    if (Object.keys(changedFields(saved.settings, draft.settings, CARE_FIELDS)).length) dirty.add("care");
    return dirty;
}

/** El borrador del apartado vuelve a lo guardado; los demás no se tocan. */
export function discardSection(saved, draft, section) {
    const pick = (source, fields) => Object.fromEntries(fields.map((field) => [field, source?.[field]]));
    switch (section) {
        case "clinic":
            return { ...draft, org: { ...draft.org, ...pick(saved.org, CLINIC_FIELDS) } };
        case "schedule":
            return { ...draft, schedule: saved.schedule };
        case "billing":
            return { ...draft, settings: { ...draft.settings, ...pick(saved.settings, BILLING_FIELDS) } };
        case "care":
            return { ...draft, settings: { ...draft.settings, ...pick(saved.settings, CARE_FIELDS) } };
        default:
            return draft;
    }
}
