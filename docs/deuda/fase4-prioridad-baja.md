# Fase 4 — Deuda prioridad baja (mejoras arquitectónicas)

Items que NO son bugs ni vulnerabilidades, sino decisiones arquitectónicas que mejoran el sistema a largo plazo. Resolver después de Fases 2-3 o cuando un sprint específico lo requiera.

---

## C1 — Decisión semántica: cross-tenant access → 400 "Acceso inválido" vs 404 "Not found"

**Origen:** ADR p14 — decisión rechazada en Día 3.

**Filosofía actual del proyecto:** "el recurso existe pero no puedes acceder" → 400 + `'Acceso inválido.'`. Aplicado en todos los serializers (Día 3 mantiene este patrón).

**Alternativa más fuerte (404 "Not found"):** ocultar incluso la existencia del PK. Requiere:
- `TenantScopedPrimaryKeyRelatedField` con `queryset=Model.objects.for_organization(org)` — FK foreign no resuelve → "Invalid pk... object does not exist".
- Frontend actualizado para parsear mensaje DRF interno (inglés) o backend traduce.
- ADR explícito documentando el cambio de contrato API.

**Trade-offs:**

| Filosofía | Pro | Con |
|-----------|-----|-----|
| **400 "Acceso inválido"** (actual) | Mensaje en español, parsers de error consistentes, frontend ya integrado | Revela existencia del PK (enumeración cross-tenant posible) |
| **404 "Not found"** | Aislamiento más fuerte, no revela PKs, alineado con REST best-practices | Cambio de contrato API, requiere coordinación frontend, mensajes en inglés (DRF default) o traducción custom |

**Bloqueado por:** decisión arquitectónica + coordinación con equipo frontend + ADR.

**Criterio de cierre (si se decide migrar):**
- ADR explícito documentando trade-off.
- `TenantScopedPrimaryKeyRelatedField` extraído a `apps/core/fields.py`.
- Mensajes 404 traducidos al español (custom error handler).
- Frontend tests E2E actualizados.
- Backwards compat por 1-2 releases (200 → 404).

**Estimación:** 1 sprint completo (incluye coordinación + frontend + ADR + tests).

---

## C2 — `InvoiceSerializer.validate()` acoplamiento de reglas (generic owner forces direct_sale)

**Origen:** Pre-existente. `InvoiceSerializer.validate()` (`billing/serializers.py:191-204` post-Día 3) implementa:

```python
if owner and getattr(owner, 'is_generic', False):
    data['invoice_type'] = 'direct_sale'   # ← side effect
elif pet is None and not (owner and getattr(owner, 'is_generic', False)):
    raise serializers.ValidationError(...)
```

**Problema arquitectónico:** el `validate()` MUTA `data['invoice_type']` (side effect) en lugar de validar. Esto es lógica de dominio en el serializer, no validación.

**Riesgo bajo (funciona, no es bug):** pero:
- Mezcla validación con mutación.
- Si un caller no-DRF llama `Invoice.objects.create(...)` con `owner=<generic>, invoice_type='consultation'`, el create NO fuerza `direct_sale`. Solo el serializer lo hace.
- Source-of-truth del "generic owner forces direct_sale" está en el serializer, no en `Invoice.save()` ni en `services.py`.

**Solución (post Fase 2 A2):** mover la regla al service-layer junto con la migración de `Invoice.clean()`:

```python
# apps/billing/services.py
@transaction.atomic
def create_invoice(*, organization, owner, pet=None, invoice_type='consultation', **fields):
    if owner.is_generic:
        invoice_type = 'direct_sale'   # regla autoritativa
    if not owner.is_generic and pet is None:
        raise ValidationError("La mascota es requerida para ventas con cliente registrado.")
    # ... validación de tenant (heredada de A2)
    return Invoice.objects.create(
        organization=organization, owner=owner, pet=pet,
        invoice_type=invoice_type, **fields,
    )
```

`InvoiceSerializer.validate()` se reduce a validación pura (sin mutación).

**Bloqueado por:** A2 (Invoice.clean() migration). Hacer en el mismo sprint que A2.

**Criterio de cierre:**
- Regla "generic owner → direct_sale" centralizada en `services.py`.
- `InvoiceSerializer.validate()` sin side effects (sin `data['invoice_type'] = ...`).
- Tests directos al service confirman regla.
- Tests DRF (test_invoice_multitenancy) siguen pasando.

**Estimación:** 1 día (post A2).

---

## C3 — Fast refresh: separar `useAuth` de `authContext.jsx` (DX, no bloqueante)

**Origen:** limpieza de warnings CI P1-3 (commit `chore(frontend): clean CI lint warnings` y `remove remaining safe lint warnings`). Diferido deliberadamente.

**Warning:** `frontend/src/auth/authContext.jsx:184` → `react-refresh/only-export-components` ("Fast refresh only works when a file only exports components"). El archivo exporta `AuthProvider` (componente) **y** `useAuth` (hook) → rompe fast refresh para ese módulo en dev.

**Mismo patrón ya resuelto en `ConfirmDialog`** (P1-3): se movió `ConfirmContext`+`useConfirm` a `components/useConfirm.js` y el archivo quedó exportando solo componentes. La separación de `authContext` es idéntica en mecánica:
- Nuevo `auth/useAuth.js` con `AuthContext` + `useAuth`.
- `authContext.jsx` importa `AuthContext`, exporta solo `AuthProvider`.
- Repuntar imports de `useAuth` (**31 archivos**), API idéntica.

**Por qué se difirió (no es bug):**
- Es solo un warning de DX en dev (HMR), **no bloquea CI** (lint es `continue-on-error`) ni afecta el build de producción.
- Toca el flujo auth/token (alto fan-out: 31 imports) → el churn excede el alcance de una limpieza post-CI ("no refactor grande").

**Criterio de cierre (P1-4 frontend reliability):**
- `auth/useAuth.js` creado (context + hook), `authContext.jsx` exporta solo `AuthProvider`.
- 31 imports de `useAuth` repuntados; `App.jsx` sigue importando `AuthProvider` de `authContext`.
- `pnpm build` verde, sin cambios de comportamiento del refresh de token.
- Warning `react-refresh/only-export-components` en 0 (src).

**Estimación:** 30–45 min (mecánico, 1 archivo nuevo + 31 import swaps + verificación).

**Estado:** cerrado en el orden 5 ([expediente](../remediaciones/orden-5/README.md)). El criterio escrito fue sustituido: se movió `AuthProvider` en lugar de crear `useAuth.js`.

---

## C4 — `PaymentLinesEditor` duplica la matemática de pago de `utils/payments.js`

**Origen:** detectado en auditoría P1-4 (riesgo #9 del plan) y confirmado al testear el componente en Fase B2 (`7c2773c`).

**Problema:** `components/PaymentLinesEditor.jsx` recalcula `sum`/`remaining`/`change`
**inline** (líneas 8-10) en vez de consumir `utils/payments.js`, que ya es la fuente
única de la regla de dinero (ADR p30 rev). Dos copias de la misma matemática → drift
posible si una se corrige y la otra no.

```javascript
// PaymentLinesEditor.jsx (inline, duplicado)
const sum = Number(lines.reduce((a, l) => a + (Number(l.amount) || 0), 0).toFixed(2));
const remaining = Number((Number(total) - sum).toFixed(2));
```

**Riesgo bajo (funciona, hay test):** el test `PaymentLinesEditor.test.jsx` incluye un
caso de float-drift (`199.99 + 300.01 → "Exacto"`) que ancla la normalización `.toFixed(2)`
actual. Refactor seguro porque el test atrapa regresiones.

**Solución (Fase C):** extraer un helper en `utils/payments.js` (p.ej.
`paymentSummary(lines, total) → { sum, remaining, change }`) y que tanto el componente
como cualquier consumidor lo usen. Sin cambiar comportamiento (el test lo verifica).

**Criterio de cierre:**
- Una sola fuente para `sum`/`remaining`/`change` en `utils/payments.js`.
- `PaymentLinesEditor` la consume; sin matemática inline.
- `PaymentLinesEditor.test.jsx` + `payments.test.js` verdes sin cambios de assertions.

**Estimación:** 30 min.

**Estado:** cerrado en el orden 5 ([expediente](../remediaciones/orden-5/README.md)).

---

## C5 — `PaymentLinesEditor`: controles sin nombre accesible (a11y)

**Origen:** P1-4 Fase B2 — reportado, **no** corregido (la fase prohibía tocar el componente).

**Problema:** el botón eliminar línea es icon-only (`Icon.Trash`) sin `aria-label`; los
`<select>` de método y los `<input>` de monto no tienen `<label>` asociado. Lectores de
pantalla no anuncian la función de estos controles. El test los consulta por exclusión
(filtrar el botón "+ Otro método") — funciona hoy pero es frágil si se agrega un tercer
botón icon-only.

**Solución (cuando se toque el componente):**
- `aria-label="Quitar método"` en el botón trash.
- `aria-label` / `<label>` en select de método e input de monto.
- Migrar las queries del test a `getByRole('button', { name: /quitar/i })` etc. (cierra
  la fragilidad de la query por exclusión, ver C4/Fase C).

**Riesgo:** bajo (UX visual intacta; solo accesibilidad + robustez de test).

**Estimación:** 20 min (junto con C4, mismo componente).

**Estado:** cerrado en el orden 5 ([expediente](../remediaciones/orden-5/README.md)).

---

## C6 — Docstring desactualizado en `utils/mapFieldErrors.js`

**Origen:** P1-4 Fase A — reconciliación de tests.

**Problema:** el docstring solo describe la forma dotted (`presentation_input.sale_price`),
pero la implementación real escribe **además** la clave plana de raíz (`sale_price`) cuando
está libre. Ambas son load-bearing (el wizard de inventario las consume como fallback,
`inventory.jsx:1404`). El comentario de la lógica de colisión sí lo describe; el docstring
de cabecera no.

**Solución:** corregir el docstring para reflejar el dual-key (dotted + plana). **No** tocar
la implementación (comportamiento enviado a producción, cubierto por `mapFieldErrors.test.js`).

**Riesgo:** nulo (solo comentario).

**Estimación:** 5 min.

**Estado:** cerrado en el orden 5 ([expediente](../remediaciones/orden-5/README.md)).

---

## C7 — `apps/platform` colisiona con el módulo `platform` de la stdlib de Python

**Origen:** detectado al correr la suite completa (2026-06-24). Python ya provee
`import platform` (stdlib); la app local `apps/platform` comparte el nombre base.

**Problema:** con ciertas invocaciones del test runner, el discovery de unittest
resuelve `platform` al módulo stdlib en vez de `apps.platform`:
- `python manage.py test apps` → 2 `_FailedTest` espurios (`platform.tests`,
  `platform.services`: *"'platform' is not a package"*). La suite igual corre
  (428 tests), pero el runner reporta `errors=2` falsos.
- `python manage.py test apps.platform` (label de paquete) → **crash**
  `TypeError: _path_normpath ... not NoneType` en `unittest.discover` (Py 3.13).

Mientras Django resuelva `apps.platform` por su `AppConfig` (runtime normal), **no
hay impacto funcional** — es solo fricción de tooling (test discovery, y
potencialmente otras herramientas que importen `platform` sin calificar).

**Workaround vigente (ya documentado, no es deuda):** listar los test modules con
full path (`apps.platform.tests.test_*`). Ver `docs/modules/platform.md` § Tests.

**Por qué se difiere el rename (no pre-testers):** renombrar `apps/platform` →
p.ej. `apps/saas_platform` implica tocar: imports en todo el código, `AppConfig`
(`name`/`label`), **migraciones** (`app_label` en `dependencies`), los
`ContentType`/permisos persistidos en DB, `INSTALLED_APPS`, rutas, y todos los
tests. Alto churn + riesgo de migración de datos para una fricción que hoy solo
afecta al test runner. No vale la pena antes de testers.

**Criterio de cierre (si se decide renombrar, post-testers):**
- Nuevo nombre de app sin colisión stdlib (p.ej. `apps.saas_platform`).
- Data migration de rename con `ContentType`/permisos preservados.
- `INSTALLED_APPS`, imports, urls, tests actualizados.
- `python manage.py test apps` sin `_FailedTest` espurios.

**Estimación:** 0.5–1 día (rename mecánico + migración de ContentType + verificación).

---

## C8 — El Caddy del SaaS sirve la landing (acoplamiento temporal de despliegue)

**Origen:** solución temporal de beta (2026-06-25). Para sacar la beta rápido, el
Caddy del stack SaaS sirve **también** la landing estática (Astro) del repo
**independiente** `SaaSVet-Landing`, desde un bind-mount RO
`/home/deploy/apps/SaaSVet-Landing/frontend/dist → /srv/landing`. Hecho a mano en
el VPS y reconciliado al repo (commit de drift) para que la infra trackeada
describa producción.

**Archivos afectados:**
- `infra/Caddyfile` — bloque de sitio `saaslyvet.com, www.saaslyvet.com` (`root */srv/landing` + `file_server`).
- `docker-compose.prod.yml` — volumen `/srv/landing` (RO) del servicio `caddy`.

**Problema (no es bug — funciona):** acopla el despliegue de **dos repos
independientes**. La landing depende del Caddy del SaaS; una caída/cambio del
stack SaaS afecta a `saaslyvet.com`. El build de la landing debe existir en ese
host path antes de levantar `caddy`. Contradice la decisión de mantener ambos
repos/despliegues separados — pero es intencional y temporal para la beta.

**Decisión de arquitectura vigente (NO cambiar en esta tarea):** los repos siguen
separados. Esto NO mueve la landing al repo del SaaS; solo **versiona la config de
infra que hoy corre** para eliminar el drift del VPS.

**Criterio de cierre (desacople — migración de infra futura):**
- La landing obtiene su **propio despliegue**, independiente del Caddy del SaaS
  (host estático propio: Vercel/Netlify/Caddy aparte/CDN).
- Retirar el bloque `saaslyvet.com, www.saaslyvet.com` de `infra/Caddyfile` y el
  volumen `/srv/landing` de `docker-compose.prod.yml`.
- DNS de `saaslyvet.com`/`www` apuntando al nuevo host.
- Verificar `www.saaslyvet.com` y `app.saaslyvet.com` siguen respondiendo `200`
  tras el corte (sin regresión).

**Estimación:** ~0.5 día (provisionar host de landing + DNS + retirar bloque). No bloqueante para beta.

---

## Tracking

Cuando un item se cierre, mover a `docs/deuda/cerrado/` con su PR asociado + fecha de cierre.
