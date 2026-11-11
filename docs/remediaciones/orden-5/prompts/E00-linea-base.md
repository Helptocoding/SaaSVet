# E00 — Línea base y exclusión de `standalone`

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Crear la rama de trabajo, guardar los documentos del plan y dejar que ESLint mida solo la aplicación. `frontend/standalone` está en `.gitignore` y CI nunca lo ve, pero aporta 136 errores locales.

## Precondición

Desde la raíz del repositorio:

1. `git status --short` solo puede listar:
   - `docs/plan-remediacion-orden-5-2026-11-09.md`
   - `docs/plan-remediacion-priorizado-2026-10-28.md`
   - `docs/remediaciones/orden-5/`
2. `git log -1 --format=%h` debe dar `c3f42ba` o un commit posterior, y `git branch --show-current` debe ser `codex/e4-capacity-scheduling`.

Si algo no coincide, detente con `BLOQUEADA`.

## Pasos

1. Crea la rama: `git switch -c fix/orden-5-calidad-frontend`.
2. Commit de documentos, con solo esas tres rutas: `docs(order5): add plan and per-delivery prompts`.
3. Desde `frontend/`, mide el estado inicial con el comando de recuento. Debe indicar **197 errores y 20 warnings**. Si difiere, anótalo en evidencia y continúa.
4. En `frontend/eslint.config.js` cambia exactamente esta línea:

   ```js
   globalIgnores(['dist']),
   ```

   por:

   ```js
   // standalone/ está en .gitignore: CI nunca lo ve y su build ensucia el lint local.
   globalIgnores(['dist', 'standalone']),
   ```

5. Vuelve a medir. Debe indicar **61 errores y 19 warnings**.
6. Ejecuta la suite completa. Aplica la regla de timeouts por carga.

## Verificación

- Recuento antes y después.
- Suite completa: resultado. En evidencia, separa timeouts por carga de fallos reales.

## Cierre

Commit de `frontend/eslint.config.js` y del expediente: `chore(frontend): exclude untracked standalone build from lint (order 5, F01)`.

No marques F01 como cerrado: solo actualiza la fila E00 de la tabla de avance.
