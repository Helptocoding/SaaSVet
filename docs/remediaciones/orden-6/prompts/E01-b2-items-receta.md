# E01 — B2: una sola validación para los ítems de receta

Primero lee y aplica `docs/remediaciones/orden-6/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

`PrescriptionItemSerializer` (anidado en `PrescriptionSerializer.items`) y `PrescriptionItemWriteSerializer` (endpoint `POST /api/prescriptions/<uuid>/items/`) duplican sus validadores, y ya divergieron: el segundo no tiene `validate_quantity`. Por eso hoy `quantity` `0` o `-1.00` en `/items/` responde **500**, porque solo lo frena el CHECK `prescriptionitem_quantity_positive` de la base. Al terminar, ambos heredan de una base común y el endpoint responde 400.

Diferencias que se conservan a propósito:

- El anidado añade `product_name` y `product_unit` y **no** exige `requires_prescription`.
- El endpoint `/items/` exige `requires_prescription`, siempre **después** del chequeo de organización, para no revelar ese dato de productos de otra clínica.

## Archivos permitidos

- `backend/apps/prescriptions/serializers.py`
- `backend/apps/prescriptions/tests/test_multitenancy.py`
- Expediente del orden 6 (`MATRIZ.md`, `EVIDENCIA.md`)

## Precondición

1. `grep -rn "requiere 'request' en su context" backend/apps --include=*.py | grep /tests/` no debe dar resultados: ninguna prueba depende del texto de las aserciones que vas a unificar. Si da alguno, `BLOQUEADA`.
2. Antes de editar nada, desde `backend/`, anota el recuento actual:
   `rtk proxy python scripts/orden6_isolated.py test apps.prescriptions --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"`. Debe pasar; si falla, `BLOQUEADA`.

## Paso 1. `serializers.py`, cabecera y anidado

Reemplaza **todo** desde la primera línea del archivo hasta la línea anterior a `class PrescriptionSerializer(serializers.ModelSerializer):` (hoy son las líneas 1–52: imports, el comentario huérfano del logger y `PrescriptionItemSerializer` completo) por exactamente esto, seguido de dos líneas en blanco:

```python
from rest_framework import serializers
from .models import Prescription, PrescriptionItem
from apps.core.tenant_validation import require_same_organization
from apps.core.sanitize import sanitize_text


class _PrescriptionItemBase(serializers.ModelSerializer):
    """Validación común de un medicamento recetado (deuda B2, orden 6).

    La comparten el anidado de `PrescriptionSerializer.items` y el endpoint
    `/prescriptions/<id>/items/`. Cada subclase declara solo su diferencia. Una regla
    nueva va aquí: si se pone en una sola subclase, las dos vías vuelven a divergir,
    como pasó con `validate_quantity`, que faltaba en el endpoint y dejaba un 500.
    """

    class Meta:
        model = PrescriptionItem
        fields = ['id', 'product', 'dose', 'duration', 'quantity', 'instructions']

    def validate_dose(self, value):
        clean = sanitize_text(value or '', max_length=255)
        if not clean.strip():
            raise serializers.ValidationError("La dosis es obligatoria.")
        return clean

    def validate_duration(self, value):
        return sanitize_text(value or '', max_length=255)

    def validate_instructions(self, value):
        return sanitize_text(value or '', max_length=5000)

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor a 0.")
        return value

    def validate_product(self, product):
        # Tenant isolation (ADR p14 — P0 #9). En el anidado, DRF propaga al hijo el
        # context del padre.
        request = self.context.get('request')
        assert request is not None, (
            f"{type(self).__name__} requiere 'request' en su context."
        )
        return require_same_organization(
            product, request, field='product', serializer=type(self).__name__)


class PrescriptionItemSerializer(_PrescriptionItemBase):
    """Anidado en `PrescriptionSerializer.items`: no exige `requires_prescription`."""

    product_name = serializers.CharField(source='product.name', read_only=True)
    product_unit = serializers.SerializerMethodField()

    def get_product_unit(self, obj):
        pres = obj.product.presentations.first()
        return pres.base_unit if pres else None

    class Meta(_PrescriptionItemBase.Meta):
        fields = [
            'id', 'product', 'product_name', 'product_unit',
            'dose', 'duration', 'quantity', 'instructions',
        ]
```

`type(self).__name__` produce `PrescriptionItemSerializer` y `PrescriptionItemWriteSerializer`, los mismos nombres que hoy van en el log `TENANT_VALIDATION_REJECTED`.

## Paso 2. `serializers.py`, endpoint dedicado

Reemplaza **todo** desde `class PrescriptionItemWriteSerializer(serializers.ModelSerializer):` hasta el final del archivo por exactamente esto:

```python
class PrescriptionItemWriteSerializer(_PrescriptionItemBase):
    """Endpoint `/prescriptions/<id>/items/`: además exige un producto con receta."""

    def validate_product(self, product):
        # El chequeo de organización va primero: no revelar `requires_prescription`
        # de productos de otra clínica (ADR p14 — P0 #9).
        product = super().validate_product(product)
        if not product.requires_prescription:
            raise serializers.ValidationError(
                "Este producto no requiere receta. Puede dispensarse directamente desde inventario."
            )
        return product
```

No toques `PrescriptionSerializer`.

## Paso 3. Comprobación estática

Desde `backend/`:

```bash
python -m py_compile apps/prescriptions/serializers.py && echo "py_compile OK"
grep -c "def validate_dose\|def validate_duration\|def validate_instructions\|def validate_quantity" apps/prescriptions/serializers.py
grep -c "require_same_organization" apps/prescriptions/serializers.py
```

El segundo comando debe dar `4` y el tercero `4` (import, base y los dos validadores de `PrescriptionSerializer`). Si no, revisa el paso 1 o 2.

## Paso 4. Pruebas

En `backend/apps/prescriptions/tests/test_multitenancy.py`:

1. Añade `from django.test import SimpleTestCase` justo encima de `from rest_framework import status`.
2. Dentro de `PrescriptionMultitenancyTests`, inmediatamente después del método `test_add_item_endpoint_same_org_product_without_requires_prescription_returns_domain_error`, añade:

```python
    def test_add_item_endpoint_rejects_non_positive_quantity(self):
        """B2 (orden 6): /items/ comparte validate_quantity con el anidado. Antes
        respondía 500, porque solo lo frenaba el CHECK de la base."""
        rx = self._create_prescription()
        for quantity in ('0', '-1.00'):
            with self.subTest(quantity=quantity):
                r = self.client.post(f'/api/prescriptions/{rx.public_id}/items/', {
                    'product': self.product_a_rx.pk,
                    'dose': '1ml',
                    'quantity': quantity,
                }, format='json')
                self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, r.content)
                self.assertEqual(r.data['errors'], {'quantity': ['La cantidad debe ser mayor a 0.']})
        self.assertEqual(rx.items.count(), 1)

    def test_add_item_endpoint_accepts_positive_quantity(self):
        rx = self._create_prescription()
        r = self.client.post(f'/api/prescriptions/{rx.public_id}/items/', {
            'product': self.product_a_rx.pk,
            'dose': '2ml',
            'quantity': '2.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.content)
        self.assertEqual(rx.items.count(), 2)
```

3. Al final del archivo añade:

```python
class PrescriptionItemSerializersShareValidation(SimpleTestCase):
    """B2 (orden 6): una regla nueva no puede quedar en un solo serializer de ítems."""

    def test_both_inherit_the_shared_validators(self):
        from apps.prescriptions.serializers import (
            PrescriptionItemSerializer, PrescriptionItemWriteSerializer, _PrescriptionItemBase,
        )
        shared = ('validate_dose', 'validate_duration', 'validate_instructions', 'validate_quantity')
        for serializer_class in (PrescriptionItemSerializer, PrescriptionItemWriteSerializer):
            for name in shared:
                with self.subTest(serializer=serializer_class.__name__, validator=name):
                    self.assertIs(getattr(serializer_class, name), getattr(_PrescriptionItemBase, name))

    def test_only_the_dedicated_endpoint_adds_a_product_rule(self):
        from apps.prescriptions.serializers import (
            PrescriptionItemSerializer, PrescriptionItemWriteSerializer, _PrescriptionItemBase,
        )
        self.assertIs(PrescriptionItemSerializer.validate_product, _PrescriptionItemBase.validate_product)
        self.assertIsNot(
            PrescriptionItemWriteSerializer.validate_product, _PrescriptionItemBase.validate_product)
```

No cambies ninguna prueba existente.

## Verificación

```bash
R="rtk proxy python scripts/orden6_isolated.py"
python -m py_compile apps/prescriptions/tests/test_multitenancy.py && echo "py_compile OK"
$R test apps.prescriptions apps.core.tests.test_tenant_validation --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -20
```

Todo debe pasar. Ejecuta además `$R test apps.prescriptions --keepdb --noinput` solo: su `Ran` debe ser el de la precondición más 4 (dos pruebas de API y dos estructurales).

## Cierre

Commit: `refactor(prescriptions): share item validation between nested and /items/ serializers (order 6, B2)`.

En `MATRIZ.md`, fila B2: `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, commit `ver commit E01`, evidencia `EVIDENCIA.md §E01`; y la fila E01 del avance. En evidencia registra el `Ran N` antes y después, y que el 500 de `/items/` pasa a 400.

En «Para revisar»: el cambio de 500 a 400 en `POST /api/prescriptions/<uuid>/items/` con cantidad no positiva.
