# Plan — rediseño del módulo Equipo (2026-11-25)

Especificación del PO (lista de integrantes y ficha de edición) con sus decisiones del
2026-11-25. Contrato de permisos: [ADR p69](decisions/2026-11-25-p69-permisos-por-integrante.md).

**Estado: implementado** (rama `feat/equipo-rediseno`). Añadidos durante la implementación: la
precondición de permisos (ADR p69 §12), `mfa_enabled` en la ficha (Seguridad y acceso), y
«Todos» = el equipo actual (los desactivados viven en su pestaña).

## Decisiones del PO

| Tema | Decisión |
|---|---|
| Permisos por persona | Sí. Solo un ADMIN concede o quita; nadie se quita a sí mismo permisos de administración |
| Eliminar integrante | No existe. Se mantiene **Desactivar** (y Reactivar) |
| Especialidades | Varias por persona (catálogo de la Fase 4) |
| Ficha | Se abre como **modal** desde Equipo; sustituye a la página `/staff/:publicId` |

## Qué había (Fases 1–4)

- Permisos = los de los roles; sin ajustes por persona (ver ADR p69).
- Cédula: `User.license_number`, solo dígitos (5–10), con restricción en la base.
- Especialidades: `User.specialties`, lista de códigos del catálogo cerrado
  (`apps.users.specialties`, desde `users.0017`). Un texto como «Experto» ya se descartó al
  migrar.
- Acceso: `last_login`, estado de acceso y contraseña temporal con vencimiento (Fase 1).
- Sin invitaciones por correo: «Reenviar invitación» = contraseña temporal nueva (la misma
  acción de restablecer), que se muestra una vez.

## Decisiones de adaptación (a la especificación)

1. **Estado** (`access.status` del backend → texto):
   `inactive` → «Desactivado»; `temp_password_expired` → «Invitación vencida»;
   `pending_first_login`, `temp_password_active`, `password_change_pending` → «Invitación
   pendiente»; `active` → «Activo». La contraseña del alta sigue sin caducar (Fase 1), así que
   «vencida» aparece tras un restablecimiento o una reactivación.
2. **Pestañas**: Todos, Activos, Pendientes, Requieren atención y, para quien puede reactivar,
   **Desactivados** (la especificación no la mencionaba; sin ella no habría dónde reactivar).
3. **Áreas**: Clínica, Operación y Administración según el catálogo real de 96 códigos.
   «Cirugías» y «estudios» no existen como permisos (la cirugía es un tipo de consulta). Las
   lecturas que todos necesitan (panel de inicio, directorio, datos de la clínica, catálogo de
   servicios) van en Operación, para que Administración signifique de verdad administrar.
4. **Firma de recetas**: permiso `prescription.create` + cédula → «Habilitada»; con permiso y sin
   cédula → «Falta cédula»; sin permiso → «No aplica».
5. **Ficha (modal lateral)**: encabezado con aviso; Rol (y «Atiende pacientes» en ADMIN);
   Permisos; Datos (nombre, apellido, correo, cédula y especialidades — la especificación no
   mencionaba nombre y correo, que ya eran editables); Seguridad y acceso; y lo operativo de la
   Fase 3: citas por atender (reasignar), ausencias e historial. Pie: Desactivar acceso,
   Cancelar, Guardar cambios. `/staff/:publicId` redirige a `/staff?member=<uuid>`.
6. **Menú ⋯**: Editar, Cambiar rol (abre la ficha en Rol), Restablecer contraseña,
   Desactivar/Reactivar. Sin Eliminar.

## Entregas

### Backend
1. `apps.core.permission_catalog` (áreas, grupos y acciones por código) + prueba de cobertura.
2. `UserPermissionOverride` + migración; permisos efectivos en `_get_cached_permissions`.
3. Código `staff.manage_permissions`; permisos reservados a ADMIN; regla de autoedición.
4. Servicio único `update_staff_member` (datos, rol, función clínica, permisos) en una
   transacción; `PATCH /api/staff/<uuid>/` lo usa; `/role/` también.
5. `GET /api/staff/permission-catalog/`; la lista de Equipo incluye permisos y ajustes.
6. Evento `permissions_changed`; pruebas (incluida concurrencia y mutaciones).

### Frontend
1. Página Equipo: encabezado con conteos, «Requiere atención», pestañas, buscador, filtro por
   rol, tabla nueva (avatar, Rol + especialidades, Acceso por área con popover, Firma de recetas,
   Estado, Último acceso, acciones) y vista en tarjetas en pantallas angostas.
2. Ficha modal con las secciones del punto 5 y guardado único.
3. Cambio de rol: preguntar si se conservan los ajustes; impacto de citas como hoy.
4. Pruebas de comportamiento (filtros, alertas, popover con teclado, guardado, reglas).

### Documentación
ADR p69, `modules/organizations.md`, `modules/frontend.md`, `system-reference.md`,
`system-module-operations.md` y registro en la auditoría de Equipo.
