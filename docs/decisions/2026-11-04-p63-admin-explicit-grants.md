# ADR p63 — Concesiones explícitas para el ADMIN de clínica

**Fecha**: 2026-11-04
**Estado**: **PROPUESTO. No implementado.** Requiere aprobar la matriz de abajo y evidencia de producción.
**Origen**: auditoría de seguridad run-1, H-1 (`docs/plan-implementacion-seguridad-run1-2026-10-28.md`)

## Contexto

El ADMIN de clínica tiene `*.*`, igual que `ADMIN_SAAS`. Todo código de permiso nuevo se le concede sin que nadie lo decida.

`cb0ff9e` añadió una versión reducida que **no resuelve esto**: cada código se clasifica, y `_is_allowed` niega al comodín los de `WILDCARD_EXCLUDED`. Pero clasificar no es controlar la concesión: mientras exista `*.*`, un código clasificado como ordinario o sensible se concede solo. Lo único que impide es que un código excluido a propósito llegue por el comodín.

## Decisión propuesta

Sustituir `*.*` del rol `ADMIN` por la lista explícita de la matriz. `ADMIN_SAAS` conserva `*.*`, y un superuser no se evalúa por comodín.

Un código nuevo no llega al ADMIN hasta añadirlo a su lista. El test de partición existente pasaría a exigir esa decisión.

## Inventario

87 códigos: 19 sensibles y 68 ordinarios. 28 solo los tiene el ADMIN hoy. Ningún código sensible lo tiene otro rol.

Generado cruzando el catálogo con el código, sin tests ni migraciones. «Derivado del recurso» significa que `_resolve_required` lo construye desde `basename` o `resource_name`, sin literal. Es evidencia estática: **no prueba qué se usa en producción**.

| Código | Clase | VET | ASSISTANT | AGENT | Quién lo pide | UI |
|---|---|---|---|---|---|---|
| `appointment.list` | ordinario | sí | sí | sí | appointments, notifications |  |
| `appointment.retrieve` | ordinario | sí | sí | sí | appointments |  |
| `appointment.create` | ordinario | sí | sí | sí | appointments |  |
| `appointment.create_walkin` | ordinario | sí |  |  | appointments | sí |
| `appointment.update` | ordinario | sí | sí | sí | appointments |  |
| `appointment.destroy` | ordinario | sí | sí |  | (derivado del recurso) |  |
| `medicalrecord.list` | ordinario | sí | sí |  | medical_records |  |
| `medicalrecord.retrieve` | ordinario | sí | sí |  | inventory, medical_records |  |
| `medicalrecord.create` | ordinario | sí |  |  | (derivado del recurso) |  |
| `medicalrecord.update` | ordinario | sí |  |  | inventory, medical_records |  |
| `medicalrecord.close` | ordinario | sí |  |  | medical_records |  |
| `medicalrecord.vitals.create` | ordinario | sí |  |  | medical_records |  |
| `medicalrecord.vitals.list` | ordinario | sí | sí |  | medical_records |  |
| `medicalrecord.summary.retrieve` | ordinario | sí | sí |  | medical_records |  |
| `vaccinerecord.list` | ordinario | sí | sí | sí | (derivado del recurso) |  |
| `vaccinerecord.retrieve` | ordinario | sí | sí | sí | (derivado del recurso) |  |
| `vaccinerecord.create` | ordinario | sí |  |  | (derivado del recurso) |  |
| `vaccinerecord.update` | ordinario | sí |  |  | (derivado del recurso) |  |
| `invoice.list` | ordinario | sí | sí |  | billing |  |
| `invoice.retrieve` | ordinario | sí | sí |  | billing |  |
| `invoice.create` | ordinario | sí | sí |  | billing | sí |
| `invoice.destroy` | sensible |  |  |  | billing |  |
| `invoice.pay` | ordinario |  | sí |  | billing |  |
| `invoice.post_unpaid` | sensible |  |  |  | billing, core | sí |
| `invoice.replace_waive` | sensible |  |  |  | billing | sí |
| `invoice.replace` | sensible |  |  |  | billing | sí |
| `invoice.replace_adjust` | sensible |  |  |  | billing | sí |
| `invoice.replace_manage` | sensible |  |  |  | billing | sí |
| `invoice.void_terminal` | sensible |  |  |  | billing | sí |
| `billing.clinical_charge.reprice` | sensible |  |  |  | billing |  |
| `checkout.prescription_decide` | ordinario |  | sí |  | billing |  |
| `checkout.estimate.issue` | ordinario |  | sí |  | billing | sí |
| `checkout.dispute.open` | ordinario | sí | sí |  | billing | sí |
| `checkout.dispute.resolve` | sensible |  |  |  | billing | sí |
| `collection.resolve` | sensible |  |  |  | billing |  |
| `billing.rx_dispense` | ordinario | sí |  |  | billing |  |
| `billing.refund` | sensible |  |  |  | billing | sí |
| `service.list` | ordinario | sí | sí | sí | (derivado del recurso) |  |
| `service.retrieve` | ordinario | sí | sí | sí | (derivado del recurso) |  |
| `service.create` | ordinario |  |  |  | (derivado del recurso) | sí |
| `service.update` | ordinario |  |  |  | (derivado del recurso) |  |
| `service.destroy` | ordinario |  |  |  | (derivado del recurso) |  |
| `patient.list` | ordinario | sí | sí | sí | patients |  |
| `patient.retrieve` | ordinario | sí | sí | sí | (derivado del recurso) | sí |
| `patient.create` | ordinario | sí | sí | sí | (derivado del recurso) | sí |
| `patient.update` | ordinario | sí | sí |  | (derivado del recurso) |  |
| `patient.destroy` | ordinario | sí | sí |  | (derivado del recurso) | sí |
| `owner.list` | ordinario | sí | sí | sí | (derivado del recurso) |  |
| `owner.retrieve` | ordinario | sí | sí | sí | (derivado del recurso) |  |
| `owner.create` | ordinario | sí | sí | sí | (derivado del recurso) |  |
| `owner.update` | ordinario | sí | sí |  | (derivado del recurso) |  |
| `owner.destroy` | ordinario | sí | sí |  | (derivado del recurso) | sí |
| `inventory.list` | ordinario | sí | sí | sí | inventory |  |
| `inventory.retrieve` | ordinario | sí | sí | sí | (derivado del recurso) |  |
| `inventory.create` | ordinario |  |  |  | (derivado del recurso) | sí |
| `inventory.update` | ordinario |  |  |  | inventory | sí |
| `prescription.list` | ordinario | sí | sí |  | (derivado del recurso) |  |
| `prescription.retrieve` | ordinario | sí | sí |  | prescriptions |  |
| `prescription.create` | ordinario | sí |  |  | (derivado del recurso) |  |
| `prescription.destroy` | ordinario | sí |  |  | (derivado del recurso) |  |
| `staff.list` | ordinario | sí | sí |  | users |  |
| `staff.create` | sensible |  |  |  | users |  |
| `staff.destroy` | sensible |  |  |  | users |  |
| `staff.reset_password` | sensible |  |  |  | users |  |
| `organization.retrieve` | ordinario |  |  |  | (derivado del recurso) |  |
| `organization.update` | sensible |  |  |  | (derivado del recurso) |  |
| `dashboard.view` | ordinario | sí | sí |  | dashboard |  |
| `dashboard.financial.view` | sensible |  |  |  | dashboard |  |
| `dashboard.summary` | ordinario | sí | sí |  | dashboard |  |
| `cashsession.list` | ordinario | sí | sí |  | (derivado del recurso) |  |
| `cashsession.retrieve` | ordinario | sí | sí |  | cash |  |
| `cashsession.open` | ordinario | sí | sí |  | cash | sí |
| `cashsession.close` | ordinario | sí | sí |  | cash, notifications | sí |
| `cashmovement.list` | ordinario | sí | sí |  | (derivado del recurso) |  |
| `cashmovement.create` | ordinario | sí | sí |  | (derivado del recurso) | sí |
| `import.list` | ordinario |  |  |  | imports |  |
| `import.retrieve` | ordinario |  |  |  | imports |  |
| `import.create` | ordinario |  |  |  | core, imports | sí |
| `import.commit` | sensible |  |  |  | imports | sí |
| `notification.list` | ordinario | sí | sí |  | notifications | sí |
| `notification.retrieve` | ordinario | sí | sí |  | **sin consumidor** |  |
| `notification.seen` | ordinario | sí | sí |  | notifications |  |
| `agentinbox.view` | ordinario | sí | sí |  | agent | sí |
| `agentinbox.claim` | ordinario |  | sí |  | agent | sí |
| `agentinbox.send` | ordinario |  | sí |  | agent | sí |
| `agentinbox.config` | sensible |  |  |  | agent | sí |
| `agentinbox.identity_verify` | sensible |  |  |  | agent | sí |

## Riesgos

- **El cambio llega a todas las clínicas de golpe.** `seed_permissions` corre en cada release y hace `role.permissions.set(...)`, así que el primer despliegue reescribe el rol ADMIN de todas las organizaciones. Si la lista omite un código en uso, todos los administradores pierden esa función a la vez.
- **Rollback.** Revertir exige otro despliegue, y la caché de permisos por usuario debe contemplarse al verificarlo.
- **Roles personalizados.** La matriz cubre roles de sistema. Falta comprobar si alguna organización editó roles a mano.

## Condiciones para implementar

1. **Matriz aprobada** por el dueño del producto: en particular, confirmar los 19 sensibles y decidir sobre `notification.retrieve`, que no tiene consumidor.
2. **7 días de logs de producción sin `RBAC_FALLBACK_ALLOWED`**, la condición ya documentada en `apps/core/permissions.py`. **No se puede cumplir hoy porque no hay servidor, y no se simula.**
3. **Prueba de equivalencia**: `build_permissions_list` de un ADMIN da el mismo conjunto antes y después, y cada ruta exige un código que el ADMIN conserva.

## Criterio de cierre de H-1

Matriz aprobada, pruebas de regresión en verde y la evidencia de los 7 días adjunta. Hasta entonces, H-1 sigue abierta.

## Alternativas descartadas

- **Quitar `*.*` ahora con la lista generada:** sin evidencia de uso real, un error deja sin función a todos los administradores.
- **Dar por resuelta H-1 con la versión reducida:** no impide que un código nuevo se conceda solo.
