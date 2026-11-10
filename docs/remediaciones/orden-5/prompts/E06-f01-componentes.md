# E06 — F01: componentes, dashboard y tours

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Resolver 16 errores. Hay tres tipos de cambio: inicialización perezosa de colores, dos reordenamientos pequeños y supresiones justificadas.

## Archivos permitidos

Los citados abajo, más el expediente del orden 5.

## Paso 1. Colores CSS con estado perezoso

Los gráficos leen variables CSS una vez tras montar. Se leen en el inicializador de `useState`, que produce el mismo valor y ahorra un render con colores de respaldo.

Patrón en cuatro archivos de `src/components/dashboard/`: `ActivityAreaChart.jsx`, `DashboardChart.jsx`, `RevenueLineChart.jsx` y `StatusPieChart.jsx`. Ejemplo de `RevenueLineChart.jsx`:

```js
// ANTES
const [colors, setColors] = useState({ primary: "#1a4434", accent: "#d67b5c" });
useLayoutEffect(() => {
  setColors({
    primary: readCssVar("--c-primary", "#1a4434"),
    accent:  readCssVar("--c-accent",  "#d67b5c"),
  });
}, []);

// DESPUÉS
const [colors] = useState(() => ({
  primary: readCssVar("--c-primary", "#1a4434"),
  accent:  readCssVar("--c-accent",  "#d67b5c"),
}));
```

Conserva exactamente las llamadas a `readCssVar` y cualquier comentario previo. Quita `useLayoutEffect` del import de `react` si queda sin uso.

En `DashboardTopBar.jsx` cambia estas dos líneas:

```js
const [color, setColor] = useState("#1a4434");
useLayoutEffect(() => { setColor(readCssVar("--c-primary", "#1a4434")); }, []);
```

por:

```js
const [color] = useState(() => readCssVar("--c-primary", "#1a4434"));
```

No extraigas `readCssVar` a un helper común: queda fuera de esta entrega.

## Paso 2. `useAgendaTour.js`

En `src/features/appointments/tour/useAgendaTour.js`, cambia:

```js
actionsRef.current = actions;
```

por:

```js
useEffect(() => { actionsRef.current = actions; }, [actions]);
```

Añade `useEffect` al import de `react`.

## Paso 3. `MultiPresentationAnimation.jsx`

En `src/features/inventory/tutorial/`:

1. Mueve el bloque completo `const handleDismiss = useCallback(...)` para que quede justo **antes** de `const goNext = useCallback(...)`.
2. Cambia las dependencias de `goNext` a `[scene, total, goTo, handleDismiss]`.

## Paso 4. `StockEntryModal.jsx`

En `src/components/`, la directiva está debajo de la línea que debería cubrir, y por eso no surte efecto. Elimina la línea:

```js
// eslint-disable-next-line react-hooks/set-state-in-effect
```

y añade, inmediatamente encima de `if (tracksLots) { setLots([emptyLot()]); setSupplierName(""); }`:

```js
// eslint-disable-next-line react-hooks/set-state-in-effect -- reinicia el editor de lotes al cambiar de producto
```

## Paso 5. Supresiones

Mismo formato: comentario en línea propia, inmediatamente encima y con su indentación.

| Archivo | Encima de esta línea | Regla | Motivo |
|---|---|---|---|
| `src/components/LotManagerModal.jsx` | `useEffect(() => { load(); }, [load]);` | `set-state-in-effect` | `carga inicial desde la API al montar` |
| `src/components/SearchSelect.jsx` | `setInputVal(value?.label ?? "");` del `useEffect` | `set-state-in-effect` | `sincroniza el texto visible con el valor controlado por el padre` |
| `src/components/SpotlightTour.jsx` | `if (!target) { setRect(null); return undefined; }` | `set-state-in-effect` | `sin objetivo en este paso se limpia la posición medida del DOM` |
| `src/components/dashboard/FirstRunAssistant.jsx` | `setCelebrateKey(step);` | `set-state-in-effect` | `consume una señal de un solo uso que llega por el estado del router` |
| `src/components/dashboard/FirstRunAssistant.jsx` | `if (current) sawStepRef.current = true;` | `refs` | `latch que solo pasa de false a true; no cambia lo que se renderiza` |
| `src/features/inventory/tutorial/MultiPresentationAnimation.jsx` | `setPhase("idle");` | `set-state-in-effect` | `reinicia la animación de la escena` |
| `src/features/inventory/tutorial/ProductCreationTour.jsx` | `setRect(null);` dentro de `if (!demoActive || !currentStep?.target) {` | `set-state-in-effect` | `sin demo activa se limpia la posición medida del DOM` |

## Verificación

```
rtk proxy node_modules/.bin/eslint src/components src/features
rtk proxy node_modules/.bin/vitest run src/components src/features --reporter=dot 2>&1 | tail -15
pnpm run build
```

Lint de esas carpetas: 0 errores. Recuento total: **34 errores**.

## Cierre

Commit: `refactor(frontend): resolve hook lint in shared components (order 5, F01)`.

En «Para revisar» indica: mirar que las gráficas del dashboard conservan sus colores.
