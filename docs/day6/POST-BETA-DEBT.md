# Día 6 — Deuda técnica diferida a post-beta

> **Recuperado el 15-11-2026.** Este archivo se borró en `84d4e48` (12-06-2026, limpieza de `docs/day6/`), pero la deuda que registra seguía abierta y lo enlazaban el [índice de deuda](../deuda/README.md), [ADR p19](../decisions/2026-05-22-p19-platform-org-provisioning.md), [platform.md](../modules/platform.md) y el runbook [exposing-new-model](../runbooks/exposing-new-model.md). Se restaura sin cambios desde `84d4e48^`. Estado de cada ticket, comprobado en el código el 15-11:
>
> | Ticket | Estado 15-11 | Evidencia |
> |---|---|---|
> | POST-BETA-001 | Abierto | `MeView` (`apps/users/views.py`) sigue emitiendo `organization` (PK) junto a `organization_public_id`. |
> | POST-BETA-002 | Abierto | Los serializers con `public_id` siguen exponiendo también `id` (por ejemplo `PetSerializer`). |
> | POST-BETA-003 | Abierto | `PetSerializer.owner_id` sigue en `apps/patients/serializers.py`. |
> | POST-BETA-004 | Abierto | `AppointmentSerializer.medical_record_ids` sigue junto a `medical_record_public_ids`. |
> | POST-BETA-005 | Abierto | `PlatformOrgCreateView` no acepta clave de idempotencia; en `apps/platform` solo el borrado físico (orden 2) la usa. |
> | Flag `ALLOW_LEGACY_ID_LOOKUP` | Abierto | `_resolve_or_404` (`apps/core/views.py`) conserva la rama del flag. |
>
> Los IDs «D2» y «D5» de este archivo no son los D2 y D5 de la [Fase 2 de deuda](../deuda/fase2-prioridad-alta.md).

**Estado:** documentada, NO bloqueante para beta.
**Owner del cleanup:** backend lead.
**Trigger:** primer sprint post-beta launch.

Estos ítems se identificaron durante la auditoría post-implementación de Día 6
(ADR p18). Se aceptan temporalmente porque:

1. Romper contratos pre-beta para cleanup estético tiene mayor blast radius que
   beneficio operacional.
2. El backlog post-beta tendrá ventana de breaking-change controlado.
3. Ningún ítem genera vulnerabilidad de seguridad activa — son cleanups de
   consistencia/maintainability.

---

## D2 — `MeView` response: dual representation `organization` (PK) + `organization_public_id` (UUID)

**Archivo:** `backend/apps/users/views.py:MeView.get`.

**Shape actual del response:**
```json
{
  "id": 1,
  "organization": 42,                                  // PK entero
  "organization_public_id": "uuid-v4-string",          // UUID
  "organization_name": "Clínica X",
  "organization_timezone": "America/Mexico_City",
  ...
}
```

**Por qué se introdujo:** Día 6 Fase 4 agregó `organization_public_id` para que
frontend pueda construir deep links / referencias externas con UUID. El campo
legacy `organization` (PK) se mantuvo para retrocompatibilidad del contrato pre-beta.

**Riesgo dejado:**
- Naming drift: convención REST típica usa `<resource>_id` para FK PK, `<resource>` para objeto embebido. Aquí `organization` es PK pero el nombre sugiere objeto.
- Frontend nuevo puede consumir `organization` (PK) sin darse cuenta — y eventualmente romper cuando se elimine.

**Plan de cleanup post-beta:**
1. Sprint S1 post-launch: agregar deprecation log `MeView.organization` (warn-only) cuando algún caller observado en métricas Sentry siga leyendo el campo.
2. Sprint S2 post-launch: renombrar response shape a:
   ```json
   {
     "organization_id": 42,            // PK (alineado a convención REST)
     "organization_public_id": "uuid"  // UUID
   }
   ```
   Coordinar con frontend para migrar consumers ANTES del swap.
3. Sprint S3 post-launch: eliminar `organization_id` PK del response (solo UUID).
4. Documentar en `CHANGELOG.md` como breaking change.

**Ticket sugerido:** `POST-BETA-001 — MeView response shape rename`.

**Test gate antes de cleanup:** `test_me_public_id.py::test_me_response_retains_organization_pk_for_backcompat` debe seguir pasando hasta sprint S3. Cuando se ejecute S3, eliminar el test junto con el campo.

---

## D5 — Serializers exponen `id` (PK) + `public_id` (UUID) ambos en response

**Archivos afectados (lista exhaustiva):**

| Serializer | Archivo | Campos duplicados |
|---|---|---|
| `PetSerializer` | `apps/patients/serializers.py` | `id`, `public_id` |
| `OwnerSerializer` | `apps/patients/serializers.py` | `id`, `public_id` |
| `AppointmentSerializer` | `apps/appointments/serializers.py` | `id`, `public_id` |
| `MedicalRecordSerializer` | `apps/medical_records/serializers.py` | `id`, `public_id` + plus `pet`, `pet_public_id`, etc. |
| `InvoiceSerializer` | `apps/billing/serializers.py` | `id`, `public_id` + embeds |
| `PrescriptionSerializer` | `apps/prescriptions/serializers.py` | `id`, `public_id` + embeds |
| `VaccineRecordSerializer` | `apps/medical_records/serializers.py` | `id`, `public_id` (Fase 5) |
| `UserSerializer` | `apps/users/serializers.py` | `id`, `public_id` (Fase 5) |
| `OrganizationSerializer` | `apps/organizations/serializers.py` | `id`, `public_id` (Fase 4) |
| `ProductSerializer`, `PresentationSerializer`, `ServiceSerializer` | varios | `id`, `public_id` |

**Por qué se introdujo:** ADR p18 §13 aceptó explícitamente la duplicación
pre-beta para evitar romper consumers existentes. Frontend Día 6 migró a usar
`public_id` en URLs/navegación pero el campo `id` queda por retrocompat.

**Riesgo dejado:**
- Response payload más grande (overhead red, marginal).
- Devs nuevos pueden consumir `id` (PK) sin darse cuenta — silent breakage cuando se elimine.
- Imposible saber si un consumer real usa `id` para algo crítico sin métricas de uso.

**Plan de cleanup post-beta:**

### Fase 1 — Observability (sprint S1 post-launch)
Agregar middleware o decorador que detecte cuando un response JSON serializado contiene `id` Y `public_id` ambos. Loguear cuántos clients usan `id` por endpoint vía monitoreo Sentry/Railway. Sin esto el cleanup es a ciegas.

### Fase 2 — Frontend audit (sprint S2 post-launch)
Grep gate más estricto en frontend:

```bash
# Detecta cualquier consumo de .id en componentes que renderizan datos de API
grep -rnE "\.id\b" frontend/src/{pages,components}/ | grep -vE "\.(public_id|.*_id)\b"
```

Para cada match: validar si el `id` es local (React key, cache lookup) o cross-HTTP. Localizar y migrar los cross-HTTP a `public_id`.

### Fase 3 — Backend deprecation (sprint S3 post-launch)
Agregar marker en cada serializer:

```python
class PetSerializer(serializers.ModelSerializer):
    # DEPRECATED: remove `id` field after 2026-12-01 (POST-BETA-002).
    # Frontend debe consumir public_id (UUID) en todo response shape.
    class Meta:
        fields = ['id', 'public_id', ...]  # `id` queda hasta gate Sentry: 0 hits/7días
```

### Fase 4 — Cleanup (sprint S4 post-launch)
Eliminar `id` de `fields` en cada serializer. Mantener `pet_public_id`, `owner_public_id`, etc. como única forma de referenciar FK embebido externamente. PK interno sigue en DB (joins, ORM) pero NO se serializa.

**Ticket sugerido:** `POST-BETA-002 — Serializers cleanup: eliminar id de response shape`.

**Riesgos del cleanup:**
- Cliente desconocido (no controlado por nosotros) que dependa de `id` rompe sin warning.
- Frontend con caché localStorage que serializó objeto con `id` → al deserializar y enviar al backend rompe.

**Mitigación:** observability fase 1 obligatorio. Cero hits a `id` por 14 días antes de eliminar.

---

## Ítems relacionados (no bloqueantes, post-beta tracking)

### `pets.serializers.PetSerializer.owner_id` legacy

`PetSerializer` expone `owner_id` (PK) además de `owner` (nested OwnerSerializer con `public_id`). Cleanup similar a D5. Ticket `POST-BETA-003`.

### `AppointmentSerializer.medical_record_ids` (plural PK array)

Backend ya emite `medical_record_public_ids` (UUID array, Día 6 B2). Eliminar la versión PK post-beta. Ticket `POST-BETA-004`.

### Flag `ALLOW_LEGACY_ID_LOOKUP` y branch deprecated en `_resolve_or_404`

**Vencimiento duro:** 2026-06-19.

`apps/core/views.py:_resolve_or_404` retiene branch `if str(lookup).isdigit() and ALLOW_LEGACY_ID_LOOKUP`. Documentado en ADR p18.

**Ticket:** `POST-CUTOVER-001 — Eliminar branch legacy de _resolve_or_404 + ALLOW_LEGACY_ID_LOOKUP setting`.

**Pasos:**
1. Verificar flag flip prod completado y estable 30 días.
2. Eliminar branch en `_resolve_or_404`.
3. Eliminar `ALLOW_LEGACY_ID_LOOKUP` de `config/settings.py`.
4. Eliminar referencias en CLAUDE.md, ADR p18, docs/day6/.
5. Actualizar `test_day6_invariants.py` para eliminar tests `@override_settings(ALLOW_LEGACY_ID_LOOKUP=True)`.

---

## POST-BETA-005 — Idempotency key en `POST /api/platform/organizations/`

**Archivo:** `backend/apps/platform/views.py:PlatformOrgCreateView`.

**Estado actual:** El endpoint NO acepta header `X-Idempotency-Key`. Cada
POST es tratado como request nuevo. Las validaciones pre-DB de duplicados
(`username`, `email`, `org name` case-insensitive) mitigan el caso común
de retry post-success, pero no son una solución completa.

**Por qué se difiere:**
- Validaciones pre-DB cubren ~95% de duplicate-create scenarios (retry
  después de timeout, doble click en UI, refresh accidental).
- Operación con throttle bajo (`20/hour`) — blast radius limitado.
- Beta-launch tiene volumen bajo de provisioning — el riesgo de duplicados
  generados por retry es estadísticamente bajo durante los primeros sprints.
- Implementación completa requiere: storage de `(idempotency_key, response)`
  con TTL, decisión sobre scope (per-actor vs global), invalidation policy.
  Diseño merece su propio ADR.

**Por qué será importante post-beta:**
- Retries de timeouts (nginx/Cloudflare default ~60s puede cortar antes
  del completion de provisioning + signal cascade).
- Mobile clients con conexión inestable que reintentan automáticamente.
- Webhook-driven provisioning desde billing SaaS (Stripe/etc.) que reintenta
  hasta recibir 2xx.
- Customer support tooling con doble-click humano.

**Diseño tentativo post-beta:**
- Header opcional `X-Idempotency-Key: <uuid v4>` (cliente provee).
- Storage: tabla `platform_idempotency_records(key, actor_id, response_body,
  status_code, created_at)` con TTL 24h.
- En POST con key presente:
  1. SELECT FOR UPDATE en `(key, actor_id)` — si existe y completed, devolver
     response_body cached con status original.
  2. Si existe y en-progress (created_at < 30s ago), retornar 409 Conflict
     con `Retry-After`.
  3. Si no existe, INSERT in-progress + proceder con provisioning normal +
     UPDATE con response final.
- Mantener provisión actual sin key (idempotency es opt-in).

**Ticket:** `POST-BETA-005 — Idempotency-Key support para platform provisioning`.

**Sprint estimado:** S2-S4 post-launch (depende de volumen de retries
observados en Sentry/logs de prod).

**Pasos cuando se ejecute:**
1. ADR formal: scope (per-actor vs global), TTL, conflict semantics.
2. Migration: `platform_idempotency_records` con index UNIQUE en
   `(key, actor_id)`.
3. Middleware o decorator que envuelve la view.
4. Tests: replay request con key reutilizada devuelve mismo response
   sin side-effects nuevos.
5. Documentar header en OpenAPI / runbook.
6. Métricas: cantidad de hits cached vs misses (visibilidad del valor).

---

## Resumen — checklist post-beta

- [ ] `POST-CUTOVER-001` (2026-06-19): eliminar `ALLOW_LEGACY_ID_LOOKUP` branch.
- [ ] `POST-BETA-001` (sprint S1-S3): rename `MeView.organization` → `organization_id` o eliminar (D2).
- [ ] `POST-BETA-002` (sprint S1-S4): eliminar `id` de serializers de response (D5).
- [ ] `POST-BETA-003`: cleanup `PetSerializer.owner_id` PK redundant.
- [ ] `POST-BETA-004`: cleanup `AppointmentSerializer.medical_record_ids` PK array.
- [ ] `POST-BETA-005` (sprint S2-S4): `X-Idempotency-Key` en `POST /api/platform/organizations/`.

Cada ticket requiere:
- Observability fase obligatoria antes del cleanup.
- Test gate Sentry cero hits 14 días.
- Coordinación con frontend antes del swap.
- ADR menor opcional si el cleanup cambia contrato externo más allá de remove.
