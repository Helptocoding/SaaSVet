# Runbook — Exponer un modelo nuevo a la API pública

**Owner:** backend lead
**Trigger:** un modelo interno debe pasar a ser navegable / compartible standalone (deep link, URL bookmark, embed externo).
**Tiempo estimado:** 0.5–1 día por modelo.

**NUNCA exponer un modelo "por estética".** Trigger explícito: caso de uso navegable documentado.

Referencias:
- ADR p18 (`docs/decisions/2026-05-20-p18-ids-en-superficies-externas.md`)
- CLAUDE.md sección "IDs en URLs (ADR p18 — Día 6)"
- `apps/core/models.py::PublicIdMixin`

---

## Pre-flight — decisión de exposición

Antes de tocar código, validar:

1. **Trigger documentado**: hay caso de uso navegable / compartible / bookmarkable. Si no, NO promover.
2. **El modelo NO es child interno** de otro recurso (ej. `InvoiceItem`, `MedicalRecordService`, `StockMovement`, `VitalSigns`). Si es child, el recurso se accede vía parent — promoción NO aplica.
3. **El modelo NO es catálogo RBAC** (`Permission`, `Role`, `UserRole`). No se exponen.

Si los 3 chequeos pasan, proceder.

---

## Los 10 pasos

### 1 — Heredar `PublicIdMixin` en el modelo

```python
# apps/<app>/models.py
from apps.core.models import OrganizationalModel, PublicIdMixin

class MiModelo(PublicIdMixin, OrganizationalModel):
    ...
```

**Orden de herencia importa**: `PublicIdMixin` antes que `OrganizationalModel`. El campo `public_id` queda definido en la subclase.

### 2 — Migración aditiva 3 pasos

Pre-beta single-shot (cero tráfico productivo). Patrón canonical:

```python
# apps/<app>/migrations/00XX_dayN_<modelo>_public_id.py
from uuid import uuid4
from django.db import migrations, models


def _backfill_public_id(apps, schema_editor):
    Model = apps.get_model('<app>', '<MiModelo>')
    for obj in Model.objects.filter(public_id__isnull=True):
        obj.public_id = uuid4()
        obj.save(update_fields=['public_id'])


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('<app>', '<previous_migration>')]
    operations = [
        # Paso 1: nullable + index
        migrations.AddField(
            model_name='mimodelo',
            name='public_id',
            field=models.UUIDField(null=True, editable=False, db_index=True),
        ),
        # Paso 2: backfill
        migrations.RunPython(_backfill_public_id, _noop_reverse),
        # Paso 3: NOT NULL + UNIQUE
        migrations.AlterField(
            model_name='mimodelo',
            name='public_id',
            field=models.UUIDField(
                default=uuid4, editable=False, unique=True, db_index=True,
            ),
        ),
    ]
```

**Post-beta (modelo grande, >10k rows)**: chunked update vía SQL nativo o queryset `.update(public_id=...)` con expresión `gen_random_uuid()` Postgres. NO loop Python row-by-row.

### 3 — Serializer expone `public_id`

```python
# apps/<app>/serializers.py
class MiModeloSerializer(serializers.ModelSerializer):
    class Meta:
        model = MiModelo
        fields = ['id', 'public_id', ...]   # `id` queda pre-beta (D5)
        read_only_fields = ['id', 'public_id', ...]
```

`id` PK + `public_id` UUID ambos en response durante deuda D5 (`POST-BETA-DEBT.md`).

**FK embebido**: si el serializer expone una FK a otro modelo público, agregar también `<fk>_public_id`:

```python
pet_public_id = serializers.UUIDField(source='pet.public_id', read_only=True)
```

### 4 — URLs usan `<str:pk>`

```python
# apps/<app>/urls.py
urlpatterns = [
    path('mimodelo/', MiModeloListCreateView.as_view()),
    path('mimodelo/<str:pk>/', MiModeloDetailView.as_view()),  # NUNCA <int:pk>
]
```

**Prohibido `<int:pk>` en endpoints de modelos públicos.** `test_url_audit.IntPkInPublicUrlsTest` falla CI si se introduce.

### 5 — View hereda `PublicIdLookupMixin`

```python
# apps/<app>/views.py
from apps.core.views import PublicIdLookupMixin, TenantQueryMixin, resolve_public_id

class MiModeloDetailView(PublicIdLookupMixin, TenantQueryMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MiModeloSerializer
    permission_classes = [HybridPermission]
    resource_name = "mimodelo"
    lookup_url_kwarg = 'pk'  # cuando URL usa <str:pk> en lugar de <str:public_id>

    def get_queryset(self):
        return MiModelo.objects.for_organization(self.request.user.organization)
```

**ADR-10**: `for_organization()` SIEMPRE primero en cadena queryset. Antes que `select_related()` / `prefetch_related()`.

**FBVs**: usar `resolve_public_id`:

```python
@api_view(['POST'])
def mi_accion(request, pk):
    obj = resolve_public_id(
        MiModelo.objects.for_organization(request.user.organization), pk
    )
```

### 6 — Query params filtran via `resolve_public_id`

Si el listado acepta `?<modelo>=<value>` filter:

```python
def get_queryset(self):
    org = self.request.user.organization
    qs = MiModelo.objects.for_organization(org).select_related(...)
    pet_lookup = self.request.query_params.get('pet')
    if pet_lookup:
        pet = resolve_public_id(Pet.objects.for_organization(org), pet_lookup)
        qs = qs.filter(pet=pet)
    return qs
```

**Prohibido `qs.filter(<modelo>_id=raw_value)`** — bypasea tenant scope. `test_url_audit.QueryParamPublicModelFilterTest` falla CI.

### 7 — Nested views declaran `required_permission` per HTTP method

Si la nueva view es List/Create bajo URL con `<str:pk>` parent UUID:

```python
class MiModeloChildListCreateView(generics.ListCreateAPIView):
    permission_classes = [HybridPermission]
    resource_name = "mimodelo"

    def initial(self, request, *args, **kwargs):
        if request.method == 'GET':
            self.required_permission = 'mimodelo.retrieve'  # o .list según semántica
        else:
            self.required_permission = 'mimodelo.update'  # o .create
        return super().initial(request, *args, **kwargs)
```

**ADR-09**: sin declaración explícita, `_method_to_action` infiere `retrieve` por `pk` en kwargs y rompe RBAC silenciosamente.

### 8 — Frontend API layer + páginas

`frontend/src/api/<modelo>.js`:

```javascript
/** @param {string} miModeloPublicId UUID v4 — never accept integer PK */
export const updateMiModelo = (miModeloPublicId, data) =>
    api.patch(`mimodelo/${miModeloPublicId}/`, data).then(r => r.data);
```

Páginas consumen `obj.public_id`, nunca `obj.id` para URL/query/deep-link.

**Prohibido frontend**:
- `editing.public_id || editing.id` — dual-lookup spaghetti.
- `navigate("/mimodelo/${obj.id}")` — usar `obj.public_id`.
- `?modelo=${obj.id}` — usar `obj.public_id`.

Smoke gate: `npm run smoke:urls` (G1-G5) debe pasar verde.

### 9 — Tests obligatorios

Crear `backend/apps/<app>/tests/test_<modelo>_lookup.py`:

- GET propio UUID → 200
- GET cross-tenant UUID → 404 (no leak)
- GET PK con `ALLOW_LEGACY_ID_LOOKUP=False` → 404
- GET malformed UUID → 404 (no 500)
- `?<modelo>=<uuid>` query param filtering OK + cross-tenant 404
- Si tiene sub-recursos, `test_subresource_parent_child.py` para cross-parent 404

### 10 — Actualizar inventarios

- [ ] CLAUDE.md sección "IDs en URLs (ADR p18 — Día 6)" — agregar modelo a lista "Modelos con `public_id`".
- [ ] ADR menor opcional (`docs/decisions/<fecha>-<modelo>-publico.md`) si afecta contrato externo o invariante cross-team.
- [ ] Verificar `POST-BETA-DEBT.md` no necesita actualización (D5 cleanup post-beta cubre todos los serializers).
- [ ] Suite tests verde: `apps.core.tests.test_url_audit`, `apps.core.tests.test_day6_invariants`, nuevos `test_<modelo>_lookup.py`.
- [ ] Smoke frontend: `npm --prefix frontend run smoke:urls` → 0 matches.

---

## Anti-patterns prohibidos (recordatorio)

1. **Dual-lookup**: `try uuid except pk` ad-hoc en views — usar `resolve_public_id`.
2. **Helpers genéricos**: `resolve_anything()`, `SmartIdField`, `IdentityService` — YAGNI.
3. **Query param dual-aceptación** PK + UUID — cortar limpio con flag.
4. **`PrimaryKeyRelatedField` con UUID en body** — rompe contrato DRF. FK body sigue PK.
5. **Middleware genérico de IDs** — magia invisible. URL declarada `<str:>` + mixin explícito.
6. **`<int:pk>` en URL de modelo público** — bloqueado por `test_url_audit`.
7. **Backfill row-by-row Python** en modelos >10k rows — chunked SQL.

---

## Rollback

1. **Migración aditiva** es reversible: `python manage.py migrate <app> <N-1>` regresa a pre-publicidad. La columna se borra.
2. **URLs cambiadas** revertibles vía git revert.
3. **Frontend** revertir vía git revert + `npm run smoke:urls` para confirmar.
4. **Flag global** `ALLOW_LEGACY_ID_LOOKUP=True` permite PK lookup en transición — flag flip OFF cuando todo verde.

---

## Checklist final

- [ ] Step 1 — `PublicIdMixin` heredado, orden correcto.
- [ ] Step 2 — Migration 3 pasos creada, reversible verificado.
- [ ] Step 3 — Serializer expone `id` + `public_id` + FK `*_public_id`.
- [ ] Step 4 — URLs `<str:pk>`.
- [ ] Step 5 — View hereda `PublicIdLookupMixin`, `for_organization()` primero.
- [ ] Step 6 — Query params via `resolve_public_id`.
- [ ] Step 7 — Nested views con `required_permission` per HTTP method.
- [ ] Step 8 — Frontend `api/*.js` + páginas migradas, `public_id` en URLs/queries/navs.
- [ ] Step 9 — Tests `test_<modelo>_lookup.py` verdes.
- [ ] Step 10 — CLAUDE.md actualizado, ADR opcional, smoke gates verdes.

Sin uno de estos cerrado, **el modelo NO está completo en superficie pública.**
