# VeterinariaSaaS - Reglas para Claude Code

## Stack actual
- Backend: Django 6 + DRF + SimpleJWT
- Frontend: React 19 + Vite (JavaScript, no TypeScript)
- DB: PostgreSQL multitenant
- Deploy objetivo: Docker / VPS
- Branch activa de desarrollo: `develop`

## Proposito de este archivo
Este archivo contiene reglas operativas cortas para trabajar en el repo.

La documentacion larga vive en:
- `docs/decisions/` - ADRs y decisiones historicas
- `docs/modules/` - contratos y acoplamientos por modulo
- `docs/runbooks/` - operacion, testing y soporte
- `DEPLOY_VPS_PLAN.md` - plan de despliegue Docker/VPS

---

## Reglas backend no negociables

### Sanitizacion de texto libre
Todos los campos de texto libre pasan por `sanitize_text()` de `apps/core/sanitize.py`.

Patron obligatorio:
```python
clean = sanitize_text(value or '', max_length=255)
```

Reglas:
- Nunca pasar `None` directo; siempre `value or ''`
- Validar campos obligatorios despues de sanitizar
- FBVs con texto libre sanitizan en la view, no delegan ciegamente al serializer

Limites frecuentes:
- `diagnosis`, `treatment` -> `max_length=400`
- `notes` -> `max_length=5000`
- `vaccine_name`, `reason` -> `max_length=255`
- `motivo`, `cancellation_reason`, `batch_number` -> `max_length=100`

### Multitenancy
Toda query de negocio debe usar `for_organization()`.

Correcto:
```python
obj = Model.objects.for_organization(request.user.organization)
```

Incorrecto:
```python
Model.objects.filter(pk=pk)
```

### Validacion tenant de FKs en serializers
Todo serializer que reciba FKs de modelos organizacionales debe validar tenant.

Patron:
```python
def validate_pet(self, pet):
    if pet and pet.organization != self.context['request'].user.organization:
        raise ValidationError('Acceso invalido.')
    return pet
```

### Serializer checklist minimo
Todo serializer nuevo debe cumplir:
- `CharField` / `TextField` libre -> `sanitize_text()` con `max_length`
- campo obligatorio -> no vacio despues de sanitizar
- precio -> `> 0`
- stock / cantidad -> `>= 0` o `> 0` segun dominio
- FK de otro modulo -> validacion tenant

---

## Concurrencia, stock y facturacion

### Transacciones
Toda operacion que toque stock + factura debe vivir dentro de `transaction.atomic()`.

Reglas:
- `select_for_update()` solo bloquea cuando el queryset se evalua (`.get()`, `.first()`, `.exists()`, iteracion)
- si un service recibe un objeto ya cargado, debe re-fetch con lock al inicio
- el lock debe cubrir toda la cadena, incluyendo helpers y `save()` internos

Patron:
```python
with transaction.atomic():
    locked = Model.objects.select_for_update().filter(...).first()
```

### Mutaciones numericas contables
Las mutaciones de `InvoiceItem.quantity` deben usar `F()` via `.update()`, nunca `item.quantity += delta; item.save()`.

Helper canonico:
- `apps.billing.services.apply_invoice_item_quantity_delta(item, delta)`

### Contratos criticos
- `apply_stock_movement()` no adquiere su propio lock; el caller debe poseer `select_for_update()` sobre `presentation`
- `MedicalRecordProduct.save()` / `.delete()` exigen `transaction.atomic()`
- `bulk_create` siempre asigna `organization` explicitamente
- deletes que revierten stock deben envolver lock + `atomic()` antes de `super().delete()`
- en operaciones idempotentes tipo walk-in, lockear una fila estable que siempre exista

### Orden global de locks (canonico)
Todo flujo que adquiera multiples locks DEBE seguir este orden, para evitar deadlocks ABBA:

```
MedicalRecord -> Invoice -> Presentation -> InvoiceItem
```

Reglas:
- Dentro de un mismo tipo, lockear por PK ascendente (`_lock_presentations` ordena los IDs).
- Toda mutacion de `InvoiceItem` (create / save / delete / quantity-delta) debe correr con la Invoice ya lockeada (`select_for_update`) dentro del mismo `atomic()`. Garantiza que `recalculate_totals` no sufra lost-update. `InvoiceItem.save/delete` loguea `INVOICEITEM_MUTATION_OUTSIDE_ATOMIC` (warn) si se llama fuera de `atomic()`.
- Verificado por la suite real `apps.billing.tests.test_invoice_concurrency` (Postgres + threads). No reordenar locks sin volver a correrla.

### Validacion de stock
Las validaciones de stock en serializers son solo pre-check UX. La validacion autoritativa vive en la view/service con lock.

---

## IDs publicos y URLs

### Regla general
Modelos expuestos publicamente usan `public_id` (UUID) en URLs, no PK entero.

Modelos con `public_id`:
- `Pet`, `Owner`, `Appointment`, `MedicalRecord`, `Invoice`, `Prescription`, `Product`, `Presentation`, `Service`, `VaccineRecord`, `User`, `Organization`

Modelos internos sin `public_id`:
- `InvoiceItem`, `StockMovement`, `MedicalRecordProduct`, `MedicalRecordService`, `InvoiceAuditLog`, `AppointmentStatusChange`, `VitalSigns`, `Permission`, `Role`, `UserRole`

### Reglas de implementacion
- parametros URL de modelos publicos: siempre `<str:>`
- resolver IDs con `resolve_public_id()`, no con `pk=` directo
- query params de modelos publicos tambien resuelven via `resolve_public_id(Model.objects.for_organization(org), raw)`
- cross-tenant debe dar `404`, no `[]`

### Convencion por capa
- backend / JSON: `public_id`
- frontend JS: `publicId`
- URLs: UUID raw
- FK en body `POST/PATCH`: PK entero (`PrimaryKeyRelatedField`)

### Anti-patterns prohibidos
- `editing.public_id || editing.id`
- `try uuid except pk` ad-hoc en views
- helpers genericos tipo `resolve_anything()`
- dual-lookup PK + UUID sin flag de migracion
- `PrimaryKeyRelatedField` esperando UUID en body

---

## RBAC y permisos
- Todos los endpoints usan `HybridPermission` o `make_permission()`
- Nunca usar `RolePermission` directamente
- Nunca verificar `user.role == 'ADMIN'` directo en views o permissions locales
- Si agregas nuevos codigos a `PERMISSION_CODES`, debes correr `seed_permissions` en el siguiente deploy
- `billing` usa `cancelled`; `appointments` usa `canceled` - no mezclar

### Gotcha de vistas anidadas
En list views anidadas bajo `<str:pk>` del padre, declarar `required_permission` por metodo en `initial()` para evitar que `HybridPermission` infiera `retrieve` por error.

Ejemplo:
```python
def initial(self, request, *args, **kwargs):
    if request.method == 'GET':
        self.required_permission = 'medicalrecord.vitals.list'
    else:
        self.required_permission = 'medicalrecord.vitals.create'
    super().initial(request, *args, **kwargs)
```

---

## Facturacion y estados
- Invoice: `draft -> confirmed -> paid`
- Cancelacion permitida desde `draft` o `confirmed`
- Solo `draft` es editable
- `confirm_invoice` requiere al menos un item activo
- `pay_invoice` requiere estado `confirmed` + `payment_method`
- `total`, `subtotal`, `tax_amount`, `tax_rate` se recalculan en backend y son `read_only`

Flujo canonico de sync de invoice:
1. `billing.signals.create_draft_invoice_on_done`
2. `medical_records.views._sync_invoice_item`
3. `inventory.views._sync_invoice_item`

Si la invoice aun no existe, usar `get_or_create_invoice_for_medical_record()` de `apps.billing.services`.

---

## Frontend auth y seguridad
- No tocar tokens fuera de `frontend/src/auth/tokenStorage.js`
- No usar `localStorage.getItem("access_token"|"refresh_token"|"user")` fuera de ese modulo
- No crear update paths alternos para password que bypassen `change_password` / reset flows oficiales
- Respetar `MustChangePasswordGate` backend y frontend
- Si frontend agrega headers custom (`X-Request-ID`, futuros idempotency keys, etc.), actualizar `CORS_ALLOW_HEADERS`

---

## Analytics no negociable
Cuando toques `billing`, `medical_records`, `appointments` o `analytics`, validar:

1. writers de anchors solo en `services.py`
2. escritura nueva usa provenance `'service'`
3. `build_daily_metrics` sigue siendo idempotente
4. today nunca se snapshottea
5. dashboard siempre devuelve `source` y `lifecycle_state`
6. no usar `cache.clear()` masivo en signals
7. CHECK constraints analiticos son contrato
8. si cambia semantica de KPI, bumpear `METRICS_SCHEMA_VERSION`

---

## Gotchas importantes del repo
- `for_organization()` debe ir primero en la cadena del queryset; `select_related()` / `prefetch_related()` antes rompen el manager custom
- `apps.platform` en Windows + Python 3.13: no correr `python manage.py test apps.platform`; usar modulos completos `apps.platform.tests.test_X`
- errores 500 incluyen `request_id`; no exponer mensajes crudos del ORM al frontend
- `IntegrityError` no esta normalizado por el exception handler global; validar duplicados antes de llegar a DB

---

## Comandos de referencia rapida

Setup minimo:
```bash
python manage.py migrate
python manage.py seed_permissions
```

Comandos utiles:
```bash
python manage.py audit_anchor_integrity
python manage.py build_daily_metrics
python manage.py flushexpiredtokens
```

Para suites completas, bootstrap detallado, password flows y deploy Docker/VPS, ver:
- `docs/runbooks/password-change.md`
- `docs/runbooks/platform-org-provisioning.md`
- `docs/runbooks/audit_orphan_fks.md`
- `docs/modules/frontend.md`
- `docs/modules/analytics.md`
- `DEPLOY_VPS_PLAN.md`
- `docs/decisions/`
