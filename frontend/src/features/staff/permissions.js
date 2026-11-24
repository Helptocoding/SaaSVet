// Permisos de gestión de personal (plan Equipo F4; Fase 1 Equipo).
// Quien tiene alguno ve Equipo en el menú y puede abrir /staff; el backend usa el
// mismo conjunto para decidir quién recibe correo, cédula y estado de acceso de
// los integrantes (`apps/users/access.py`, STAFF_MANAGEMENT_PERMISSIONS).
export const STAFF_MANAGEMENT_PERMS = [
    "staff.create", "staff.update", "staff.destroy", "staff.reset_password", "staff.reactivate",
];
