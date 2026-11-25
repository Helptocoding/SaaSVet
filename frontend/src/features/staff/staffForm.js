// Validación previa y diferencias de los formularios de Equipo (alta y ficha).
//
// El backend es la autoridad (apps/users/serializers.py y services.py); aquí solo
// se avisa antes de enviar con las mismas reglas, y se calcula qué cambió para
// enviar únicamente eso.
import { orderSpecialties, sameSpecialties } from "./specialties";

// M01 (orden 7): cédula profesional, solo dígitos (5 a 10). Obligatoria para quien atiende.
const LICENSE_RE = /^\d{5,10}$/;
const LICENSE_REQUIRED = "La cédula profesional es obligatoria para veterinarios";
const LICENSE_REQUIRED_CLINICIAN = "La cédula profesional es obligatoria para quien atiende pacientes";
const LICENSE_FORMAT = "La cédula profesional debe tener solo dígitos, entre 5 y 10";

// D4 (plan Equipo): NFC + recorte de extremos; nada más.
const PERSON_NAME_RE = /^[A-Za-zÀ-ÖØ-öø-ÿĀ-ž '’-]+$/;
const USERNAME_RE = /^[A-Za-z0-9_.-]+$/;

export const DEMO_EMAIL_HINT = "En la demo usa un correo de ejemplo, como nombre@example.com.";
export const EMAIL_CHANGE_NOTICE = "Es su acceso al sistema. Desde que guardes entrará con el correo nuevo; avísale.";

export const fullName = (member) =>
    `${member?.first_name || ""} ${member?.last_name || ""}`.trim() || member?.username || "";

export const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

// ADR p66: atiende quien es VET, o ADMIN marcado (apps/users/professional.py).
export const attendsFor = (role, attendsPatients) =>
    role === "VET" || (role === "ADMIN" && Boolean(attendsPatients));

export const normalizeName = (value) => (value || "").normalize("NFC").trim();

export function licenseError(role, value, attendsPatients = false) {
    const license = (value || "").trim();
    if (!license) {
        if (role === "VET") return LICENSE_REQUIRED;
        return attendsFor(role, attendsPatients) ? LICENSE_REQUIRED_CLINICIAN : null;
    }
    return LICENSE_RE.test(license) ? null : LICENSE_FORMAT;
}

export function nameError(value, { label, required }) {
    const name = normalizeName(value);
    if (!name) return required ? `${label} es obligatorio.` : null;
    return PERSON_NAME_RE.test(name)
        ? null
        : `${label} solo puede contener letras, espacios, guiones y apóstrofos.`;
}

function identityErrors(draft, role, attendsPatients) {
    const errors = {};
    const first = nameError(draft.first_name, { label: "El nombre", required: true });
    if (first) errors.first_name = first;
    const last = nameError(draft.last_name, { label: "El apellido", required: false });
    if (last) errors.last_name = last;
    if (!(draft.email || "").trim()) errors.email = "El correo electrónico es obligatorio.";
    const license = licenseError(role, draft.license_number, attendsPatients);
    if (license) errors.license_number = license;
    return errors;
}

export function createErrors(form) {
    const errors = identityErrors(form, form.role, form.attends_patients);
    const username = form.username.trim();
    if (!username) errors.username = "El nombre de usuario es obligatorio.";
    else if (!USERNAME_RE.test(username)) {
        errors.username = "El nombre de usuario solo puede contener letras, números, puntos, guiones y guiones bajos.";
    }
    return errors;
}

/** Errores de la ficha con el rol y la función clínica que quedarían al guardar. */
export const profileErrors = (draft) => identityErrors(draft, draft.role, draft.attends_patients);

/** Datos personales que cambiaron respecto del integrante (el backend rechaza claves de más). */
export function profileChanges(draft, member) {
    const changes = {};
    const first = normalizeName(draft.first_name);
    if (first !== (member.first_name || "")) changes.first_name = first;
    const last = normalizeName(draft.last_name);
    if (last !== (member.last_name || "")) changes.last_name = last;
    const email = draft.email.trim();
    if (email.toLowerCase() !== (member.email || "").toLowerCase()) changes.email = email;
    const specialties = attendsFor(draft.role, draft.attends_patients) ? draft.specialties : [];
    if (!sameSpecialties(specialties, member.specialties)) {
        changes.specialties = orderSpecialties(specialties);
    }
    const license = draft.license_number.trim();
    if (license !== (member.license_number || "")) changes.license_number = license;
    return changes;
}

export const inputClass = (error) => `input${error ? " input-error" : ""}`;

/** «Tiene 3 citas próximas y 1 consulta abierta a su nombre…» (ADR p66). */
export function impactSentence(impact) {
    if (!impact) return "";
    const parts = [];
    if (impact.upcoming_appointments > 0) {
        parts.push(plural(impact.upcoming_appointments, "cita próxima", "citas próximas"));
    }
    if (impact.open_medical_records > 0) {
        parts.push(plural(impact.open_medical_records, "consulta abierta", "consultas abiertas"));
    }
    if (parts.length === 0) return "";
    return `Tiene ${parts.join(" y ")} a su nombre: seguirán asignadas; las citas se reasignan desde su ficha.`;
}
