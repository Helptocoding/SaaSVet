# E02 — M01: cédula profesional en el usuario y en Equipo

Primero lee y aplica `docs/remediaciones/orden-7/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Añadir `User.license_number` (vacío o solo dígitos, de 5 a 10) con su CHECK en base de datos, y el campo `MedicalRecord.vet_license_at_close` que E03 llenará al cerrar. Equipo pasa a capturarla: el alta la exige para `VET`, y un `PATCH /api/staff/<public_id>/` nuevo, con el permiso `staff.update` (solo ADMIN), edita especialidad y cédula de usuarios existentes.

Esta entrega **no** bloquea todavía cierres ni recetas: eso es E03.

## Precondición

`git log --oneline -1` muestra el commit de E01 (`feat(medical-records): make VitalSigns the only weight source (order 7, M03)`). En `MATRIZ.md`, M03 está en `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. Si no, `BLOQUEADA`.

## Archivos permitidos

- `backend/apps/core/permissions_codes.py`
- `backend/apps/core/tests/test_day6_invariants.py`
- `backend/apps/medical_records/migrations/0031_medicalrecord_vet_license_at_close.py`
- `backend/apps/medical_records/models.py`
- `backend/apps/users/migrations/0012_user_license_number.py`
- `backend/apps/users/models.py`
- `backend/apps/users/professional.py`
- `backend/apps/users/serializers.py`
- `backend/apps/users/services.py`
- `backend/apps/users/tests/test_staff_create_must_change.py`
- `backend/apps/users/tests/test_staff_email_enforcement.py`
- `backend/apps/users/tests/test_staff_license.py`
- `backend/apps/users/views.py`
- `backend/config/urls.py`
- `docs/modules/organizations.md`
- `docs/remediaciones/orden-7/MATRIZ.md` y `docs/remediaciones/orden-7/EVIDENCIA.md`

## Excepción a la regla de pruebas

Tres archivos de pruebas existentes dan de alta un `VET` por API sin cédula, que desde esta entrega es `400` por diseño: `test_staff_create_must_change.py`, `test_staff_email_enforcement.py` y `test_day6_invariants.py`. Solo se les añade `license_number` al payload; sus aserciones no cambian.

## Contexto

- Decisiones del usuario: la cédula es obligatoria para quien firma (E03) y para todo `VET`; formato de 5 a 10 dígitos; sin verificación contra la SEP; edición por un PATCH de Equipo con permiso propio.
- Las dos columnas nuevas llevan `db_default=''`. Sin él, los ensayos de migración que rebobinan apps y crean filas con el modelo histórico reciben `NotNullViolation` (la nota de `Organization.is_active` en `apps/organizations/models.py` explica la trampa).
- Las migraciones vienen escritas. Tras crearlas, `makemigrations --check` debe decir `No changes detected`; si propone algo, `BLOQUEADA`.
- `StaffCreateView` devuelve `serializer.errors` sin el sobre `{code, errors}`; el PATCH usa el manejador estándar y sí lo trae. Las pruebas nuevas cubren las dos formas.
- `StaffDeactivateView` pasa a llamarse `StaffDetailView`: con `HybridPermission` y `resource_name = "staff"`, DELETE exige `staff.destroy` (como antes) y PATCH `staff.update`.
- `staff.update` es sensible y solo entra en la lista literal del ADMIN (ADR p63). `UpdateEmployeeSerializer` rechaza cualquier clave que no sea `specialty` o `license_number`, para no aparentar que guardó un cambio de rol.

## Cambios

Aplícalos en este orden.

### Cambio 1 — `backend/apps/users/professional.py`

Archivo nuevo. Créalo con este contenido exacto:

```python
"""Cédula profesional del firmante (M01, orden 7; ADR p64).

Solo dígitos, de 5 a 10. No se verifica contra el registro de la SEP. Es
obligatoria para todo VET (serializers de Equipo) y para quien firma una
consulta o una receta, sea cual sea su rol (dominio clínico).
"""
import re

from rest_framework import serializers

LICENSE_NUMBER_RE = re.compile(r'^[0-9]{5,10}$')
LICENSE_REQUIRED_ROLES = frozenset({'VET'})
LICENSE_FORMAT_MESSAGE = 'La cédula profesional debe tener solo dígitos, entre 5 y 10.'
LICENSE_REQUIRED_MESSAGE = 'La cédula profesional es obligatoria para veterinarios.'


def normalize_license_number(value):
    """Devuelve '' o la cédula sin espacios en los bordes; rechaza otro formato."""
    value = (value or '').strip()
    if value and not LICENSE_NUMBER_RE.fullmatch(value):
        raise serializers.ValidationError(LICENSE_FORMAT_MESSAGE)
    return value
```

### Cambio 2 — `backend/apps/users/migrations/0012_user_license_number.py`

Archivo nuevo. Créalo con este contenido exacto:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0011_user_is_service_account_alter_user_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='license_number',
            field=models.CharField(blank=True, db_default='', default='', max_length=10),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(('license_number', ''), ('license_number__regex', '^[0-9]{5,10}$'), _connector='OR'),
                name='user_license_number_digits',
            ),
        ),
    ]
```

### Cambio 3 — `backend/apps/medical_records/migrations/0031_medicalrecord_vet_license_at_close.py`

Archivo nuevo. Créalo con este contenido exacto:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medical_records', '0030_backfill_vitals_weight_from_record'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicalrecord',
            name='vet_license_at_close',
            field=models.CharField(blank=True, db_default='', default='', editable=False, max_length=10),
        ),
    ]
```

### Cambio 4 — `backend/apps/users/tests/test_staff_license.py`

Archivo nuevo. Créalo con este contenido exacto:

```python
"""M01 (orden 7): cédula profesional en Equipo.

Alta: obligatoria para VET. Edición: PATCH /api/staff/<uuid>/ con `staff.update`,
que solo acepta especialidad y cédula. Los roles salen de la siembra real de la
organización, no de un comodín.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.permissions import user_has_permission_strict
from apps.core.permissions_codes import PERMISSION_CODES, PERMISSIONS, SENSITIVE_CODES
from apps.organizations.models import Organization

User = get_user_model()
CREATE_URL = '/api/staff/create/'


def staff_url(user):
    return f'/api/staff/{user.public_id}/'


class StaffLicenseTests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Org Cedula M01', timezone='UTC')
        cls.other_org = Organization.objects.create(name='Org Cedula Otra', timezone='UTC')
        cls.admin = User.objects.create_user(
            username='admin_ced', password='x', organization=cls.org, role='ADMIN')
        cls.vet = User.objects.create_user(
            username='vet_ced', password='x', organization=cls.org, role='VET',
            license_number='1234567')
        cls.assistant = User.objects.create_user(
            username='asst_ced', password='x', organization=cls.org, role='ASSISTANT')
        cls.foreign_vet = User.objects.create_user(
            username='vet_ced_otra', password='x', organization=cls.other_org, role='VET',
            license_number='7654321')

    def _create(self, **overrides):
        payload = {
            'username': 'nuevo_ced', 'email': 'nuevo_ced@example.com',
            'password': 'Segura123', 'first_name': 'Ana', 'role': 'VET',
        }
        payload.update(overrides)
        self.client.force_authenticate(self.admin)
        return self.client.post(CREATE_URL, payload, format='json')

    def test_catalog_grants_staff_update_only_to_admin(self):
        self.assertIn('staff.update', PERMISSION_CODES)
        self.assertIn('staff.update', SENSITIVE_CODES)
        self.assertIn('staff.update', PERMISSIONS['ADMIN'])
        self.assertNotIn('staff.update', PERMISSIONS['VET'])
        self.assertNotIn('staff.update', PERMISSIONS['ASSISTANT'])
        self.assertTrue(user_has_permission_strict(self.admin, 'staff.update'))
        self.assertFalse(user_has_permission_strict(self.vet, 'staff.update'))

    def test_create_vet_requires_license(self):
        r = self._create()
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        # StaffCreateView devuelve serializer.errors sin el sobre {code, errors}.
        self.assertIn('license_number', r.data)
        self.assertFalse(User.objects.filter(username='nuevo_ced').exists())

    def test_create_vet_with_license_strips_spaces(self):
        r = self._create(license_number='  1234567 ')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        self.assertEqual(r.data['license_number'], '1234567')
        self.assertEqual(User.objects.get(username='nuevo_ced').license_number, '1234567')

    def test_create_assistant_without_license(self):
        r = self._create(role='ASSISTANT')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        self.assertEqual(r.data['license_number'], '')

    def test_create_rejects_bad_formats(self):
        for value in ('1234', '12345678901', '12a4567', '123 4567'):
            with self.subTest(value=value):
                r = self._create(license_number=value)
                self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
                self.assertIn('license_number', r.data)

    def test_staff_list_exposes_license(self):
        self.client.force_authenticate(self.admin)
        r = self.client.get('/api/staff/')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        row = next(m for m in r.data if m['username'] == 'vet_ced')
        self.assertEqual(row['license_number'], '1234567')

    def test_admin_patches_vet_license_and_specialty(self):
        self.client.force_authenticate(self.admin)
        with self.assertLogs('users.events', level='INFO') as logs:
            r = self.client.patch(staff_url(self.vet), {
                'license_number': '87654321', 'specialty': 'Cirugía'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.vet.refresh_from_db()
        self.assertEqual((self.vet.license_number, self.vet.specialty), ('87654321', 'Cirugía'))
        self.assertEqual(r.data['license_number'], '87654321')
        self.assertTrue(any('STAFF_PROFILE_UPDATED' in line for line in logs.output))

    def test_patch_cannot_clear_vet_license(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.vet), {'license_number': ''}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.license_number, '1234567')

    def test_admin_license_is_optional_and_self_editable(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.admin), {'license_number': '55555'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        r = self.client.patch(staff_url(self.admin), {'license_number': ''}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.content)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.license_number, '')

    def test_patch_rejects_other_fields(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.assistant), {
            'role': 'ADMIN', 'license_number': '12345'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
        self.assistant.refresh_from_db()
        self.assertEqual((self.assistant.role, self.assistant.license_number), ('ASSISTANT', ''))

    def test_patch_rejects_empty_body(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.vet), {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)

    def test_patch_requires_staff_update(self):
        self.client.force_authenticate(self.vet)
        r = self.client.patch(staff_url(self.vet), {'license_number': '99999'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN, r.content)
        self.vet.refresh_from_db()
        self.assertEqual(self.vet.license_number, '1234567')

    def test_patch_other_tenant_is_404(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(staff_url(self.foreign_vet), {'license_number': '99999'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND, r.content)
        self.foreign_vet.refresh_from_db()
        self.assertEqual(self.foreign_vet.license_number, '7654321')

    def test_delete_still_deactivates(self):
        target = User.objects.create_user(
            username='asst_baja', password='x', organization=self.org, role='ASSISTANT')
        self.client.force_authenticate(self.admin)
        r = self.client.delete(staff_url(target))
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT, r.content)
        target.refresh_from_db()
        self.assertFalse(target.is_active)

    def test_database_rejects_non_digit_license(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.assistant.pk).update(license_number='abc12')
```

### Cambio 5 — `backend/apps/users/models.py`

Texto actual:

```python
    specialty = models.CharField(max_length=100, blank=True, default='')
```

Texto nuevo:

```python
    specialty = models.CharField(max_length=100, blank=True, default='')
    # M01 (orden 7, ADR p64): cédula profesional, solo dígitos (5 a 10), sin
    # verificar contra la SEP. Obligatoria para VET y para quien firma consultas y
    # recetas: lo exigen apps/users/professional.py y el dominio clínico. db_default
    # mantiene aditiva la migración (ver la nota de Organization.is_active).
    license_number = models.CharField(max_length=10, blank=True, default='', db_default='')
```

### Cambio 6 — `backend/apps/users/models.py`

Texto actual:

```python
                condition=~models.Q(email=""),
            ),
        ]
```

Texto nuevo:

```python
                condition=~models.Q(email=""),
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(license_number='')
                    | models.Q(license_number__regex=r'^[0-9]{5,10}$')
                ),
                name='user_license_number_digits',
            ),
        ]
```

### Cambio 7 — `backend/apps/medical_records/models.py`

Texto actual:

```python
    vet_specialty_at_close = models.CharField(max_length=100, blank=True, default='', editable=False)
```

Texto nuevo:

```python
    vet_specialty_at_close = models.CharField(max_length=100, blank=True, default='', editable=False)
    # M01 (orden 7, ADR p64): cédula del veterinario congelada al cerrar.
    vet_license_at_close = models.CharField(
        max_length=10, blank=True, default='', db_default='', editable=False,
    )
```

### Cambio 8 — `backend/apps/users/serializers.py`

Texto actual:

```python
from apps.organizations.models import Organization
```

Texto nuevo:

```python
from apps.organizations.models import Organization
from apps.users.professional import (
    LICENSE_REQUIRED_MESSAGE, LICENSE_REQUIRED_ROLES, normalize_license_number,
)
```

### Cambio 9 — `backend/apps/users/serializers.py`

Texto actual:

```python
                  'role', 'specialty', 'is_active', 'organization', 'organization_name']
```

Texto nuevo:

```python
                  'role', 'specialty', 'license_number', 'is_active', 'organization',
                  'organization_name']
```

### Cambio 10 — `backend/apps/users/serializers.py`

Texto actual:

```python
    specialty = serializers.CharField(required=False, allow_blank=True, default='')
    # Día 6 Fase 4 (Issue #40): organization_id NO writable.
```

Texto nuevo:

```python
    specialty = serializers.CharField(required=False, allow_blank=True, default='')
    # M01 (orden 7): obligatoria para VET (validate).
    license_number = serializers.CharField(required=False, allow_blank=True, default='')
    # Día 6 Fase 4 (Issue #40): organization_id NO writable.
```

### Cambio 11 — `backend/apps/users/serializers.py`

Texto actual:

```python
                  'role', 'specialty', 'organization_id']

    def validate_username(self, value):
```

Texto nuevo:

```python
                  'role', 'specialty', 'license_number', 'organization_id']

    def validate_username(self, value):
```

### Cambio 12 — `backend/apps/users/serializers.py`

Texto actual:

```python
            raise serializers.ValidationError("La contraseña debe contener al menos un número.")
        return value

    def create(self, validated_data):
```

Texto nuevo:

```python
            raise serializers.ValidationError("La contraseña debe contener al menos un número.")
        return value

    def validate_license_number(self, value):
        return normalize_license_number(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get('role') in LICENSE_REQUIRED_ROLES and not attrs.get('license_number'):
            raise serializers.ValidationError({'license_number': LICENSE_REQUIRED_MESSAGE})
        return attrs

    def create(self, validated_data):
```

### Cambio 13 — `backend/apps/users/serializers.py`

Texto actual:

```python
            specialty=validated_data.get('specialty', ''),
            role=validated_data.get('role', 'ASSISTANT'),
```

Texto nuevo:

```python
            specialty=validated_data.get('specialty', ''),
            license_number=validated_data.get('license_number', ''),
            role=validated_data.get('role', 'ASSISTANT'),
```

### Cambio 14 — `backend/apps/users/serializers.py`

Texto actual:

```python
class ChangePasswordSerializer(serializers.Serializer):
```

Texto nuevo:

```python
class UpdateEmployeeSerializer(serializers.Serializer):
    """PATCH /api/staff/<uuid>/ (M01, orden 7): solo especialidad y cédula.

    Cualquier otra clave es 400: rol, correo o contraseña tienen sus propios
    caminos, y descartarla en silencio haría creer que se guardó.
    """
    EDITABLE_FIELDS = frozenset({'specialty', 'license_number'})

    specialty = serializers.CharField(required=False, allow_blank=True, max_length=100)
    license_number = serializers.CharField(required=False, allow_blank=True)

    def to_internal_value(self, data):
        unknown = sorted(set(data) - self.EDITABLE_FIELDS) if hasattr(data, 'keys') else []
        if unknown:
            raise serializers.ValidationError({'non_field_errors': [
                'Solo se pueden editar la especialidad y la cédula profesional.']})
        return super().to_internal_value(data)

    def validate_license_number(self, value):
        return normalize_license_number(value)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({'non_field_errors': [
                'Indica la especialidad o la cédula profesional.']})
        target = self.context.get('target')
        assert target is not None, 'UpdateEmployeeSerializer requiere context["target"]'
        license_number = attrs.get('license_number', target.license_number)
        if target.role in LICENSE_REQUIRED_ROLES and not license_number:
            raise serializers.ValidationError({'license_number': LICENSE_REQUIRED_MESSAGE})
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
```

### Cambio 15 — `backend/apps/users/services.py`

Texto actual:

```python
def ensure_agent_user(organization):
```

Texto nuevo:

```python
def update_staff_profile(*, admin, target_user, changes):
    """Edita especialidad y cédula de un miembro de Equipo (M01, orden 7).

    La view ya limita el target a la organización del ADMIN; aquí se repite como
    defensa en profundidad (404-as-403). El log lleva nombres de campo, no valores.
    """
    if (
        target_user.organization_id is None
        or target_user.organization_id != admin.organization_id
        or getattr(target_user, 'role', None) == 'ADMIN_SAAS'
        or getattr(target_user, 'is_service_account', False)
    ):
        from django.http import Http404
        raise Http404("Usuario no encontrado.")
    fields = sorted(changes)
    for field in fields:
        setattr(target_user, field, changes[field])
    target_user.save(update_fields=fields)
    logger.info(
        "STAFF_PROFILE_UPDATED",
        extra={
            'event': 'STAFF_PROFILE_UPDATED',
            'actor_id': admin.pk,
            'target_user_id': target_user.pk,
            'organization_id': admin.organization_id,
            'fields': fields,
        },
    )
    return target_user


def ensure_agent_user(organization):
```

### Cambio 16 — `backend/apps/users/views.py`

Texto actual:

```python
from apps.core.permissions import make_permission, build_permissions_list, NotDemoAccount
```

Texto nuevo:

```python
from apps.core.permissions import (
    HybridPermission, NotDemoAccount, build_permissions_list, make_permission,
)
```

### Cambio 17 — `backend/apps/users/views.py`

Texto actual:

```python
    CreateEmployeeSerializer,
    ChangePasswordSerializer,
)
from apps.users.services import (
    change_password,
    deactivate_staff,
    reset_password_for_staff,
)
```

Texto nuevo:

```python
    CreateEmployeeSerializer,
    ChangePasswordSerializer,
    UpdateEmployeeSerializer,
)
from apps.users.services import (
    change_password,
    deactivate_staff,
    reset_password_for_staff,
    update_staff_profile,
)
```

### Cambio 18 — `backend/apps/users/views.py`

Texto actual:

```python
class StaffDeactivateView(APIView):
    permission_classes = [make_permission("staff.destroy")]

    def delete(self, request, pk):
```

Texto nuevo:

```python
class StaffDetailView(APIView):
    """DELETE desactiva (`staff.destroy`); PATCH edita especialidad y cédula
    (`staff.update`, M01 orden 7). HybridPermission deriva el código del método."""
    permission_classes = [HybridPermission]
    resource_name = "staff"
    http_method_names = ['patch', 'delete', 'options']

    def patch(self, request, pk):
        target = resolve_public_id(
            User.objects.filter(
                organization=request.user.organization,
                is_active=True,
            ).exclude(role='ADMIN_SAAS').exclude(is_service_account=True),
            pk,
        )
        serializer = UpdateEmployeeSerializer(
            data=request.data,
            context={'request': request, 'target': target},
        )
        serializer.is_valid(raise_exception=True)
        user = update_staff_profile(
            admin=request.user, target_user=target, changes=serializer.validated_data,
        )
        return Response(UserSerializer(user).data)

    def delete(self, request, pk):
```

### Cambio 19 — `backend/config/urls.py`

Texto actual:

```python
    StaffDeactivateView,
```

Texto nuevo:

```python
    StaffDetailView,
```

### Cambio 20 — `backend/config/urls.py`

Texto actual:

```python
    path('api/staff/<str:pk>/', StaffDeactivateView.as_view(), name='staff-deactivate'),
```

Texto nuevo:

```python
    path('api/staff/<str:pk>/', StaffDetailView.as_view(), name='staff-detail'),
```

### Cambio 21 — `backend/apps/core/permissions_codes.py`

Texto actual:

```python
    "staff.list",
    "staff.create",
    "staff.destroy",
```

Texto nuevo:

```python
    "staff.list",
    "staff.create",
    # M01 (orden 7): editar especialidad y cédula profesional. Solo ADMIN.
    "staff.update",
    "staff.destroy",
```

### Cambio 22 — `backend/apps/core/permissions_codes.py`

Texto actual:

```python
    "staff.create", "staff.destroy", "staff.reset_password",
    "organization.update", "import.commit", "dashboard.financial.view",
```

Texto nuevo:

```python
    "staff.create", "staff.update", "staff.destroy", "staff.reset_password",
    "organization.update", "import.commit", "dashboard.financial.view",
```

### Cambio 23 — `backend/apps/core/permissions_codes.py`

Texto actual:

```python
        "staff.list", "staff.create", "staff.destroy", "staff.reset_password",
```

Texto nuevo:

```python
        "staff.list", "staff.create", "staff.update", "staff.destroy",
        "staff.reset_password",
```

### Cambio 24 — `backend/apps/users/tests/test_staff_create_must_change.py`

Texto actual:

```python
                'password': 'VetPass1234',
                'role': 'VET',
            },
```

Texto nuevo:

```python
                'password': 'VetPass1234',
                'role': 'VET',
                'license_number': '1234567',  # M01: obligatoria para VET
            },
```

### Cambio 25 — `backend/apps/users/tests/test_staff_email_enforcement.py`

Texto actual:

```python
            "password": "VetPass1234", "role": "VET",
        }
```

Texto nuevo:

```python
            "password": "VetPass1234", "role": "VET",
            "license_number": "1234567",  # M01: obligatoria para VET
        }
```

### Cambio 26 — `backend/apps/core/tests/test_day6_invariants.py`

Texto actual:

```python
            "last_name": "Vet",
            "role": "VET",
            "organization_id": self.org_b.id,
```

Texto nuevo:

```python
            "last_name": "Vet",
            "role": "VET",
            "license_number": "1234567",  # M01 (orden 7): obligatoria para VET
            "organization_id": self.org_b.id,
```

### Cambio 27 — `docs/modules/organizations.md`

Texto actual:

````markdown
  "role": "VET",
  "specialty": "Cirugia"
}
```

Validaciones de password: minimo 8 caracteres, al menos una mayuscula, al menos un numero.
````

Texto nuevo:

````markdown
  "role": "VET",
  "specialty": "Cirugia",
  "license_number": "1234567"
}
```

Validaciones de password: minimo 8 caracteres, al menos una mayuscula, al menos un numero.

`license_number` es la cédula profesional (M01, orden 7; ADR p64): solo dígitos, de 5 a 10, sin verificar contra la SEP. Es **obligatoria para `VET`** y opcional para los demás roles. Hay además un CHECK en base de datos (`user_license_number_digits`). Este endpoint devuelve `serializer.errors` sin el sobre `{code, errors}`.
````

### Cambio 28 — `docs/modules/organizations.md`

Texto actual:

````markdown
No elimina el usuario, marca `is_active = False`.
````

Texto nuevo:

````markdown
No elimina el usuario, marca `is_active = False`.

### Editar especialidad y cédula (M01, orden 7)

```
PATCH /api/staff/<public_id>/
Authorization: Bearer <token ADMIN>

{ "specialty": "Cirugia", "license_number": "1234567" }
```

Permiso `staff.update` (sensible, solo ADMIN; ADR p63 y p64). Solo acepta esas dos claves: cualquier otra es `400`, para no aparentar que se guardó un cambio de rol, correo o contraseña. Un `VET` no puede quedar sin cédula. Alcance: la misma organización, usuarios activos, sin `ADMIN_SAAS` ni cuentas de servicio (fuera de eso, `404`). El ADMIN puede editar también la suya. Registra `STAFF_PROFILE_UPDATED` con los nombres de los campos, nunca sus valores.

La misma ruta con `DELETE` sigue desactivando (`staff.destroy`): `StaffDetailView` deriva el permiso del método.
````


## Verificación

Desde `backend/`:

```bash
R="rtk proxy python scripts/orden7_isolated.py"
for f in apps/users/professional.py apps/users/models.py apps/users/serializers.py apps/users/services.py \
  apps/users/views.py config/urls.py apps/core/permissions_codes.py apps/medical_records/models.py \
  apps/users/migrations/0012_user_license_number.py \
  apps/medical_records/migrations/0031_medicalrecord_vet_license_at_close.py \
  apps/users/tests/test_staff_license.py apps/users/tests/test_staff_create_must_change.py \
  apps/users/tests/test_staff_email_enforcement.py apps/core/tests/test_day6_invariants.py; do
  python -m py_compile $f || echo "FAIL $f"; done; echo compilado
grep -rn "StaffDeactivateView" config apps --include=*.py | grep -v "/tests/\|services.py"
$R makemigrations --check --dry-run 2>&1 | tail -2
$R migrate --noinput 2>&1 | tail -3
$R test apps.users apps.core.tests.test_admin_explicit_grants apps.core.tests.test_permissions_catalog \
  apps.core.tests.test_default_permissions apps.core.tests.test_seed_permissions_prune \
  apps.core.tests.test_wildcard_policy apps.core.tests.test_day6_invariants \
  --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -30
```

Esperado:

- `compilado` sin ningún `FAIL`.
- El `grep` no imprime nada: `StaffDeactivateView` solo queda citado en el docstring de `services.py` y en el de una prueba, que describen la historia.
- `No changes detected`.
- `migrate` aplica `users.0012_user_license_number` y `medical_records.0031_medicalrecord_vet_license_at_close`.
- **`Ran 226 tests`** y `OK`.

## Cierre

- `MATRIZ.md`: M01 pasa a `EN_CURSO` (se cierra en E04). Completa la fila E02 del avance.
- `EVIDENCIA.md`: sección E02 con las salidas. Límite: los cierres y las recetas aún no exigen la cédula.

Commit: `feat(users): add professional license number and staff profile edit (order 7, M01)`.
