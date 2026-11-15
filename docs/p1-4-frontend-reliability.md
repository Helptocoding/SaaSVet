# P1-4 — Frontend Reliability: Investigación + Plan Técnico

**Fecha:** 2026-06-13 (act. 2026-06-14)
**Estado (act. 2026-11-15):** Fases A, B1, B2 y B3 completas (B3 en `5da196e`). C y D cerradas por el orden 5: providers separados (C3), matemática de pagos centralizada (C4), subcomponentes de billing extraídos (F02) y lint bloqueante en CI (F01). Ver el [expediente del orden 5](remediaciones/orden-5/README.md).
**Audiencia:** dev frontend, QA.
**Principio rector:** *"puedo cambiar billing/inventario sin miedo antes de vender clínicas"*. Estabilidad > arquitectura bonita. No buscamos frontend perfecto.

> No es un ADR (no fija invariante cross-team ni contrato externo). Es un plan de fases ejecutable por PRs independientes.

---

## 1. Mapa del estado frontend actual

### Tamaño y forma

| Capa | Archivos | Líneas | Observación |
|---|---|---|---|
| `pages/` | 30 | 12,045 | 5 archivos >900 líneas concentran el riesgo |
| `components/` | ~45 | 6,119 | razonablemente troceado (dashboard, pos modularizados) |
| `hooks/` | 8 | 578 | sanos, single-purpose |
| `api/` | 17 | 527 | capa fina, 1 archivo por dominio — buena |
| `utils/` | 12 | 538 | **lógica pura testable** — oro barato |

### Testing — estado real (peor de lo documentado)

```
vitest            → NO instalado
@testing-library  → NO instalado
jsdom / happy-dom → NO instalado
msw (mocks)       → NO instalado
vite.config.js    → sin bloque `test`
package.json      → sin script `test`
Tests existentes  → 2 archivos huérfanos (toList.test.js, mapFieldErrors.test.js)
                    importan `vitest` pero NINGÚN runner los ejecuta
```

Conclusión: no hay infraestructura de test, solo 2 archivos que no corren. Toda estrategia empieza por instalar el runner (Fase A).

### CI actual (lo que realmente bloquea)

> Foto del 13-06-2026. Desde el orden 5 (PR #3, 11-11-2026) `lint` bloquea por errores y `pnpm test` también es bloqueante; la app pasó de 61 errores a 0 ([expediente](remediaciones/orden-5/README.md)). Las cifras de lint de esta sección son las de junio.

| Job | Gate | Bloquea merge |
|---|---|---|
| backend | tests Django + migration check | **Sí** |
| frontend | `build` | **Sí** |
| frontend | `smoke:urls` | **Sí** |
| frontend | `lint` | No (`continue-on-error`) |
| security | gitleaks | **Sí** |
| security | pip-audit / pnpm audit | No (warning) |

### Lint real (fresh checkout = solo archivos trackeados)

`src/`: **42 errores + 10 warnings**.

| Regla | Err | Naturaleza |
|---|---|---|
| `react-hooks/set-state-in-effect` | 26 | nueva (react-hooks 7.x, alineada React Compiler) |
| `react-hooks/immutability` | 10 | nueva — posible mutación directa de state/props |
| `react-hooks/exhaustive-deps` | 9 (warn) | clásica — NO tocar |
| `no-unused-vars` | 3 | features incompletas (reportadas) |
| `react-refresh/only-export-components` | 1 | authContext |
| `purity` / `preserve-manual-memoization` | 2 | nuevas |

`standalone/dist` añade 129 errores **locales** pero tiene 0 archivos git-trackeados → CI nunca los ve. Ruido solo en máquina local.

---

## 2. Top 10 riesgos reales (impacto × probabilidad)

1. **Cero red de seguridad en flujos de dinero.** `billing.jsx`, `pos/`, `cash`, refunds — ningún test.
2. **`utils/payments.js` sin tests** — regla de sobrepago/cambio (ADR p30) y validación de líneas. Pura, crítica, 0 cobertura.
3. **`inventory.jsx` 1709 líneas** — wizard + ajuste + stock + `computedStock` en un archivo.
4. **No runner de tests instalado** — puerta cerrada de todo lo demás.
5. **`react-hooks/immutability` (10) + `set-state-in-effect` (26)** — algunos bugs reales latentes, hoy invisibles (lint no bloquea).
6. **`appointments.jsx` 1454 líneas** — calendario + filtros + modales + estado.
7. **`apiError.js` / `handleFormError.js` sin tests** — única fuente de mensajes de error de TODOS los forms.
8. **`billing.jsx` 983 líneas con 3 sub-componentes embebidos** — refund + pago + dispensación + caja mezclados.
9. **Duplicación de cálculo de pago** — `sum`/`remaining` en `utils/payments.js` Y en `PaymentLinesEditor.jsx`.
10. **`mapFieldErrors.test.js` sin reconciliar** — 3 tests rojos al instalar el runner (ver §nota).

---

## 3. Archivos más peligrosos

| # | Archivo | Líneas | Por qué peligroso | Tests |
|---|---|---|---|---|
| 1 | `pages/inventory.jsx` | 1709 | stock math + wizard + ajuste, 40+ useState | No |
| 2 | `pages/billing.jsx` | 983 | refund + pago + caja + dispensación | No |
| 3 | `pages/appointments.jsx` | 1454 | agenda + filtros + transiciones estado | No |
| 4 | `utils/payments.js` | 37 | **regla de dinero pura** (ADR p30) | No → B1 |
| 5 | `pages/medicalRecords/ConsultationForm.jsx` | 922 | autosave + cargos + cierre→cobro | No |
| 6 | `pages/pos/index.jsx` + `usePOSCart.js` | 287+102 | checkout 2 pasos, draft cancelable | No |
| 7 | `utils/apiError.js` | 101 | mensajes de error de todos los forms | No → B1 |

El riesgo está concentrado: 4 páginas + 2 utils cubren ~90% del peligro de dinero/operación.

---

## 4. Plan de implementación

### Fase A — Base de testing ✅ (commit `9ad376e`)
- Instalar `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, `jsdom`.
- `vite.config.js`: bloque `test` (`environment: 'jsdom'`, `globals: true`, `setupFiles`).
- `src/test/setup.js`: `@testing-library/jest-dom`.
- `package.json`: `test` (`vitest run`) + `test:watch` (`vitest`).
- Reconciliar `mapFieldErrors.test.js`.

### Fase B1 — Tests de lógica crítica ✅ (commit `9ad376e`)
- `utils/payments.js`: pago exacto, insuficiente, sobrepago, cambio no persistido, múltiples métodos, líneas vacías (ADR p30).
- `utils/apiError.js`: orden 429 → detail → error → errors[] → errors{} → message → fallback; FIELD_MAP.
- `utils/handleFormError.js`: errores DRF de campo (setErrors) vs error inesperado (toast).

### Fase B2 — PaymentLinesEditor con Testing Library ✅ (commit `7c2773c`)
- 19 tests vía host controlado (`useState`): catálogo de métodos, captura de monto,
  exacto, sobrepago (Cambio vs Excede), split, agregar/quitar línea, inválidos
  (vacío/cero/texto/negativo), float-drift `.toFixed(2)`, disabled. `payments.js` real.
- Componente **sin tocar**; a11y gap (trash icon-only sin label) reportado → deuda fase 4.

### Fase B3 — extraer lógica de stock de `inventory.jsx` ✅ (commit `5da196e`)
- `utils/inventory.js`: `stockStatus`, `productStockQty`, `productStockValue` (`sale_price/cf×qty`),
  `computeInitialStock`, `fmt`, `fmtCur`. Rewire en metrics/filas/wizard, behavior-preserving.
- 33 tests (normal/cero/negativo/bajo, null-API, valor con cf, div-by-zero, umbral `<` estricto).
- **Bug UX descubierto** (no arreglado, extracción era behavior-preserving): el sort de
  "Valor en stock" usa `sale_price × stock` sin `/cf` → no coincide con el valor mostrado.
  Registrado en deuda fase 3 **B7** (fix: usar `productStockValue` en el comparador).

### Fase C — Refactor seguro (extraer lógica pura, sin tocar JSX/UX).

### Fase D — CI más estricto: `vitest run` bloqueante (cuando B1 verde); lint blocking diferido hasta triar react-hooks.

---

## 5. Tiempo estimado

| Fase | Estimación |
|---|---|
| A | 0.5 día |
| B1 | 1–1.5 días |
| B2 | 0.5 día |
| B3 | 1 día |
| C | 2–3 días (incremental) |
| D | 0.5 día |
| **Total** | **~5.5–7 días** por fases independientes |

A+B1 (1.5–2 días) ya da el 60% del valor.

---

## 6. Qué NO arreglar todavía

- `react-hooks/exhaustive-deps` (9 warn) — falso-positivo-frecuente; caso por caso, fuera de P1-4.
- `react-hooks/immutability` + `set-state-in-effect` (36 err) en masa — triar individual en Fase C.
- `standalone/dist` lint — 0 trackeado, no afecta CI; opcional `globalIgnores(['standalone'])` cosmético.
- Reescritura de inventory/billing/appointments — prohibido.
- Lint → blocking — hasta triar los 42 errores (Fase D). *Hecho en el orden 5 (2026-11).*
- Coverage % gate — invita a tests de relleno.
- Playwright/Cypress — fuera de scope beta.
- 3 features incompletas (`unitChoices`, `unitsLoaded`, `totalCount`) — deuda documentada.
- **authContext split (deuda C3):** diferir (opción B). ~31 imports; mecánico pero riesgoso. Solo si Fase C tiene tiempo, validado con build+smoke. *Hecho en el orden 5 (2026-11), moviendo los providers.*

---

## 7. Orden recomendado

```
A (runner)
 └─ B1 (utils dinero/error)      ← 60% del valor, parar aquí es válido
     └─ B2 (PaymentLinesEditor)
         └─ D parcial: gate vitest blocking
             └─ B3 + C (stock extract, billing split)
                 └─ C: authContext (opcional)
                     └─ D final: triar lint, evaluar blocking
```

Cada flecha = PR independiente.

---

## 8. Criterio de "P1-4 terminado"

**Mínimo (beta-ready):**
- [x] `pnpm test` corre en local y CI como gate bloqueante. *(Fase A, `9ad376e`)*
- [x] `utils/payments.js` + `utils/apiError.js` con tests verdes. *(Fase B1)*
- [x] `PaymentLinesEditor` con test de "total exacto / cambio". *(Fase B2, `7c2773c`)*
- [x] Lógica de stock (`stockStatus`/`computeInitialStock`/valor) extraída y testeada. *(Fase B3, `5da196e`)*
- [x] 0 tests rojos. *(112 verde)*

**Deseable (no bloqueante):**
- [x] billing.jsx sub-componentes extraídos. (orden 5, F02, `d40bdae`)
- [x] duplicación `sum/remaining` eliminada. (orden 5, C4, `92c4b96`)
- [x] 42 errores react-hooks triados → lint blocking. (orden 5, 2026-11)

**Señal de éxito:** un dev cambia un campo en billing/inventory, corre `pnpm test`, y si rompe la regla de cobro/stock el test falla **antes** del merge.

---

## Nota — reconciliación `mapFieldErrors.test.js`

La implementación (`mapFieldErrors.js`) aplana cada error anidado a **dos** claves: la
forma dotted (`presentation_input.sale_price`) **y** la forma bare-root (`sale_price`)
cuando esa raíz está libre. Esto es intencional y load-bearing: los campos del wizard
de inventario tienen nombre plano (`sale_price`), mientras el backend los anida bajo
`presentation_input`; sin la escritura bare-root el error no se mostraría en el input.

El docstring de la función describe solo la forma dotted → está **desactualizado**
(no refleja la lógica de colisión real). 3 tests codificaban el contrato del docstring
(dotted-only) y por eso fallaban contra el comportamiento enviado a producción.

**Resolución (Fase A):** se alinean los 3 tests al comportamiento real (preservar
ambas claves), sin tocar la implementación → cero cambio de comportamiento. El
docstring stale queda como limpieza menor diferida (no bloqueante).
