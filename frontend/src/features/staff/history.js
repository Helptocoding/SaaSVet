// Historial de accesos de un integrante (ADR p66): traduce cada evento del
// backend a una frase. Los eventos solo traen nombres de campo y roles; nunca
// valores personales, así que aquí tampoco se muestran.
import { roleLabel } from "./roles";

const FIELD_LABELS = {
    first_name: "nombre",
    last_name: "apellido",
    email: "correo",
    specialty: "especialidad",
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
        default:
            return event?.kind_label || "Cambio";
    }
}
