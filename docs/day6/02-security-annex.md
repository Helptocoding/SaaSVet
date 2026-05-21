# Anexo de Seguridad — Plan Día 6

## 1. Veredicto

**Parcial.** El draft cierra IDOR/enumeration sobre los detail endpoints de modelos públicos (Pet, Owner, Appointment, MR, Invoice, Prescription, Product, Presentation, Service) cuando se ejecutan las fases 1-6 y se apaga `ALLOW_LEGACY_ID_LOOKUP`. Pero quedan **siete superficies con `<int:>` o `?param=<pk>` que el draft enumera de forma genérica sin convertirlas en acciones bloqueantes**, dos vectores de tenant-leak en sub-recursos, una regresión potencial en `HybridPermission._method_to_action` y dos serializers que aceptan FK organization sin defensa en profundidad. Sin las cláusulas de §3 incorporadas, el cutover deja IDOR explotable en `vaccines/<int:pk>/`, enumeration en `prescriptions/pet/<int:pet_id>/`, y filtros `?pet=<pk>` que ignoran tenant antes del filtro.

## 2. Hallazgos por categoría

### IDOR — sub-recursos y endpoints con `<int:pk>` actuales

- **HIGH — `vaccines/<int:pk>/` (`VaccineRecordDetailView`)**. El draft menciona vaccines como modelo interno "sin caso de uso standalone", pero la URL ya existe y es accesible. Hoy `get_queryset()` filtra por org (mitigación real), pero el PK secuencial permite enumeration trivial vía 404 vs 200. Ataque: barrido `1..N` revela rango de IDs creados por la plataforma cross-org. Refuerzo: promover `VaccineRecord` a `public_id` (la lista de "modelos públicos" del §3 del draft debe incluirlo) o anidarlo bajo `/medical-records/<uuid>/vaccines/<int:pk>/`.
- **HIGH — `prescriptions/<int:prescription_pk>/items/<int:pk>/`**. El parent es `<int:>`, no UUID. Aunque la view filtra por `organization=request.user.organization`, el atacante enumera prescriptions ajenas observando 404 vs 403. Refuerzo: `<str:prescription_pk>` + `resolve_public_id`. Está en el draft Fase 1 pero como genérico — debe quedar checklist explícito.
- **MEDIUM — Sub-items `/invoices/<uuid>/items/<int:pk>/`**. El draft acepta esto. Riesgo residual: si un atacante con UUID de invoice válida de su org enumera `items/1, items/2, ...` y recibe 404 para items pertenecientes a OTRA invoice **del mismo tenant**, leakea cardinalidad global del tenant. El control `pk + invoice=parent` lo bloquea (verificado en `InvoiceItemDetailView.get_object`), pero el patrón debe ser obligatorio en el draft: §4 menciona el ejemplo pero no lo eleva a regla. Refuerzo: cláusula explícita "todo sub-recurso detail filtra `pk + parent=parent_obj`, ambos en la misma query".

### Enumeration

- **HIGH — `medical-records/pet/<int:pet_id>/` y `prescriptions/pet/<int:pet_id>/`**. El draft los enumera en Fase 1 pero no como acción separada. Riesgo: aunque el resultado se filtre por org, **el `pet_id` entero permite enumerar la existencia de pets de otras orgs** vía respuesta `200 []` (pet existe, sin MRs) vs `200 []` (pet no existe). Indistinguible — beneficio: no leakea. Pero si por error en el futuro alguien agrega `Pet.objects.get(pk=pet_id)` para enriquecer respuesta, se rompe. Refuerzo: cambiar a `<str:pet_public_id>` + `resolve_public_id(Pet.objects.for_organization(...), pet_public_id)` **antes** del filtro de MRs. Esto elimina el vector y la trampa futura.

### Tenant leaks — query params

- **BLOCKER — `?pet=<pk>` y `?owner=<pk>` filtran sin resolver tenant primero**. `AppointmentListCreateView`, `MedicalRecordListCreateView`, `PrescriptionListCreateView`, `VaccineRecordListCreateView`, `InvoiceListCreateView`, `PetViewSet` (`?owner=`) hacen `qs.filter(pet_id=pet_id)` directo. Ataque: con UUID de pet ajeno (Fase 3 acepta UUID), `?pet=<uuid-ajeno>` devuelve `[]` (no rompe) — pero si se pasa el `pk` entero de un pet ajeno, hoy con flag ON el filtro JOIN-ea sin tenant scope sobre `pet_id` y el `for_organization` del queryset principal salva. **Si en Fase 3 se acepta UUID directo sin resolver vía instancia validada por tenant, el draft pierde la oportunidad de hacer enforcement explícito**. Refuerzo: el draft ya propone el patrón correcto en §6 (resolve → instance → filter). Subirlo a obligación con test: "query param de modelo público SIEMPRE pasa por `resolve_public_id(Model.objects.for_organization(org), value)` antes de filtrar — never `qs.filter(pet_id=raw_value)`".

### Tenant leaks — sub-recurso sin verificación parent↔child

- **MEDIUM — `MedicalRecordServiceDeleteView.get_object` verifica `medical_record=mr` pero NO verifica `service.organization`**. El draft no aborda este caso. Riesgo: aunque hoy el flujo correcto valida, una refactor que pase `service` desde body sin re-validar tenant rompería el invariante (patrón P0 #7 walk-in dedup ignoraba campo). Refuerzo: cláusula explícita "sub-recurso que mantiene FK a tercer modelo (`service`, `presentation`) revalida `obj.organization == request.user.organization` además del parent chain".

### RBAC regressions

- **MEDIUM — `HybridPermission._method_to_action` infiere `retrieve` cuando `kwargs` tiene `pk` o `id`**. Para list views anidadas bajo `<str:pk>` (ej. `VitalSignsListCreateView` GET con `pk` del MR padre) infiere `retrieve` en lugar de `list`. ADR-09 documenta esto y el código ya lo neutraliza con `initial()` declarando `required_permission` explícito. **El draft NO menciona** que el cambio masivo de `<int:pk>` a `<str:pk>` puede regresar este caso en views que no hayan recibido el fix de ADR-09. Refuerzo: agregar paso de auditoría — grep `<str:` y verificar que toda list/create view anidada declare `required_permission` por método HTTP en `initial()`. Si no lo declara, queda vulnerable a denegación o sobreautorización por mapping incorrecto.

### Privilege escalation

- **HIGH — `OrganizationSerializer` incluye `id` writable de facto**. `Meta.fields = ['id', ...]` sin `read_only_fields = ['id', ...]`. DRF marca `id` read-only por default solo si el campo es el PK declarado en `Meta.model`, pero a `OrganizationLegacyView` PATCH es teóricamente posible escalar si el cliente envía `id` en body — DRF lo ignora porque es PK, pero el draft P1 #40 va contra ESTE patrón exactamente. Refuerzo: documentar lista exhaustiva de serializers con campos org/id writable o `IntegerField`-mapeados — además de `CreateEmployeeSerializer.organization_id`, auditar `OrganizationSettingsSerializer` (OK, no expone FK), y bloquear cualquier futuro `OrganizationField(write=True)`.
- **MEDIUM — `MedicalRecordServiceListCreateView.perform_create` ya valida `service.organization_id != request.user.organization_id`** — esto es defense-in-depth correcto. Documentar en draft como patrón obligatorio para create views que aceptan FK de catálogo cross-app.

### Information leak en error responses

- **MEDIUM — Inconsistencia 404 vs 403 entre `PublicIdLookupMixin` y `HybridPermission.has_object_permission`**. El mixin retorna `NotFound` (404) cuando el UUID no calza en el queryset filtrado por tenant. Pero si el objeto SÍ existe (UUID legítimo de otra org se pasa) y por algún flujo bypaseara `for_organization` en `get_queryset`, `has_object_permission` retorna False → 403 → confirma existencia. Hoy todos los `get_queryset` aplican `for_organization` (verificado), pero el draft debe declarar invariante: **tenant mismatch responde 404, nunca 403**. Refuerzo: cláusula en §4 "queryset de detail SIEMPRE empieza por `for_organization` antes que `select_related/prefetch_related` (ADR-10) — esto colapsa cross-tenant a 404 antes que `check_object_permissions` vea el objeto".

### DoS — UUID malformado

- **LOW — `PublicIdLookupMixin.get_object` y `resolve_public_id` llaman `_uuid_module.UUID(str(lookup))` sin límite de longitud**. Payload de 10 MB en path produce string-cast costoso antes del UUID parse. Mitigación: Django/nginx ya capean URL path a ~8KB, riesgo real bajo. Refuerzo opcional: `if len(str(lookup)) > 64: raise NotFound()` antes del `UUID(...)`. No bloqueante.
- **LOW — Path con UUID válido pero inexistente** consume un SELECT por request. Sin rate limit dedicado, atacante autenticado puede sondear UUIDs aleatorios. Mitigación existente: `DEFAULT_THROTTLE_RATES` global. No agregar throttle scope dedicado al endpoint legacy lookup; reciclar `user` scope.

## 3. Adiciones al draft

Incorporar antes de comenzar Fase 1:

- **Query param resolution rule (§6 elevar a obligación)**: "Todo `?<modelo_publico>=<value>` resuelve vía `resolve_public_id(Model.objects.for_organization(org), value)` y filtra por instancia. Prohibido `qs.filter(<modelo>_id=raw_value)`."
- **Sub-recurso parent-child invariante (§4 nuevo)**: "Sub-recurso detail filtra `pk + parent=parent_obj` en la misma query, donde `parent_obj` viene de `resolve_public_id(... for_organization(org) ...)`. Sub-recurso que referencia FK a tercer modelo (service, presentation, product) revalida `obj.organization == request.user.organization` después del lookup."
- **VaccineRecord promover a `public_id`** (§3 lista de modelos públicos). Hoy expone `<int:pk>` detail editable y `<int:>` no se elimina con sub-recurso anidado.
- **404-as-403 invariante (§4 nuevo)**: "Queryset de detail empieza por `for_organization()` (ADR-10). Tenant mismatch siempre 404, nunca 403. Verificación: tests `test_cross_tenant_returns_404` por cada detail endpoint."
- **Defense-in-depth FK catálogo en create views (§4)**: "create views que reciben FK de catálogo (service, product, presentation) deben validar `fk.organization == request.user.organization` antes de `serializer.save()`, además de la validación del serializer (ADR-13). El patrón `MedicalRecordServiceListCreateView` es canónico."
- **List views anidadas — `required_permission` explícito (§4)**: "List view bajo URL con `<str:pk>` (parent UUID) DEBE declarar `required_permission` por método HTTP en `initial()` (ADR-09). El mapping automático de `_method_to_action` infiere `retrieve` por presencia de `pk` y rompe RBAC list/create."
- **Audit de serializers con FK `organization` writable (§4 nuevo)**: "Listar exhaustivamente serializers que exponen `organization`/`organization_id` writable. Solo `derived from JWT` es válido. Tests: `test_cannot_set_organization_via_body` por serializer afectado."

## 4. Gaps de scope

- **`/medical-records/pet/<int:pet_id>/` y `/prescriptions/pet/<int:pet_id>/`** — el draft los enumera en Fase 1 pero no como ítems bloqueantes con propietario. Agregar a checklist con conversión a `<str:pet_public_id>` resolviendo el Pet vía `resolve_public_id` ANTES del filtro.
- **`/vaccines/<int:pk>/`** — el draft ni lo lista en §3 ni en Fase 1. Agregar.
- **`OrganizationSettingsView`** — el draft lo ignora. Verificar que no expone `organization_id` writable y que el lookup viene de `request.user.organization` (verificado OK), pero documentarlo como invariante en §3.
- **`StaffListView`** y **`StaffDeactivateView` `?role=`** — el draft Fase 5 toca `StaffDeactivateView` URL pero no `StaffListView`. `?role=` ya valida contra `VALID_ROLES` (OK), pero documentar.
- **`MeView` response no incluye `organization.public_id`** — el draft Fase 4 promete `Organization.public_id` para `/me/`. Verificar que el response shape gane el campo sin perder `organization` (que hoy es PK).
- **`PrescriptionListCreateView.get_queryset` con `?pet=<value>`** — el código actual hace `filter(pet_id=pet_id)` aceptando ambos hoy con flag. Fase 3 debe cubrirlo explícitamente.

## 5. Lo que está OK

- **`PublicIdLookupMixin.get_object` invoca `check_object_permissions`** después del lookup — RBAC sobre objeto resuelto se mantiene, no rompe con cambio de URL kwargs.
- **`HybridPermission.has_object_permission` filtra `obj.organization_id != user.organization_id` antes que cualquier otra cosa** y emite `TENANT_MISMATCH_DETECTED` (ERROR). Defense-in-depth real para el caso degenerado donde el queryset no filtre por org.
- **Sub-recursos `InvoiceItemDetailView`** ya implementan `pk + invoice=parent` en `get_object_or_404` — patrón correcto, solo falta elevarlo a regla declarada.
- **ADR-13 tenant validators en `InvoiceSerializer` / `PrescriptionItemSerializer`** cierra el vector de FK body cross-tenant. El draft mantiene FK body como PK — consistente y seguro.
- **`OrganizationLegacyView` valida `pk_int != request.user.organization_id` → 404** — no leakea existencia de orgs ajenas. RFC 8594 + Sunset 2026-08-17 documentado.
- **`CreateEmployeeSerializer.create` pop-ea `organization_id` y deriva de `request.user.organization`** — el campo writable es decorativo y será removido en Fase 4. Confirmado.
- **`resolve_public_id` rechaza strings no-UUID no-numéricos con 404 inmediato**, sin fallback silencioso — comportamiento estricto.
