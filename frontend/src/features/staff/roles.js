// Roles de sistema de la clínica y qué permite cada uno (Fase 1 Equipo).
//
// Los textos viven en `roleScopes.json` junto con los permisos que los
// respaldan (`grants`) y los que el rol no tiene (`lacks`). Una prueba del
// backend (apps/users/tests/test_role_scopes_match_rbac.py) compara ese archivo
// con la lista real de permisos (`apps/core/permissions_codes.py`, ADR p63): si
// un rol pierde o gana un permiso que el texto menciona, la prueba falla. Los
// roles no son configurables; los textos no deben sugerir lo contrario.
import ROLE_SCOPES from "./roleScopes.json";

export const STAFF_ROLE_ORDER = ["VET", "ASSISTANT", "ADMIN"];

export const roleLabel = (role) => ROLE_SCOPES[role]?.label || role;
export const roleShort = (role) => ROLE_SCOPES[role]?.short || "";
export const roleSummary = (role) => ROLE_SCOPES[role]?.summary || "";
