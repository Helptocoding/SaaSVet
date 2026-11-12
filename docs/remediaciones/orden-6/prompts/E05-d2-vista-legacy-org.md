# E05 — D2: retirar `/api/organizations/<pk>/`

Primero lee y aplica `docs/remediaciones/orden-6/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

`OrganizationLegacyView` venció su Sunset RFC 8594 el 17-08-2026 y desde entonces responde 410 a todo. El frontend no la usa. Se borran la vista, la ruta y sus helpers de Sunset; la ruta pasa a 404. `/api/organizations/me/`, `settings/` y `schedule/` no cambian.

El 404 está comprobado: sin el patrón `organization-legacy`, ninguna otra ruta resuelve `/api/organizations/1/`.

## Archivos permitidos

- `backend/apps/organizations/views.py`
- `backend/config/urls.py`
- `backend/apps/organizations/tests/test_views.py`
- `backend/apps/organizations/tests/test_legacy_view_org_id_writable.py`
- `backend/apps/core/tests/test_url_audit.py`
- `docs/modules/organizations.md`, `docs/modules/logs.md`, `docs/modules/frontend.md`
- Expediente del orden 6

**Eliminación de pruebas autorizada en esta entrega, y solo esta:** la clase `OrganizationLegacyViewTests` de `test_views.py`, que prueba el 410, los encabezados y el log de una vista que deja de existir.

## Precondición

1. `grep -rn "organizations/\${" frontend/src` no da resultados.
2. `grep -rn "endpoint_sunset\|_EndpointSunsetException" backend/apps backend/config --include=*.py | grep -v "/tests/"` solo muestra `apps/organizations/views.py`.
3. Desde `backend/`, `rtk proxy python scripts/orden6_isolated.py test apps.organizations apps.core.tests.test_url_audit --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED"` pasa. Anota el `Ran N`.

Si algo no coincide, `BLOQUEADA`.

## Paso 1. `backend/apps/organizations/views.py`

1. En el docstring del módulo, sustituye el punto 2 completo:

   ```text
   2. **Legacy `/api/organizations/<pk>/`** (`OrganizationLegacyView`):
      mantiene retrocompat 90 días pero con validación EXPLÍCITA `pk ==
      request.user.organization_id` → 404 si mismatch. NO devuelve silenciosamente
      "tu org" cuando el pk no calza (rompe expectativas REST).
      Headers RFC 8594 en TODO response (200, 404, 405).
   ```

   por:

   ```text
   2. **Legacy `/api/organizations/<pk>/`**: retirado en el orden 6 (deuda D2), tras
      su Sunset RFC 8594 del 17-08-2026. La ruta ya no existe y responde 404.
   ```

2. Borra las líneas `import logging` y `from datetime import datetime, timezone`.
3. Sustituye `from rest_framework.exceptions import APIException, NotFound` por `from rest_framework.exceptions import NotFound`.
4. Borra el bloque que empieza en `_deprecation_logger = logging.getLogger('core.deprecation')` y termina en la `}` que cierra `_DEPRECATION_HEADERS`. Incluye los comentarios del Sunset, `_SUNSET_DATETIME`, `_SUNSET_DATE` y la clase `_EndpointSunsetException`. Deben quedar dos líneas en blanco entre el último import y `class OrganizationMeView`.
5. Borra la clase `OrganizationLegacyView` completa: desde `class OrganizationLegacyView(generics.RetrieveUpdateAPIView):` hasta el `return response` de su `finalize_response`. Deben quedar dos líneas en blanco entre `OrganizationMeView` y `class OrganizationSettingsView`.

Comprueba desde `backend/`:

```bash
python -m py_compile apps/organizations/views.py && echo "py_compile OK"
grep -n "datetime\|logging\|APIException\|_SUNSET\|_DEPRECATION\|_deprecation_logger\|OrganizationLegacyView" apps/organizations/views.py
```

El `grep` no debe imprimir nada.

## Paso 2. `backend/config/urls.py`

1. En el bloque `from apps.organizations.views import (...)`, borra la línea `    OrganizationLegacyView,`.
2. Borra la línea `    path('api/organizations/<int:pk>/', OrganizationLegacyView.as_view(), name='organization-legacy'),`.

Comprueba: `python -m py_compile config/urls.py && echo "py_compile OK"` y `grep -n "OrganizationLegacyView\|organization-legacy" config/urls.py` sin resultados.

## Paso 3. Pruebas

**`backend/apps/organizations/tests/test_views.py`:**

1. Sustituye el docstring del módulo completo (desde la primera línea `"""` hasta el `"""` que lo cierra) por:

   ```python
   """
   Tests del refactor OrganizationViewSet → OrganizationMeView (Issue #10 / PR-4B / ADR p16).

   Cubre:
   - Singleton /api/organizations/me/ — GET/PATCH/405 + guard null org
   - Router list/create/destroy removidos → 404 en /api/organizations/
   - Legacy /api/organizations/<pk>/ retirado en el orden 6 (D2) → 404
   """
   ```

2. Borra la clase `OrganizationLegacyViewTests` completa.
3. Tras borrar la clase, confirma que `grep -n "datetime\|[^.]patch(" apps/organizations/tests/test_views.py` solo muestra la línea `from datetime import datetime, timezone` (los `self.client.patch(` no cuentan). Entonces borra `from datetime import datetime, timezone` y `from unittest.mock import patch`.
4. Al final de `OrganizationRouterRemovedTests`, después de `test_create_route_returns_404`, añade:

   ```python
       def test_legacy_pk_route_is_gone(self):
           """D2 (orden 6): la vista legacy se retiró tras su Sunset; la ruta ya no existe."""
           for method in ('get', 'patch', 'delete'):
               with self.subTest(method=method):
                   r = getattr(self.client, method)(
                       f'/api/organizations/{self.org.pk}/', {'name': 'X'}, format='json')
                   self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
           self.org.refresh_from_db()
           self.assertEqual(self.org.name, 'Org Router Test')
   ```

**`backend/apps/organizations/tests/test_legacy_view_org_id_writable.py`:**

1. En el docstring del módulo sustituye `sobre OrganizationLegacyView/OrganizationMeView. Ambos deben ser` por `sobre la ruta legacy (retirada en el orden 6, D2) y OrganizationMeView. Ambos deben ser`.
2. Sustituye el docstring de la clase, `"""El endpoint legacy ya venció: ningún body puede mutar la org."""`, por `"""La ruta legacy se retiró (orden 6, D2): ningún body puede mutar la org."""`.
3. Renombra `test_patch_with_id_in_body_is_rejected_after_sunset` a `test_patch_with_id_in_body_to_removed_route_is_404`, y `test_patch_with_public_id_in_body_is_rejected_after_sunset` a `test_patch_with_public_id_in_body_to_removed_route_is_404`.
4. En esos dos métodos, sustituye las dos líneas

   ```python
           self.assertEqual(r.status_code, status.HTTP_410_GONE, r.content)
           self.assertEqual(r.data['code'], 'endpoint_sunset')
   ```

   por la línea

   ```python
           self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
   ```

   Conserva todas las demás aserciones sobre la organización. Una respuesta 404 de una ruta inexistente no trae `r.data`: por eso desaparece la aserción del código.

No toques las pruebas de `/me/` de ese archivo.

**`backend/apps/core/tests/test_url_audit.py`:** en `ALLOWED_INT_PATTERNS` borra estas dos líneas:

```python
    # OrganizationLegacyView — Sunset RFC 8594 (ADR-15 / p16)
    re.compile(r'organizations/<int:pk>'),
```

## Paso 4. Documentación

**`docs/modules/organizations.md`.** Sustituye desde la línea `### Legacy — deprecado` hasta la línea `` - **Post-Sunset (>2026-08-17): responde 410 Gone automaticamente** via `_EndpointSunsetException` raised en `initial()` `` (ambas incluidas) por:

```markdown
### Legacy — retirado

`GET/PATCH /api/organizations/<pk>/` se retiró en el orden 6 (deuda D2), tras su Sunset RFC 8594 del 17-08-2026. La ruta ya no existe y responde 404. Usar `/api/organizations/me/`.
```

Y sustituye `` - `DEPRECATED_ENDPOINT_HIT` — uso del legacy `/api/organizations/<pk>/` (logger `core.deprecation`) `` por `` - `DEPRECATED_ENDPOINT_HIT` — uso de un endpoint deprecado vigente (logger `core.deprecation`; ver `logs.md`) ``.

**`docs/modules/logs.md`**, tres sustituciones:

1. `` Un cliente uso un endpoint marcado deprecado via RFC 8594. Hoy el unico es `/api/organizations/<pk>/` (PR-4B / ADR p16) cuyo successor es `/api/organizations/me/`. Post-Sunset (2026-08-17) el endpoint responde 410 Gone automaticamente. `` → `` Un cliente uso un endpoint marcado deprecado via RFC 8594. Hoy lo emiten `DELETE /api/appointments/<id>/` (ADR p57) y `GET /api/inbox/conversations/` (bandeja del agente). `/api/organizations/<pk>/` se retiro en el orden 6 (deuda D2) y ya responde 404. ``
2. `Accion requerida: monitorear adopcion frontend. Gate para corte total: 0 hits durante 7 dias consecutivos antes del Sunset.` → `` Accion requerida: identificar el cliente que aun usa el endpoint y migrarlo a su sucesor (campo `successor`). ``
3. `` | `DEPRECATED_ENDPOINT_HIT` | Decrece hasta cero antes de 2026-08-17 | Frontend aun usa `/api/organizations/<pk>/`; migrar a `/me/` | `` → `` | `DEPRECATED_ENDPOINT_HIT` | Decrece hasta cero antes del Sunset de cada endpoint | Un cliente aun usa un endpoint deprecado; migrarlo al `successor` | ``

**`docs/modules/frontend.md`.** Sustituye `` - Endpoint deprecado removido (410): `{code: 'endpoint_sunset', message}` (post-Sunset RFC 8594, e.g. `/api/organizations/<pk>/` post-2026-08-17) `` por `` - Endpoint deprecado removido (410): `{code: 'endpoint_sunset', message}` (post-Sunset RFC 8594). Hoy ningún endpoint lo emite: `/api/organizations/<pk>/` se retiró por completo en el orden 6 y responde 404. ``

## Verificación

Desde `backend/`:

```bash
R="rtk proxy python scripts/orden6_isolated.py"
python -m py_compile apps/organizations/tests/test_views.py apps/organizations/tests/test_legacy_view_org_id_writable.py apps/core/tests/test_url_audit.py && echo "py_compile OK"
$R check 2>&1 | tail -2
$R test apps.organizations apps.core.tests.test_url_audit apps.core.tests.test_admin_explicit_grants --keepdb --noinput 2>&1 | grep -E "^Ran |^OK|^FAILED|^FAIL:|^ERROR:" | head -20
```

Todo debe pasar. El recuento de `apps.organizations apps.core.tests.test_url_audit` debe ser el de la precondición menos 7 (las pruebas de `OrganizationLegacyViewTests`) más 1.

Comprobación final desde la raíz: `git grep -n "OrganizationLegacyView\|organization-legacy" -- backend docs/modules` no debe dar resultados.

## Cierre

Commit: `refactor(organizations): remove the sunset legacy /organizations/<pk>/ view (order 6, D2)`.

En `MATRIZ.md`, fila D2: `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`, `ver commit E05`, `EVIDENCIA.md §E05`; y la fila E05 del avance.

En «Para revisar»: que la ruta pasa de 410 a 404.
