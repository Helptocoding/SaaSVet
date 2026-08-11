# Modulo: Frontend

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Stack

- React 19 + Vite 8 (JavaScript, sin TypeScript)
- Routing: React Router 7
- Estilos: CSS modules por pagina + variables globales en `tokens.css`
- Toasts: `sonner` (configurado en `App.jsx`)
- Iconos: `lucide-react`
- Auth: Context propio (`src/auth/authContext.jsx`) con JWT + refresh automatico
- HTTP: Axios con interceptores (`src/api/client.js`)
- Confirmaciones: `useConfirm` hook (`src/components/ConfirmDialog.jsx`)
- Calendario: `@fullcalendar/react` (core + daygrid + timegrid + interaction)
- Gráficas: `recharts`
- Date picker: `react-day-picker` 9
- Animaciones: Framer Motion
- Testing: Vitest 4 + React Testing Library + jsdom (`pnpm test`, **gate CI bloqueante**) — ver § Testing

### Tipografía y favicon

- Display/body: **Plus Jakarta Sans** (400/500/600/700)
- Mono (datos clínicos): **IBM Plex Mono** (400/500)
- Login display: **Space Grotesk** (500/600/700)
- Favicon: `iconosaaslyvet.ico`
- Título: `SaaslyVet`

Tokens en `src/styles/tokens.css`: `--font-display`, `--font-body`, `--font-mono`.

## Estructura de directorios

```
src/
├── api/           — funciones de llamada a la API por dominio
├── auth/          — context de autenticacion + login
├── components/    — componentes reutilizables
├── hooks/         — hooks compartidos
├── pages/         — vistas completas por ruta
│   └── medicalRecords/
│       ├── index.jsx            — orquestador de la página
│       ├── PetSidebar.jsx       — sidebar izquierdo: búsqueda de mascota server-side (searchPets + "Ver más"), NO carga la lista completa (ADR p44c)
│       ├── PatientHeader.jsx    — header con datos del paciente + vitales (solo lectura)
│       ├── VitalsEditor.jsx     — editor inline de vitales (ya no se usa en PatientHeader)
│       ├── Timeline.jsx         — lista de consultas agrupadas por año/mes
│       ├── TimelineCard.jsx     — card individual de consulta (expandible)
│       ├── SidePanel.jsx        — panel derecho con summary (3 modos: live/patient/empty)
│       ├── ConsultationForm.jsx — pantalla "Nueva consulta" single-screen (container: estado + API + autosave)
│       ├── ConsultationPatientBanner.jsx — banner de paciente + chips de vitales (mono)
│       ├── EvaluationSection.jsx — sección Evaluación (tipo consulta + motivo + diagnóstico)
│       ├── TreatmentSection.jsx  — sección Tratamiento + medicamentos recetados (no cobran)
│       ├── ChargesSection.jsx    — sección Cargos (productos toggle Insumo|Cobrar + servicios + total MXN en vivo)
│       ├── ConsultationFooter.jsx — footer con indicador de autosave + "Finalizar y enviar a Cobros"
│       ├── VitalsModal.jsx       — modal de captura de signos vitales (mono)
│       └── *.module.css         — estilos modulares (consultationForm.module.css)
├── routes/        — proteccion de rutas privadas
└── utils/         — helpers (apiError, datetime)
```

### Flujo "Atender ahora" → consulta ligada a la cita (ADR p34)

`handleAttendNow` (`pages/appointments.jsx`) **NO** pre-crea el `MedicalRecord`. Solo
transiciona la cita a `in_progress` y navega a la consulta pasando el **PK de la cita
por router state** (`navigate(url, { state: { appointmentId } })`), no por la URL (el
body FK usa PK entero, ADR p18; la URL solo lleva `public_id`).

`medicalRecords/index.jsx` lee `location.state.appointmentId` y lo pasa al
`ConsultationForm` como prop `appointmentId`. El stepper crea el **único** `MedicalRecord`
(lazy, al primer autosave) incluyendo `appointment` en el payload → queda ligado a la cita.
Al finalizar, `close_medical_record` completa la cita (`in_progress → done`, ADR p34).

Reglas:
- `appointmentId` se limpia (`null`) en "+ Nueva Consulta" manual, al editar desde el
  Timeline y al cerrar el stepper. Consulta manual = MR sin cita.
- **NO** reintroducir la pre-creación del MR en `handleAttendNow`: antes creaba un MR
  ligado y el stepper creaba OTRO sin `appointment` → el segundo, al cerrarse, no
  completaba la cita y el primero quedaba huérfano abierto (bug corregido en ADR p34).

### Protocolos clínicos de la consulta (Vacuna) — primer protocolo

`consultation_type` puede activar una **sección clínica especializada** ("protocolo")
dentro de `ConsultationForm`. Primer y único protocolo hoy: **Vacuna**.

```
src/features/consultation/protocols/
├── registry.js            — protocolFor(type) → protocolo | null (general → null)
└── vaccine/
    ├── VaccineSection.jsx  — sección "Vacuna aplicada" (presentacional; SearchSelect de presets)
    ├── vaccineProtocol.js  — contrato { label, Section, initDraft, validate }
    ├── vaccinePresets.js   — catálogo estático extensible (getVaccinePresets/computeNextDue/todayISO)
    └── index.js            — barrel
```

- **Contrato mínimo** `{ label, Section, initDraft, validate }` — sin método de
  persistencia: el `VaccineRecord` lo crea el **backend** al finalizar (ver
  `docs/modules/medical_records.md` §Protocolos). Crece por evidencia (`initDraft` apareció
  por reload-survival). Agregar protocolo = **copiar la carpeta** + 1 entrada en `registry.js`.
  **No** es un motor de schema (cada protocolo es código con su UI/validación).
- **Estado en `ConsultationForm`**: slice `protocolDraft[type]` (sembrado por `initDraft`),
  se persiste como `MedicalRecord.consultation_draft` por el **mismo autosave** (sobrevive
  recarga). **No** se limpia al cambiar `consultation_type` (capturar vacuna → General →
  volver a Vacuna conserva lo capturado). `proto.validate` corre en `handleFinalize`.
- **UI Vacuna**: combobox `SearchSelect` de presets (con "Otra vacuna" para texto libre),
  fecha de aplicación (default hoy), switch "Programar próximo refuerzo", fecha de refuerzo
  auto-calculada con hint "Calculado según protocolo"/"Personalizado" + ayuda contextual,
  y banner histórico no bloqueante (`api/vaccines.js` `getVaccines`, solo lectura).
- Glosario: la sección se titula **"Vacuna aplicada"** (voz clínica), nunca "Plantilla".

## Reglas de UX (no negociables)

### Prevenir doble submit

Todo formulario con llamada a la API usa el patron:

```javascript
const [saving, setSaving] = useState(false);

// validar ANTES de setLoading
if (!field.trim()) { toast.error("Campo requerido"); return; }

setSaving(true);
try {
    await toast.promise(apiCall(payload), {
        loading: "Procesando...",
        success: "Listo",
        error: (err) => apiError(err, "Error inesperado"),
    });
    // reset / refetch
} catch (err) {
} finally {
    setSaving(false);
}
```

Botones durante la operacion:
```jsx
<button disabled={saving}>{saving ? "Guardando..." : "Guardar"}</button>
<button disabled={saving} onClick={onCancel}>Cancelar</button>
```

### Confirmaciones de acciones destructivas

Usar siempre `useConfirm`, nunca `window.confirm`:

```javascript
const confirm = useConfirm();
const ok = await confirm({ message: "¿Eliminar?", confirmText: "Eliminar", dangerMode: true });
if (!ok) return;
```

Tambien se usa para transiciones con peso operativo fuerte aunque no sean destructivas, por ejemplo `in_progress -> done` en citas.

Patron recomendado para transiciones terminales:
- confirmar primero con `useConfirm`
- ejecutar la mutacion
- mantener el contexto abierto si el siguiente paso esperado requiere un CTA inmediato

### Manejo de errores

Todos los `catch` usan `apiError` de `src/utils/apiError.js`:

```javascript
toast.error(apiError(err, "Error inesperado"));
// o en toast.promise:
error: (err) => apiError(err, "Error inesperado")
```

**Nunca loguear el objeto de error crudo de Axios (ADR p47 / H-07·H-08).**
`console.log(err)` / `console.error(err)` exponen `err.config.headers.Authorization`
(= `Bearer <JWT>`) en la consola del navegador; loguear `err.response.data` vuelca
el cuerpo HTTP completo. Para depurar usar siempre `console.error(apiError(err))`
(string sanitizado, nunca toca `config.headers`). **Gate de regresión bloqueante:**
`src/test/noConsoleTokenLeak.test.js` escanea `src/` y falla si reaparece
`console.*(err)` o un `console.*` sobre `…response…data`.

`apiError` extrae el primer mensaje legible en este orden: 429 → detail → error → errors[] → errors{} → message → fallback.

**Shape canónico de errores backend (PR-4B / ADR p16):**
- Validación (400): `{code: 'validation_error', errors: {field: [messages]}}`
- Acceso/permisos (403): `{code: 'permission_denied', message}`
- No encontrado (404): `{code: 'not_found', message}`
- Conflicto de estado/integridad (409): `{code: 'resource_has_dependencies', message, protected_count: int, protected_count_truncated: bool, protected_sample: [{type, id, public_id}]}` (cuando el backend bloquea por FK PROTECT)
- Conflicto de recurso genérico (409): `{code: 'generic_resource_protected', message}` (cuando se intenta borrar Owner/Pet genérico)
- **Precondición de cita vencida (409)**: `{code: 'appointment_changed', message, current: {status, date, start_time}}` (INV-A, ADR p57). La cita cambió desde que se leyó. **No es un error técnico**: la UI recarga la cita, muestra «esta cita cambió mientras la editabas» y deja al usuario decidir. **Nunca** auto-reintentar ni reenviar sin `expected_state`. Hoy el frontend **no** envía `expected_state` (opt-in) — enviarlo es trabajo de F5
- **Cliente ya existente (409)**: `{code: 'owner_exists', message, candidate: {public_id, name}}` (INV-B/INV-C, ADR p57). El teléfono ya tiene expediente y ese camino no puede reutilizarlo. **No es un error técnico.** El **registro rápido de citas** (`create-with-patient`) solo lo produce si envía `require_new_owner` — hoy el frontend **no** lo envía, así que su comportamiento no cambia: sigue reutilizando el expediente del cliente que vuelve. En el **alta de mascota** (`POST /api/pets/`) la UI debe preguntar «¿es este cliente?» con `candidate.name` y, si el usuario confirma, **reenviar en modo referencia** (`{owner_public_id: candidate.public_id}` en vez de `{owner: {name, phone}}`); si no, corregir el teléfono. Al **cambiar un teléfono** significa que ese número ya es de otro cliente: cero escrituras (tampoco los campos de la mascota, si venía por `PATCH /api/pets/`). **Nunca** reintentar el mismo payload
- **Cliente ambiguo (409)**: `{code: 'owner_ambiguous', message, candidate_count: int}` (INV-C, ADR p57). Ese teléfono tiene **dos o más** expedientes y el sistema **no elige**. **No hay candidato en el cuerpo a propósito** — ofrecerlo sería sugerir la elección prohibida. La UI muestra que el dato está por ordenar y no ofrece ninguna acción de «continuar igual»; la salida es corregir los expedientes duplicados desde Clientes
- **Horario ocupado (400)**: `{code: 'slot_taken', message, errors: {error: [message]}}` (INV-D, ADR p57). El veterinario ya tiene una cita activa en ese intervalo, lo detecte el pre-chequeo o lo rechace la restricción de PostgreSQL. Aplica también a la **atención sin cita** y a la **reactivación** de una cita cancelada; la UI ofrece otro horario u otro veterinario. **No existe bandera de forzado**. El cuerpo es un superset del 400 anterior → `apiError` ya lo resuelve por `errors{}` sin cambios
- Endpoint deprecado removido (410): `{code: 'endpoint_sunset', message}` (post-Sunset RFC 8594, e.g. `/api/organizations/<pk>/` post-2026-08-17)
- Demo en reset (503): `{code: 'demo_resetting', message}` + header `Retry-After` (solo **escrituras** de la org demo durante un reset automático; las lecturas pasan — ADR p49). Tenants reales nunca lo reciben.

Frontend debe distinguir por `code` field, no por status code. El handler `apiError` ya extrae `message` correctamente. Para mostrar acción específica (e.g. "este registro tiene 5 mascotas asociadas"), parsear `protected_count` y `protected_sample`.

### Manejo centralizado de errores de formularios

- Utilities:
  - `src/utils/handleFormError.js`: centraliza la lógica para mapear errores DRF a `formErrors` y mostrar toasts globales.
  - `src/utils/mapFieldErrors.js`: normaliza la respuesta de errores DRF a claves planas (soporta colisiones y nested keys).

- Convenciones obligatorias:
  - Todos los formularios POST/PATCH deben usar `handleFormError(err, setFormErrors)` dentro del `catch`.
  - Al abrir un modal con formulario limpiar errores: `setFormErrors({})`.
  - Usar modo merge limpiando las claves a reemplazar antes de fusionar para evitar errores "stale".

Implementación pragmática en CI:
- El script `scripts/check-handle-errors.sh` detecta archivos con `catch(` en `frontend/src` y filtra aquellos que no importan `handleFormError`.
- Mejoras futuras: pasar a análisis AST para evitar falsos positivos (recomendado a mediano plazo).

### IDs en llamadas a la API (ADR p18 — Día 6)

Los modelos con `public_id` exponen UUID en las URLs del backend. Usar siempre `item.public_id` en las llamadas, nunca `item.id`:

```javascript
// Correcto
getInvoice(invoice.public_id)
confirmInvoice(selectedInvoice.public_id)

// Incorrecto — falla con ALLOW_LEGACY_ID_LOOKUP=False
getInvoice(invoice.id)
```

**Modelos con `public_id` en el frontend (12):** `Invoice`, `Pet`, `Owner`, `Appointment`, `MedicalRecord`, `Prescription`, `Product`, `Presentation`, `Service`, **`VaccineRecord`** (Día 6), **`User`** (Día 6), **`Organization`** (Día 6).

El campo `id` (entero) puede usarse para display (ej. "Cobro #123") y para React keys locales pero **no** como argumento de URL en la API.

### FKs embebidos — usar `*_public_id`

Los serializers backend exponen `<fk>_public_id` para FKs a modelos públicos. Frontend debe consumirlo para deep links y query params:

```javascript
// MedicalRecord embebido: pet_public_id disponible
navigate(`/medical-records?pet=${record.pet_public_id}`);   // ✓
navigate(`/medical-records?pet=${record.pet}`);             // ✗ es PK

// Appointment embebido: medical_record_public_ids array UUID
navigate(`/medical-records?record=${appt.medical_record_public_ids[0]}`);
```

Lista de FKs embebidos disponibles (incompleta — ver serializers backend):
- `MedicalRecordSerializer`: `pet_public_id`, `appointment_public_id`, `prescription_public_id`, `invoice_public_id`
- `AppointmentSerializer`: `pet_public_id`, `owner_public_id`, `veterinarian_public_id`, `medical_record_public_ids`, `invoice_public_id`
- `InvoiceSerializer`: `pet_public_id`, `owner_public_id`, `appointment_public_id`, `medical_record_public_id`
- `PrescriptionSerializer`: `pet_public_id`, `medical_record_public_id` + metadatos
  read-only de la mascota `pet_species`/`pet_sex`/`pet_birth_date` (para que la
  página de Recetas filtre sin cargar el catálogo completo de mascotas — ADR p44b)
- `VaccineRecordSerializer`: `pet_public_id`, `applied_by_public_id`, `medical_record_public_id`
- `MeView` response: `organization_public_id`

### Body FK fields — siguen PK entero

ADR p18 distingue claramente:

- **URL paths y query params** → `public_id` (UUID).
- **Body FK fields** (POST/PATCH JSON) → PK entero (`PrimaryKeyRelatedField`).

```javascript
// Correcto: body field con PK
await createAppointment(token, {
  pet: petItem.id,             // ← PK (SearchSelect)
  veterinarian: vetId,         // ← PK
});

// Correcto: deep link / URL con UUID
navigate(`/pets/${pet.public_id}`);
```

PatientSearchSelect entrega `item.id` = PK consistente. NO usar `parseInt(petId)` (fail-fast vía NaN si contrato cambia).

### Anti-patterns prohibidos (grep gate CI bloqueante)

```bash
! grep -rnE "\.public_id\s*\|\|\s*\w+\.id" frontend/src/
```

Patrones cero matches:
1. `editing.public_id || editing.id` — dual-lookup spaghetti.
2. `navigate(`/foo/${x.id}`)` para modelo público — debe usar `${x.public_id}`.
3. `?pet=${x.id}` con `x.id` = PK — debe ser `x.public_id`.

### Filtros con varias claves por evento — un solo setState

Un handler que actualiza **varias** claves de filtro a la vez (ej. DateRangePicker
→ `created_from` + `created_to`) debe hacerlo en UN solo `setState` con patch:

```javascript
// Correcto — un solo update por evento
const updateFilters = (patch) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    /* sync de searchParams con `next` */
};
onChange={(f, t) => updateFilters({ created_from: f, created_to: t })}

// Incorrecto — la 2a llamada lee `filters` stale y PISA a la 1a (React batchea)
onChange={(f, t) => { updateFilter("created_from", f); updateFilter("created_to", t); }}
```

Bug real de Cobros (el rango de fechas nunca llegaba completo al request),
corregido en `42836f3`. Aplica a cualquier página con filtros multi-clave.

### Refetch despues de mutaciones

Despues de crear, editar o eliminar, siempre refrescar la lista local:

```javascript
await createItem(payload);
await loadItems();   // no asumir que el estado local refleja la DB
```

### PATCH en lugar de PUT para actualizaciones parciales

**Convención**: Todos los endpoints de actualización usan `PATCH`, no `PUT`.

```javascript
// api/medicalRecords.js
export const updateMedicalRecord = async (token, id, data) => {
    const res = await api.patch(`medical-records/${id}/`, data);  // ← PATCH, no PUT
    return res.data;
};
```

**Razones**:
1. **Semántica HTTP**: `PUT` = reemplazo completo, `PATCH` = actualización parcial
2. **Seguridad multi-tenant**: `organization` es `read_only` en el backend — nunca debe venir del cliente
3. **Robustez**: Si se agrega un campo requerido al serializer, `PATCH` no se rompe (solo los campos enviados se validan)

**Archivos que siguen esta convención**:
- `api/medicalRecords.js` — `updateMedicalRecord`
- `api/pets.js` — `updatePet`
- `api/inventory.js` — `updateProduct`
- `api/prescriptions.js` — `updatePrescription`
- `api/billing.js` — `updateService`
- `api/appointments.js` — `updateAppointment`

## Infraestructura de API

### client.js

- Base URL desde `VITE_API_URL`
- Interceptor request: inyecta `Authorization: Bearer <token>` leyendo vía `tokenStorage.getItem("access_token")` (NO `localStorage` raw — ver `auth/tokenStorage.js`)
- Interceptor request: inyecta `X-Request-ID` (uuid por request vía `utils/requestId.js`) si el caller no lo seteó — correlación end-to-end P1-5 A1 (el backend lo reusa en logs/Sentry/respuesta). No pisar un id ya provisto.
- Interceptor response 401:
  - **Bypassa redirect** si el request fallido es el endpoint de login (`url` termina en `token/`). Sin esto, credenciales malas disparaban full page reload antes de que el toast del login se renderizara. Helper local `isLoginAttempt(config)`. Ver ADR p22.
  - Para 401 en cualquier otro endpoint: `clearTokens()` (vía `tokenStorage`) + `window.location.href = "/login"` (sesión expirada legítima).
- Interceptor response 500+: alert global "Error del servidor".

### Observabilidad de errores (P1-5 Fase A)

> Runbook operativo completo: [`docs/runbooks/observability.md`](../runbooks/observability.md).

- **`ErrorBoundary`** (`components/ErrorBoundary.jsx`) reporta a Sentry: en
  `componentDidCatch` llama `Sentry.captureException(error, {contexts:{react:{componentStack}}})`,
  guarda el `event_id` y lo muestra en el fallback ("Código de error: … compártelo
  con soporte"). Ya no solo evita la pantalla blanca — el crash es visible para ops.
  Envuelve root + cada ruta (`App.jsx`). Si Sentry no está inicializado (sin DSN), el
  `event_id` no se muestra (degradación silenciosa).
- **`Sentry.init`** (`main.jsx`): `environment` (`VITE_SENTRY_ENVIRONMENT`),
  `release` (`VITE_SENTRY_RELEASE`) y `beforeSend = scrubEvent` (`utils/sentryScrub.js`).
- **Privacidad** (`utils/sentryScrub.js`, espejo del backend): dropea `request.data`/
  `cookies`, filtra headers sensibles (`Authorization`, `Cookie`, `X-Idempotency-Key`,
  `X-CSRFToken`, `X-Api-Key`) y strip de PII del `user`. **Nunca** enviar PII
  clínica/financiera a Sentry.
- **Source maps**: `vite.config.js` emite `sourcemap: 'hidden'` y `@sentry/vite-plugin`
  los sube solo con credenciales de upload (CI), luego los borra; el Dockerfile borra
  los `.map` como safeguard. Sin minified stack traces en beta.

### Paginación de listas (ADR p42)

La paginación backend es **opt-in por endpoint** (NO global). Algunos listados
devuelven array crudo `[...]`, otros el envelope DRF `{count, next, previous, results}`.

**Regla**: todo consumidor de un endpoint de lista normaliza con
`utils/toList.js`:

```javascript
import { toList } from "../utils/toList";
const data = await getInvoices(params);
setInvoices(toList(data));   // array y {results} ambos → array; null/undefined → []
```

`toList()` es idempotente sobre arrays → seguro aplicarlo aunque el endpoint aún
no pagine (defensivo ante el rollout incremental).

Endpoints **paginados** hoy (consumir `count`/`next` de la respuesta cruda si se
necesita metadata):

| Endpoint | api/ | Forma |
|---|---|---|
| `GET /billing/invoices/` | `getInvoices` | PageNumber 25 + `?ordering=created_at\|total` server-side |
| `GET /inventory/movements/` | `getMovements` | Cursor (`next`/`previous`, **sin** `count`) |
| `GET /owners/` (sin `search`) | `getOwners` | PageNumber 25 |
| `GET /pets/` (con `?page`) | `getPets` | PageNumber 25/50/100, **opt-in por `?page`** + filtros server-side (ADR p44) |

**`?search` NO pagina** (Owners): `getOwners({search})` y los demás endpoints de
búsqueda que alimentan `SearchSelect` siguen devolviendo array plano `[:20]`. Los
dropdowns con `.then(ps => ps.map(...))` NO se rompen.

**Pets — paginación opt-in por `?page` (ADR p44)**: la página Mascotas llama
`getPets({page, page_size, search, species, sex, age})` → envelope. **Sin `?page`**
(dropdowns SearchSelect de citas/recetas/POS, y `getPets()` de prescriptions/
medicalRecords) sigue devolviendo array plano (`[:20]` con filtro, completo sin
filtro). NO mandar `?page` desde un dropdown. Stat-cards de Mascotas vienen de
`getPetStats()` (`GET /pets/stats/`, conteos de toda la clínica), no del length
local; el contador de citas de la semana reusa `getStatusBreakdown` (conteo, sin
traer filas). Esto **supera** la entrada "Pets sin paginar" de DD-013.

Sin paginar (lista completa, filtro/KPI client-side — DD-013): Products,
Prescriptions, Appointments. No asumir que pasarán a paginado sin antes
mover sus filtros a server-side.

**Paginador UI**: `components/Pagination.jsx` (Anterior/Siguiente). El sort de una
tabla paginada va **server-side** vía `?ordering` (no client-side `useMemo`), o
solo ordenaría la página actual.

### Descarga de PDFs (consulta / receta / cobro)

Patrón único en `api/{medicalRecords,prescriptions,billing}.js` + `utils/downloadBlob.js`:

```javascript
const { blob, contentDisposition } = await downloadXxxPDF(publicId); // responseType: "blob"
const filename = extractFilename(contentDisposition, "consulta.pdf"); // fallback genérico
triggerDownload(blob, filename);
```

- El backend arma el nombre identificable (`tipo_id_mascota_YYYY-MM-DD.pdf`, ADR p36);
  el fallback del frontend es solo red de seguridad.
- **Dependencia de infra**: `extractFilename` solo funciona porque el backend expone
  `CORS_EXPOSE_HEADERS=['content-disposition']`. Si las descargas vuelven a salir como
  "consulta (1).pdf", revisar ese setting antes que este código.
- Handler estándar: `downloadingId` state para deshabilitar el botón + `apiError` en catch.

### authContext.jsx

Autenticación basada en JWT con refresh automático. El flujo de inicialización sigue una **máquina de estados determinista** que evita montar rutas protegidas con tokens vencidos.

**Máquina de estados de inicialización:**

```
UNKNOWN            no access_token en storage        → LOGIN
UNKNOWN            access_token válido (exp > now)   → FETCH_USER
UNKNOWN            access_token expirado             → RESTORING_SESSION
RESTORING_SESSION  refresh ok                        → FETCH_USER
RESTORING_SESSION  refresh fail / no refresh token   → LOGIN
FETCH_USER         /me/ ok                           → AUTHENTICATED
FETCH_USER         /me/ fail                         → LOGIN
```

**Invariante crítico:** `initializing` permanece `true` durante toda la cadena `RESTORING_SESSION → FETCH_USER`. Solo se vuelve `false` al alcanzar un estado terminal (`LOGIN` o `AUTHENTICATED`). `PrivateRoute` espera `initializing=false` antes de evaluar `isAuthenticated`.

**Estados:**

- **LOGIN** — sin sesión válida. Tokens limpiados, React state vacío. `PrivateRoute` redirige a `/login`.
- **FETCH_USER** — token válido en storage. Se setea en React state, se programa el refresh periódico, y se valida con `GET /api/me/`. Si `/me/` rechaza → `LOGIN`.
- **RESTORING_SESSION** — token expirado, refresh token disponible. **NO se setea el token expirado en React state.** Se ejecuta secuencialmente:
  1. `POST /api/token/refresh/` con el refresh token almacenado.
  2. Si falla → `LOGIN` con limpieza de storage.
  3. Si ok → se persisten ambos tokens nuevos (`applyTokensAndScheduleRefresh`), se programa el refresh periódico, y se valida con `GET /api/me/`.
  4. Si `/me/` ok → `AUTHENTICATED`.
  5. Si `/me/` rechaza → `LOGIN` (no se usa user cache).

**`applyTokensAndScheduleRefresh(access, refresh, remember)`** — función privada compartida que persiste tokens, actualiza React state y programa el siguiente refresh. La usan tanto `login()` como el flujo de `RESTORING_SESSION`, eliminando código duplicado.

**`refreshUser()`** — re-lee `GET /me/` con el access token vigente y refresca `user` + `permissions` en React state (devuelve el user fresco o `null`). Necesario cuando un flag del usuario cambió **server-side** pero el token que ya tenía el cliente no lo reflejaba. Caso canónico: **cambio de contraseña temporal obligatoria**. `changePassword` devuelve solo `{access, refresh}`; `login()` intercambia tokens pero **no** refetcha `/me/`, así que `user.must_change_password` seguía en `true` en React state → el `MustChangePasswordGate` rebotaba a `/change-password` en un loop (el usuario tenía que cerrar sesión y re-loguear). `ChangePasswordForm`, tras `login()`, llama `await refreshUser()` para sincronizar el flag; si el cambio era el **obligatorio** (`user.must_change_password` capturado antes del submit) y el flag ya quedó limpio, navega a `/` → **Login → cambio obligatorio → Dashboard → Onboarding, sin re-login**.

**Restauración de sesión tras cerrar/reabrir el navegador:**
- `remember` se reconstruye del flag explícito `auth_persist` (escrito por `setTokens()` durante el login), no inferido del store.
- Si el flag no existe (legacy), default `true` (localStorage) por compatibilidad hacia atrás.
- La secuencia `refresh → /me/` es **secuencial**, no concurrente. Esto elimina la condición de carrera donde `/me/` con token expirado completaba antes que el refresh, causando que el dashboard montara con un access token inválido y el interceptor 401 destruyera la sesión.

**Refresh periódico** (sesión ya autenticada):
- Decodifica el JWT para leer `exp` y programa refresh 5 min antes de expirar.
- El callback del timer usa `fetch()` nativo (no axios) para evitar el interceptor 401.
- Chequea `isLoggingOut()` antes de aplicar tokens — previene revival de sesión recién terminada (race logout/refresh). Ver ADR p22.

**Control de acceso:**
- `permissions` como `Set` (desde el array retornado por `/api/me/`).
- Helpers memoizados: `can(permCode)`, `canAny(codes)`, `canAll(codes)`.
- `Object.freeze` sobre el `Set` para prevenir mutaciones accidentales.
- **Regla**: nunca inferir permisos por `user.role`. Usar exclusivamente `can()`.

### Auth storage (`tokenStorage.js`) — ADR p22

Módulo único que centraliza acceso a auth storage. **Todo acceso a `access_token`, `refresh_token`, `user` en el frontend DEBE pasar por este módulo.**

**Invariantes (ver docstring del módulo):**

1. **No coexistencia**: tokens válidos NUNCA en `localStorage` y `sessionStorage` simultáneamente. `setTokens()` enforce wipe del other store.
2. **Read priority**: `sessionStorage > localStorage`. Sesión temporal de tab gana sobre persistente vieja.
3. **Source of truth**: presencia del `access_token` en algún store. El `auth_persist` flag registra la decisión explícita del checkbox "Recordarme" y se usa para reconstruir `remember` durante la restauración de sesión (`getItem("auth_persist") !== "0"`). No se infiere el store activo de la presencia física de los tokens en localStorage/sessionStorage — el flag es la fuente autoritativa de esa decisión.
4. **Logout flag**: `clearTokens()` levanta `loggingOut=true`; `setTokens()` lo limpia. Async callbacks (refresh) chequean `isLoggingOut()` antes de mutar estado.

**API:**
- `getItem(key)` — lectura con prioridad session > local.
- `setTokens({ access, refresh, remember })` — escribe ambos tokens al store correcto + wipea el otro + escribe flag `auth_persist`.
- `setAccessToken(access)` — actualiza solo el access token en el `activeStore()` actual. Usado por el refresh periódico.
- `setRefreshToken(refresh)` — actualiza solo el refresh token en el `activeStore()` actual. Usado por el refresh periódico para persistir el token rotado (el backend emite un refresh nuevo con `ROTATE_REFRESH_TOKENS=True`; sin esta función el token viejo blacklisteado seguía en storage y el siguiente refresh fallaba con 401).
- `setUser(user)` — actualiza user data en el `activeStore()` actual.
- `clearTokens()` — borra ambos stores + levanta flag de logout.
- `isLoggingOut()` — predicado para async guard.

**"Recordarme" del login:**

| `remember` | Store | Vida útil |
|---|---|---|
| `true` (default) | `localStorage` | Persiste hasta logout o expiración. Sobrevive cerrar browser. |
| `false` | `sessionStorage` | Muere al cerrar tab. No comparte sesión entre tabs (per-tab por diseño). |

**Anti-patterns prohibidos:**
- ❌ `localStorage.getItem("access_token"|"refresh_token"|"user")` fuera de `tokenStorage.js`.
- ❌ Leer `PERSIST_FLAG` para decisiones de routing — solo se lee durante la restauración de sesión vía `getItem("auth_persist")` para reconstruir `remember`.
- ❌ Bypass de `isLoggingOut()` en callbacks async que mutan estado de auth.

Grep gate sugerido (post-beta, vía ESLint custom rule): bloquear `(localStorage|sessionStorage)\.(getItem|setItem|removeItem)\(['"](access_token|refresh_token|user|auth_persist)` en archivos != `auth/tokenStorage.js`.

## Componentes compartidos

### DateField (selector de fecha — calendario con selects mes/año)

`components/DateField.jsx` — **fuente única** de captura de fechas. Reemplaza los
`<input type="date">` nativos por un calendario `react-day-picker` con navegación
por **selects de mes y año** (estilo OriginUI) + locale `es`. Un solo look en toda
la app; el año se elige con dropdown (clave para fecha de nacimiento).

- Contrato: `value`/`onChange` en **string ISO `"YYYY-MM-DD"`** (`""` al limpiar).
  `min`/`max` (ISO | `Date`) limitan días seleccionables y el rango de años.
  `disabled`, `placeholder`, `clearable` (botón ×, para fechas opcionales),
  `inputClassName` (para reusar el estilo del control del contenedor, p.ej.
  `styles.control` en las secciones de consulta), `id`, `className`.
- **Popover en portal** (`createPortal` → `document.body`) con `position: fixed`:
  no lo recorta el scroll del riel de consulta ni un modal. Se reubica en
  scroll/resize (listener con `capture`) y hace **flip** hacia arriba si no cabe
  abajo. z-index 1100 (sobre modales).
- Internamente reusa `styles/day-picker.css` (tokens) + `react-day-picker/style.css`.
  **No** duplicar el import de esos CSS en las páginas — viven en `DateField`.

Consumidores: **Mascotas** (fecha de nacimiento, `max=hoy`), y las **fechas de
consulta**: Vacuna (aplicación `max=hoy`; refuerzo `min=aplicación`, clearable),
Cirugía (retiro de puntos), General (próxima revisión), Urgencia (revaloración).
**No** volver a poner `<input type="date">` para fechas de negocio — usar DateField.
Fuera de alcance (siguen nativos por ahora): fecha de cita (agenda), caducidad de
lote (Entrada de stock), DOB de QuickPatientForm, y el date-range de Cobros
(`DateRangePicker`, impl vanilla aparte).

### EmptyState (estado vacío accionable)

`components/EmptyState.jsx` — **fuente única** de estados vacíos guiados. Reemplaza
los `.empty-state` pasivos por uno que responde: qué pasa (`title`), por qué +
siguiente paso (`body`) y la acción (`actions`). **Presentacional puro: NO conoce
RBAC, NO usa `useAuth`.** El caller arma las acciones ya filtradas por permiso
(`can("x") ? action : null`) y las pasa; el componente solo descarta las nulas →
nunca muestra un CTA roto.

Props: `icon` (componente de icono, opcional), `title` (req), `body` (opcional),
`actions` (array de `{ label, onClick, variant }` | `null`), `compact` (padding
reducido). Las acciones usan `onClick` (el caller reusa su handler existente: abrir
modal/wizard o `navigate`) — router-agnóstico.

Aplicado en: **Mascotas** (Importar Excel `import.create` + Agregar paciente
`patient.create`), **Agenda** (empty complementario sobre el calendario, no lo
reemplaza; "Registrar atención sin cita" `appointment.create_walkin`),
**Inventario** (`inventory.create`), **Config·Servicios** (`service.create`).
**NO** crear empty states por página — usar este componente. Estilos:
`.empty-state*` en `global.css` (`.empty-state-icon`, `.empty-state-actions`,
`.empty-state-compact`).

### SearchSelect

Combobox con busqueda asincrona. Debounce de 250ms. Maneja race conditions con `reqId`. Props clave: `value`, `onChange`, `onSearch`, `disabled`, `prefetchOnFocus`. Devuelve un array y muestra **solo `item.label`** (string). Úsalo para selects simples y de bajo volumen; para entidades relacionales con muchos registros usa **EntitySearch**.

### EntitySearch (combobox relacional — ADR p44b)

`components/EntitySearch.jsx` — combobox para entidades con miles de registros
(clínicas importadas). Reusa el patrón de `SearchSelect` (debounce 250ms, race
con `reqId`, loading) pero resuelve sus dos límites:

- **Render rico** (`renderItem(item) → JSX`): cada opción muestra contexto para
  diferenciar homónimos (dueño · teléfono · expediente), no solo el nombre.
- **Paginación incremental** (`fetchPage({query,page}) → {items, hasMore}` +
  botón "Ver más"): inicial 8, carga más bajo demanda. **Sin tope invisible**
  (el viejo `maxSuggestions=5` ocultaba coincidencias).

Props: `value` (objeto seleccionado | null), `onChange(item)`, `fetchPage`,
`renderItem`, `getOptionLabel(item)` (texto del input tras elegir), `placeholder`,
`disabled`, `prefetchOnFocus`.

**No rearmar el fetch/label por módulo.** Usar las piezas compartidas:
- `api/lookups.js`: `searchPets({query,page,pageSize,ownerPublicId})` y
  `searchOwners({query,page,pageSize})` → `{items, hasMore}` sobre los endpoints
  paginados (`?page` → envelope; `next` → hay más).
- `components/lookupOptions.jsx`: `renderPetOption`/`renderOwnerOption` +
  `petOptionLabel`/`ownerOptionLabel`.

Consumidores: selectores de mascota de **Citas** (`appointments.jsx`),
**Recetas** (`PrescriptionForm`), **POS** (`CustomerSelector`, también cliente).
El **historial clínico** (`PetSidebar`) usa el mismo `searchPets` pero como lista
inline (no dropdown). El `value` pasa a ser el **objeto completo** de la entidad
(trae `id` PK para el body + `public_id`).

> `PrescriptionForm` combina **EntitySearch** (picker de mascota, server-side) con
> **SearchSelect** (picker de medicamento). No quitar `import SearchSelect`: el
> picker de medicamento lo necesita (la regresión ff68196 lo borró → crash; ver
> ADR p44b addendum).

**Recetas (página) NO carga la lista completa de mascotas** (ADR p44b addendum):
los filtros especie/sexo/edad leen los metadatos embebidos en cada receta
(`pet_species`/`pet_sex`/`pet_birth_date`, ver lista de FKs embebidos) y el
selector "Todas las mascotas" se **deriva** de las recetas cargadas (solo las que
tienen receta), con filtro por mascota client-side. La lista de recetas en sí
sigue sin paginar (deuda P1 — DD-013).

### ConfirmDialog / useConfirm

Modal de confirmacion. `dangerMode: true` pone el boton de confirmacion en rojo. Retorna `Promise<boolean>`.

### QuickPatientForm

Form embebido para crear paciente anonimo dentro del flujo de citas walk-in o nueva cita. No valida internamente; la validacion la hace el componente padre.

### PrescriptionForm

Formulario de receta reutilizable. Acepta `lockedPet` y `lockedMedicalRecord` para bloquear campos cuando viene desde el flujo de historial clinico.

### SortHeader (orden de columnas en tabla global)

`components/SortHeader.jsx` — encabezado ordenable para la tabla canon
(`.table-wrap` + `.table`); estilos `th-sortable`/`th-inner`/`sort-arrow` en
`global.css`. Accesible: `tabIndex`, Enter/Espacio y `aria-sort`. Props:
`col`, `label`, `sortCol`, `sortDir`, `onSort`, `align`. Usado en Cobros
(Fecha/Total). **Desde ADR p42 el sort de Cobros es server-side**: `onSort`
actualiza `(sortCol, sortDir)` → `?ordering` y refetcha (la tabla pagina; ordenar
client-side solo ordenaría la página actual). **No crear sorting por módulo**
(design-system.md §5). Deuda contenida: Inventario conserva su SortHeader local
(module CSS) — migrar junto con la unificación de su tabla, no piecemeal.

### Pagination (paginador Anterior/Siguiente) — ADR p42

`components/Pagination.jsx` — paginador reusable para tablas paginadas
server-side. Props: `page` (1-based), `count` (total del backend), `pageSize`
(default 25), `onPage(nextPage)`, `fetching`. No se renderiza si
`count <= pageSize`. **No crear paginadores por módulo.** Cobros lo monta bajo la
tabla; al cambiar filtro o sort se resetea `page` a 1. Ver § Paginación de listas.

### CajaBar (estado del turno de caja) — ADR p28

`components/CajaBar.jsx` — dos variantes:

- `variant="full"` (default): fila completa — header de `/cash`.
- `variant="compact"`: chip badge + acciones `btn-xs` — vive en el `page-header`
  de `/billing` (la fila completa duplicaba la alerta de caja requerida).

Props: `onSession(session|null)` notifica **cada** cambio de sesión conocido
(carga inicial, abrir, cerrar) — el padre consume el estado sin duplicar el GET
de sesión actual (Cobros ya NO llama `getCurrentSession` por su cuenta).
`onChange` se conserva para refrescos post abrir/cerrar (lista de `/cash`).
Ambas variantes comparten los modales de abrir/cerrar.

### StatusBadge (estados de cita) — ADR p35

`components/StatusBadge.jsx` + `utils/appointmentStatus.js` = **fuente única visual de estados de cita**. Antes los mapas `STATUS_LABELS`/`STATUS_BADGE` estaban duplicados por componente (timeline, modal, etc.). `appointmentStatus.js` exporta `APPT_STATUS_LABEL`, `APPT_STATUS_BADGE`, `statusLabel()`, `statusBadgeClass()`.

```jsx
<StatusBadge status={appt.status} />   // → <span class="badge badge-info">Programada</span>
```

Mapeo (no crear enums ni clases nuevas):

| status | label | clase |
|---|---|---|
| `scheduled` | Programada | `badge-info` |
| `confirmed` | Confirmada | `badge-purple` |
| `in_progress` | En consulta | `badge-warning` |
| `done` | Completada | `badge-success` |
| `canceled` | Cancelada | `badge-danger` |
| `no_show` | No se presentó | `badge-default` (unificado; antes el modal usaba `badge-secondary`) |

Migrados a `StatusBadge`: `TodayAgendaList`, `AppointmentQuickModal`. NO migrados aún (deuda contenida, no piecemeal): `billing`, `cash`, `petDetail`, `appointments`, `AppointmentBreakdown`.

### AppointmentQuickModal (acciones rápidas de cita) — ADR p35

`components/dashboard/AppointmentQuickModal.jsx` = **única fuente de acciones rápidas de cita**. Consume el detalle (`GET appointments/<public_id>/`), reusa `useConfirm` para destructivas y dispara `dashboard:refresh` tras cada acción. Acciones por estado (reusan handlers existentes; sin duplicar permisos/estado/nav):

| status | acciones |
|---|---|
| `scheduled` | Confirmar · ▶ Atender ahora · No asistió · Reprogramar · Cancelar |
| `confirmed` | ▶ Atender ahora · No asistió · Reprogramar · Cancelar |
| `in_progress` | Continuar consulta |
| `done` | Ver expediente |
| `canceled` / `no_show` | (solo) Ver más detalles |

"Ver más detalles" siempre disponible. Cualquier lista de citas (agenda, citas por resolver) abre **este** modal — no crear modales nuevos ni acciones inline.

## Toaster

Configurado en `App.jsx`:
```jsx
<Toaster richColors position="top-right" toastOptions={{ duration: 4000 }} visibleToasts={3} />
```

Usar `toast.promise` para operaciones asincronas con feedback de progreso.
Usar `toast.error(apiError(err, fallback))` en catch blocks.

**Gotcha (sonner v2): `toast.promise(p)` NO resuelve a la data de `p`.** Devuelve un
objeto interno del toast, no el valor de la promesa. Nunca hacer
`const data = await toast.promise(req, {...})` y usar `data` — quedará sin las
propiedades reales (causó crash `selectedInvoice.items.map` y un `getInvoice(undefined)`
→ 404 en Cobros). Patrón correcto: disparar el toast y await la promesa original:
```jsx
const req = miApiCall();           // la promesa real
toast.promise(req, { loading, success, error });
const data = await req;            // <- await la promesa, no el retorno de toast.promise
usar(data);
```
Si solo se necesita feedback (sin usar la data), `await toast.promise(...)` sin
capturar el retorno es aceptable.

## Inventario — wizard de alta de producto (ADR p33)

`frontend/src/pages/inventory.jsx`  
Tutorial y animación: `frontend/src/features/inventory/tutorial/`

### Selector de modo

Al abrir "Nuevo producto", se muestra una pantalla de selección antes del formulario:

| Opción | `wizardMode` | `divides` | Descripción |
|---|---|---|---|
| Producto normal | `"simple"` | `false` | Shampoo, collar, alimento — una sola forma de venta |
| Varias formas de venta | `"multi"` | `true` | Caja de jeringas → también vendo por pieza |

`switchMode()` resetea todo el estado del wizard y vuelve al selector.

### Estado del wizard

```javascript
// Producto
wizardProduct = { name, internal_code, description, category, requires_prescription, min_stock }
// Modo y stock
wizardMode      // null | "simple" | "multi"
divides         // false (simple) | true (multi)
countQty        // stock inicial (string)
countUnit       // unidad base ("piece", "ml", "kg"…)
dividesCount    // cuántas partes tiene cada unidad — solo multi
dividesUnit     // unidad de la parte — solo multi
// Presentaciones
salesPres = [{ _localId, publicId, name, conversion_factor, sale_price, purchase_price, barcode }]
// UI
showDetails     // boolean — accordion descripción/receta
wizardEditing   // null = crear, product = editar
showMultiAnim   // boolean — animación educativa modo multi
```

### Modo multi — auto-sync de salesPres[1]

Al seleccionar modo multi, `salesPres` se inicializa con 2 entradas. Los campos de `salesPres[1]` se auto-rellenan mientras el usuario no los haya editado manualmente:

- `salesPres[1].name` ← label de `countUnit` (ej. "Pieza")
- `salesPres[1].conversion_factor` ← valor de `dividesCount`

El tracking de edición manual usa `presSecondAutoRef = useRef({ nameEdited, cfEdited })` (ref, no state — no provoca re-renders). Una vez que el usuario edita un campo, el auto-sync para ese campo se desactiva.

```javascript
// En updateSalesPres:
if (idx === 1 && field === "name") presSecondAutoRef.current.nameEdited = true;
if (idx === 1 && field === "conversion_factor") presSecondAutoRef.current.cfEdited = true;
```

### Flujo de guardado

1. `handleSubmit()` valida: `name` requerido, `sale_price > 0` por presentación, `dividesCount ≥ 1` si multi
2. `handleWizardSave()` → `POST /inventory/products/` + `POST /inventory/products/<pk>/presentations/` para adicionales
3. Producto siempre se crea con `stock: 0` — existencia inicial se registra vía Ajuste de inventario

Para edición: "Guardar cambios" → `handleWizardSave()` directo.

### Exit confirmation

`requestCloseWizard()` usa `useConfirm` si hay datos sin guardar.

### Tutorial interactivo

`frontend/src/features/inventory/tutorial/`

| Archivo | Rol |
|---|---|
| `productTourSteps.js` | 6 pasos del tour con `target` (selector CSS) + texto |
| `useProductTour.js` | Hook — orquesta auto-llenado sincronizado con `waitForNext()` |
| `ProductCreationTour.jsx` | Overlay: spotlight + popover posicionado fuera del modal |
| `MultiPresentationAnimation.jsx` | Animación 5 escenas (Framer Motion) — explica modo multi |
| `AnimationSvgs.jsx` | SVG components inline (fuente: `frontend/src/assets/svgs/`) |

**Posicionamiento del popover:** `getPopoverPos` busca `.modal.modal-md` en el DOM y coloca el popover a su derecha (o izquierda si no hay espacio). El spotlight sigue apuntando al elemento dentro del formulario.

**Gate de animación:** `localStorage.getItem("multi_presentation_animation_seen")` — se muestra una sola vez por dispositivo.

### `api/inventory.js` — funciones disponibles

```javascript
getProducts()                              // lista con presentations[]
createProduct(data)                        // data.presentation_input requerido
updateProduct(publicId, data)              // PATCH — stock inmutable via esta ruta
createPresentation(productPublicId, data)  // POST /products/<pk>/presentations/
updatePresentation(presPublicId, data)     // PATCH /presentations/<pk>/
adjustStock(productPublicId, data)         // POST /products/<pk>/adjust/
getUnitChoices()                           // catálogo de unidades base
```

## Dashboard (composición y reglas)

`frontend/src/pages/dashboard/index.jsx` + `frontend/src/components/dashboard/`

### Fuentes de datos

| Zona | Hook | Endpoint | Naturaleza |
|---|---|---|---|
| KPIs, sidebar (Ahora/backlog/stock) | `useDashboardSummary` | `GET /api/v1/dashboard/summary/` | Live, cache 30s, polling 30s |
| **Activación primer uso (`FirstRunAssistant`)** | `useActivationContext` (`ActivationProvider` en `Root`) | `GET /api/v1/dashboard/activation/` | Read-only, **existencia real** (sin flags), refetch en mount + `dashboard:refresh` + `refetch()` bajo demanda (sin polling) |
| **Agenda del día (`TodayAgendaList`)** | `useDayAppointments` | `GET /appointments/?date=YYYY-MM-DD` | Live, refetch al cambiar día + evento `dashboard:refresh` (ADR p35) |
| Spark + Δ de ingresos (admin) | `useFinancialSeries` | `financial/series/` | Snapshot + hoy live |
| Card "Analítica" | `useDashboardSeries` + `useFinancialSeries` | `operations/series/` + `financial/series/` | Snapshot + hoy live |
| Card "Citas por resolver" | `useAppointmentsByStatus` | `GET /appointments/status-breakdown/?from=&to=` | Live, rango |

`summary` solo expone datos **point-in-time de HOY**. No es fuente de reporting (ver `dashboard-metrics-contract.md`).

> **Agenda ya NO consume `summary.timeline`** (ADR p35). Antes la "Agenda de hoy" era un timeline horizontal alimentado por `summary.timeline` (fijo a hoy). Ahora es una mini-agenda con navegación por día vía `appointments/?date=` — el día puede ser pasado/hoy/futuro. `summary.timeline` sigue existiendo en el payload (alias legacy `appointment` + `appointments[]` con `species`/`breed`) pero el dashboard ya no lo usa; `OperationalTimeline.jsx` quedó retirado (no montado, no borrado).

### Composición

Sidebar (orden = urgencia): **Ahora** → **Citas por resolver** → **Pendientes clínicos** → **Stock crítico**.

Columna principal: **KPIs** → **Agenda del día** (`TodayAgendaList`) → **Analítica**.
Mientras la activación esté incompleta, **`FirstRunAssistant`** se monta como
**overlay full-screen** por encima de todo (no es un ítem de la columna).

### FirstRunAssistant (experiencia de primer uso)

`components/dashboard/FirstRunAssistant.jsx` — reemplaza al viejo `SetupChecklist`
(checklist de 4 cajas apiladas, **retirado**; antes había reemplazado a
`EmptyDashboard`). Experiencia de **primer uso** estilo Linear/Notion/Stripe: guía con
**un solo paso a la vez**, jerarquía tipográfica (sin cajas/bordes), mucho blanco.

- **Completado = READINESS, no "ya usó el sistema"**: el onboarding mide si la clínica
  quedó **lista para operar**, NO si ya recibió un cliente real. Por eso `completed` =
  `has_patients && has_clinic_contact && has_services` (3 hitos: **pacientes → datos de
  tu clínica → servicios**). **NO** incluye cita ni consulta: ésos dependen de que
  llegue un cliente y mantendrían el overlay activo días. Objetivo: completarse en la
  **primera sesión (3-5 min)**. El gate vive en el backend (`dashboard_activation`);
  `has_appointments`/`has_consultations` se siguen devolviendo (informativos) pero **no**
  gatean el cierre.
- **Hito `has_clinic_contact` = `bool(Organization.phone)`** (Configuración → Clínica).
  Existe porque el teléfono es lo que el asistente de WhatsApp da en su **plantilla de
  urgencia**: sin él, un cliente que reporta una emergencia recibe *"acude de inmediato
  a la clínica"* sin número al que llamar. Sigue siendo señal derivable porque el campo
  nace vacío y el serializer impide guardar basura (ver
  [`organizations.md`](organizations.md) §Teléfono de la clínica) → *existir* equivale
  a *ser válido*.
  - El **horario NO es hito**: `create_default_schedule` siembra las 7 filas al crear la
    org, así que "tiene horario" es `true` desde el segundo cero; distinguir "es el
    default" de "la clínica lo revisó" exigiría un flag — justo lo prohibido. Se edita
    dentro del paso pero no gatea.
  - **Consecuencia aceptada por el PO**: una organización ya activada **sin** teléfono
    ve reaparecer el overlay una vez. Tiene causa clara y solución inmediata; no se
    inventan excepciones. La demo se blinda sembrando el contacto en
    `seed_demo_clinic` (`DEMO_ORG_CONTACT`, idempotente, sobrevive al reset de ADR p49).
  - Defensa complementaria (no la sustituye): `PATCH /api/inbox/settings/` con
    `enabled: true` exige teléfono válido → 400 (ver [`agent.md`](agent.md) §Gate del
    kill switch). El onboarding **educa**, el gate **garantiza**.
- **Overlay takeover**: `position: fixed; inset: 0; z-index: 200` (tapa la sidebar,
  z-index 100) — solo en `/` (los módulos conservan su sidebar). Se muestra mientras
  `!activation.completed`; al completar **desaparece para siempre** (sin "card de
  felicitaciones"): overlay `opacity→0` + `onComplete()` → el dashboard entra con
  **una sola** animación de página (`.dash-reveal`, keyframe `firstrun-rise`), no una
  coreografía por widget. **No es un bloqueo**: es una guía. Fuera de `/` el usuario
  navega libremente toda la app (el único gate global es `MustChangePasswordGate`,
  por seguridad, no el onboarding).
- **Estado real, sin flags** (PRINCIPIO, no romper): deriva de
  `useActivationContext()` (`ActivationProvider` en `Root`, `GET .../activation/`,
  read-only, multi-tenant, `for_organization`) → `{has_patients, has_services,
  has_appointments, has_consultations, completed}`. `has_patients` **excluye la
  mascota genérica**. El onboarding **nunca** introduce estado persistente propio
  (`has_seen_step_2`, `completed_onboarding`, `onboardingDismissed`, `localStorage`…):
  siempre se deriva del estado operativo real — no duplicar la fuente de verdad.
- **Provider "tonto"**: `ActivationProvider` expone solo `{activation, loading,
  refetch}`. **Toda** la lógica de UI del onboarding (paso actual, celebración, cierre,
  animaciones) vive en `FirstRunAssistant`. Si el onboarding se rediseña/elimina, el
  provider no queda acoplado.
- **Orden de producto** (no reordenar sin justificar): pacientes → datos de tu clínica
  → servicios. Abre con **pacientes**, que es donde está el valor visible — nunca con un
  formulario. Luego **identidad** (contacto) y al final **configuración operativa**: el
  servicio cierra como final de readiness.
- **Composición editorial de dos columnas** (desktop ≥900px, art direction — no cambia
  UX): izquierda = flujo (saludo discreto + **título del paso dominante** ~40px + lead +
  CTA + timeline + ETA); derecha = **preview elegante del módulo** por paso (lista de
  pacientes / lista de servicios). La preview es **no interactiva** (`aria-hidden`, una
  sola superficie `--c-surface`), simplificada — no mockups/capturas. <900px: una
  columna, sin preview.
- **Progreso**: **timeline conectado** estilo Stripe (nodos unidos por tramos que se
  estiran a lo ancho de la columna). **No** verbaliza "Paso N de N".
- **CTA secundario solo con ruta alterna real**: únicamente el paso 1 (Agregar
  paciente / **Importar Excel**, gateado por `can("import.create")` y oculto si
  `user.is_demo`). Datos de clínica y servicios = solo primary.
- **Flujo sin intervención (auto-redirect)**: cada CTA navega con
  `{ state: { fromOnboarding: true } }` (+ `section` cuando el destino es `/config`:
  `"clinic"` o `"services"` — sin eso ambos CTAs caían en la sección por defecto).
  El módulo destino, tras el create-success **de creación** (no edición), si
  `location.state?.fromOnboarding` → `navigate('/', { state: { onboardingStep: '<key>' } })`.
  Al volver, `FirstRunAssistant` lee ese `onboardingStep` → **micro-celebración**
  `✓ …` (~1.2 s) → siguiente paso o cierre.
  - Quién emite la señal: `pets.jsx` (`has_patients`) y **`pages/config/index.jsx`**
    (`has_clinic_contact`, `has_services`). El layout de Configuración es el **único**
    dueño del `navigate` — las secciones (`ClinicSection`, `ServicesSection`) solo
    reciben `onOnboardingDone` y avisan que el hito quedó cubierto (no duplican
    lógica de router). **Antes ninguna sección de `/config` lo emitía**: el paso de
    servicios no celebraba ni cerraba y el usuario se quedaba en Configuración.
  - `ClinicSection` solo avisa si el guardado **devolvió teléfono**; guardar sin él
    no cubre el hito (celebrar algo que el endpoint sigue viendo incompleto
    confundiría al ADMIN) — muestra un toast diciendo qué falta.
- **Cierre robusto al remontaje**: `FirstRunAssistant` se desmonta al navegar a un
  módulo y se re-monta al volver a `/`. El latch `sawStepRef` (que autoriza el momento
  de cierre solo si el montaje vio un paso en marcha — evita mostrarlo a una clínica ya
  activada) se levanta **también** al consumir el signal `onboardingStep`, porque ese
  signal prueba que el usuario venía del flujo. Así, aunque al volver la activación ya
  esté `completed` (sin paso que renderizar), el momento final igual dispara. Muestra
  ~1 s `Todo listo. {clínica} ya está lista. ✓` y fade. Personalizado con
  `user.organization_name` (nunca la marca).
- **Volver guiado**: `Layout.jsx`, si `location.state?.fromOnboarding`, muestra
  `← Volver al Dashboard` en el header en vez del título (hint de recorrido).
- **Gateado por capability** (no por rol): solo se renderiza si `can("service.create")`
  — proxy del acceso a la configuración inicial (un VET/ASISTENTE no ve CTAs a lugares
  sin permiso, p.ej. `/config`). No existe capability única para "ajustes de la org".
- **Motion**: `framer-motion` — entrada **orquestada escalonada** (marca → saludo →
  eyebrow → título → lead → CTA → timeline → ETA; preview desliza desde la derecha),
  transición fade+slide entre pasos, y micro-motions CSS (pulso del nodo actual del
  timeline, pop del ✓). Todo gateado por `useReducedMotion`
  / `@media (prefers-reduced-motion: reduce)`.
- **Atmósfera** (no plano): fondo con doble `radial-gradient` tonal (spotlight cálido +
  halo verde `--c-primary-ring`) + grano SVG sutil (`::before`, `mix-blend: multiply`),
  marca `SaaslyVet` arriba-izquierda y eyebrow "Primeros pasos" en color de marca. Solo
  tokens (sin teal, sin hex).

### Recorridos por módulo (spotlight sobre la UI real)

Recorridos guiados que enseñan **para qué sirve cada módulo** resaltando los elementos
**reales** de la pantalla (coach-marks), NO un modal con mocks. Motor **genérico y
reutilizable**: `components/SpotlightTour.jsx` (+ `.module.css`) — atenúa la pantalla,
recorta un hueco sobre `step.target` (selector CSS) y muestra un popover con la narración.
Un **overlay bloquea toda interacción** con la UI real (z 10499, encima de modales z 1000)
→ el usuario navega solo por el popover; **imposible disparar acciones reales por
accidente**. Precedente: `features/inventory/tutorial/ProductCreationTour.jsx` (bespoke de
inventario; `SpotlightTour` es el motor canónico a futuro — inventario migra luego).

**Primero implementado para Citas**: `features/appointments/tour/` = `agendaSteps.js`
(10 pasos + copy + `makeDemoLuna`) + `useAgendaTour.js` (orquestador). Cada paso resalta
un elemento real (`data-tour="agenda-*"` en `appointments.jsx`: calendario, formulario,
`#new-appt-pet`, quickadd, walk-in, detalle, "▶ Atender ahora") y su `onEnter(actions)`
**maneja la página real** (`setSelectedSlot`, `setWeekOffset`, `setViewAppt`,
`setTourDemoAppt`).

Reglas (no negociables — voz de producto):
- **EN VIVO sobre la UI real, no un modal de mocks.** El recorrido opera la pantalla real:
  abre el formulario de nueva cita, y el **modal de detalle REAL** de la cita.
- **Cita demo Luna NO persistida**: `makeDemoLuna()` (`public_id="__demo__"`) se inyecta
  SOLO en el grid local (`tourDemoAppt` → merge en `weekAppts`, **no** en las stats,
  **nunca** al backend) para que aparezca como `ApptBadge` real y abra el `DetailModal`
  real. Se limpia en `skip`/`finish` (`setViewAppt(null)` + `setTourDemoAppt(null)` +
  `setSelectedSlot(null)`). Resuelve el problema de clínica vacía sin escribir datos.
- **Contar una HISTORIA, no listar features.** Narra la visita de un paciente (**Luna**)
  en 10 pasos; el usuario aprende calendario, búsqueda, detalle, estados y flujo clínico
  *sin darse cuenta*. Un "calendario → botón → filtro → …" se siente PowerPoint y está
  **prohibido**.
- **Prohibida la palabra "Tutorial" en texto visible.** Usar **"Recorrido" / "Cómo
  funciona" / "Conoce…"**. Disparador en el `page-header` de Citas: **"Cómo funciona"**
  (`btn-secondary`, `Icon.Help`).
- **Cierre que no intimida** (último paso): "Ya conoces lo esencial… conforme uses el
  sistema irás descubriendo funciones más avanzadas" (evita sentir que "ya debería
  saberlo todo"). Ahí se *mencionan* las funciones que no son paso propio (atención sin
  cita, alta de paciente).
- **Glosario es-MX**: Cliente / Mascota / Paciente / **"Atención sin cita"** (NO
  "Walk-in") / **Cobro**. Estados vía `StatusBadge` (`Programada`/`En consulta`/`Completada`).
- **Gate**: auto 1ª visita (`localStorage: agenda_tour_seen !== "true"`, solo si
  `canCreate`) + replay desde "Cómo funciona". Flag = **preferencia de UI** ("ya vio esta
  ayuda"), distinto del principio de onboarding (deriva de estado de negocio real) — no
  confundir.
- **Solo tokens** (sin teal/hex), reusa `.btn`. Spotlight/popover gateados por
  `@media (prefers-reduced-motion)`.
- **Gate CI**: `components/SpotlightTour.test.jsx` (smoke del motor: navegación de pasos,
  cierre, `Anterior` deshabilitado en el 1º, ausencia de "Tutorial").

Extender a otros módulos = nuevo `features/<módulo>/tour/` (`<módulo>Steps.js` +
`use<Módulo>Tour.js`) reusando `SpotlightTour` + `data-tour` en la página real.

Extender a otros módulos = nuevo `features/<módulo>/tour/` siguiendo esta plantilla
(historia real, sin "Tutorial", cierre amable, autocontenido).

### Agenda del día (`TodayAgendaList`) — ADR p35

Mini-agenda operativa con navegación por día. Patrón **appointment cards** (NO volver a timeline).

- **Dueño de estado**: `TodayAgendaList` posee `selectedDate`, date strip, fetch por día, conteo y empty state. `index.jsx` solo compone (`<TodayAgendaList />` sin props).
- **Fuente**: `useDayAppointments(isoDate)` → `getAppointments(token, { date })`. Sin endpoint nuevo. Maneja respuesta array o paginada (`results`).
- **Date strip** (`AgendaDateStrip`): etiqueta mes/año arriba (contexto, no botón); flechas `←/→` navegan **semanas** (no meses) flanqueando 7 chips Lun→Dom. Día seleccionado resaltado (primary), hoy con punto. La ventana se reencuadra a la semana de la selección vía **remount** (`key={isoDate}` desde el padre) — sin `useEffect`+`setState` (evita `react-hooks/set-state-in-effect`). Navegar con flechas no cambia `selectedDate` → la ventana persiste independiente.
- **Botón "Hoy"**: resetea `selectedDate` al día actual (deshabilitado si ya es hoy).
- **Card**: avatar (inicial mascota) · `pet_name` (600) · `· owner_name` (muted) · `reason` (secundario) · `StatusBadge`. Máximo 2 líneas de texto — especie/raza/veterinario NO se muestran (viven en `AppointmentQuickModal`). Marcador `●` walk-in (requiere `walk_in` en el serializer, ADR p35).
- **`isLate` (regla exacta)**: mostrar "Pendiente desde hace N min" **solo si** `selectedDate == hoy` **y** status `scheduled|confirmed` **y** `now > start_time`. Nunca para `done`/`canceled`/`no_show`. `isNow` (resaltado + tag "Ahora") solo si día==hoy y status `in_progress`.
- **Acciones**: clic en card abre `AppointmentQuickModal` (única fuente de acciones; sin acciones inline, sin lógica de permisos en la lista). El modal dispara `dashboard:refresh` → la agenda refetcha.
- **Edge cases**: sin citas → "No hay citas para este día"; pasado → históricas (sin chips ahora/atrasada); futuro → programadas. Scroll interno (`max-height`).
- **TZ**: fechas construidas con `Date` local del browser; el backend filtra por día local de la org (`filter_by_local_day`). Posible desfase browser≠org tz — aceptado, consistente con `PendingFollowUp`.

### Reglas no negociables (Fase 1 UX)

- **Alert badge (`DashboardTopBar`)**: la barra superior señala **solo lo crítico** (= stock agotado, `stock_alerts.severity==='critical'`). Los avisos viven en sus cards, NO en la barra. Prohibido reintroducir un contador único que mezcle dominios ("N alertas").
- **Pendientes clínicos (`ClinicalBacklog`)**: partición **mutuamente excluyente** sobre `backlog.open_total`:
  - 🟢 Listas para cerrar = `open_total − without_diagnosis` (abiertas con diagnóstico) → "Continuar consulta".
  - 🟡 Sin diagnóstico = `without_diagnosis` → "Completar expediente".
  - **NO usar `needs_attention_count` en UI**: es subconjunto de `without_diagnosis` (open + >3h sin diagnóstico) y mostrarlo junto duplicaba el conteo visual. El backend lo sigue exponiendo; el frontend lo ignora.
  - **Presentación = acordeón compacto (ADR p34)**: vista inicial solo muestra los dos encabezados de grupo con su conteo. Cada grupo es clickeable y despliega inline sus consultas (acordeón, un grupo abierto a la vez — consistente con los demás paneles laterales que expanden inline, no drawer). NO listar todos los registros expandidos por defecto.
  - **Conteos vs filas**: los conteos de cabecera (`ready`, `noDiag`) salen de los agregados exactos (`open_total`, `without_diagnosis`); las filas listadas vienen de `backlog.open_records[]` (cap 50 del backend), particionadas por `has_diagnosis`. Si el conteo exacto supera lo listado, se muestra overflow ("+N más"). Cada fila navega **directo** al registro con `navigate(\`/medical-records?record=${public_id}\`)` — **solo `public_id`**, nunca PK.
- **Citas por resolver (`PendingFollowUp`)**: citas con fecha pasada aún en `scheduled`/`confirmed` (nadie las cerró/canceló/marcó no-asistió). Query a `status-breakdown` rango `hoy-30d → ayer`; el límite de filas es **visual (5)**, no del query (una cita perdida hace semanas no debe desaparecer). Las acciones (Atender / No asistió / Reprogramar) reutilizan `AppointmentQuickModal` (no crear modal nuevo).
- **Terminología analítica**: usar **"No asistieron"** (no "No-show") y **"Conversión de citas"** (no "Embudo"). Cada gráfica lleva título + descripción que solo nombra lo que realmente grafica (la de actividad no menciona canceladas porque no las plotea).

## Terminología de UI (glosario — fuente única, es-MX)

Reglas de lenguaje del producto para una clínica veterinaria mexicana. Aplican al
**texto visible** (labels, placeholders, toasts, títulos). **NO** cambian
variables, modelos, permisos, keys ni endpoints (p.ej. `walk_in`, `Owner`, `Pet`,
`Invoice` siguen igual en código/serializers).

| Concepto | Término UI | Evitar |
|---|---|---|
| Persona que paga / contacto | **Cliente** (Nombre del cliente, Teléfono del cliente) | ~~Dueño~~, ~~Propietario~~ (eliminados de UI) |
| Animal — contexto **administrativo** (listado, agenda, importación, cobros) | **Mascota** | — |
| Animal — contexto **clínico** (consulta, historial médico) | **Paciente** | — |
| Atención sin cita previa | **Atención sin cita** | ~~Walk-in~~ |
| Documento de venta/pago | **Cobro** (mientras no haya facturación fiscal) | ~~Factura~~ |
| Cierre de turno de caja | **Corte de caja** | ~~Corte Z~~, ~~Z-close~~ |
| Correo | **Correo electrónico** / Correo | ~~Email~~ |
| Métrica clínica del dashboard | **"Pacientes hoy"** (correcto — es clínica) | — |
| Inventario | **Stock** (entendido en MX; consistente — no traducir) | — |
| Analítica | **"No asistieron"**, **"Conversión de citas"** | ~~No-show~~, ~~Embudo~~ |

Notas:
- **Mascota/Paciente** es split por contexto, no sinónimos intercambiables: si la
  pantalla es administrativa → Mascota; si es el acto clínico → Paciente.
- La mascota genérica de walk-in se etiqueta en agenda como *"Atención sin mascota
  registrada — vincular mascota"* (no "Paciente anónimo").
- Deuda conocida (no clínica, fuera del piloto): `platform/createOrganization`
  aún valida `"Username requerido."` (anglicismo "Username").

## Punto de Venta (`/pos`)

Pantalla dedicada de venta directa de mostrador. Reemplaza al modal "Nuevo Cobro"
de `/billing` ("+ Cobro" y F11 ahora navegan a `/pos`). Cobros queda como listado
de documentos.

```
pages/pos/
├── index.jsx        — orquestador: modo cart|paying, checkout 2 pasos, caja
└── pos.module.css   — layout (grid carrito | panel derecho sticky)
components/pos/
├── ProductSearch.jsx    — input único: escáner de código de barras + búsqueda
├── Cart.jsx             — tabla de venta (qty inline, atestación Rx ADR p26)
├── CustomerSelector.jsx — cliente opcional (ADR p25, genérico por default)
└── PaymentPanel.jsx     — total + PaymentLinesEditor + CTA cobrar
hooks/usePOSCart.js      — estado del carrito (solo UI)
```

**Checkout en 2 pasos, server-driven (sin matemática financiera en React):**

1. Modo `cart`: se arma la venta en estado local. El panel muestra "Total
   estimado" (subtotal sin IVA — el frontend NO replica `invoice_totals`).
   "Cobrar" → `createInvoice(direct_sale)` + `addInvoiceItem ×N` + `getInvoice`.
2. Modo `paying`: el panel muestra subtotal/IVA/**total reales del backend** y
   reusa `PaymentLinesEditor` (mismo flujo que Registrar Pago de Cobros: split,
   total exacto ADR p30 rev, cambio en efectivo no persistido). "Confirmar
   cobro" → `direct-pay` atómico con `X-Idempotency-Key`.

- "Volver al carrito" / abandonar la página en modo pago → `cancelInvoice` del
  draft (auditable vía `InvoiceAuditLog`, no quedan borradores huérfanos).
- Reintento tras fallo de pago: conserva draft + idemKey (anti doble cobro).
- **Escáner USB** = teclado (escribe código + Enter): Enter intenta primero
  `GET /inventory/presentations/barcode/?barcode=` (lookup exacto, agrega qty 1;
  re-escaneo incrementa) y cae a la búsqueda por nombre (productos + servicios).
- Guard de stock del carrito = pre-check visual; el backend valida bajo lock al
  confirmar. Cero endpoints nuevos: el POS vive sobre la API existente.

**Compartido (no duplicar por módulo):**

- `components/PaymentLinesEditor.jsx` — editor de líneas de pago único
  (extraído de `billing.jsx`; lo usan Registrar Pago, devoluciones y POS).
- `utils/payments.js` — `PAYMENT_METHODS`, `paymentLinesValid()`,
  `buildPaymentLines()` (regla de sobrepago/cambio ADR p30 rev, única fuente).
- `utils/idempotency.js` — `newIdempotencyKey()`.

## Rutas

| Ruta                | Pagina              | Acceso       |
|---------------------|---------------------|--------------|
| `/`                 | Dashboard           | Privada      |
| `/analytics`        | Analítica           | Privada (Financiero solo ADMIN) |
| `/login`            | Login               | Publica      |
| `/pets`             | Mascotas            | Privada      |
| `/pets/:id`         | Ficha mascota       | Privada      |
| `/appointments`     | Citas               | Privada      |
| `/medical-records`  | Historial clinico   | Privada      |
| `/inventory`        | Inventario          | Privada      |
| `/billing`          | Facturacion (listado de documentos) | Privada |
| `/pos`              | Punto de Venta      | Privada      |
| `/cash`             | Caja (turnos + Z)   | Privada      |
| `/prescriptions`    | Recetas             | Privada      |
| `/staff`            | Equipo              | Solo ADMIN   |
| `/config`           | Configuracion       | Solo ADMIN   |

## Testing (Vitest + Testing Library) — P1-4

> Plan completo y fases: [`docs/p1-4-frontend-reliability.md`](../p1-4-frontend-reliability.md).

Red de seguridad de frontend. **No** se busca % de coverage — se protegen los
flujos que mueven dinero/stock y la operación clínica.

### Stack y config

- `vitest` 4 + `@testing-library/react` + `@testing-library/jest-dom` + `jsdom`.
- Config: bloque `test` en `vite.config.js` (`environment: 'jsdom'`, `globals: true`,
  `setupFiles: ['./src/test/setup.js']`).
- `src/test/setup.js` carga los matchers de jest-dom. **No** poner mocks globales ahí
  (los mocks viven por archivo de test, aislamiento explícito).

### Scripts

```bash
pnpm test         # vitest run (lo que corre el CI)
pnpm test:watch   # vitest (desarrollo)
```

### CI (gate bloqueante)

El job `frontend` corre `pnpm run test` como paso **bloqueante** (ADR/plan P1-4
Fase A): `.github/workflows/ci.yml`. Un test rojo tumba el merge. `lint` sigue
siendo advisory (`continue-on-error`); ver el plan para la condición de pasarlo a
blocking (Fase D).

### Convenciones (obligatorias)

- Nombrar `*.test.js` (lógica pura) o `*.test.jsx` (componentes), junto al archivo
  bajo prueba.
- **Probar comportamiento observable**: roles ARIA, texto visible, valores de input,
  callbacks. **Nunca** estado interno de React, nombres de variables ni detalles de
  implementación.
- **Cero snapshots** (no aportan, se rompen por ruido).
- **Mocks mínimos**: solo side-effects globales inevitables (p.ej. `sonner.toast`).
  **No** mockear lógica de negocio — `utils/payments.js` se usa real para probar la
  integración con las reglas protegidas.
- **Componentes controlados** (los que reciben `value`/`setX` del padre, p.ej.
  `PaymentLinesEditor`): envolver en un host con `useState` que reproduzca el contrato
  del padre, y observar el render resultante tras la interacción (`@testing-library/user-event`).

### Cobertura actual

| Archivo testeado | Test | Qué protege |
|---|---|---|
| `utils/payments.js` | `payments.test.js` | regla de dinero: total exacto, sobrepago/cambio no persistido, split, líneas vacías/negativas (ADR p30) |
| `utils/apiError.js` | `apiError.test.js` | cadena de prioridad de mensajes 429→detail→error→errors[]→errors{}→message→fallback |
| `utils/handleFormError.js` | `handleFormError.test.js` | ruteo de errores DRF a `setErrors` (campo) vs `toast` (global) |
| `utils/mapFieldErrors.js` | `mapFieldErrors.test.js` | normalización DRF (incluye dual-key dotted+bare-root, consumido por wizard inventario) |
| `utils/toList.js` | `toList.test.js` | normalización array \| paginado DRF |
| `components/PaymentLinesEditor.jsx` | `PaymentLinesEditor.test.jsx` | interacción usuario→inputs→footer (Falta/Exacto/Cambio/Excede), split, agregar/quitar línea, float-drift `.toFixed(2)` |
| `utils/inventory.js` | `inventory.test.js` | stock: `stockStatus` (agotado/bajo/normal), `productStockQty`, `productStockValue` (`sale_price/cf×qty`), `computeInitialStock`, `fmt`/`fmtCur` |
| `components/dashboard/FirstRunAssistant.jsx` | `FirstRunAssistant.test.jsx` | onboarding: orden de los 3 hitos, un solo paso a la vez, deep-link de sección en los CTAs, celebración/cierre, gate por `service.create` |

### Gotchas

- `mapFieldErrors` aplana cada error anidado a **dos** claves (dotted
  `presentation_input.sale_price` + plana `sale_price`); ambas load-bearing
  (`inventory.jsx` las consume como fallback). El docstring de la función está
  desactualizado (solo menciona la dotted) — ver deuda fase 4.
- `PaymentLinesEditor` recalcula `sum`/`remaining`/`change` **inline**, duplicando la
  matemática de `payments.js` (deuda fase 4). El test de float-drift ancla ese cálculo.
- Botón eliminar de `PaymentLinesEditor` con 1 sola línea: `visibility:hidden` →
  queda **fuera** del árbol de accesibilidad (no matchea `getAllByRole('button')`).
  Es el contrato: el usuario no puede borrar el único método de pago.
- Inventario: el **valor en stock** se calcula `sale_price / conversion_factor × qty`
  (`productStockValue`); el `/cf` normaliza el precio de la presentación a unidad base.
  Conviven **dos** definiciones de "bajo stock": `stockStatus.low` (frontend, `min>0 &&
  stock<min`) y `metrics.lowStock` (flag backend `is_low_stock`). No unificar sin ADR.
- **Bug conocido (deuda fase 3 B7):** el sort de la columna "Valor en stock" ordena por
  `sale_price × stock` **sin** `/cf` → no coincide con el valor mostrado para productos
  con `conversion_factor ≠ 1`. Bug de UX (orden), sin pérdida de datos. Fix: usar
  `productStockValue`/`productStockQty` en el comparador.

### Pendiente (siguientes fases)

- B7 (deuda fase 3): alinear el sort "Valor en stock" con `productStockValue` (fix + test).
- C: extraer la lógica pura restante (billing sub-componentes, dedup sum/remaining).
- D: triar los ~6 errores `react-hooks` (lint) para pasar lint a blocking.
