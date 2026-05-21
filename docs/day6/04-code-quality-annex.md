# Anexo de Code Quality / Deuda Técnica — Plan Día 6

## 1. Veredicto

**Parcial.** El draft + sus dos anexos son técnicamente sanos en lo macro (división `public_id` vs PK, prohibición explícita de dual-lookup, lista de anti-patterns en §9), pero introduce **dos formas de deuda invisible**:

1. **Repetición sancionada del patrón `resolve_public_id(Model.objects.for_organization(org), value)`** en ~8 sitios nuevos (query params Fase 3 + 2 endpoints `pet/<pet_id>/` + invariantes de sub-recurso del anexo seguridad) sin promover a helper, lo cual está bien — pero el plan no documenta dónde tolerar repetición vs cuándo es ya code smell.
2. **Coupling implícito con `ALLOW_LEGACY_ID_LOOKUP`** dentro de `resolve_public_id` y `PublicIdLookupMixin` (`backend/apps/core/views.py:49,76`). Cuando se "elimine el flag 30 días post-cutover" (§13), se tocan al menos 3 archivos, y ningún test bloquea el regreso accidental del fallback.

El plan también deja **dos contratos no escritos** que producirán drift en 6 meses: nomenclatura `publicId`/`public_id`/`uuid` y el orden canónico `for_organization() → select_related()` (ADR-10).

## 2. Hallazgos

### Helper creep / over-abstraction

**SEVERIDAD: BAJA.** Anti-pattern potencial: `IdentityResolverFactory`.
El draft (§9 punto 2) ya prohíbe `resolve_anything()`/`SmartIdField`/`MagicLookup`, lo cual es correcto. Pero el anexo seguridad agrega "query param resolution rule" y "sub-recurso parent-child invariante", y el draft Fase 3 los implementa inline. Tres ocurrencias del mismo patrón (`pet`, `owner`, `appointment` en `MedicalRecordListCreateView`, `InvoiceListCreateView`, `AppointmentListCreateView`) NO justifican helper — son 3 líneas cada una y el contexto local (qué campo filtrar) es distinto.
**Fix:** mantener inline. Documentar regla en §9: "Repetición de `resolve_public_id(Model.objects.for_organization(org), val)` es tolerada hasta 6 ocurrencias por app. Promoción a helper requiere ADR."

### Fallback spaghetti

**SEVERIDAD: MEDIA.** Anti-pattern: dual-source-of-truth.
`frontend/src/pages/inventory.jsx:263,298,600` ya tiene `editing.public_id || editing.id` y `OperationalFeed.jsx:49,51` también. El draft (§5) lo prohíbe pero la limpieza queda en "lint manual durante PR". Esto es frágil: el siguiente dev escribe el mismo fallback "por seguridad".
**Fix:** agregar a `package.json` script eslint con regla `no-restricted-syntax` matcheando `LogicalExpression[operator="||"] > MemberExpression[property.name="public_id"]`. Sin esto la regla §5 es aspiracional. Si eslint custom es caro, agregar al test de smoke pre-merge `grep -E "\.public_id\s*\|\|\s*\w+\.id" src/` con exit-code gate.

### `PublicIdLookupMixin` con `ALLOW_LEGACY_ID_LOOKUP`: ¿fallback o trampa?

**SEVERIDAD: MEDIA.** Anti-pattern: flag-driven branching dentro de helper genérico.
El mixin lee `getattr(settings, 'ALLOW_LEGACY_ID_LOOKUP', False)` (`apps/core/views.py:49`). El draft promete cortar el flag, pero `resolve_public_id` y `PublicIdLookupMixin` retienen el branch en código indefinidamente ("30 días post-cutover" §13). Riesgo real: en 60 días alguien lee el código, ve el fallback, asume que es feature y lo activa para "debug".
**Fix concreto:** Día 6 ya debe agregar `# DEPRECATED: remove after 2026-06-19 — see Issue #18` como comment encima de ambas ramas. Crear ticket en backlog con fecha. Sin esto el cleanup no ocurre.

### Acoplamiento accidental — agregar `Organization.public_id` y `User.public_id`

**SEVERIDAD: MEDIA.** Anti-pattern: shotgun surgery no enumerada.
El draft Fase 4-5 dice "migración + serializer expone `public_id`" pero no enumera puntos de actualización. La realidad: `MeView`, `StaffListView`, `StaffDeactivateView`, `CreateEmployeeSerializer`, `OrganizationLegacyView`, `OrganizationMeView`, plus cualquier embed de `organization` en respuestas (Invoice, MedicalRecord, Appointment). El anexo seguridad sólo cubre 5/7.
**Fix:** Fase 4-5 debe abrir con un grep concreto: `grep -rn "organization\.id\|organization_id" backend/apps/*/serializers.py` y enumerar en la PR description. Sin lista exhaustiva, Fase 6 (flag off) descubrirá el faltante en staging.

### Duplicación de lógica `resolve_public_id` vs `PublicIdLookupMixin.get_object`

**SEVERIDAD: BAJA.** Anti-pattern: shotgun divergence.
Ambos (`apps/core/views.py:40-50` y `:60-80`) tienen lógica idéntica de parse UUID → fallback numérico → 404. Hoy es DRY-violation aceptable porque viven adyacentes. Si en Fase 6 alguien decide endurecer el parse en `resolve_public_id` y olvida `PublicIdLookupMixin.get_object`, divergen silenciosamente.
**Fix:** Día 6 no introduce nuevo helper, pero **debe extraer la lógica de parse a un `_resolve_or_404(queryset, lookup)` privado en el mismo archivo** que ambos consuman. Cambio interno, no API nueva, no ADR. Lo que se elimina es la posibilidad de divergencia.

### Coherencia semántica frontend

**SEVERIDAD: MEDIA.** Anti-pattern: parameter name lying.
`api/medicalRecords.js` y los demás reciben `recordId` que ya es UUID en producción con flag ON pero el nombre dice `id`. Lectores asumen PK. El draft Fase 2 propone renombrar a `recordPublicId` — correcto pero opcional ("se renombra semánticamente o se documenta"). El "o se documenta" es escape hatch.
**Fix:** Fase 2 obligatoria, no opcional, renombrar parámetros en todas las firmas `api/*.js` a `<resource>PublicId`. JSDoc comment `@param {string} petPublicId UUID v4`. Sin esto, en 6 meses devs siguen pasando `pet.id`.

### Naming drift

**SEVERIDAD: MEDIA.** Anti-pattern: tres dialectos no documentados.
JS = `publicId`, JSON = `public_id`, URL = UUID crudo. Hoy no hay README que lo declare. CLAUDE.md menciona `public_id` pero no la convención frontend.
**Fix:** agregar a CLAUDE.md sección "## Convenciones de IDs":
- Backend Python / DB / JSON: `public_id` (snake_case).
- Frontend JS variables/params: `publicId` (camelCase).
- URLs / deep links: UUID v4 raw, sin prefijo.
- React keys: `obj.public_id` preferente; `obj.id` solo si el array no sale del componente.

### Coupling con flag legacy: contar puntos de remoción

**SEVERIDAD: BAJA.** Grep actual: `ALLOW_LEGACY_ID_LOOKUP` aparece en 4 sitios (`settings.py:132`, `core/views.py:26,36,49,69,76`, CLAUDE.md, revision_auditoria.md). Remoción es 1 PR pequeña. No es coupling masivo — el draft está OK aquí.
**Fix:** ninguno bloqueante. Agregar checklist en backlog: "remover ALLOW_LEGACY_ID_LOOKUP: settings.py, core/views.py (×2 ramas), 2 docs".

### Anticipated abstractions

**SEVERIDAD: BAJA.** El draft NO introduce abstracciones nuevas (sano). Resiste la tentación de crear `BasePublicResourceViewSet`, `TenantQueryParamResolver`, etc. Mantener.

## 3. Adiciones al plan

- **§5 frontend**: agregar regla eslint o grep-gate pre-merge contra `\.public_id\s*\|\|\s*\w+\.id`. Lint manual no es enforcement.
- **§9 anti-patterns**: agregar "**Helper prematuro por 3 ocurrencias**: el patrón `resolve_public_id(Model.objects.for_organization(org), value)` se permite inline hasta 6 ocurrencias por app. Promoción a helper exige ADR."
- **§4 estrategia lookup**: agregar nota de extracción privada `_resolve_or_404` compartida entre `PublicIdLookupMixin.get_object` y `resolve_public_id` para evitar divergencia.
- **§7 Fase 4-5**: empezar con grep exhaustivo de todos los embeds de `organization` en serializers + lista enumerada en PR description. No "se actualizan los puntos relevantes".
- **§2 nuevo apartado "Nomenclatura"**: documentar las 3 capas (`public_id` / `publicId` / UUID raw). Llevar a CLAUDE.md.
- **§13 deuda técnica permitida**: agregar fecha de expiración concreta para cada item. "30 días post-cutover" = `2026-06-19`. Sin fecha, no se limpia.
- **§5 Fase 2 frontend**: hacer renombre de parámetros `api/*.js` **obligatorio**, no opcional. Y agregar JSDoc `@param {string} <name>PublicId`.

## 4. Lo que está OK

- §9 anti-patterns explícitos (especialmente prohibir `resolve_anything()`, `SmartIdField`, IntelligentResolver) — el plan resiste over-engineering.
- §10 "lo que no se toca" enumera con razones concretas; evita scope creep.
- §11 rollout con `ALLOW_LEGACY_ID_LOOKUP=False` en staging 48h primero — buena disciplina.
- Anexo DB §3 rechaza índice compuesto `(organization, public_id)` por default y UUID v7 — evita optimización prematura.
- ADR Día 6 obligatorio explícitamente declarado (§14).
- Sub-recursos con child PK justificados con costo/beneficio (§3) en lugar de regla dogmática.

## 5. Riesgos de maintainability post-cutover

- **El branch `if str(lookup).isdigit() and ALLOW_LEGACY_ID_LOOKUP` queda en código indefinido.** Sin fecha de borrado dura, es código muerto que confunde lectores nuevos.
- **`InvoiceItem`/`MRP`/`MRS` keep PK enteros** — decisión correcta hoy, pero si en 12 meses se agrega "compartir factura por link con ítem destacado" alguien va a sentir presión a agregar `public_id`. El plan debe declarar el trigger: "promoción ocurre cuando hay caso de uso standalone documentado, no antes".
- **Naming drift sin lint**: el riesgo no es Día 6 sino día 90. Sin convención escrita en CLAUDE.md y sin ESLint rule, devs nuevos escribirán `pet.id` en URLs nuevas. El próximo Día 6 cuesta el doble.
- **`?pet=<pk>` legacy en bookmarks de usuarios** (§8 R3 LOW) es real pre-beta sin usuarios pero el plan no documenta que esto requiere un blast email cuando haya beta-users.
- **Test gap**: no hay test declarado que verifique "endpoint X con flag OFF retorna 404 si se le pasa PK entero". Sin esto, el rollback del flag depende de smoke manual.

## 6. Runbook propuesto

Al cerrar Día 6 documentar en `docs/runbooks/exposing-new-model.md`:

- **Modelo público nuevo (entidad navegable, enlace compartible)**:
  1. Heredar de `PublicIdMixin` en el modelo.
  2. Migración aditiva `default=uuid.uuid4 + unique=True + db_index=True`.
  3. `<str:pk>` en URLs públicas, nunca `<int:>`.
  4. ViewSet: heredar `PublicIdLookupMixin`, set `lookup_field='public_id'`.
  5. FBV: `obj = resolve_public_id(Model.objects.for_organization(org), pk)`.
  6. Serializer: incluir `public_id` en `fields`. NO quitar `id` pre-beta.
  7. List view anidada bajo `<str:pk>`: declarar `required_permission` por método HTTP en `initial()` (ADR-09).
  8. Query param: `resolve_public_id(...).filter(modelo=instancia)`, nunca `filter(modelo_id=raw)`.
  9. FK body de este modelo desde otros: `PrimaryKeyRelatedField` (no UUID).
- **Sub-recurso interno (hijo siempre anidado)**: PK entero, NO `public_id`. Detail view filtra `pk + parent=parent_obj`.
- **Tabla de nomenclatura**: `public_id` (Python/DB/JSON), `publicId` (JS), UUID raw (URL).
- **Lista de modelos clasificados** públicos vs internos (copiar §3 del draft).
- **Checklist code review**: orden `for_organization() → select_related()` (ADR-10), no `editing.public_id || editing.id` en frontend, `required_permission` explícito en list anidadas.
