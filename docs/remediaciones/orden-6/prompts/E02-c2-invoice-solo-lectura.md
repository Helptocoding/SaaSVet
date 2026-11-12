# E02 — C2: serializers de Invoice de solo lectura

Primero lee y aplica `docs/remediaciones/orden-6/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Desde ADR p62 una Invoice nace al postear un Checkout y es inmutable. `/api/billing/invoices/` es `ListAPIView` y el detalle `RetrieveAPIView`, así que **ninguna escritura llega** a `InvoiceSerializer` ni a su anidado `InvoiceItemSerializer`. Sus validadores de escritura son código muerto:

- `InvoiceSerializer.validate()` contiene la regla «cliente genérico ⇒ venta directa» (deuda C2), que muta `data['invoice_type']`. La retiró p62: el tipo lo fija `Checkout.origin` en `post_checkout`.
- `InvoiceItemSerializer.validate()` cita una `InvoiceItemCreateView` que ya no existe.

Decisión del usuario: retirar ese código y declarar ambos serializers de solo lectura. La salida JSON no cambia: un campo de solo lectura se serializa igual.

## Archivos permitidos

- `backend/apps/billing/serializers.py`
- `backend/apps/billing/tests/test_checkout_api_contract.py`
- `backend/apps/core/tests/test_tenant_validation.py`
- `backend/apps/core/tests/test_url_audit.py`
- `backend/apps/core/tests/test_tenant_scoping_audit.py` (solo la entrada indicada)
- `docs/modules/billing.md`
- `docs/decisions/2026-05-16-p14-tenant-validators-day3.md`
- Expediente del orden 6

**Eliminación de pruebas autorizada en esta entrega, y solo esta:** las tres filas de `InvoiceSerializer` en `FIELD_VALIDATORS` de `test_tenant_validation.py`, porque prueban métodos que dejan de existir.

## Precondición

Desde la raíz:

1. `grep -rn "InvoiceSerializer(\|InvoiceItemSerializer(" backend/apps --include=*.py | grep -v "/tests/"` solo puede mostrar: las dos definiciones `class ...(serializers.ModelSerializer):`, la línea `items = InvoiceItemSerializer(many=True, read_only=True)` y tres líneas de `billing/views.py` del tipo `InvoiceSerializer(invoice...`. Ninguna puede llevar `data=`.
2. `grep -rn "invoices/<str:pk>/items\|InvoiceItemCreateView" backend/apps backend/config --include=*.py | grep -v "/tests/"` solo puede mostrar el comentario dentro de `InvoiceItemSerializer.validate` que vas a borrar.

Si algo no coincide, `BLOQUEADA`. Después, desde `backend/`, anota el recuento actual de `rtk proxy python scripts/orden6_isolated.py test apps.billing --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"`.

## Paso 1. `InvoiceItemSerializer`

En `backend/apps/billing/serializers.py`:

1. Justo debajo de `class InvoiceItemSerializer(serializers.ModelSerializer):` añade:

   ```python
       """Línea de una Invoice, de solo lectura (ADR p62).

       Las líneas nacen al postear un Checkout y no se editan después. No existe un
       endpoint que las escriba, así que aquí no se validan escrituras.
       """
   ```

2. En su `Meta`, sustituye `read_only_fields = ['id', 'subtotal', 'invoice', 'dispensed']` por `read_only_fields = fields`.
3. Borra su método `validate` completo. Empieza en `    def validate(self, data):` seguido de `        service = data.get('service')`, y termina en el `        return data` que precede a `class InvoiceSerializer(serializers.ModelSerializer):`. Deben quedar exactamente dos líneas en blanco entre el `return str(discount_amount(...))` de `get_discount_amount` y `class InvoiceSerializer`.

## Paso 2. `InvoiceSerializer`

1. Justo debajo de `class InvoiceSerializer(serializers.ModelSerializer):` añade:

   ```python
       """Proyección de lectura de una Invoice (ADR p62).

       Una Invoice nace al postear un Checkout y es inmutable: `/api/billing/invoices/`
       solo lista y muestra, así que aquí no se validan escrituras. La regla «cliente
       genérico ⇒ venta directa» que vivía en este serializer la retiró p62: el tipo lo
       fija `Checkout.origin` al postear (deuda C2, orden 6).
       """
   ```

2. En su `Meta`, sustituye el bloque `read_only_fields = [ ... ]` completo (empieza en `'id', 'public_id', 'pet_public_id', 'owner_public_id',` y termina en `'tax_rate', 'due_at', 'credit_reason',` más su `]`) por `read_only_fields = fields`.
3. Borra el bloque contiguo de métodos que empieza en `    def validate_notes(self, value):` y termina en el `        return data` inmediatamente anterior a `    def _linked_prescription(self, obj):`. Incluye, en este orden: `validate_notes`, `_get_request`, `validate_owner`, `validate_pet`, `validate_appointment`, `validate_medical_record` y `validate`. Debe quedar una línea en blanco entre el `return out` de `get_credit_notes` y `def _linked_prescription`.

## Paso 3. Import sin uso

Borra la línea `from apps.core.tenant_validation import require_same_organization, same_organization`.

Comprueba desde `backend/`:

```bash
python -m py_compile apps/billing/serializers.py && echo "py_compile OK"
grep -n "same_organization\|_get_request\|InvoiceItemCreateView" apps/billing/serializers.py
grep -n "def validate" apps/billing/serializers.py
```

El segundo comando no debe imprimir nada. El tercero debe imprimir exactamente cuatro líneas: `validate_quantity` (de `PrescriptionDispenseLineSerializer`) y `validate_name`, `validate_description` y `validate_base_price` (de `ServiceSerializer`). Si hay otra, revisa los pasos 1 y 2.

## Paso 4. Pruebas

**`backend/apps/core/tests/test_tenant_validation.py`:** borra la línea `from apps.billing.serializers import InvoiceSerializer` y, en `FIELD_VALIDATORS`, las tres filas que empiezan por `(InvoiceSerializer,`. No toques nada más.

**`backend/apps/core/tests/test_url_audit.py`:** en `ALLOWED_INT_PATTERNS` borra estas dos líneas. La ruta de ítems de factura ya no existe:

```python
    # InvoiceItem (child interno bajo Invoice UUID parent) — Día 6 audit F12
    re.compile(r'billing/invoices/<str:[A-Za-z_][A-Za-z0-9_]*>/items/<int:pk>'),
```

**`backend/apps/core/tests/test_tenant_scoping_audit.py`:** es un ratchet que exige que su `BASELINE` coincida exactamente con el código. El `InvoiceItem.objects.filter(...)` que borraste en el paso 1 deja obsoleta una entrada. En `BASELINE` borra solo la línea

```python
    ('billing', 'serializers.py', 'InvoiceItem', 'filter'),
```

No es una prueba eliminada: si no la quitas, la prueba falla con «Entradas STALE en BASELINE».

**`backend/apps/billing/tests/test_checkout_api_contract.py`:**

1. Añade `import uuid` como primera línea de imports, antes de `from decimal import Decimal`.
2. Cambia `from django.test import TestCase` por `from django.test import SimpleTestCase, TestCase`.
3. Debajo de `from apps.billing.models import Checkout, Invoice, Service` añade `from apps.billing.serializers import InvoiceItemSerializer, InvoiceSerializer`.
4. Dentro de `CheckoutApiContractTests`, inmediatamente después de `test_invoice_collection_is_read_only`, añade:

   ```python
       def test_invoice_detail_is_read_only(self):
           for method in ('patch', 'put', 'delete'):
               with self.subTest(method=method):
                   response = getattr(self.client, method)(
                       f'/api/billing/invoices/{uuid.uuid4()}/', {'notes': 'x'}, format='json')
                   self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
   ```

5. Al final del archivo añade:

   ```python
   class InvoiceSerializersAreReadOnly(SimpleTestCase):
       """C2 (orden 6): las Invoice nacen al postear un Checkout (ADR p62). Sus
       serializers solo proyectan; no puede volver a ellos validación de escritura."""

       def test_no_field_is_writable(self):
           for serializer_class in (InvoiceSerializer, InvoiceItemSerializer):
               with self.subTest(serializer=serializer_class.__name__):
                   writable = [name for name, field in serializer_class().fields.items()
                               if not field.read_only]
                   self.assertEqual(writable, [])

       def test_no_write_validation_is_declared(self):
           for serializer_class in (InvoiceSerializer, InvoiceItemSerializer):
               with self.subTest(serializer=serializer_class.__name__):
                   declared = [name for name in vars(serializer_class)
                               if name == 'validate' or name.startswith('validate_')]
                   self.assertEqual(declared, [])
   ```

## Paso 5. Documentación

**`docs/modules/billing.md`:** sustituye la línea

```markdown
  `/api/billing/invoices/` es de lectura; la creación genérica está deshabilitada.
```

por

```markdown
  `/api/billing/invoices/` es de lectura; la creación genérica está deshabilitada.
  `InvoiceSerializer` e `InvoiceItemSerializer` son de solo lectura y no validan
  escrituras. El tipo de la Invoice lo fija `Checkout.origin` (orden 6, C2).
```

**`docs/decisions/2026-05-16-p14-tenant-validators-day3.md`:** al final del archivo, tras el párrafo «**Único cambio de comportamiento, deliberado:** …», añade una línea en blanco y:

```markdown
**Orden 6 (C2, 11-11-2026):** `InvoiceSerializer` e `InvoiceItemSerializer` quedaron de solo lectura, porque desde ADR p62 ninguna vía escribe Invoices por API, y perdieron sus validadores de escritura. Con ellos se fue el único llamador directo de `same_organization()` (el lote), que sigue siendo la base de `require_same_organization()`.
```

## Verificación

Desde `backend/`:

```bash
R="rtk proxy python scripts/orden6_isolated.py"
python -m py_compile apps/billing/tests/test_checkout_api_contract.py apps/core/tests/test_tenant_validation.py apps/core/tests/test_url_audit.py apps/core/tests/test_tenant_scoping_audit.py && echo "py_compile OK"
$R test apps.billing apps.core.tests.test_tenant_validation apps.core.tests.test_url_audit apps.core.tests.test_public_id_dual_exposure_audit apps.core.tests.test_tenant_scoping_audit --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -20
```

Todo debe pasar. `apps.billing` solo debe dar el recuento de la precondición más 3.

## Cierre

Commit: `refactor(billing): make invoice serializers read-only and drop dead write validation (order 6, C2)`.

En `MATRIZ.md`, fila C2: `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, `ver commit E02`, `EVIDENCIA.md §E02`; y la fila E02 del avance.

En «Para revisar»: que `InvoiceItemSerializer` también se incluyó, por ser el mismo caso de código muerto.
