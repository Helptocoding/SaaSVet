# E07 — F01: agenda, inventario, mascota y equipo

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Resolver 16 errores y eliminar código muerto de la agenda.

## Archivos permitidos

- `frontend/src/pages/appointments.jsx`
- `frontend/src/pages/inventory.jsx`
- `frontend/src/pages/petDetail.jsx`
- `frontend/src/pages/staff.jsx`
- `docs/modules/frontend.md` (una frase)
- Expediente del orden 5

## Paso 1. Borrar el componente muerto de `appointments.jsx`

`App.jsx` importa el default, `EventManagerAppointments`. El componente `Appointments` solo tiene un export con nombre, sin importadores.

Precondición: busca `\{\s*Appointments\s*\}` en `frontend/src`. El único resultado debe ser `export { Appointments };` en `appointments.jsx`. Si hay otro, detente con `BLOQUEADA`.

Elimina, en este orden:

1. Desde el comentario `// ── Main Component ───...` y `const Appointments = () => {` hasta su `};` de cierre en columna 0, justo antes de `// ── Event manager view`. Conserva ese último comentario.
2. La línea `export { Appointments };` del final.
3. La función `ApptBadge` y su comentario `// ── ApptBadge (calendar cell) ───...`.
4. La función `apptHour`.

`MiniCalendar`, `DetailModal`, `EditModal`, `WalkInModal` y `SidebarForm` siguen en uso: no los toques.

## Paso 2. Resto de `appointments.jsx`

Supresiones, en línea propia inmediatamente encima y con su indentación:

| Encima de esta línea | Regla | Motivo |
|---|---|---|
| `if (slot?.hour !== undefined) setHour(slot.hour);` | `set-state-in-effect` | `precarga la hora del horario elegido; el usuario puede cambiarla` |
| `if (user?.role === "VET") setVetId(String(user.id));` | `set-state-in-effect` | `preselecciona al veterinario cuando llega la sesión` |
| `useEffect(() => { if (token) { loadAll(); getOrgSettings().then(setOrgSettings).catch(() => {}); } }, [token]);` | `set-state-in-effect` | `carga inicial desde la API al montar` |

El `user?.role` de la segunda fila es una preselección, no un permiso: no lo cambies.

En `AppointmentList`, cambia:

```js
useEffect(() => setPage(1), [appointments]);
```

por:

```js
const [prevAppointments, setPrevAppointments] = useState(appointments);
if (prevAppointments !== appointments) { setPrevAppointments(appointments); setPage(1); }
```

En la línea que contiene `try { seen = localStorage.getItem(AGENDA_TOUR_KEY) === "true"; } catch {}`, cambia `catch {}` por `catch { /* localStorage no disponible: se asume visto */ }`.

## Paso 3. `inventory.jsx`

1. Elimina las líneas `const [unitChoices, setUnitChoices] = useState([]);` y `const [unitsLoaded, setUnitsLoaded] = useState(false);`.
2. Elimina el `useEffect` que llama a `getUnitChoices()`, ya sin uso.
3. Quita `getUnitChoices` del import de `../api/inventory`. La función sigue exportada en la API; no la borres.
4. Cambia `const loadAll = async () => {` por `async function loadAll() {` y quita el `;` de su `};` de cierre.
5. Supresiones:

| Encima de esta línea | Regla | Motivo |
|---|---|---|
| `setIsTotalValAnimating(false);` dentro del bloque sin `requestAnimationFrame` | `set-state-in-effect` | `entorno sin requestAnimationFrame: fija el valor final sin animar` |
| `setSalesPres(prev => prev.length < 2 ? [...prev, newSalesPres()] : prev);` | `set-state-in-effect` | `inicializa la segunda presentación al entrar en modo multi` |

## Paso 4. `petDetail.jsx`

| Encima de esta línea | Regla | Motivo |
|---|---|---|
| `if (token && id) loadAll();` | `immutability` | `se invoca dentro del efecto, después de inicializar la constante` |
| `const diff = Date.now() - new Date(birthDate).getTime();` | `purity` | `edad en años o meses; la precisión entre renders no importa` |

## Paso 5. `staff.jsx`

Cambia `const fetchStaff = async () => {` por `async function fetchStaff() {` y quita el `;` de su `};` de cierre.

## Paso 6. Documentación

En `docs/modules/frontend.md`, sección de recorridos:

- `` `tourDemoAppt` → merge en `weekAppts` `` pasa a `` `tourDemoAppt` → merge en `visibleAppointments` ``.
- «para que aparezca como `ApptBadge` real» pasa a «para que aparezca como evento real del calendario».

## Verificación

```
rtk proxy node_modules/.bin/eslint src/pages/appointments.jsx src/pages/inventory.jsx src/pages/petDetail.jsx src/pages/staff.jsx
rtk proxy node_modules/.bin/vitest run src/pages/inventory.order.test.jsx src/pages/inventory.receptions.test.jsx src/api/appointments.test.js src/components/SpotlightTour.test.jsx --reporter=dot 2>&1 | tail -15
pnpm run build
```

Lint de esos archivos: 0 errores. Si lint reporta algo nuevo sin uso tras el borrado, elimínalo y decláralo en desviaciones. Recuento total: **18 errores**.

## Cierre

Commit: `refactor(frontend): remove dead agenda view and resolve page hook lint (order 5, F01)`.

En «Para revisar» indica el número de líneas eliminadas de `appointments.jsx` y que el listado de citas vuelve a la página 1 al recargar.
