# Evidencia del orden 5

Cada entrega añade su sección con comandos reales y resultados. No se resume lo que no se ejecutó. Lo que no se pudo comprobar se declara como límite.

## Medición previa (09-11-2026, `c3f42ba`)

Tomada al preparar el plan.

| Comprobación | Resultado |
|---|---|
| `eslint .` | 197 errores, 20 warnings |
| De ellos, `standalone` | 136 errores, 1 warning |
| De ellos, app | 61 errores, 18 warnings |
| De ellos, `__smoke__` | 0 errores, 1 warning |
| `vitest run` | 814 pruebas: 810 pasan, 4 timeouts en `pages/inbox/index.test.jsx` |
| `vitest run src/pages/inbox/index.test.jsx` (solo) | 93/93 pasan |

## E00 — Línea base y exclusión de `standalone` (09-11-2026, rama `fix/orden-5-calidad-frontend`, base `15d61fd`)

| Comando | Resultado |
|---|---|
| `eslint .` antes | 197 errores, 20 warnings (coincide) |
| `eslint .` después de `globalIgnores(['dist', 'standalone'])` | 61 errores, 19 warnings (coincide) |
| `vitest run --reporter=dot` (completa) | 814 pruebas: 810 pasan, 4 fallan |
| Fallos | 4 × `Test timed out in 5000ms` en `src/pages/inbox/index.test.jsx` (timeouts por carga) |
| `vitest run src/pages/inbox/index.test.jsx` (solo) | 93/93 pasan |

Límites: los 4 timeouts se tratan como no regresión según la regla de carga; no hay otros fallos.
Observaciones sin cambio: ninguna.

## E01 — C6 y F04: docstring y terminología (2026-11-10)

| Comando | Resultado |
|---|---|
| `git diff src/utils/mapFieldErrors.js` | solo cambian líneas del comentario de cabecera |
| `vitest run src/utils/mapFieldErrors.test.js --reporter=dot` | 11/11 pasan |
| `eslint src/utils/mapFieldErrors.js src/pages/platform/createOrganization.jsx` | sin salida (exit 0) |
| `eslint .` | 61 errores, 19 warnings (coincide) |

Límites: la suite completa no se corrió; el cambio es de comentario y dos textos.
Observaciones sin cambio: etiquetas `Login` y claves `admin_username` intactas.

## E02 — C4 y C5: matemática de pagos y nombres accesibles (2026-11-10)

| Comando | Resultado |
|---|---|
| `vitest run src/utils/payments.test.js src/components/PaymentLinesEditor.test.jsx --reporter=dot` | 44/44 pasan (5 nuevas en `paymentSummary`, 1 de nombres accesibles) |
| `eslint src/utils/payments.js src/components/PaymentLinesEditor.jsx` | sin salida (exit 0) |
| `eslint .` | 61 errores, 19 warnings (coincide) |
| `pnpm run build` | OK (built in 14.00s) |
| `git diff` de `PaymentLinesEditor.test.jsx` | solo cambia el helper `removeButtons` y se añade un `describe`; ninguna aserción existente cambió |

Límites: `paymentLinesValid` no se tocó (rechaza negativos y suma solo positivos). La suite completa no se corrió.
Observaciones sin cambio: C4 queda EN_CURSO hasta E03.

## E03 — Retirar `allowPartial` (2026-11-10)

| Comando | Resultado |
|---|---|
| `vitest run src/utils/payments.test.js src/components/PaymentLinesEditor.test.jsx --reporter=dot` | 44/44 pasan |
| `eslint` de `payments.js`, `PaymentLinesEditor.jsx`, `pos/PaymentPanel.jsx`, `pages/billing.jsx` | sin errores |
| `eslint .` | 61 errores, 19 warnings (coincide) |
| `pnpm run build` | OK (built in 10.26s) |
| búsqueda de `allowPartial` / `payAllowPartial` en `frontend/src` | 0 resultados |

Callers de `paymentLinesValid` tras el cambio de firma: `PaymentPanel.jsx` `(lines, total, true)`, `billing.jsx` `RefundModal` `(lines, total)` y `Billing` `(lines, total, true)`. El cambio en efectivo sigue activo en POS y Registrar Pago.
Cambio de aserciones: se elimina el test «pago insuficiente permitiendo parcial» y se añade «pago insuficiente nunca es válido, aunque se permita cambio». Es el único cambio de aserciones permitido del orden.
Límites: la suite completa no se corrió.
Observaciones sin cambio: ninguna.

## E04 — Separar providers de contexto y hook (2026-11-10)

| Comando | Resultado |
|---|---|
| `eslint src/auth src/hooks/ActivationProvider.jsx src/hooks/activationContext.js src/App.jsx` | sin `only-export-components`; quedan 3 errores previos (2 en `AuthProvider.jsx`, 1 `set-state-in-effect` en `ActivationProvider.jsx`) |
| `eslint .` | 59 errores, 19 warnings (coincide) |
| `pnpm run build` | OK (built in 16.76s) |
| `vitest run` (suite completa) | 817/820; 3 timeouts de 5000 ms en `src/pages/inbox/index.test.jsx` bajo carga |
| `vitest run src/pages/inbox/index.test.jsx` (solo) | 93/93 pasan |

Cambios: `git mv` de `authContext.jsx` → `AuthProvider.jsx` y `activationContext.jsx` → `ActivationProvider.jsx`; nuevos `authContext.js` y `activationContext.js` con contexto y hook. Importadores cambiados: `App.jsx` y `authContext.logout.test.jsx`. Docs: dos referencias en `docs/modules/frontend.md`. Sin imports con extensión previos.
Criterio sustituido: el criterio escrito en la deuda fue sustituido por decisión del usuario (plan §1).
Límites: lógica de sesión sin tocar.
Observaciones sin cambio: los errores de `AuthProvider.jsx` y `ActivationProvider.jsx` se tratan en E05.

## E05 — Auth y hooks de datos (2026-11-10)

| Comando | Resultado |
|---|---|
| `eslint src/auth src/hooks` | 0 errores, 3 warnings `exhaustive-deps` (sin tocar) |
| `eslint .` | 50 errores, 19 warnings (coincide) |
| `vitest run src/auth src/hooks src/components/dashboard --reporter=dot` | 29/29 pasan |
| `git diff` | 10 líneas añadidas, todas comentarios `eslint-disable-next-line ... -- motivo`; 1 eliminada (la directiva sin motivo de `useDayAppointments.js`, reemplazada) |

Límites: la suite completa no se corrió.
Observaciones sin cambio: la rama `FETCH_USER` del efecto de arranque no devuelve limpieza del timer. `AuthProvider` no se desmonta durante la sesión, así que no se tocó.

Plantilla por entrega:

```markdown
## E0X — título (fecha, commit)

| Comando | Resultado |
|---|---|
| ... | ... |

Límites: ...
Observaciones sin cambio: ...
```
