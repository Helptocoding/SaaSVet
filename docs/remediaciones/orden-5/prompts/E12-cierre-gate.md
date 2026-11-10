# E12 — Gate de CI, salvaguarda de supresiones y cierre

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Que un error de lint vuelva a bloquear CI, que ninguna supresión futura de estas reglas entre sin motivo, y dejar el expediente cerrado.

## Precondición

Desde `frontend/`, `rtk proxy node_modules/.bin/eslint . --quiet; echo "exit=$?"` debe dar `exit=0`. Si no, detente con `BLOQUEADA`.

## Archivos permitidos

- `.github/workflows/ci.yml`
- `frontend/src/test/lintDisableReason.test.js` (nuevo)
- `docs/modules/frontend.md`, `docs/p1-4-frontend-reliability.md`, `docs/deuda/fase4-prioridad-baja.md`
- Expediente del orden 5

## Paso 1. CI

En `.github/workflows/ci.yml`, job `frontend`:

1. Cambia el comentario `# FRONTEND (required) — build + unit tests (Vitest) must pass; lint advisory.` por `# FRONTEND (required) — build, unit tests (Vitest) and lint errors must pass.`.
2. Sustituye:

   ```yaml
   - name: Lint (warning)
     continue-on-error: true
     run: pnpm run lint
   ```

   por:

   ```yaml
   - name: Lint (blocking on errors)
     run: pnpm run lint
   ```

Respeta la indentación del archivo. `eslint` termina con exit 0 cuando solo hay warnings: no añadas `--max-warnings`.

## Paso 2. Salvaguarda de supresiones

Crea `frontend/src/test/lintDisableReason.test.js`, siguiendo el patrón de `noConsoleTokenLeak.test.js`:

```js
import { describe, it, expect } from "vitest";

// Orden 5, F01: las supresiones de estas reglas son decisiones revisadas, una por
// una. Este gate impide añadir otra sin explicar por qué es legítima.
const modules = import.meta.glob("../**/*.{js,jsx}", {
    query: "?raw",
    import: "default",
    eager: true,
});

const RULES = /eslint-disable.*react-hooks\/(set-state-in-effect|immutability|refs|purity|preserve-manual-memoization)/;

function findOffenders() {
    const hits = [];
    for (const [path, src] of Object.entries(modules)) {
        if (path.includes("/test/") || /\.test\.[jt]sx?$/.test(path)) continue;
        src.split("\n").forEach((line, idx) => {
            if (RULES.test(line) && !line.includes(" -- ")) hits.push(`${path}:${idx + 1}: ${line.trim()}`);
        });
    }
    return hits;
}

describe("supresiones de react-hooks con motivo (orden 5)", () => {
    it("toda supresión de estas reglas explica su motivo tras ' -- '", () => {
        expect(findOffenders()).toEqual([]);
    });
});
```

## Paso 3. Documentación

**`docs/modules/frontend.md`**

- En «CI (gate bloqueante)», sustituye la frase que dice que `lint` sigue siendo advisory por: `` `lint` bloquea por errores desde el orden 5; los warnings `exhaustive-deps` no bloquean. ``
- Añade a Testing, junto a los gates: `` `src/test/lintDisableReason.test.js` exige motivo en las supresiones de reglas de react-hooks. ``
- En «Pendiente (siguientes fases)», elimina la línea `D: triar los ~6 errores`.

**`docs/p1-4-frontend-reliability.md`**: marca `[x]` la casilla `42 errores react-hooks triados → lint blocking.` y añade `(orden 5, 2026-11)`.

**`docs/deuda/fase4-prioridad-baja.md`**: al final de las secciones C3, C4, C5 y C6 añade `**Estado:** cerrado en el orden 5 ([expediente](../remediaciones/orden-5/README.md)).`. En C3 añade que el criterio escrito fue sustituido: se movió `AuthProvider` en lugar de crear `useAuth.js`.

## Paso 4. Verificación final

Desde `frontend/`, conservando cada salida:

```
rtk proxy node_modules/.bin/eslint . --quiet; echo "exit=$?"
rtk proxy node_modules/.bin/eslint . 2>&1 | tail -3
pnpm run build
pnpm run smoke:urls
rtk proxy node_modules/.bin/vitest run --reporter=dot 2>&1 | tail -30
```

Comprueba también que `git diff codex/e4-capacity-scheduling --stat -- backend` no muestra cambios.

## Paso 5. Expediente

- `MATRIZ.md`: F01 como `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE` y todas las filas de avance completas con su commit.
- `EVIDENCIA.md`: sección de cierre con la salida de los comandos, los warnings restantes por regla y estos límites:
  - El gate bloqueante solo queda probado en CI cuando el usuario suba la rama.
  - Sin despliegue.
  - Verificación visual de E06 y E10: indica lo que se comprobó y lo que no.
- `README.md`: cambia el estado a `implementado localmente, pendiente de revisión y subida por el usuario`.

## Cierre

Commit: `ci(frontend): make lint errors blocking and close order 5 (order 5, F01)`.

En «Para revisar» indica que queda en manos del usuario subir la rama y confirmar el CI.
