// Borrador de permisos de la ficha (ADR p69).
//
// El borrador guarda lo mismo que el backend: el rol y la diferencia con él
// (`granted`, `revoked`). Lo que se ve marcado es `(rol ∪ concedidos) − quitados`,
// con los permisos reservados siempre dentro en ADMIN y siempre fuera en otro rol.
// El backend vuelve a validar todo (apps/users/member_permissions.py); aquí solo
// se calcula la vista previa y qué casillas no se pueden mover y por qué.

const asSet = (codes) => new Set(codes || []);

export const roleBase = (catalog, role) => asSet(catalog?.roles?.[role]);
const reservedOf = (catalog) => asSet(catalog?.reserved);

export const administrationCodes = (catalog) => new Set(
    (catalog?.areas || [])
        .filter((area) => area.key === "administration")
        .flatMap((area) => area.groups.flatMap((group) => group.permissions.map((p) => p.code))),
);

/** Borrador inicial a partir del integrante de la lista o de su ficha. */
export const draftFromMember = (member) => ({
    role: member.role,
    granted: asSet(member.permission_overrides?.granted),
    revoked: asSet(member.permission_overrides?.revoked),
});

export function effectiveCodes(catalog, draft) {
    const result = new Set(roleBase(catalog, draft.role));
    draft.granted.forEach((code) => result.add(code));
    draft.revoked.forEach((code) => result.delete(code));
    for (const code of reservedOf(catalog)) {
        if (draft.role === "ADMIN") result.add(code);
        else result.delete(code);
    }
    return result;
}

/** Marca o desmarca una casilla: solo cambia la diferencia con el rol. */
export function toggleCode(catalog, draft, code, checked) {
    const base = roleBase(catalog, draft.role);
    const granted = new Set(draft.granted);
    const revoked = new Set(draft.revoked);
    if (checked) {
        revoked.delete(code);
        if (!base.has(code)) granted.add(code);
    } else {
        granted.delete(code);
        if (base.has(code)) revoked.add(code);
    }
    return { ...draft, granted, revoked };
}

/** Al cambiar de rol: conservar la diferencia o volver a los del rol nuevo. */
export const changeRole = (draft, role, keepCustom) => (keepCustom
    ? { ...draft, role }
    : { role, granted: new Set(), revoked: new Set() });

export const restoreRoleDefaults = (draft) => ({ ...draft, granted: new Set(), revoked: new Set() });

/** Ajustes visibles (sin contar los reservados, que el rol fija). */
export function customCounts(catalog, draft) {
    const effective = effectiveCodes(catalog, draft);
    const base = roleBase(catalog, draft.role);
    const reserved = reservedOf(catalog);
    let extra = 0;
    let removed = 0;
    effective.forEach((code) => { if (!base.has(code) && !reserved.has(code)) extra += 1; });
    base.forEach((code) => { if (!effective.has(code) && !reserved.has(code)) removed += 1; });
    return { extra, removed };
}

/**
 * Por qué una casilla no se puede mover, o `null`. `initial` son los permisos
 * efectivos con que se abrió la ficha (la regla de autoedición mira lo que se
 * pierde respecto de ellos, igual que el backend).
 */
export function lockReason(catalog, draft, code, { isSelf = false, initial = new Set() } = {}) {
    if (reservedOf(catalog).has(code)) {
        return draft.role === "ADMIN" ? "Siempre incluido en Administrador" : "Solo administradores";
    }
    if (isSelf && initial.has(code) && administrationCodes(catalog).has(code)) {
        return "No puedes quitarte permisos de administración";
    }
    return null;
}

export function codeBadge(catalog, draft, code) {
    const effective = effectiveCodes(catalog, draft);
    const base = roleBase(catalog, draft.role);
    if (reservedOf(catalog).has(code)) return null;
    if (effective.has(code) && !base.has(code)) return "extra";
    if (!effective.has(code) && base.has(code)) return "removed";
    return null;
}

const sameSet = (a, b) => a.size === b.size && [...a].every((code) => b.has(code));

/** ¿El usuario movió casillas (no solo el rol)? */
export const overridesChanged = (draft, original) =>
    !sameSet(draft.granted, original.granted) || !sameSet(draft.revoked, original.revoked);

export const hasOverrides = (draft) => draft.granted.size + draft.revoked.size > 0;

/** Lista ordenada como la envía el PATCH (`permissions`). */
export const permissionsPayload = (catalog, draft) => [...effectiveCodes(catalog, draft)].sort();
