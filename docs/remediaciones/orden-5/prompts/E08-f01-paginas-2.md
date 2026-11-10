# E08 — F01: configuración, analítica, importador y consulta

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Resolver los últimos 18 errores de la aplicación.

## Archivos permitidos

Los citados abajo, más el expediente del orden 5.

## Paso 1. `catch` vacíos en `src/pages/config/`

Estos formularios usan `toast.promise`, que ya informa del error. Añade un comentario para documentarlo.

En `ClinicSection.jsx`, `RulesSection.jsx`, `ScheduleSection.jsx` y en el `catch` de `ServicesSection.jsx` que va seguido de `finally`, deja:

```js
    } catch {
      /* toast.promise ya mostró el error */
    } finally {
```

En `handleDelete` de `ServicesSection.jsx`, cambia `} catch { }` por `} catch { /* toast.promise ya mostró el error */ }`.

## Paso 2. `src/pages/config/index.jsx`

1. Elimina `import { useAuth } from "../../auth/authContext";`.
2. Encima de `setLoading(false);`, dentro de `if (!showTenantSections) {`:

```js
// eslint-disable-next-line react-hooks/set-state-in-effect -- operador sin clínica: no hay configuración que cargar
```

## Paso 3. `src/pages/analytics/index.jsx`

| Encima de esta línea | Regla | Motivo |
|---|---|---|
| `setScope(SCOPE.OPERATIONS);` | `set-state-in-effect` | `corrige un alcance no permitido antes de cargar` |
| `setLoading(true);` de `ProtocolSection` | `set-state-in-effect` | `marca carga justo antes de la petición` |

## Paso 4. `src/pages/imports/PreviewStep.jsx`

1. Cambia `const [selected, setSelected] = useState(null);` por:

   ```js
   const [selected, setSelected] = useState(() => allItems[0] ?? null);
   ```

2. Elimina el `useEffect` que le sigue, incluido su comentario `// eslint-disable-line react-hooks/exhaustive-deps`.
3. Cambia el import a `import { useMemo, useState } from "react";`.
4. Cambia la firma a `const ReviewPanel = ({ blockingGroups, warningsGroups }) => {` y quita la línea `labelByKey={labelByKey}` donde se usa `<ReviewPanel`.
5. Encima de la línea `[warnings, labelByKey],` del segundo `useMemo`:

   ```js
   // eslint-disable-next-line react-hooks/preserve-manual-memoization -- labelByKey ya está memoizada y las acciones de cfg no la mutan
   ```

## Paso 5. `src/pages/medicalRecords/`

**`ConsultationForm.jsx`.** Encima de `setProductLots([]);` dentro de `if (!prod?.tracks_lots || !prod?.public_id) {`:

```js
// eslint-disable-next-line react-hooks/set-state-in-effect -- producto sin lotes: limpia la lista antes de cualquier carga
```

Elimina la directiva sin uso `// eslint-disable-next-line react-hooks/exhaustive-deps` que precede a `}, [productLine.product, productMap]);`.

**`PetSidebar.jsx`.** Encima de `fetchFirst("");` dentro del `useEffect`:

```js
// eslint-disable-next-line react-hooks/set-state-in-effect -- carga inicial desde la API al montar
```

Elimina la directiva sin uso `// eslint-disable-next-line react-hooks/exhaustive-deps` de ese mismo efecto.

**`SidePanel.jsx`.** Encima de `setSummary(null);` dentro de `if (!recordId) {`:

```js
// eslint-disable-next-line react-hooks/set-state-in-effect -- sin consulta seleccionada se limpia el panel
```

**`index.jsx`.**

1. Cambia `const loadAllData = async () => {` por `async function loadAllData() {` y `const loadRecords = async () => {` por `async function loadRecords() {`. Quita el `;` de cada `};` de cierre.
2. Encima de `setSelectedPet(petParam);`:

   ```js
   // eslint-disable-next-line react-hooks/set-state-in-effect -- aplica los parámetros de la URL (deep-link) al entrar
   ```

## Verificación

```
rtk proxy node_modules/.bin/eslint src/pages/config src/pages/analytics src/pages/imports src/pages/medicalRecords
rtk proxy node_modules/.bin/vitest run src/pages/imports src/pages/medicalRecords --reporter=dot 2>&1 | tail -15
pnpm run build
```

Ejecuta también la suite completa y `rtk proxy node_modules/.bin/eslint . --quiet; echo "exit=$?"`, que debe dar `exit=0`.

Recuento total: **0 errores**. Los warnings restantes deben ser solo `exhaustive-deps` y el de `__smoke__`, unos 14.

## Cierre

Commit: `refactor(frontend): resolve remaining page hook lint (order 5, F01)`.

Registra en evidencia el conteo final de warnings por regla.
