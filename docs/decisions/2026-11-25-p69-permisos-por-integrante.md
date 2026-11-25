# ADR p69 — Permisos por integrante sobre su rol

**Fecha:** 2026-11-25
**Estado:** ACEPTADO (decisiones del PO del 2026-11-25, rediseño del módulo Equipo;
plan en [`plan-equipo-rediseno-2026-11-25.md`](../plan-equipo-rediseno-2026-11-25.md))
**Enmienda a:** ADR p63 (además de la lista de su rol, una persona puede tener permisos
concedidos o quitados uno a uno), ADR p66 (el cambio de rol decide qué pasa con esos ajustes),
y la auditoría de Equipo §10, que dejaba el editor de permisos para después.

## Contexto

Los permisos de una persona eran exactamente los de sus roles (`UserRole` → `Role` →
`Permission`). Los roles de sistema (ADMIN, VET, ASSISTANT) los reescribe `seed_permissions` en
cada despliegue, así que no se pueden ajustar por clínica. Una clínica que quiere que su
recepcionista emita devoluciones, o que un veterinario no vea los reportes financieros, no tenía
cómo hacerlo sin cambiarle el rol completo.

No hay clínicas ni usuarios reales (`CLAUDE.md` § Datos y usuarios reales): no hay ajustes
previos que migrar.

## Decisiones

1. **Ajustes por persona, en una tabla propia**: `UserPermissionOverride` (organización,
   persona, permiso, efecto `grant` | `revoke`, quién y cuándo). Único por persona y permiso.
   Fuera de `Role`, para que el seed no los borre. Borrar un permiso del catálogo borra sus
   ajustes.
2. **Permisos efectivos** = (permisos de sus roles ∪ concedidos) − quitados. Los comodines de un
   rol se expanden al catálogo antes de restar, así que un permiso quitado gana a `recurso.*`. Lo
   calcula `_get_cached_permissions`, el único punto que usan `user_has_permission`,
   `user_has_permission_strict` y `/me/`: el cambio aplica en la siguiente petición, sin cerrar
   sesiones (como el cambio de rol, ADR p66).
3. **Se guarda solo la diferencia**: al guardar se envía el conjunto efectivo deseado y el
   servicio calcula los ajustes. Un ajuste igual al rol no se guarda. «Personalizado» =
   tiene al menos un ajuste.
4. **Solo un ADMIN concede o quita** (PO): código nuevo `staff.manage_permissions`, sensible y
   solo en la lista de ADMIN.
5. **Permisos reservados a ADMIN**: `staff.create`, `staff.update`, `staff.destroy`,
   `staff.reset_password`, `staff.reactivate`, `staff.change_role` y
   `staff.manage_permissions`. **No se conceden a otro rol y no se quitan a un ADMIN.** Con
   cualquiera de ellos se puede llegar a controlar cuentas ajenas, así que delegarlos sería
   escalar privilegios. Por eso «administrador» sigue siendo exactamente el rol ADMIN y la regla
   del último ADMIN (INV-J) no cambia.
6. **Nadie se quita a sí mismo permisos de administración** (PO): un ADMIN no puede quitarse
   ningún permiso del área Administración. Los demás ajustes sobre sí mismo sí se permiten.
7. **Cambio de rol**: si la persona tiene ajustes, el llamador debe decidir
   `keep_custom_permissions` (conservar o descartar); sin decidir es `400`. Los que se conservan
   se recalculan contra el rol nuevo y vuelven a pasar las reglas 5 y 6.
8. **Catálogo de permisos con nombres y áreas** (`apps.core.permission_catalog`): cada código
   tiene área (Clínica, Operación, Administración), grupo y acción en español. Una prueba exige
   cubrir todo `PERMISSION_CODES`. `GET /api/staff/permission-catalog/` lo entrega junto con los
   permisos de cada rol de la clínica: el frontend no tiene copia.
9. **Guardar de una vez**: `PATCH /api/staff/<uuid>/` acepta, además de los datos, `role`,
   `attends_patients`, `permissions` y `keep_custom_permissions`, y lo aplica en una sola
   transacción. Cada parte exige su permiso (`staff.update`, `staff.change_role`,
   `staff.manage_permissions`). `POST /api/staff/<uuid>/role/` sigue existiendo y usa el mismo
   servicio.
10. **Historial**: evento `permissions_changed` con los códigos concedidos y quitados (códigos,
    no datos personales). El cambio de rol registra si se conservaron los ajustes.
11. Las cuentas de servicio y `ADMIN_SAAS` no admiten ajustes; el agente sigue limitado por B8A.
12. **Precondición, como INV-A**: el PATCH envía el conjunto efectivo completo, así que una ficha
    abierta hace rato pisaría en silencio lo que otro ADMIN acaba de conceder o quitar. Quien
    envía `permissions` declara en `expected_permissions` los efectivos que veía al abrir la ficha
    (nunca releídos antes de guardar). Sin ellos, `400 precondition_required`; si ya no coinciden
    con los actuales —comparados con la fila de la persona bloqueada—, `409 permissions_changed`
    con `current` y cero escrituras. La interfaz recarga y vuelve a preguntar; jamás reintenta.

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Un rol personalizado por persona | Duplica la lista entera; un cambio del rol base ya no llegaría a esa persona |
| Editar los roles de sistema por clínica | El seed los reescribe en cada despliegue |
| Dejar que un ADMIN delegue la gestión del equipo | Escalada de privilegios: quien restablece contraseñas o cambia roles controla cuentas ajenas |
| Solo mostrar los permisos, sin editarlos | Decisión del PO: editar |
| Enviar solo la diferencia (conceder/quitar) en vez del conjunto | Mezclaría en silencio dos ediciones simultáneas; con el conjunto completo y la precondición, el conflicto se ve y lo resuelve una persona |

## Consecuencias

- Migración aditiva en `core` (tabla de ajustes) y en `users` (tipo de evento nuevo).
- La lista de Equipo, para quien gestiona personal, incluye los permisos efectivos y los ajustes
  de cada persona.
- Un permiso nuevo del catálogo llega automáticamente a quien tenga el rol que lo incluye; los
  ajustes solo cubren excepciones.
