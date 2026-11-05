# ADR p63 — Concesiones explícitas para el ADMIN de clínica

**Fecha**: 2026-11-04
**Estado**: **PROPUESTO. No implementado.** H-1 sigue abierta y el despliegue no está autorizado. Decisiones registradas abajo; falta la aprobación explícita de los permisos sensibles y la evidencia de producción.
**Origen**: auditoría de seguridad run-1, H-1 (`docs/plan-implementacion-seguridad-run1-2026-10-28.md`)

## Contexto

El ADMIN de clínica tiene `*.*`, igual que `ADMIN_SAAS`. Todo código de permiso nuevo se le concede sin que nadie lo decida.

`cb0ff9e` añadió una versión reducida que **no resuelve esto**: cada código se clasifica, y `_is_allowed` niega al comodín los de `WILDCARD_EXCLUDED`. Pero clasificar no es conceder: mientras exista `*.*`, un código clasificado como ordinario o sensible se concede solo.

## Decisión propuesta

Sustituir `*.*` del rol `ADMIN` por una lista literal en `permissions_codes.py`, con el contenido de la matriz. `ADMIN_SAAS` conserva `*.*`. Un superuser no se evalúa por comodín.

La lista **no se deriva** de `PERMISSION_CODES` ni de los grupos de clasificación. Añadir un código al catálogo o clasificarlo no se lo concede al ADMIN: hay que añadirlo a su lista. Sin esto, la clasificación volvería a ser una concesión automática.

**Contenido exacto:** los 87 códigos del catálogo, menos o más lo que se decida en las dos tablas de abajo.

## Decisiones registradas

| Decisión | Resultado |
|---|---|
| Corregir `PATCH` para VET y ASSISTANT | Sí, como trabajo independiente |
| `organization.list` y `prescription.update` | Se incorporan: solo ADMIN, ordinarios |
| `inventory.destroy` y `medicalrecord.destroy` | Se incorporan: solo ADMIN, sensibles |
| `notification.retrieve` | Se retira |
| Los 19 sensibles para el ADMIN | Recomendado; **falta aprobación explícita** |
| `ADMIN_SAAS` con `*.*` | Se mantiene |
| `*.*` en cualquier otro rol | No se admite como excepción implícita: bloquea el despliegue |
| Los escritores de roles | Consumen una única fuente |
| Implementar H-1 | Todavía no |
| Autorizar el despliegue | No, hasta cumplir el gate de producción |

## Dos decisiones separadas

| Decisión | Qué autoriza | Qué exige |
|---|---|---|
| **Aprobar el ADR** | La política, la matriz y escribir el código y las pruebas | Las decisiones pendientes de este documento |
| **Autorizar el despliegue** | Que el cambio llegue a las clínicas | Preflight limpio, y la evidencia de producción descrita abajo |

Hoy se puede avanzar en la primera. **La segunda no se puede cumplir porque no hay servidor, y no se simula.**

## Hallazgo: los 87 códigos no bastan

La primera versión de este ADR cruzó el catálogo con literales del código. Esa dirección no ve lo importante: **códigos que una ruta exige y que no están en el catálogo**. El ADMIN los pasa hoy solo por `*.*`, así que una lista de 87 se los quitaría.

Se enumeraron las rutas reales con el mismo `_resolve_required` de producción: 221 combinaciones de ruta y método, 195 con RBAC. Una prueba contra base de datos local confirmó los códigos de abajo: con los 87 concedidos, el ADMIN recibe `403` en las 10 rutas.

| Código exigido | Rutas (ADMIN hoy → con 87 códigos) | Quién más lo tiene | Decisión | Clase |
|---|---|---|---|---|
| `organization.list` | `GET` de `organizations/me`, `organizations/schedule`, `organizations/settings` y `settings/configuration` (200 → 403) | Nadie | Al catálogo y al ADMIN. **Corrige H-10** | Ordinario |
| `prescription.update` | `PATCH /api/prescriptions/<id>/` (pasa RBAC → 403) | Nadie | Al catálogo y al ADMIN | Ordinario |
| `inventory.destroy` | `DELETE` de `inventory/products/<id>` e `inventory/presentations/<id>` (pasa RBAC → 403) | Nadie | Al catálogo y al ADMIN | Sensible |
| `medicalrecord.destroy` | `DELETE /api/medical-records/<id>/` (pasa RBAC → 403) | Nadie | Al catálogo y al ADMIN | Sensible |
| `patient.partial_update` | `PATCH /api/pets/<id>/` (200 → 403) | Nadie | **No entra al catálogo:** `partial_update` se resuelve como `update` | |
| `owner.partial_update` | `PATCH /api/owners/<id>/` (200 → 403) | Nadie | **No entra al catálogo:** igual que el anterior | |

Los cuatro códigos deben estar en `PERMISSION_CODES` antes de que el seed intente asignarlos, porque el seed descarta en silencio lo desconocido.

**Corrección de H-10.** `1d13389` retiró `organization.list` como código sin consumidor. Era falso: lo exigen cuatro rutas, derivado de `resource_name` y del método, sin literal. El test `test_no_view_service_or_screen_asks_for_them` solo busca texto y no puede verlo. Hoy no hay regresión, porque el ADMIN entra por `*.*`, pero ese test y `RETIRED` deben corregirse. `organization.create` no lo exige ninguna ruta y puede seguir retirado.

**Defecto aparte, fuera de H-1: corregido.** VET y ASSISTANT tienen `patient.update` y `owner.update`, pero recibían `403` en esos `PATCH` porque la ruta pedía `*.partial_update`. Era una distinción técnica de DRF, no una decisión de autorización: `_resolve_required` ya resuelve `partial_update` como `update`. Con eso, H-1 solo necesita los cuatro códigos nuevos; las otras 8 rutas siguen dependiendo de `*.*`.

## Retiro de `notification.retrieve`

**Decisión: se retira al implementar H-1**, y no se concede al ADMIN.

Verificación final: el código aparece solo en `permissions_codes.py` y en este ADR, en todo el repositorio. Ninguna ruta lo exige ni ningún servicio o pantalla lo pide. **Límite:** una integración externa solo podría depender de él leyendo la lista de `/api/me/`; el repositorio no puede descartarlo, así que debe confirmarse con el dueño antes de retirarlo.

El retiro actualiza `PERMISSION_CODES`, los grupos de clasificación, VET y ASSISTANT, los tests de partición y catálogo, y la documentación.

## Permisos sensibles: aprobación por grupo

Solo el ADMIN tiene estos 19 hoy. Recomendación: el ADMIN es titular de todos los grupos, con **aprobación explícita pendiente del dueño del producto**. El análisis estático no puede demostrar esta decisión.

RBAC decide quién puede iniciar una operación, no si esa operación es válida. Las condiciones de cada grupo se conservan; este ADR no verificó que todas estén implementadas hoy, así que la columna es un requisito.

| Área | Códigos | Qué permite | Condición que debe conservarse | Aprobación |
|---|---|---|---|---|
| Documentos de cobro | `invoice.destroy`, `invoice.void_terminal`, `invoice.replace`, `invoice.replace_adjust`, `invoice.replace_manage`, `invoice.replace_waive` | Eliminar, anular o sustituir documentos ya emitidos | Reglas de estado del documento y auditoría | Pendiente |
| Crédito | `invoice.post_unpaid` | Emitir sin cobrar | Trazabilidad de la emisión sin cobro | Pendiente |
| Dinero | `billing.refund`, `billing.clinical_charge.reprice`, `collection.resolve` | Devolver, cambiar precios de cargos clínicos, resolver cobranza | Validaciones de negocio y registro de devoluciones y ajustes | Pendiente |
| Disputas | `checkout.dispute.resolve` | Resolver disputas | | Pendiente |
| Personal | `staff.create`, `staff.destroy`, `staff.reset_password` | Altas, bajas y acceso de empleados | | Pendiente |
| Organización | `organization.update` | Configuración de la clínica | | Pendiente |
| Analítica | `dashboard.financial.view` | Ver datos financieros | | Pendiente |
| Importación | `import.commit` | Escritura masiva de datos | Validaciones de integridad y organización; confirmación y registro de la ejecución | Pendiente |
| Agente WhatsApp | `agentinbox.config`, `agentinbox.identity_verify` | Apagar el agente; vincular una identidad a un expediente | Controles de identidad y auditoría | Pendiente |

Con `inventory.destroy` y `medicalrecord.destroy` serán 21 sensibles.

### Qué significa «sensible»

El comentario actual de `permissions_codes.py` dice que estos códigos «mueven dinero, acceso o identidad». No describe bien la clasificación: `invoice.pay` mueve dinero y figura como ordinario.

**Definición propuesta:** sensible es un código de alto impacto, difícil de deshacer, que por defecto solo tiene el ADMIN. Ordinario es la operación rutinaria de la clínica, aunque toque dinero o borre registros.

Estos ordinarios quedan a confirmar con esa definición. No se propone moverlos de categoría ni de rol:

| Código | Roles además de ADMIN | Justificación propuesta |
|---|---|---|
| `invoice.pay` | ASSISTANT | Cobro diario de recepción |
| `checkout.dispute.open` | VET, ASSISTANT | Abrir no resuelve; resolver es sensible |
| `billing.rx_dispense` | VET | Acto clínico habitual, aunque ADR p26 lo llama de alta confianza |
| `appointment.destroy` | VET, ASSISTANT | Operación de agenda; ADR p57 la deprecó a favor de `/status/` |
| `patient.destroy` | VET, ASSISTANT | El borrado se bloquea si hay dependencias (FK `PROTECT`) |

## Matriz

Filas del catálogo actual. Las concesiones sensibles del ADMIN quedan sujetas a su aprobación. Los cuatro códigos nuevos del hallazgo se añaden al implementar, y `notification.retrieve` se retira.

| Código | Clase | ADMIN | VET | ASSISTANT | AGENT | Rutas que lo exigen | UI |
|---|---|---|---|---|---|---|---|
| `appointment.list` | ordinario | sí | sí | sí | sí | 2 |  |
| `appointment.retrieve` | ordinario | sí | sí | sí | sí | 2 |  |
| `appointment.create` | ordinario | sí | sí | sí | sí | 3 |  |
| `appointment.create_walkin` | ordinario | sí | sí |  |  | chequeo en la vista | sí |
| `appointment.update` | ordinario | sí | sí | sí | sí | 4 |  |
| `appointment.destroy` | ordinario | sí | sí | sí |  | 1 |  |
| `medicalrecord.list` | ordinario | sí | sí | sí |  | 5 |  |
| `medicalrecord.retrieve` | ordinario | sí | sí | sí |  | 2 |  |
| `medicalrecord.create` | ordinario | sí | sí |  |  | 3 |  |
| `medicalrecord.update` | ordinario | sí | sí |  |  | 4 |  |
| `medicalrecord.close` | ordinario | sí | sí |  |  | 1 |  |
| `medicalrecord.vitals.create` | ordinario | sí | sí |  |  | dinámica (`initial`) |  |
| `medicalrecord.vitals.list` | ordinario | sí | sí | sí |  | dinámica (`initial`) |  |
| `medicalrecord.summary.retrieve` | ordinario | sí | sí | sí |  | 1 |  |
| `vaccinerecord.list` | ordinario | sí | sí | sí | sí | 1 |  |
| `vaccinerecord.retrieve` | ordinario | sí | sí | sí | sí | 1 |  |
| `vaccinerecord.create` | ordinario | sí | sí |  |  | 1 |  |
| `vaccinerecord.update` | ordinario | sí | sí |  |  | 1 |  |
| `invoice.list` | ordinario | sí | sí | sí |  | 3 |  |
| `invoice.retrieve` | ordinario | sí | sí | sí |  | 3 |  |
| `invoice.create` | ordinario | sí | sí | sí |  | 6 | sí |
| `invoice.destroy` | sensible | sí |  |  |  | 1 |  |
| `invoice.pay` | ordinario | sí |  | sí |  | 2 |  |
| `invoice.post_unpaid` | sensible | sí |  |  |  | 1 | sí |
| `invoice.replace_waive` | sensible | sí |  |  |  | 1 | sí |
| `invoice.replace` | sensible | sí |  |  |  | 1 | sí |
| `invoice.replace_adjust` | sensible | sí |  |  |  | 1 | sí |
| `invoice.replace_manage` | sensible | sí |  |  |  | 1 | sí |
| `invoice.void_terminal` | sensible | sí |  |  |  | 1 | sí |
| `billing.clinical_charge.reprice` | sensible | sí |  |  |  | 1 |  |
| `checkout.prescription_decide` | ordinario | sí |  | sí |  | 1 |  |
| `checkout.estimate.issue` | ordinario | sí |  | sí |  | 2 | sí |
| `checkout.dispute.open` | ordinario | sí | sí | sí |  | 1 | sí |
| `checkout.dispute.resolve` | sensible | sí |  |  |  | 1 | sí |
| `collection.resolve` | sensible | sí |  |  |  | 1 |  |
| `billing.rx_dispense` | ordinario | sí | sí |  |  | 3 |  |
| `billing.refund` | sensible | sí |  |  |  | 2 | sí |
| `service.list` | ordinario | sí | sí | sí | sí | 1 |  |
| `service.retrieve` | ordinario | sí | sí | sí | sí | 1 |  |
| `service.create` | ordinario | sí |  |  |  | 1 | sí |
| `service.update` | ordinario | sí |  |  |  | 2 |  |
| `service.destroy` | ordinario | sí |  |  |  | 1 |  |
| `patient.list` | ordinario | sí | sí | sí | sí | 2 |  |
| `patient.retrieve` | ordinario | sí | sí | sí | sí | 1 | sí |
| `patient.create` | ordinario | sí | sí | sí | sí | 1 | sí |
| `patient.update` | ordinario | sí | sí | sí |  | 1 |  |
| `patient.destroy` | ordinario | sí | sí | sí |  | 1 | sí |
| `owner.list` | ordinario | sí | sí | sí | sí | 1 |  |
| `owner.retrieve` | ordinario | sí | sí | sí | sí | 1 |  |
| `owner.create` | ordinario | sí | sí | sí | sí | 1 |  |
| `owner.update` | ordinario | sí | sí | sí |  | 1 |  |
| `owner.destroy` | ordinario | sí | sí | sí |  | 1 | sí |
| `inventory.list` | ordinario | sí | sí | sí | sí | 8 |  |
| `inventory.retrieve` | ordinario | sí | sí | sí | sí | 2 |  |
| `inventory.create` | ordinario | sí |  |  |  | 2 | sí |
| `inventory.update` | ordinario | sí |  |  |  | 8 | sí |
| `prescription.list` | ordinario | sí | sí | sí |  | 2 |  |
| `prescription.retrieve` | ordinario | sí | sí | sí |  | 2 |  |
| `prescription.create` | ordinario | sí | sí |  |  | 2 |  |
| `prescription.destroy` | ordinario | sí | sí |  |  | 1 |  |
| `staff.list` | ordinario | sí | sí | sí |  | 1 |  |
| `staff.create` | sensible | sí |  |  |  | 1 |  |
| `staff.destroy` | sensible | sí |  |  |  | 1 |  |
| `staff.reset_password` | sensible | sí |  |  |  | 1 |  |
| `organization.retrieve` | ordinario | sí |  |  |  | 1 |  |
| `organization.update` | sensible | sí |  |  |  | 4 |  |
| `dashboard.view` | ordinario | sí | sí | sí |  | 2 |  |
| `dashboard.financial.view` | sensible | sí |  |  |  | 1 |  |
| `dashboard.summary` | ordinario | sí | sí | sí |  | 2 |  |
| `cashsession.list` | ordinario | sí | sí | sí |  | 1 |  |
| `cashsession.retrieve` | ordinario | sí | sí | sí |  | 1 |  |
| `cashsession.open` | ordinario | sí | sí | sí |  | 1 | sí |
| `cashsession.close` | ordinario | sí | sí | sí |  | 1 | sí |
| `cashmovement.list` | ordinario | sí | sí | sí |  | 1 |  |
| `cashmovement.create` | ordinario | sí | sí | sí |  | 1 | sí |
| `import.list` | ordinario | sí |  |  |  | 1 |  |
| `import.retrieve` | ordinario | sí |  |  |  | 2 |  |
| `import.create` | ordinario | sí |  |  |  | 3 | sí |
| `import.commit` | sensible | sí |  |  |  | 1 | sí |
| `notification.list` | ordinario | sí | sí | sí |  | 1 | sí |
| `notification.retrieve` | ordinario | **no: se retira** | sí | sí |  | **0** |  |
| `notification.seen` | ordinario | sí | sí | sí |  | 2 |  |
| `agentinbox.view` | ordinario | sí | sí | sí |  | 9 | sí |
| `agentinbox.claim` | ordinario | sí |  | sí |  | 6 | sí |
| `agentinbox.send` | ordinario | sí |  | sí |  | 2 | sí |
| `agentinbox.config` | sensible | sí |  |  |  | 5 | sí |
| `agentinbox.identity_verify` | sensible | sí |  |  |  | 2 | sí |

«Rutas que lo exigen» cuenta combinaciones de ruta y método, sin los sufijos de formato del router.

## Qué se verificó y qué no

| Verificación | Resultado | Límite |
|---|---|---|
| Catálogo | 87 códigos clasificados; un test ya exige la partición | |
| Rutas | Enumeradas contra `_resolve_required` | Las 4 rutas sin clase DRF (webhook y salud) no usan RBAC |
| Servicios | Ningún `user_has_permission` usa un literal fuera del catálogo | Solo literales; un código armado en ejecución no se ve |
| Frontend | Ningún `can()` usa un código fuera del catálogo | Solo literales y, en `canAny` y `canAll`, solo el primero de la lista. Que la pantalla corresponda al permiso no se revisó pantalla por pantalla |
| Agente | Su lista es explícita y no cambia. `inbox_assignment.py` busca `agentinbox.send` o `*.*`, y el ADMIN sigue teniendo el primero | |
| Producción | **Sin evidencia** | Todo lo anterior es estático o de base local |

## Alcance real de `seed_permissions`

Leído en el código, con estas consecuencias:

- **Solo toca roles con nombre de `PERMISSIONS`:** `ADMIN`, `VET`, `ASSISTANT` y `AGENT`, en cada organización. Un rol con otro nombre no se modifica.
- **Un rol personalizado con `*.*` conservaría el comodín.** `_get_cached_permissions` une todos los roles del usuario. El preflight debe detectarlo.
- **Editar a mano un rol de sistema ya no sobrevive:** cada release lo reescribe, y un rol llamado `ADMIN` se adopta como de sistema. p63 no añade esa pérdida.
- **No hay vía de producto para editar roles:** ni API ni admin de Django; solo shell o SQL. Hay que comprobar en producción, no asumir, que nadie lo hizo.
- **Hay dos escritores:** `seed_permissions` para las existentes y `_seed_roles_for_org` para las nuevas. Ambos leen `PERMISSIONS`, y las pruebas deben cubrir los dos.
- **Descarta en silencio lo que no esté en el catálogo.** Con `organization.list` en la lista del ADMIN pero no en `PERMISSION_CODES`, el rol quedaría sin él y sin error. La lista debe ser subconjunto del catálogo, por test.
- **No es atómico entre organizaciones.** Un fallo a mitad deja unas con lista y otras con comodín. Volver a correrlo converge, y el procedimiento debe decirlo.
- **La demo es un tercer escritor.** `seed_demo_clinic` arma su lista con `PERMISSION_CODES` menos `import.*`, así que un código nuevo le llegaría solo. Además, cada `seed_permissions` le pisa esa restricción hasta la siguiente corrida de la demo. Eso ya ocurre hoy y debe resolverse aquí.

**Política única.** `seed_permissions`, `_seed_roles_for_org` y `seed_demo_clinic` consumen la misma fuente explícita. La demo solo puede restarle `import.*` de forma declarada, nunca mantener otra lista. Sin esto habría tres políticas que coinciden por casualidad.

## Preflight

`seed_permissions` no tiene `--dry-run`: hay que construirlo. Sin escribir nada, informa por organización:

1. Roles `ADMIN` y usuarios con `role='ADMIN'`.
2. Usuarios activos sin `UserRole`, y usuarios cuyo `role` no coincide con su `UserRole`.
3. Permisos actuales de cada rol, y qué ganaría o perdería con la matriz.
4. Roles que no son de sistema, y los permisos efectivos de cada usuario que combine varios roles.
5. Diferencias entre organizaciones.

**Bloquea el despliegue, sin opción de continuar con advertencia:**

- Cualquier rol distinto de `ADMIN_SAAS` que fuera a conservar `*.*` o un comodín `recurso.*`. Como `_get_cached_permissions` une todos los roles del usuario, uno solo bastaría para que siga recibiendo permisos futuros. Solo se admite con una excepción explícita, aprobada y documentada, identificada por organización y rol.
- Cualquier otro resultado que no corresponda a la matriz aprobada.

## Pruebas exigidas

**A. No perder capacidades.** Sobre roles sembrados de verdad, en dos organizaciones:

- Conjunto efectivo antes y después, evaluado con `_is_allowed` sobre el catálogo **más todos los códigos que exigen las rutas**. `build_permissions_list` no sirve sola: filtra por `PERMISSION_CODES` y no ve los códigos de fuera, justo los que causaron el hallazgo.
- Ninguna concesión accidental, salvo exclusiones aprobadas.
- Un test recorre las rutas: todo código exigido está en la lista del ADMIN o tiene exclusión aprobada.
- La lista del ADMIN es subconjunto del catálogo.

**B. No conceder códigos futuros.** Es la prueba que demuestra que H-1 quedó resuelta. Con un código ficticio `future_module.execute` en el catálogo:

1. El ADMIN no lo recibe, ni por base de datos ni por el fallback estático.
2. `ADMIN_SAAS` y el superuser conservan su comportamiento.
3. Lo recibe solo después de añadirlo a su lista y volver a sembrar.
4. Clasificarlo como ordinario o sensible no se lo concede.

**C. Los tres escritores.** Se ejecuta de verdad cada uno de `seed_permissions`, `_seed_roles_for_org` y `seed_demo_clinic`, y sobre el resultado **persistido**:

- Los permisos del rol en base de datos coinciden con la política; la demo, solo con su resta declarada.
- La autorización responde igual por las rutas reales, no solo al comparar listas de Python.

**D. Usuario con varios roles.** Un usuario `ADMIN` con además un rol personalizado con `*.*` no pasa el preflight, y un código futuro no le llega si el rol adicional no tiene comodín.

**Advertencia:** 69 archivos de test asignan `*.*` directamente en sus fixtures. Seguirán en verde aunque la lista esté mal, así que una suite verde no demuestra esta decisión.

## Rollback

- **Caché:** no hay caché compartida que invalidar. `_cached_permissions` vive en la instancia del usuario, que `TenantJWTAuthentication` carga en cada request. La versión anterior de este ADR sugería lo contrario.
- **Frontend:** conserva los permisos en memoria hasta releer `/me/`. Tras el cambio puede mostrar botones que reciben `403`. El backend es quien decide.
- **Procedimiento:** revertir y correr `release` con la imagen anterior. Según el código, `seed_permissions` restaura `*.*` en los roles de sistema, porque sobrescribe el rol y la fila `*.*` no se borra. No toca roles personalizados.

Esto aún no está probado. Se exigen estos escenarios sobre base de datos:

| Escenario | Qué comprobar |
|---|---|
| Lista explícita → comodín | El ADMIN recupera las capacidades anteriores |
| Lista explícita → comodín, con códigos nuevos ya sembrados | No se pierden permisos ni quedan duplicados o concesiones inconsistentes |
| Seed que falla a mitad, y se vuelve a correr hacia adelante y hacia atrás | Todas las organizaciones convergen. Que sea convergente debe demostrarse |

En producción, el preflight confirma que el ADMIN recuperó sus permisos, y que `ADMIN_SAAS`, VET, ASSISTANT y AGENT no cambiaron.

## Evidencia de producción

**Se conserva el gate documentado en `apps/core/permissions.py`**, que la versión anterior de este ADR citaba incompleto: 7 días sin `RBAC_FALLBACK_ALLOWED` **ni `TENANT_MISMATCH_DETECTED`**, con **≥500 requests** y **≥1 request por cada endpoint crítico**. Esa lista no estaba escrita en ningún sitio: la propuesta está abajo.

Se añade, porque la ausencia de un evento no basta:

1. **Cobertura de logs:** todos los procesos e instancias, sin huecos de recolección durante los 7 días.
2. **`UserRole` en base de datos:** todo usuario activo lo tiene. El log no alcanza: `user_has_permission` usa el mismo fallback sin emitir evento, y un usuario inactivo esos días no aparece.
3. **Uso real del ADMIN:** los `required_permission` de `RBAC_ALLOWED_DB` con rol `ADMIN` están todos en la lista. Es la evidencia que responde a este cambio. El gate de fallback dice si los usuarios están migrados, no qué usa un administrador.

### Endpoints críticos (propuesta, por aprobar)

| Área | Endpoints |
|---|---|
| Autenticación y contexto | `POST /api/token/`, `POST /api/token/refresh/`, `GET /api/me/`, `GET /api/organizations/me/` |
| Pacientes y propietarios | `GET` y `POST /api/pets/`, `PATCH /api/pets/<id>/`, `GET /api/owners/`, `PATCH /api/owners/<id>/` |
| Agenda | `GET` y `POST /api/appointments/`, `POST /api/appointments/walk-in/`, `PATCH /api/appointments/<id>/status/` |
| Expedientes | `GET` y `POST /api/medical-records/`, `POST /api/medical-records/<id>/vitals/`, `POST /api/medical-records/<id>/close/` |
| Prescripciones | `GET` y `POST /api/prescriptions/`, `POST /api/billing/prescriptions/<id>/dispense/` |
| Inventario | `GET /api/inventory/products/`, `POST /api/inventory/products/<id>/adjust/`, `GET /api/inventory/movements/` |
| Facturación y cobros | `GET /api/billing/checkouts/`, `POST /api/billing/checkouts/direct-sale/`, `POST /api/billing/checkouts/<id>/post/`, `POST /api/billing/checkouts/<id>/pay/`, `PATCH /api/billing/invoices/<id>/pay/`, `POST /api/billing/invoices/<id>/refund/`, `POST /api/billing/invoices/<id>/void/` |
| Caja | `POST /api/cash/sessions/open/`, `GET /api/cash/sessions/current/`, `POST /api/cash/sessions/<id>/close/`, `POST /api/cash/movements/` |
| Usuarios | `GET /api/staff/`, `POST /api/staff/create/`, `POST /api/staff/<id>/reset-password/` |
| Notificaciones | `GET /api/v1/notifications/feed/`, `POST /api/v1/notifications/<key>/seen/` |
| Agente WhatsApp, si está habilitado | `GET /api/inbox/threads/`, `POST /api/inbox/conversations/<id>/send/`, `POST /api/inbox/conversations/<id>/claim/`, `POST /api/inbox/conversations/<id>/verify-identity/`, `POST /api/inbox/conversations/<id>/authorize-identity/`, `PATCH /api/inbox/settings/` |

Los 500 requests no sustituyen esta cobertura. Tres puntos que el gate debe resolver:

- **El campo `endpoint` guarda `request.path`, con identificadores.** Medir cobertura exige normalizarlo contra el patrón de la ruta.
- **Los eventos RBAC no ven todo.** `/api/token/`, `/api/token/refresh/` y `/api/me/` no aparecen entre las rutas con RBAC, así que su cobertura necesita otra fuente de logs, aún por identificar.
- **Una operación rara puede no ocurrir en 7 días**, como una devolución en una clínica pequeña. Propuesta: la ventana se amplía hasta cubrirla, sin generar tráfico sintético en producción. Debe aprobarse.

## Criterio de cierre de H-1

Decisiones aprobadas, pruebas A, B, C y D y escenarios de rollback en verde, preflight limpio y evidencia de producción adjunta. Hasta entonces, H-1 sigue abierta.

## Alternativas descartadas

- **Quitar `*.*` ahora con la lista generada:** habría cortado 10 rutas a todos los administradores, incluida la configuración de la clínica.
- **Dar por resuelta H-1 con la versión reducida:** no impide que un código nuevo se conceda solo.
- **Derivar la lista de los grupos de clasificación:** clasificar volvería a conceder.
