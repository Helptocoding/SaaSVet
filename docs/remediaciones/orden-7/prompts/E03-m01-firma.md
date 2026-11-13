# E03 — M01: quien firma necesita cédula

Primero lee y aplica `docs/remediaciones/orden-7/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Exigir la cédula profesional a quien firma, sea cual sea su rol: al veterinario de la consulta cuando se cierra (aunque cierre un ADMIN) y a quien emite una receta. Congelarla al cierre en `vet_license_at_close` y mostrarla en los PDF de consulta y receta. La demo siembra números de demostración para que siga pudiendo cerrar y recetar.

## Precondición

`git log --oneline -1` muestra el commit de E02 (`feat(users): add professional license number and staff profile edit (order 7, M01)`) y `backend/apps/users/professional.py` define `normalize_license_number`. Si no, `BLOQUEADA`.

## Archivos permitidos

- `backend/apps/analytics/tests/test_late_arrival_observability.py`
- `backend/apps/core/management/commands/_demo_data.py`
- `backend/apps/core/management/commands/seed_demo_clinic.py`
- `backend/apps/core/tests/test_pdf_markup_injection.py`
- `backend/apps/medical_records/services.py`
- `backend/apps/medical_records/tests/test_close.py`
- `backend/apps/medical_records/tests/test_consultation_draft.py`
- `backend/apps/medical_records/tests/test_emergency_materialization.py`
- `backend/apps/medical_records/tests/test_order2_close_atomicity.py`
- `backend/apps/medical_records/tests/test_signer_license.py`
- `backend/apps/medical_records/tests/test_surgery_materialization.py`
- `backend/apps/medical_records/tests/test_vaccine_lot_materialization.py`
- `backend/apps/medical_records/views.py`
- `backend/apps/prescriptions/tests/test_multitenancy.py`
- `backend/apps/prescriptions/views.py`
- `backend/apps/users/professional.py`
- `docs/modules/medical_records.md`
- `docs/remediaciones/orden-7/MATRIZ.md` y `docs/remediaciones/orden-7/EVIDENCIA.md`

## Excepciones

- **Pruebas.** Nueve archivos de pruebas existentes cierran consultas o emiten recetas con un firmante sin cédula, que desde esta entrega es `400` por diseño. Solo se les da cédula al usuario que firma (en el helper `_make_user` del archivo o en la creación del usuario). Ninguna aserción cambia. La regla en sí se prueba en `test_signer_license.py`.
- **Analítica.** `apps/analytics/tests/test_late_arrival_observability.py` cierra una consulta por el endpoint. Es el único archivo de analítica que se toca, y solo para añadir `license_number` a su veterinario.

## Contexto

- `require_signer_license` vive en `apps/users/professional.py` (E02). Lanza el `ValidationError` de DRF con la clave `license_number`; el manejador lo devuelve como `{code: "validation_error", errors: {license_number: [...]}}` y el frontend lo muestra con `apiError`.
- En el cierre va **después** de las validaciones de diagnóstico y tratamiento, dentro de la misma transacción: si falla, no se cierra nada ni se crea el Checkout.
- La receta se bloquea en `perform_create`, después de validar el payload. El PATCH de una receta existente no se toca.
- `test_pdf_markup_injection` audita que todo lo que entra a un `Paragraph` esté escapado y solo admite ciertos nombres de variable, entre ellos `spec`. Por eso la cédula se añade **dentro de `spec`** y no en una variable nueva. No toques esa prueba.
- La cédula de los PDF sale del snapshot si la consulta está cerrada y del usuario vivo si está abierta: mismo criterio que el nombre y la especialidad.

## Cambios

Aplícalos en este orden.

### Cambio 1 — `backend/apps/users/professional.py`

Texto actual:

```python
    if value and not LICENSE_NUMBER_RE.fullmatch(value):
        raise serializers.ValidationError(LICENSE_FORMAT_MESSAGE)
    return value
```

Texto nuevo:

```python
    if value and not LICENSE_NUMBER_RE.fullmatch(value):
        raise serializers.ValidationError(LICENSE_FORMAT_MESSAGE)
    return value


def require_signer_license(user, action):
    """Exige cédula a quien firma una consulta o una receta, sea cual sea su rol.

    `action` completa el mensaje («cerrar la consulta», «emitir la receta»). Sin
    firmante también se rechaza: un documento clínico sin veterinario no se firma.
    """
    if user is None:
        raise serializers.ValidationError({'license_number': [
            f'La consulta no tiene veterinario asignado; no se puede {action}.']})
    if not user.license_number:
        name = f'{user.first_name} {user.last_name}'.strip() or user.username
        raise serializers.ValidationError({'license_number': [
            f'Registra la cédula profesional de {name} en Equipo para {action}.']})
```

### Cambio 2 — `backend/apps/medical_records/tests/test_signer_license.py`

Archivo nuevo. Créalo con este contenido exacto:

```python
"""M01 (orden 7): quien firma una consulta o una receta necesita cédula.

El firmante es el veterinario de la consulta al cerrarla y quien emite la receta,
sea cual sea su rol. La cédula se congela al cierre y los PDF la muestran.
"""
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.billing.models import Checkout
from apps.inventory.models import Presentation, Product
from apps.medical_records.models import MedicalRecord
from apps.medical_records.tests.test_vitals import _make_user
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.prescriptions.models import Prescription, PrescriptionItem
from apps.prescriptions.tests.test_pdf import _extract_pdf_text


class SignerLicenseTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Org Firma M01', timezone='UTC')
        cls.vet = _make_user('vet_firma_m01', cls.org, 'VET')
        cls.vet.first_name, cls.vet.last_name = 'Ana', 'Galeno'
        cls.vet.save(update_fields=['first_name', 'last_name'])
        cls.admin = _make_user('adm_firma_m01', cls.org, 'ADMIN')
        cls.admin.first_name, cls.admin.last_name = 'Luis', 'Mora'
        cls.admin.save(update_fields=['first_name', 'last_name'])
        owner = Owner.objects.create(name='Dueña', phone='5512345602', organization=cls.org)
        cls.pet = Pet.objects.create(name='Kira', species='dog', owner=owner, organization=cls.org)
        cls.product = Product.objects.create(
            name='Antibiotico Firma', internal_code='FIRMA1',
            requires_prescription=True, organization=cls.org,
        )
        Presentation.objects.create(
            product=cls.product, name='Frasco', base_unit='bottle',
            sale_price=Decimal('100'), stock=Decimal('20'), organization=cls.org,
        )

    def _set_license(self, user, value):
        user.license_number = value
        user.save(update_fields=['license_number'])

    def _record(self, veterinarian):
        return MedicalRecord.objects.create(
            organization=self.org, pet=self.pet, veterinarian=veterinarian,
            diagnosis='dx', treatment='tx',
        )

    def _close(self, record, actor):
        self.client.force_authenticate(actor)
        return self.client.post(f'/api/medical-records/{record.public_id}/close/')

    def _create_rx(self, record, actor):
        self.client.force_authenticate(actor)
        return self.client.post('/api/prescriptions/', {
            'medical_record': record.pk, 'pet': self.pet.pk, 'notes': 'rx',
            'items': [{'product': self.product.pk, 'dose': '1ml', 'quantity': '1.00'}],
        }, format='json')

    def test_vet_without_license_cannot_close(self):
        record = self._record(self.vet)
        r = self._close(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assertIn('license_number', r.data['errors'])
        self.assertIn('Ana Galeno', str(r.data['errors']['license_number']))
        record.refresh_from_db()
        self.assertEqual(record.status, MedicalRecord.Status.OPEN)
        self.assertFalse(Checkout.objects.filter(medical_record=record).exists())

    def test_admin_cannot_close_for_a_vet_without_license(self):
        self._set_license(self.admin, '7654321')
        record = self._record(self.vet)
        r = self._close(record, self.admin)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        record.refresh_from_db()
        self.assertEqual(record.status, MedicalRecord.Status.OPEN)

    def test_admin_signing_needs_own_license(self):
        record = self._record(self.admin)
        r = self._close(record, self.admin)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self._set_license(self.admin, '7654321')
        r = self._close(record, self.admin)
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)

    def test_close_freezes_license_snapshot(self):
        self._set_license(self.vet, '1234567')
        record = self._record(self.vet)
        r = self._close(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        record.refresh_from_db()
        self.assertEqual(record.vet_license_at_close, '1234567')
        self._set_license(self.vet, '7777777')
        pdf = self.client.get(f'/api/medical-records/{record.public_id}/pdf/')
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        text = _extract_pdf_text(pdf.content)
        self.assertIn('1234567', text)
        self.assertNotIn('7777777', text)

    def test_open_record_pdf_shows_live_license(self):
        self._set_license(self.vet, '2468024')
        record = self._record(self.vet)
        self.client.force_authenticate(self.vet)
        pdf = self.client.get(f'/api/medical-records/{record.public_id}/pdf/')
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        self.assertIn('2468024', _extract_pdf_text(pdf.content))

    def test_prescription_requires_issuer_license(self):
        record = self._record(self.vet)
        r = self._create_rx(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assertIn('license_number', r.data['errors'])
        self.assertFalse(Prescription.objects.filter(medical_record=record).exists())
        self.assertFalse(PrescriptionItem.objects.filter(product=self.product).exists())
        self._set_license(self.vet, '1234567')
        r = self._create_rx(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)

    def test_prescription_pdf_signature_shows_license(self):
        self._set_license(self.vet, '1357913')
        record = self._record(self.vet)
        r = self._create_rx(record, self.vet)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        rx = Prescription.objects.get(medical_record=record)
        pdf = self.client.get(f'/api/prescriptions/{rx.public_id}/pdf/')
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        text = _extract_pdf_text(pdf.content)
        self.assertIn('Cédula profesional 1357913', text)
```

### Cambio 3 — `backend/apps/medical_records/services.py`

Texto actual:

```python
    from apps.core.views import resolve_public_id
    from .policies import can_close_medical_record, log_ownership_denied
```

Texto nuevo:

```python
    from apps.core.views import resolve_public_id
    from apps.users.professional import require_signer_license
    from .policies import can_close_medical_record, log_ownership_denied
```

### Cambio 4 — `backend/apps/medical_records/services.py`

Texto actual:

```python
            raise ValidationError({'treatment': 'El tratamiento es obligatorio.'})

        apply_consultation_draft_on_close(record, request)
```

Texto nuevo:

```python
            raise ValidationError({'treatment': 'El tratamiento es obligatorio.'})
        # M01 (orden 7, ADR p64): firma el veterinario de la consulta, no quien cierra.
        require_signer_license(record.veterinarian, 'cerrar la consulta')

        apply_consultation_draft_on_close(record, request)
```

### Cambio 5 — `backend/apps/medical_records/services.py`

Texto actual:

```python
            record.vet_specialty_at_close = vet.specialty
            record.vet_snapshot_source = 'captured'
```

Texto nuevo:

```python
            record.vet_specialty_at_close = vet.specialty
            record.vet_license_at_close = vet.license_number
            record.vet_snapshot_source = 'captured'
```

### Cambio 6 — `backend/apps/medical_records/services.py`

Texto actual:

```python
            'vet_public_id_at_close', 'vet_name_at_close', 'vet_specialty_at_close',
            'vet_snapshot_source', 'vet_snapshot_recorded_at',
        ])
```

Texto nuevo:

```python
            'vet_public_id_at_close', 'vet_name_at_close', 'vet_specialty_at_close',
            'vet_license_at_close', 'vet_snapshot_source', 'vet_snapshot_recorded_at',
        ])
```

### Cambio 7 — `backend/apps/medical_records/views.py`

Texto actual:

```python
        specialty = record.vet_specialty_at_close if vet is None else vet.specialty
        spec = f" &nbsp;·&nbsp; {pdf_markup(specialty)}" if specialty else ""
        flow += section(st, theme, "Veterinario")
        flow.append(Paragraph(f"{pdf_markup(vet_name)}{spec}", st['body']))
```

Texto nuevo:

```python
        specialty = record.vet_specialty_at_close if vet is None else vet.specialty
        # M01 (orden 7): cédula congelada al cierre; la del usuario mientras está abierta.
        license_number = record.vet_license_at_close if vet is None else vet.license_number
        spec = f" &nbsp;·&nbsp; {pdf_markup(specialty)}" if specialty else ""
        if license_number:
            spec += f" &nbsp;·&nbsp; Céd. Prof. {pdf_markup(license_number)}"
        flow += section(st, theme, "Veterinario")
        flow.append(Paragraph(f"{pdf_markup(vet_name)}{spec}", st['body']))
```

### Cambio 8 — `backend/apps/prescriptions/views.py`

Texto actual:

```python
from apps.medical_records.policies import assert_can_modify_medical_record
```

Texto nuevo:

```python
from apps.medical_records.policies import assert_can_modify_medical_record
from apps.users.professional import require_signer_license
```

### Cambio 9 — `backend/apps/prescriptions/views.py`

Texto actual:

```python
    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.user.organization,
            veterinarian=self.request.user,
        )
```

Texto nuevo:

```python
    def perform_create(self, serializer):
        # M01 (orden 7, ADR p64): quien emite la receta la firma; sin cédula no puede.
        require_signer_license(self.request.user, 'emitir la receta')
        serializer.save(
            organization=self.request.user.organization,
            veterinarian=self.request.user,
        )
```

### Cambio 10 — `backend/apps/prescriptions/views.py`

Texto actual:

```python
        specialty = (prescription.medical_record.vet_specialty_at_close
                     if prescription.medical_record.status == 'closed' else vet.specialty)
        spec = f" &nbsp;·&nbsp; {pdf_markup(specialty)}" if specialty else ""
        flow += section(st, theme, "Veterinario")
        flow.append(Paragraph(f"{pdf_markup(vet_name)}{spec}", st['body']))
```

Texto nuevo:

```python
        specialty = (prescription.medical_record.vet_specialty_at_close
                     if prescription.medical_record.status == 'closed' else vet.specialty)
        # M01 (orden 7): cédula congelada al cierre; la del usuario mientras está abierta.
        license_number = (prescription.medical_record.vet_license_at_close
                          if prescription.medical_record.status == 'closed'
                          else vet.license_number)
        spec = f" &nbsp;·&nbsp; {pdf_markup(specialty)}" if specialty else ""
        if license_number:
            spec += f" &nbsp;·&nbsp; Céd. Prof. {pdf_markup(license_number)}"
        flow += section(st, theme, "Veterinario")
        flow.append(Paragraph(f"{pdf_markup(vet_name)}{spec}", st['body']))
```

### Cambio 11 — `backend/apps/prescriptions/views.py`

Texto actual:

```python
        flow += signature_block(
            st, theme, pdf_markup(vet_name),
            [pdf_markup(specialty)] if specialty else (),
        )
```

Texto nuevo:

```python
        flow += signature_block(
            st, theme, pdf_markup(vet_name),
            [pdf_markup(specialty) if specialty else '',
             f"Cédula profesional {pdf_markup(license_number)}" if license_number else ''],
        )
```

### Cambio 12 — `backend/apps/core/management/commands/_demo_data.py`

Texto actual:

```python
        "last_name": "Hernández",
        "role": "ADMIN",
    },
```

Texto nuevo:

```python
        "last_name": "Hernández",
        "role": "ADMIN",
        # M01 (orden 7): números de demostración, no cédulas reales.
        "license_number": "00000001",
    },
```

### Cambio 13 — `backend/apps/core/management/commands/_demo_data.py`

Texto actual:

```python
        "role": "VET",
        "specialty": "Medicina general",
    },
```

Texto nuevo:

```python
        "role": "VET",
        "specialty": "Medicina general",
        "license_number": "00000002",
    },
```

### Cambio 14 — `backend/apps/core/management/commands/seed_demo_clinic.py`

Texto actual:

```python
            self.stdout.write(f"  usuario creado: {u['username']} ({u['role']})")
        return {
```

Texto nuevo:

```python
            self.stdout.write(f"  usuario creado: {u['username']} ({u['role']})")
        # M01 (orden 7): la demo cierra consultas y emite recetas, y quien firma
        # necesita cédula. Solo rellena la vacía: no pisa una capturada a mano.
        for u in DEMO_USERS:
            if u.get("license_number"):
                User.objects.filter(username=u["username"], license_number="").update(
                    license_number=u["license_number"])
        return {
```

### Cambio 15 — `backend/apps/medical_records/tests/test_close.py`

Texto actual:

```python
def _make_user(username, org, role_name):
    u = User.objects.create_user(username=username, password="pass", organization=org, role=role_name)
```

Texto nuevo:

```python
def _make_user(username, org, role_name):
    # M01 (orden 7): quien firma necesita cédula; la regla se prueba en test_signer_license.
    u = User.objects.create_user(username=username, password="pass", organization=org,
                                 role=role_name, license_number="1234567")
```

### Cambio 16 — `backend/apps/medical_records/tests/test_consultation_draft.py`

Texto actual:

```python
def _make_user(username, org, role_name):
    u = User.objects.create_user(username=username, password="pass", organization=org, role=role_name)
```

Texto nuevo:

```python
def _make_user(username, org, role_name):
    # M01 (orden 7): quien firma necesita cédula; la regla se prueba en test_signer_license.
    u = User.objects.create_user(username=username, password="pass", organization=org,
                                 role=role_name, license_number="1234567")
```

### Cambio 17 — `backend/apps/prescriptions/tests/test_multitenancy.py`

Texto actual:

```python
    u = User.objects.create_user(
        username=username, password="pass", organization=org, role=role_name,
    )
```

Texto nuevo:

```python
    # M01 (orden 7): quien emite la receta necesita cédula.
    u = User.objects.create_user(
        username=username, password="pass", organization=org, role=role_name,
        license_number="1234567",
    )
```

### Cambio 18 — `backend/apps/core/tests/test_pdf_markup_injection.py`

Texto actual:

```python
        cls.vet = _make_user('vet_markup', cls.org, 'VET')
```

Texto nuevo:

```python
        cls.vet = _make_user('vet_markup', cls.org, 'VET')
        cls.vet.license_number = '1234567'  # M01 (orden 7): firma la consulta
        cls.vet.save(update_fields=['license_number'])
```

### Cambio 19 — `backend/apps/medical_records/tests/test_emergency_materialization.py`

Texto actual:

```python
            username='vet_em', password='pass1234!', organization=self.org, role='VET')
```

Texto nuevo:

```python
            username='vet_em', password='pass1234!', organization=self.org, role='VET',
            license_number='1234567')  # M01 (orden 7): firma la consulta
```

### Cambio 20 — `backend/apps/medical_records/tests/test_surgery_materialization.py`

Texto actual:

```python
            username='vet_surg', password='pass1234!', organization=self.org, role='VET')
```

Texto nuevo:

```python
            username='vet_surg', password='pass1234!', organization=self.org, role='VET',
            license_number='1234567')  # M01 (orden 7): firma la consulta
```

### Cambio 21 — `backend/apps/medical_records/tests/test_vaccine_lot_materialization.py`

Texto actual:

```python
            username='adm_vl', password='pass1234!', organization=self.org, role='ADMIN')
```

Texto nuevo:

```python
            username='adm_vl', password='pass1234!', organization=self.org, role='ADMIN',
            license_number='1234567')  # M01 (orden 7): el ADMIN firma la consulta
```

### Cambio 22 — `backend/apps/medical_records/tests/test_order2_close_atomicity.py`

Texto actual:

```python
            role='VET', organization=self.org, first_name='Vet', last_name='Prueba')
```

Texto nuevo:

```python
            role='VET', organization=self.org, first_name='Vet', last_name='Prueba',
            license_number='1234567')  # M01 (orden 7): firma la consulta
```

### Cambio 23 — `backend/apps/analytics/tests/test_late_arrival_observability.py`

Texto actual:

```python
            username="vet_t8", password="x",
            organization=org, role="VET",
        )
```

Texto nuevo:

```python
            username="vet_t8", password="x",
            organization=org, role="VET",
            license_number="1234567",  # M01 (orden 7): firma la consulta
        )
```

### Cambio 24 — `docs/modules/medical_records.md`

Texto actual:

````markdown
- La receta incluye bloque de firma del veterinario (nombre + especialidad). La cédula
  profesional llega en Fase 2 (`User.license_number`, pendiente).
````

Texto nuevo:

````markdown
- La receta incluye bloque de firma del veterinario: nombre, especialidad y cédula
  profesional (M01, orden 7; ADR p64). La consulta muestra la cédula junto al
  veterinario. En documentos cerrados sale del snapshot `vet_license_at_close`; en
  abiertos, del usuario vivo.
````

### Cambio 25 — `docs/modules/medical_records.md`

Texto actual:

````markdown
- la receta por si sola NO descuenta stock ni crea items financieros
````

Texto nuevo:

````markdown
- la receta por si sola NO descuenta stock ni crea items financieros
- emitirla (`POST /api/prescriptions/`) exige que quien la emite tenga cédula
  profesional, porque es quien la firma: si no, `400` con `errors.license_number`
  (M01, orden 7). El PATCH de una receta existente no lo exige
````

### Cambio 26 — `docs/modules/medical_records.md`

Texto actual:

````markdown
- `treatment` no puede estar vacío **excepto** si `consultation_type = vaccine`
````

Texto nuevo:

````markdown
- `treatment` no puede estar vacío **excepto** si `consultation_type = vaccine`
- el veterinario de la consulta, que la firma, debe tener cédula profesional
  (`license_number`), aunque cierre un ADMIN. Si no, `400` con `errors.license_number`.
  Al cerrar, la cédula se congela en `vet_license_at_close` junto al nombre y la
  especialidad (M01, orden 7; ADR p64)
````


## Verificación

Desde `backend/`:

```bash
R="rtk proxy python scripts/orden7_isolated.py"
for f in apps/users/professional.py apps/medical_records/services.py apps/medical_records/views.py \
  apps/prescriptions/views.py apps/core/management/commands/_demo_data.py \
  apps/core/management/commands/seed_demo_clinic.py apps/medical_records/tests/test_signer_license.py; do
  python -m py_compile $f || echo "FAIL $f"; done; echo compilado
$R makemigrations --check --dry-run 2>&1 | tail -2
$R test apps.medical_records apps.prescriptions apps.core.tests.test_pdf_markup_injection \
  apps.core.tests.test_demo_reset apps.analytics.tests.test_late_arrival_observability \
  apps.platform.tests.test_physical_deletion --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -30
cd .. && git diff --stat HEAD -- backend/apps/analytics
```

Esperado:

- `compilado` sin ningún `FAIL`.
- `No changes detected`.
- **`Ran 195 tests`** y `OK`.
- El `diff` de analítica muestra solo `test_late_arrival_observability.py`, con una línea añadida.

## Cierre

- `MATRIZ.md`: M01 sigue en `EN_CURSO`. Completa la fila E03 del avance.
- `EVIDENCIA.md`: sección E03 con las salidas. Límites: el sistema no verifica la cédula contra la SEP; editar una receta existente no la exige.

Commit: `feat(medical-records): require signer license to close and prescribe (order 7, M01)`.
