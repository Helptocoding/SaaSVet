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

Plantilla por entrega:

```markdown
## E0X — título (fecha, commit)

| Comando | Resultado |
|---|---|
| ... | ... |

Límites: ...
Observaciones sin cambio: ...
```
