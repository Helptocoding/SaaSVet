// Historial de accesos de un integrante (ADR p66): traduce cada evento del
// backend a una frase. Los eventos solo traen nombres de campo y roles; nunca
// valores personales, así que aquí tampoco se muestran.
import { roleLabel } from "./roles";
import { absenceKindLabel, formatAbsenceRange } from "./absences";

const FIELD_LABELS = {
    first_name: "nombre",
    last_name: "apellido",
    email: "correo",
    specialty: "especialidad",
    specialties: "especialidades",
    license_number: "cédula",
    attends_patients: "si atiende pacientes",
};

const listOf = (items) => {
    if (items.length <= 1) return items.join("");
    return `${items.slice(0, -1).join(", ")} y ${items[items.length - 1]}`;
};

export function describeEvent(event) {
    const changes = event?.changes || {};
    switch (event?.kind) {
        case "created":
            return `Alta como ${roleLabel(changes.role).toLowerCase()}`;
        case "profile_updated": {
            const fields = (changes.fields || []).map((field) => FIELD_LABELS[field] || field);
            return fields.length ? `Editó ${listOf(fields)}` : "Editó sus datos";
        }
        case "role_changed": {
            const role = changes.role || {};
            let text = `Cambió el rol de ${roleLabel(role.from).toLowerCase()} a ${roleLabel(role.to).toLowerCase()}`;
            if (changes.attends_patients) {
                text += changes.attends_patients.to ? "; ahora atiende pacientes" : "; ya no atiende pacientes";
            }
            return text;
        }
        case "deactivated":
            return "Desactivó su acceso";
        case "reactivated":
            return "Reactivó su acceso";
        case "password_reset":
            return changes.source === "platform"
                ? "Soporte de la plataforma restableció su contraseña"
                : "Restableció su contraseña";
        case "absence_added":
            return `Registró ${absenceKindLabel(changes.kind).toLowerCase()}: ${formatAbsenceRange(changes.start_date, changes.end_date)}`;
        case "absence_cancelled":
            return `Canceló la ausencia del ${formatAbsenceRange(changes.start_date, changes.end_date)}`;
        case "appointments_reassigned": {
            const moved = Number(changes.moved) || 0;
            const skipped = Number(changes.skipped) || 0;
            let text = `Reasignó ${moved} ${moved === 1 ? "cita" : "citas"} a otro veterinario`;
            if (skipped > 0) text += `; ${skipped} ${skipped === 1 ? "quedó" : "quedaron"} sin mover`;
            return text;
        }
        default:
            return event?.kind_label || "Cambio";
    }
}
