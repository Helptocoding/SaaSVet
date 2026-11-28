// Quién entra a Configuración y qué apartados ve (ADR p70 D8). Por capacidad,
// nunca por rol: editar la clínica es `organization.update` (delegable, ADR p69)
// y el catálogo de servicios, sus propios permisos.
export const CLINIC_PERM = "organization.update";
export const SERVICE_PERMS = ["service.create", "service.update", "service.destroy"];
export const CONFIG_PERMS = [CLINIC_PERM, ...SERVICE_PERMS];
