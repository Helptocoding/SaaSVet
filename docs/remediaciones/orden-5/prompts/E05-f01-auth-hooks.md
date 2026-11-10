# E05 — F01: auth y hooks de datos

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Resolver los 9 errores de auth y hooks. Todos son sincronización legítima con la API o una máquina de arranque: se justifican por escrito, sin cambiar lógica. **No reescribas auth ni muevas ninguna línea de código.**

## Archivos permitidos

Los de la tabla, más el expediente del orden 5.

## Cómo insertar

Añade el comentario en una línea propia, **inmediatamente encima** de la línea indicada y con su misma indentación:

```js
// eslint-disable-next-line react-hooks/<regla> -- <motivo>
```

## Sitios

| Archivo | Encima de esta línea | Regla | Motivo |
|---|---|---|---|
| `src/auth/AuthProvider.jsx` | `scheduleTokenRefresh(data.access);` | `immutability` | `autorreferencia dentro de un timer; corre después de inicializar la constante` |
| `src/auth/AuthProvider.jsx` | `setInitializing(false);` dentro de `if (!storedToken) {` | `set-state-in-effect` | `estado terminal de la máquina de arranque cuando no hay token` |
| `src/hooks/ActivationProvider.jsx` | `refetch();` que sigue a `mountedRef.current = true;` | `set-state-in-effect` | `carga inicial desde la API al montar` |
| `src/hooks/useAppointmentsByStatus.js` | `fetchData();` dentro del `useEffect` | `set-state-in-effect` | `carga desde la API al montar o cambiar el rango` |
| `src/hooks/useDashboardSeries.js` | `fetchData();` del primer `useEffect` | `set-state-in-effect` | `carga desde la API al montar o cambiar el rango` |
| `src/hooks/useDashboardSummary.js` | `fetch();` que sigue a `mountedRef.current = true;` | `set-state-in-effect` | `carga inicial desde la API al montar` |
| `src/hooks/useFinancialSeries.js` | `useEffect(() => { fetchData(); }, [fetchData]);` | `set-state-in-effect` | `carga desde la API al montar o cambiar el rango` |
| `src/hooks/useNotifications.js` | `fetch();` que sigue a `mountedRef.current = true;` | `set-state-in-effect` | `carga inicial desde la API al montar` |
| `src/hooks/useOpenRecords.js` | `fetchData();` del primer `useEffect` | `set-state-in-effect` | `carga desde la API al montar o cambiar el límite` |

Además, en `src/hooks/useDayAppointments.js` ya existe una directiva sin motivo. Cámbiala por:

```js
// eslint-disable-next-line react-hooks/set-state-in-effect -- carga desde la API al montar o cambiar la fecha
```

No toques los warnings `exhaustive-deps` de estos archivos.

## Verificación

```
rtk proxy node_modules/.bin/eslint src/auth src/hooks
rtk proxy node_modules/.bin/vitest run src/auth src/hooks src/components/dashboard --reporter=dot 2>&1 | tail -15
```

Lint de `src/auth` y `src/hooks`: 0 errores. Comprueba con `git diff` que **todas** las líneas añadidas son comentarios. Recuento total: **50 errores**.

## Cierre

Commit: `chore(frontend): justify data-sync effects in auth and hooks (order 5, F01)`.

En evidencia anota esta observación sin cambio: la rama `FETCH_USER` del efecto de arranque no devuelve limpieza del timer. `AuthProvider` no se desmonta durante la sesión, así que no se tocó.
