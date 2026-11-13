# E01 — M03: VitalSigns como única fuente del peso

Primero lee y aplica `docs/remediaciones/orden-7/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

`MedicalRecord.weight` deja de leerse y escribirse. Una migración de datos copia su valor a `VitalSigns` en las consultas que no tienen ningún signo vital con peso. El API de la consulta sigue publicando `weight`, ahora de solo lectura y derivado de `VitalSigns`, así que el frontend no cambia y el historial de la mascota empieza a mostrar el peso real.

La columna **no se borra**: su `RemoveField` es una entrega posterior (fase contract), por decisión del usuario.

## Precondición

`git log --oneline -1` muestra `chore(order7): record isolated baseline (order 7)`. En `MATRIZ.md` la fila E00 tiene resultado. Si no, `BLOQUEADA`.

## Archivos permitidos

- `backend/apps/core/management/commands/seed_demo_clinic.py`
- `backend/apps/medical_records/migrations/0030_backfill_vitals_weight_from_record.py`
- `backend/apps/medical_records/models.py`
- `backend/apps/medical_records/serializers.py`
- `backend/apps/medical_records/tests/test_vitals.py`
- `backend/apps/medical_records/tests/test_weight_single_source.py`
- `backend/apps/medical_records/views.py`
- `docs/modules/medical_records.md`
- `docs/remediaciones/orden-7/MATRIZ.md` y `docs/remediaciones/orden-7/EVIDENCIA.md`

## Excepción a la regla de pruebas

En `apps/medical_records/tests/test_vitals.py` se sustituyen dos pruebas que fijaban el fallback a `MedicalRecord.weight`, que es justo lo que M03 retira. Las nuevas fijan lo contrario. No se borra ni debilita ninguna otra.

## Contexto

- El frontend nunca escribe `MedicalRecord.weight`: el peso va a `POST /medical-records/<id>/vitals/`. Solo lo escribía `seed_demo_clinic`, que ya crea un `VitalSigns` con el mismo valor.
- `get_weight` recorre `obj.vital_signs.all()` porque las vistas de lista ya hacen `prefetch_related('vital_signs')`; un `order_by` haría una consulta por fila. Devuelve texto (`"4.20"`) para conservar el formato del antiguo `DecimalField`.
- La migración usa `_base_manager` y `values_list`: en una migración solo existen los modelos históricos.
- `recorded_by` queda vacío en las filas copiadas: nadie registró ese signo vital como tal.

## Cambios

Aplícalos en este orden.

### Cambio 1 — `backend/apps/medical_records/migrations/0030_backfill_vitals_weight_from_record.py`

Archivo nuevo. Créalo con este contenido exacto:

```python
"""M03 (orden 7): VitalSigns pasa a ser la única fuente del peso.

Copia `MedicalRecord.weight` a un `VitalSigns` solo en las consultas que tienen
peso legacy y ningún signo vital con peso. `recorded_at` toma el alta de la
consulta y `recorded_by` queda vacío: nadie registró ese signo vital como tal, y
atribuírselo a alguien inventaría autoría.

Idempotente: una segunda pasada ya no encuentra consultas pendientes. La reversa
no hace nada, porque una fila copiada no se distingue de una capturada.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    MedicalRecord = apps.get_model('medical_records', 'MedicalRecord')
    VitalSigns = apps.get_model('medical_records', 'VitalSigns')
    pending = (
        MedicalRecord._base_manager
        .filter(weight__isnull=False)
        .exclude(vital_signs__weight__isnull=False)
        .order_by('pk')
        .values_list('pk', 'organization_id', 'weight', 'created_at')
    )
    VitalSigns._base_manager.bulk_create(
        [
            VitalSigns(
                organization_id=organization_id,
                medical_record_id=record_id,
                weight=weight,
                recorded_at=created_at,
                recorded_by=None,
            )
            for record_id, organization_id, weight, created_at in pending.iterator(chunk_size=500)
        ],
        batch_size=500,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('medical_records', '0029_detachable_closed_patient'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
```

### Cambio 2 — `backend/apps/medical_records/tests/test_weight_single_source.py`

Archivo nuevo. Créalo con este contenido exacto:

```python
"""M03 (orden 7): el peso sale solo de VitalSigns.

`MedicalRecord.weight` queda como columna sin lectores ni escritores hasta su
RemoveField. Estas pruebas fijan que ningún camino vuelve a leerla o escribirla.
"""
from datetime import timedelta
from importlib import import_module

from django.apps import apps as django_apps
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.medical_records.models import (
    MedicalRecord, VitalSigns, _get_last_weight, get_current_weight,
)
from apps.medical_records.serializers import MedicalRecordSerializer
from apps.medical_records.tests.test_vitals import _make_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

BACKFILL = import_module(
    'apps.medical_records.migrations.0030_backfill_vitals_weight_from_record').backfill


class WeightSingleSourceTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Org Peso M03", timezone="UTC")
        cls.vet = _make_user("vet_peso_m03", cls.org, "VET")
        owner = Owner.objects.create(name="Owner", phone="5512345601", organization=cls.org)
        cls.pet = Pet.objects.create(name="Bruno", species="dog", owner=owner, organization=cls.org)

    def _record(self, **kwargs):
        return MedicalRecord.objects.create(
            pet=self.pet, veterinarian=self.vet, organization=self.org, **kwargs)

    def _legacy_weight(self, record, value):
        MedicalRecord.all_objects.filter(pk=record.pk).update(weight=value)

    def _vital(self, record, weight, minutes_ago=0):
        return VitalSigns.objects.create(
            medical_record=record, organization=self.org, weight=weight,
            recorded_at=timezone.now() - timedelta(minutes=minutes_ago))

    def test_serializer_weight_is_read_only(self):
        self.assertTrue(MedicalRecordSerializer().fields['weight'].read_only)
        self.assertNotIn('force_weight', MedicalRecordSerializer().fields)

    def test_patch_weight_does_not_write_the_legacy_column(self):
        record = self._record()
        self.client.force_authenticate(self.vet)
        r = self.client.patch(
            f"/api/medical-records/{record.public_id}/", {"weight": "9.99"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        record.refresh_from_db()
        self.assertIsNone(record.weight)
        self.assertIsNone(r.data["weight"])

    def test_api_weight_comes_from_latest_vital_with_weight(self):
        record = self._record()
        self._legacy_weight(record, "7.00")
        self._vital(record, "4.20", minutes_ago=30)
        self._vital(record, None, minutes_ago=5)
        self.client.force_authenticate(self.vet)
        r = self.client.get(f"/api/medical-records/{record.public_id}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.assertEqual(r.data["weight"], "4.20")
        listed = self.client.get(f"/api/medical-records/?pet={self.pet.public_id}")
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.content)
        rows = listed.data["results"] if isinstance(listed.data, dict) else listed.data
        self.assertEqual([row["weight"] for row in rows], ["4.20"])

    def test_helpers_ignore_the_legacy_column(self):
        record = self._record()
        self._legacy_weight(record, "7.00")
        record.refresh_from_db()
        self.assertIsNone(_get_last_weight(self.pet))
        self.assertIsNone(get_current_weight(record))
        self._vital(record, "5.10", minutes_ago=10)
        self._vital(record, None)
        self.assertEqual(str(_get_last_weight(self.pet)), "5.10")
        self.assertEqual(str(get_current_weight(record)), "5.10")

    def test_backfill_copies_only_records_without_vital_weight(self):
        legacy_only = self._record()
        self._legacy_weight(legacy_only, "6.40")
        already = self._record()
        self._legacy_weight(already, "9.00")
        self._vital(already, "8.80")
        without = self._record()

        BACKFILL(django_apps, None)
        BACKFILL(django_apps, None)

        copied = VitalSigns.objects.get(medical_record=legacy_only)
        self.assertEqual(str(copied.weight), "6.40")
        self.assertIsNone(copied.recorded_by_id)
        self.assertEqual(copied.recorded_at, legacy_only.created_at)
        self.assertEqual(VitalSigns.objects.filter(medical_record=already).count(), 1)
        self.assertFalse(VitalSigns.objects.filter(medical_record=without).exists())
```

### Cambio 3 — `backend/apps/medical_records/models.py`

Texto actual:

```python
    notes = models.TextField(max_length=5000, blank=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
```

Texto nuevo:

```python
    notes = models.TextField(max_length=5000, blank=True)
    # DEPRECADO (orden 7, M03): VitalSigns es la única fuente del peso. Nadie lee ni
    # escribe esta columna; la migración 0030 copió sus valores a VitalSigns. Se
    # borra con un RemoveField en una entrega posterior (fase contract).
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
```

### Cambio 4 — `backend/apps/medical_records/models.py`

Texto actual:

```python
    """
    Historial global del paciente: último peso entre VitalSigns y MedicalRecord.
    Prioriza VitalSigns (más granular). Ordenado por recorded_at (momento clínico).
```

Texto nuevo:

```python
    """
    Historial global del paciente: último peso registrado en VitalSigns, la única
    fuente desde el orden 7 (M03). Ordenado por recorded_at (momento clínico).
```

### Cambio 5 — `backend/apps/medical_records/models.py`

Texto actual:

```python
    if last_vital:
        return last_vital.weight
    last_mr = (
        MedicalRecord.objects
        .for_organization(org)
        .filter(pet=pet, weight__isnull=False)
        .order_by('-created_at')
        .first()
    )
    return last_mr.weight if last_mr else None
```

Texto nuevo:

```python
    return last_vital.weight if last_vital else None
```

### Cambio 6 — `backend/apps/medical_records/models.py`

Texto actual:

```python
    Diferente a _get_last_weight, que busca en toda la historia del paciente.
    """
    last_vital = record.vital_signs.order_by('-recorded_at', '-created_at').first()
    if last_vital and last_vital.weight is not None:
        return last_vital.weight
    return record.weight
```

Texto nuevo:

```python
    Diferente a _get_last_weight, que busca en toda la historia del paciente.
    Último VitalSigns de la consulta con peso; nunca MedicalRecord.weight (M03).
    """
    last_vital = (
        record.vital_signs
        .filter(weight__isnull=False)
        .order_by('-recorded_at', '-created_at')
        .first()
    )
    return last_vital.weight if last_vital else None
```

### Cambio 7 — `backend/apps/medical_records/serializers.py`

Borra este texto y no pongas nada en su lugar:

```python
from django.core.validators import MinValueValidator, MaxValueValidator
```

### Cambio 8 — `backend/apps/medical_records/serializers.py`

Texto actual:

```python
    Detecta cambio brusco de peso (>150%) buscando el último peso en VitalSigns
    y MedicalRecord via _get_last_weight. Compartida por ambos serializers.
```

Texto nuevo:

```python
    Detecta cambio brusco de peso (>150%) contra el último peso en VitalSigns
    (_get_last_weight). La usa VitalSignsSerializer, único escritor del peso (M03).
```

### Cambio 9 — `backend/apps/medical_records/serializers.py`

Texto actual:

```python
    force_weight = serializers.BooleanField(write_only=True, required=False, default=False)

    # Scratchpad de UI (borrador de secciones en progreso). Writable pero NO es
```

Texto nuevo:

```python
    # Scratchpad de UI (borrador de secciones en progreso). Writable pero NO es
```

### Cambio 10 — `backend/apps/medical_records/serializers.py`

Texto actual:

```python
    weight = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        allow_null=True,
        validators=[
            MinValueValidator(Decimal('0.01'), message='El peso debe ser mayor a 0.'),
            # límite funcional (dominio clínico); el técnico de DB es 999.99 (max_digits=5)
            MaxValueValidator(Decimal('200.00'), message='El peso no puede superar 200 kg.'),
        ],
    )
```

Texto nuevo:

```python
    # M03 (orden 7): solo lectura y derivado de VitalSigns. El peso se escribe con
    # POST /medical-records/<id>/vitals/; un `weight` en el PATCH se ignora.
    weight = serializers.SerializerMethodField()
```

### Cambio 11 — `backend/apps/medical_records/serializers.py`

Texto actual:

```python
            'diagnosis', 'treatment', 'notes', 'weight', 'force_weight', 'created_at', 'updated_at',
```

Texto nuevo:

```python
            'diagnosis', 'treatment', 'notes', 'weight', 'created_at', 'updated_at',
```

### Cambio 12 — `backend/apps/medical_records/serializers.py`

Texto actual:

```python
        data = super().validate(data)
        weight = data.get('weight')
        force_weight = data.pop('force_weight', False)
```

Texto nuevo:

```python
        data = super().validate(data)
```

### Cambio 13 — `backend/apps/medical_records/serializers.py`

Texto actual:

```python
        # no al crear. Esto permite pre-crear registros desde el flujo "Atender ahora"
        # y llenarlos progresivamente en el stepper.

        # Validación de cambio brusco de peso (solo en actualizaciones con peso informado)
        if weight and self.instance:
            try:
                _validate_weight_change(self.instance.pet, weight, force=force_weight)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({'weight': exc.detail})
        return data
```

Texto nuevo:

```python
        # no al crear. Esto permite pre-crear registros desde el flujo "Atender ahora"
        # y llenarlos progresivamente en el stepper.
        return data
```

### Cambio 14 — `backend/apps/medical_records/serializers.py`

Texto actual:

```python
    def get_latest_vitals(self, obj):
```

Texto nuevo:

```python
    def get_weight(self, obj):
        # Recorre la relación prefetchada (orden del modelo: -recorded_at,
        # -created_at) para no sumar una consulta por fila en los listados.
        weight = next(
            (vital.weight for vital in obj.vital_signs.all() if vital.weight is not None),
            None,
        )
        return None if weight is None else str(weight)

    def get_latest_vitals(self, obj):
```

### Cambio 15 — `backend/apps/medical_records/views.py`

Texto actual:

```python
            vital_pairs.append(("Frec. respiratoria", f"{last_vital.respiratory_rate} rpm"))
    elif record.weight is not None:
        vital_pairs.append(("Peso", f"{record.weight} kg"))
```

Texto nuevo:

```python
            vital_pairs.append(("Frec. respiratoria", f"{last_vital.respiratory_rate} rpm"))
```

### Cambio 16 — `backend/apps/core/management/commands/seed_demo_clinic.py`

Texto actual:

```python
            # Datos clínicos
            mr.weight = weight
            mr.diagnosis = "" if no_diagnosis else tmpl["diagnosis"]
```

Texto nuevo:

```python
            # Datos clínicos (el peso vive solo en VitalSigns, M03)
            mr.diagnosis = "" if no_diagnosis else tmpl["diagnosis"]
```

### Cambio 17 — `backend/apps/medical_records/tests/test_vitals.py`

Texto actual:

```python
    def test_summary_no_vitals_falls_back_to_record_weight(self):
        mr = self._make_record()
        mr.weight = "7.20"
        mr.save(update_fields=["weight"])
        self.client.force_authenticate(self.vet_a)
        r = self.client.get(self._summary_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(r.data["last_vitals"]["has_vitals"])
        self.assertEqual(str(r.data["last_vitals"]["weight"]), "7.20")

    def test_summary_vital_weight_null_falls_back_to_record_weight(self):
        mr = self._make_record()
        mr.weight = "8.00"
        mr.save(update_fields=["weight"])
        VitalSigns.objects.create(
            medical_record=mr, organization=self.org_a,
            weight=None, temperature="38.0",
        )
        self.client.force_authenticate(self.vet_a)
        r = self.client.get(self._summary_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(str(r.data["last_vitals"]["weight"]), "8.00")
```

Texto nuevo:

```python
    def test_summary_without_vitals_ignores_legacy_record_weight(self):
        # M03 (orden 7): MedicalRecord.weight ya no es fuente del peso.
        mr = self._make_record()
        mr.weight = "7.20"
        mr.save(update_fields=["weight"])
        self.client.force_authenticate(self.vet_a)
        r = self.client.get(self._summary_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertFalse(r.data["last_vitals"]["has_vitals"])
        self.assertIsNone(r.data["last_vitals"]["weight"])

    def test_summary_vital_weight_null_uses_previous_vital_weight(self):
        # M03 (orden 7): si el último vital no trae peso, se usa el vital anterior
        # que sí lo trae, nunca MedicalRecord.weight.
        mr = self._make_record()
        mr.weight = "8.00"
        mr.save(update_fields=["weight"])
        VitalSigns.objects.create(
            medical_record=mr, organization=self.org_a,
            weight="6.00", recorded_at=timezone.now().replace(year=2025, month=1, day=1),
        )
        VitalSigns.objects.create(
            medical_record=mr, organization=self.org_a,
            weight=None, temperature="38.0", recorded_at=timezone.now(),
        )
        self.client.force_authenticate(self.vet_a)
        r = self.client.get(self._summary_url(mr.public_id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(str(r.data["last_vitals"]["weight"]), "6.00")
```

### Cambio 18 — `docs/modules/medical_records.md`

Texto actual:

````markdown
- peso (campo heredado; historial detallado en `VitalSigns`)
````

Texto nuevo:

````markdown
- peso: lectura derivada del último `VitalSigns` con peso (la columna `weight` está deprecada, orden 7 M03)
````

### Cambio 19 — `docs/modules/medical_records.md`

Texto actual:

````markdown
El campo `weight` de `MedicalRecord` se mantiene por compatibilidad. Los helpers centrales priorizan `VitalSigns`:
- `_get_last_weight(pet)`: busca el ultimo peso del paciente en `VitalSigns` primero, luego en `MedicalRecord`. Usado para detectar cambios bruscos de peso.
- `get_current_weight(record)`: peso a mostrar en el panel lateral de una consulta. Usa el ultimo vital con `weight != None`, sino cae al campo del registro.
````

Texto nuevo:

````markdown
Desde el orden 7 (M03), `VitalSigns` es la **única** fuente del peso. La columna `MedicalRecord.weight` queda deprecada, sin lectores ni escritores: la migración `medical_records.0030` copió sus valores a `VitalSigns` (con `recorded_by` vacío y `recorded_at` igual al alta de la consulta) y su `RemoveField` llega en una entrega posterior.
- `_get_last_weight(pet)`: último peso del paciente en `VitalSigns`. Usado para detectar cambios bruscos de peso.
- `get_current_weight(record)`: último `VitalSigns` de la consulta con peso, o `null`.
- `MedicalRecordSerializer.weight`: solo lectura; el mismo valor, calculado sobre los vitales prefetchados. Un `weight` en el PATCH de la consulta se ignora.
````

### Cambio 20 — `docs/modules/medical_records.md`

Texto actual:

````markdown
- `last_vitals.weight`: usa `get_current_weight(record)` — prioriza `VitalSigns.weight`, sino cae a `MedicalRecord.weight`
````

Texto nuevo:

````markdown
- `last_vitals.weight`: usa `get_current_weight(record)` — último `VitalSigns` con peso, o `null` (sin fallback a `MedicalRecord.weight` desde el orden 7)
````

### Cambio 21 — `docs/modules/medical_records.md`

Texto actual:

````markdown
El campo `weight` tiene las siguientes validaciones en el serializer:
````

Texto nuevo:

````markdown
El peso se valida al registrar `VitalSigns` (`VitalSignsSerializer`), su único escritor desde el orden 7:
````

### Cambio 22 — `docs/modules/medical_records.md`

Texto actual:

````markdown
- Cambio brusco: si el peso nuevo difiere mas del 150% respecto al ultimo peso registrado para esa mascota, el sistema retorna error. El ultimo peso se busca con `_get_last_weight(pet)`, que prioriza `VitalSigns` sobre `MedicalRecord`.
````

Texto nuevo:

````markdown
- Cambio brusco: si el peso nuevo difiere mas del 150% respecto al ultimo peso registrado para esa mascota, el sistema retorna error. El ultimo peso se busca con `_get_last_weight(pet)`, solo en `VitalSigns`.
````

### Cambio 23 — `docs/modules/medical_records.md`

Texto actual:

````markdown
- Se puede forzar enviando `force_weight: true` en el body (campo declarado explicitamente en el serializer — aparece en el schema OpenAPI)
- La validacion de cambio brusco aplica tanto en actualizaciones de `MedicalRecord` como al registrar nuevos `VitalSigns`
- La funcion `_validate_weight_change(pet, new_weight, force)` es compartida entre `MedicalRecordSerializer` y `VitalSignsSerializer`
````

Texto nuevo:

````markdown
- Se puede forzar enviando `force_weight: true` en el body de `POST /medical-records/<id>/vitals/`
- `MedicalRecordSerializer` ya no acepta `weight` ni `force_weight` (M03); `_validate_weight_change(pet, new_weight, force)` solo la usa `VitalSignsSerializer`
````

### Cambio 24 — `docs/modules/medical_records.md`

Texto actual:

````markdown
**Doble fuente de peso**:
- `MedicalRecord.weight` — campo legacy, se mantiene por compatibilidad con datos históricos
- `VitalSigns.weight` — fuente de verdad para signos vitales
- Solo se envía `weight` a `createVitals()`, nunca a `updateMedicalRecord()`

**Edición de consulta existente**: al editar, `ConsultationForm` precarga los vitales
desde `initialRecord.latest_vitals`, con fallback a `initialRecord.weight` si no hay
vitales registrados.
````

Texto nuevo:

````markdown
**Fuente única de peso** (orden 7, M03):
- `VitalSigns.weight` — única fuente; se escribe con `createVitals()`
- `MedicalRecord.weight` — columna deprecada, sin lectores ni escritores hasta su `RemoveField`
- el `weight` que devuelve la API de la consulta es de solo lectura y sale de `VitalSigns`

**Edición de consulta existente**: al editar, `ConsultationForm` precarga los vitales
desde `initialRecord.latest_vitals`, con fallback a `initialRecord.weight`, que ya es el
mismo peso derivado de `VitalSigns`.
````


## Verificación

Desde `backend/`:

```bash
R="rtk proxy python scripts/orden7_isolated.py"
for f in apps/medical_records/models.py apps/medical_records/serializers.py apps/medical_records/views.py \
  apps/core/management/commands/seed_demo_clinic.py \
  apps/medical_records/migrations/0030_backfill_vitals_weight_from_record.py \
  apps/medical_records/tests/test_weight_single_source.py apps/medical_records/tests/test_vitals.py; do
  python -m py_compile $f || echo "FAIL $f"; done; echo compilado
grep -n "MinValueValidator\|MaxValueValidator\|force_weight" apps/medical_records/serializers.py
$R makemigrations --check --dry-run 2>&1 | tail -2
$R migrate --noinput 2>&1 | tail -3
$R test apps.medical_records.tests.test_weight_single_source apps.medical_records.tests.test_vitals \
  apps.medical_records.tests.test_pdf apps.medical_records.tests.test_close \
  apps.core.tests.test_hybrid_permission_nested --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -30
```

Esperado:

- `compilado` sin ningún `FAIL`.
- El `grep` no muestra `MinValueValidator` ni `MaxValueValidator`, y todas sus líneas con `force_weight` están antes de `class MedicalRecordSerializer` (en `_validate_weight_change` y `VitalSignsSerializer`).
- `No changes detected`.
- `migrate` aplica `medical_records.0030_backfill_vitals_weight_from_record`.
- **`Ran 79 tests`** y `OK`.

## Cierre

- `MATRIZ.md`: M03 pasa a `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, con entrega E01, el commit y `EVIDENCIA.md §E01`. Completa la fila E01 del avance.
- `EVIDENCIA.md`: sección E01 con las salidas. Límite: la columna sigue en la base hasta su `RemoveField`; la reversa de la migración no borra las filas copiadas.

Commit: `feat(medical-records): make VitalSigns the only weight source (order 7, M03)`.
