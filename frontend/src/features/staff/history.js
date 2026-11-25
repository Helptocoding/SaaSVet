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

// ADR p69: el evento trae códigos; el nombre de cada uno sale del catálogo del
// backend. Sin catálogo se cuenta cuántos.
const permissionNames = (codes, catalog) => {
    const labels = new Map((catalog?.areas || []).flatMap((area) =>
        area.groups.flatMap((group) => group.permissions.map((p) => [p.code, p.label]))));
    return (codes || []).map((code) => (labels.get(code) || code).toLowerCase());
};

function describePermissions(changes, catalog) {
    const parts = [];
    const granted = permissionNames(changes.granted, catalog);
    const revoked = permissionNames(changes.revoked, catalog);
    const restored = changes.restored || [];
    if (granted.length) parts.push(`le concedió ${listOf(granted)}`);
    if (revoked.length) parts.push(`le quitó ${listOf(revoked)}`);
    if (restored.length) parts.push(`devolvió ${restored.length} ${restored.length === 1 ? "permiso" : "permisos"} a lo de su rol`);
    if (!parts.length) return "Ajustó sus permisos";
    const text = listOf(parts);
    return text.charAt(0).toUpperCase() + text.slice(1);
}

export function describeEvent(event, catalog = null) {
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
            if (changes.custom_permissions === "kept") text += "; conservó sus permisos personalizados";
            if (changes.custom_permissions === "discarded") text += "; volvió a los permisos del rol";
            return text;
        }
        case "permissions_changed":
            return describePermissions(changes, catalog);
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
