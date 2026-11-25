// Reglas de presentación del módulo Equipo (rediseño 2026-11-25, ADR p69).
// Todo se calcula a partir de los datos de la lista y del catálogo de permisos
// del backend (`GET /api/staff/permission-catalog/`): no hay reglas duplicadas
// de negocio aquí, solo cómo se agrupan y se nombran.

export const ACCOUNT_STATE_LABELS = {
    active: "Activo",
    pending: "Invitación pendiente",
    expired: "Invitación vencida",
    inactive: "Desactivado",
};

const PENDING_STATUSES = new Set(["pending_first_login", "temp_password_active", "password_change_pending"]);

/** Estado de la cuenta: activo, invitación pendiente o vencida, desactivado. */
export function accountState(member) {
    if (member.is_active === false || member.access?.status === "inactive") return "inactive";
    const status = member.access?.status;
    if (status === "temp_password_expired") return "expired";
    if (PENDING_STATUSES.has(status)) return "pending";
    return "active";
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Días completos desde un instante ISO (0 si es hoy o futuro). */
export function daysSince(iso, now = new Date()) {
    if (!iso) return 0;
    return Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / DAY_MS));
}

const signingCode = (catalog) => catalog?.signing_permission || "prescription.create";

/** «Firma de recetas»: habilitada, falta cédula o no aplica. */
export function signingState(member, catalog) {
    if (!(member.permissions || []).includes(signingCode(catalog))) return "not_applicable";
    return member.license_number ? "enabled" : "missing_license";
}

const lowerFirst = (text, index) => (index === 0 ? text : text.charAt(0).toLowerCase() + text.slice(1));

/** «Consultas, recetas, vacunas»: los grupos con al menos un permiso. */
export const groupsSummary = (groups) => groups.map((group, index) => lowerFirst(group.label, index)).join(", ");

/**
 * Áreas en las que la persona tiene al menos un permiso, con solo los grupos y
 * acciones que SÍ tiene. Las áreas sin acceso no aparecen.
 */
export function memberAreas(member, catalog, codes = member.permissions) {
    const held = new Set(codes || []);
    return (catalog?.areas || []).map((area) => ({
        key: area.key,
        label: area.label,
        groups: area.groups
            .map((group) => ({
                key: group.key,
                label: group.label,
                actions: group.permissions.filter((p) => held.has(p.code)).map((p) => p.label),
            }))
            .filter((group) => group.actions.length > 0),
    })).filter((area) => area.groups.length > 0);
}

const catalogCodes = (catalog) =>
    (catalog?.areas || []).flatMap((area) => area.groups.flatMap((group) => group.permissions.map((p) => p.code)));

/** ¿Tiene todos los permisos de todas las áreas? */
export function hasAllAreas(member, catalog) {
    const codes = catalogCodes(catalog);
    const held = new Set(member.permissions || []);
    return codes.length > 0 && codes.every((code) => held.has(code));
}

/** ¿Sus permisos difieren de los de su rol? */
export const isCustomized = (member) =>
    (member.permission_overrides?.granted?.length || 0) + (member.permission_overrides?.revoked?.length || 0) > 0;

/** Problemas que se pueden resolver desde Equipo, para una persona. */
export function memberAlerts(member, catalog, now = new Date()) {
    const alerts = [];
    const state = accountState(member);
    if (state === "inactive") return alerts;
    if (signingState(member, catalog) === "missing_license") alerts.push({ kind: "missing_license" });
    if (state === "expired") {
        alerts.push({ kind: "expired_invite", days: daysSince(member.access?.temp_password_expires_at, now) });
    }
    return alerts;
}

const fullName = (member) => `${member.first_name || ""} ${member.last_name || ""}`.trim() || member.username;

/** «Ahora» para la sesión actual, «Nunca» sin accesos, si no «hace 2 d». */
export function lastAccessShort(member, { isSelf = false, now = new Date() } = {}) {
    if (isSelf) return "Ahora";
    const last = member.access?.last_login;
    if (!last) return "Nunca";
    const minutes = Math.max(0, Math.floor((now.getTime() - new Date(last).getTime()) / 60000));
    if (minutes < 1) return "Ahora";
    if (minutes < 60) return `hace ${minutes} min`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `hace ${hours} h`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `hace ${days} d`;
    const months = Math.floor(days / 30);
    if (months < 12) return `hace ${months} mes${months === 1 ? "" : "es"}`;
    const years = Math.floor(days / 365);
    return `hace ${years} año${years === 1 ? "" : "s"}`;
}

export const TABS = [
    { id: "all", label: "Todos" },
    { id: "active", label: "Activos" },
    { id: "pending", label: "Pendientes" },
    { id: "attention", label: "Requieren atención" },
    { id: "inactive", label: "Desactivados" },
];

function inTab(member, tab, catalog, now) {
    const state = accountState(member);
    if (tab === "active") return state === "active";
    if (tab === "pending") return state === "pending" || state === "expired";
    if (tab === "attention") return memberAlerts(member, catalog, now).length > 0;
    if (tab === "inactive") return state === "inactive";
    // «Todos» es el equipo actual: quien está desactivado vive en su pestaña.
    return state !== "inactive";
}

const fold = (text) => (text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Pestaña, búsqueda por nombre o correo y rol. */
export function filterMembers(members, { tab = "all", query = "", role = "" } = {}, catalog, now = new Date()) {
    const needle = fold(query.trim());
    return members.filter((member) =>
        inTab(member, tab, catalog, now)
        && (!role || member.role === role)
        && (!needle || fold(`${fullName(member)} ${member.email || ""}`).includes(needle)));
}

export function tabCounts(members, catalog, now = new Date()) {
    return Object.fromEntries(TABS.map((tab) => [tab.id, members.filter((m) => inTab(m, tab.id, catalog, now)).length]));
}
