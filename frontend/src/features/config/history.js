// Historial de cambios de Configuración (ADR p70 D9): traduce cada evento del
// backend a un título y una lista de detalles «Campo: antes → después». El
// backend guarda los valores tal como quedaron; aquí solo se presentan.
import TIMEZONES from "./timezones.json";
import { formatMoney } from "../../utils/money";
import { specialtyLabel } from "../staff/specialties";
import { formatAbsenceRange } from "../staff/absences";

const CLINIC_FIELDS = {
    name: "Nombre legal",
    display_name: "Nombre comercial",
    phone: "Teléfono",
    whatsapp: "WhatsApp",
    email: "Correo electrónico",
    website: "Sitio web",
    address_line1: "Dirección",
    address_line2: "Interior, piso o referencia",
    district: "Colonia",
    city: "Ciudad",
    state: "Estado",
    postal_code: "Código postal",
    country: "País",
    google_maps_url: "Enlace del mapa",
    latitude: "Latitud",
    longitude: "Longitud",
    arrival_instructions: "Indicaciones para llegar",
};

// Incluye los ajustes retirados en F1.6 (D5) para leer eventos anteriores.
const RULE_FIELDS = {
    require_confirmation_before_start: "Confirmación obligatoria",
    auto_create_medical_record: "Historial clínico automático",
    allow_anonymous_walkin: "Atención sin cita",
    allow_emergency_walkin: "Urgencias sin cita",
    show_status_change_history: "Historial de estados de la cita",
    require_open_cash_session: "Caja abierta obligatoria",
    allow_post_unpaid: "Crédito",
    credit_default_days: "Plazo de crédito",
    locale: "Idioma",
    currency_code: "Moneda",
    default_appointment_duration_minutes: "Duración de una cita",
    appointment_buffer_minutes: "Margen entre citas",
    week_starts_on: "Inicio de la semana",
};

const SERVICE_FIELDS = {
    name: "Nombre",
    description: "Descripción",
    base_price: "Precio sin IVA",
    specialty: "Especialidad",
    is_active: "Activo",
};

// Textos largos: se dice que cambiaron, sin repetirlos.
const LONG_TEXT = new Set(["arrival_instructions", "description"]);

const WEEKDAYS = ["", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

const TIMEZONE_LABELS = new Map(TIMEZONES);
const timezoneLabel = (code) => TIMEZONE_LABELS.get(code) || code;

const EMPTY = "sin capturar";

const plain = (value) => (value === null || value === undefined || value === "" ? EMPTY : String(value));

function ruleValue(field, value) {
    if (typeof value === "boolean") return value ? "activada" : "desactivada";
    if (field === "credit_default_days") return `${value} días`;
    if (field === "default_appointment_duration_minutes" || field === "appointment_buffer_minutes") {
        return `${value} min`;
    }
    return plain(value);
}

function serviceValue(field, value) {
    if (field === "base_price") return value === null || value === undefined ? EMPTY : formatMoney(value);
    if (field === "specialty") return value ? specialtyLabel(value) || value : "ninguna";
    if (field === "is_active") return value ? "sí" : "no";
    return plain(value);
}

export function scheduleDayLabel(day) {
    if (!day) return EMPTY;
    if (day.is_closed) return "Cerrado";
    let text = `${day.opens_at}–${day.closes_at}`;
    if (day.has_break && day.break_start && day.break_end) {
        text += `, descanso ${day.break_start}–${day.break_end}`;
    }
    return text;
}

function fieldDetails(changes, labels, format) {
    return Object.entries(changes || {}).map(([field, pair]) => {
        const label = labels[field] || field;
        const [before, after] = Array.isArray(pair) ? pair : [undefined, pair];
        if (LONG_TEXT.has(field)) return `${label}: cambió`;
        return `${label}: ${format(field, before)} → ${format(field, after)}`;
    });
}

const serviceName = (event) => event?.subject?.name || "sin nombre";

/** `{title, details}` de un evento del historial. */
export function describeConfigEvent(event) {
    const changes = event?.changes || {};
    switch (event?.kind) {
        case "clinic_updated":
            return {
                title: "Editó los datos de la clínica",
                details: fieldDetails(changes, CLINIC_FIELDS, (_, value) => plain(value)),
            };
        case "timezone_changed": {
            const [before, after] = changes.timezone || [];
            return {
                title: "Cambió la zona horaria",
                details: [`${timezoneLabel(before)} → ${timezoneLabel(after)}`],
            };
        }
        case "rules_updated":
            return {
                title: "Cambió las reglas de operación",
                details: fieldDetails(changes, RULE_FIELDS, ruleValue),
            };
        case "schedule_replaced":
            return {
                title: "Cambió el horario",
                details: Object.keys(changes)
                    .sort()
                    .map((key) => {
                        const weekday = Number(key.replace("weekday_", ""));
                        const [before, after] = changes[key] || [];
                        return `${WEEKDAYS[weekday] || key}: ${scheduleDayLabel(before)} → ${scheduleDayLabel(after)}`;
                    }),
            };
        case "service_created": {
            const price = changes.base_price?.[1];
            return {
                title: `Creó el servicio «${serviceName(event)}»`,
                details: price !== undefined && price !== null ? [`Precio sin IVA: ${formatMoney(price)}`] : [],
            };
        }
        case "service_updated":
            return {
                title: `Editó el servicio «${serviceName(event)}»`,
                details: fieldDetails(changes, SERVICE_FIELDS, serviceValue),
            };
        case "service_activated":
        case "service_deactivated": {
            const others = { ...changes };
            delete others.is_active;
            return {
                title: `${event.kind === "service_activated" ? "Activó" : "Desactivó"} el servicio «${serviceName(event)}»`,
                details: fieldDetails(others, SERVICE_FIELDS, serviceValue),
            };
        }
        case "service_deleted":
            return { title: `Eliminó el servicio «${serviceName(event)}»`, details: [] };
        case "closure_added":
        case "closure_cancelled": {
            const subject = event.subject || {};
            const range = subject.start_date && subject.end_date
                ? formatAbsenceRange(subject.start_date, subject.end_date) : "";
            const reason = event.kind === "closure_added" ? changes.reason?.[1] : subject.reason;
            const verb = event.kind === "closure_added" ? "Registró un cierre" : "Canceló el cierre";
            return {
                title: range ? `${verb}: ${range}` : verb,
                details: reason ? [`Motivo: ${reason}`] : [],
            };
        }
        default:
            return { title: event?.kind_label || "Cambio de configuración", details: [] };
    }
}
