# Modulo: Frontend

> **Ver también:** [`docs/system-operational-flow.md`](../system-operational-flow.md) — mapa operacional cross-módulo (acciones, precondiciones, efectos, invariantes).

## Stack

- React 19 + Vite (JavaScript, sin TypeScript)
- Estilos: CSS modules por pagina + variables globales en `tokens.css`
- Toasts: `sonner` (configurado en `App.jsx`)
- Auth: Context propio (`src/auth/authContext.jsx`) con JWT + refresh automatico
- HTTP: Axios con interceptores (`src/api/client.js`)
- Confirmaciones: `useConfirm` hook (`src/components/ConfirmDialog.jsx`)

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
│       ├── PetSidebar.jsx       — sidebar izquierdo (lista de mascotas)
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

`apiError` extrae el primer mensaje legible en este orden: 429 → detail → error → errors[] → errors{} → message → fallback.

**Shape canónico de errores backend (PR-4B / ADR p16):**
- Validación (400): `{code: 'validation_error', errors: {field: [messages]}}`
- Acceso/permisos (403): `{code: 'permission_denied', message}`
- No encontrado (404): `{code: 'not_found', message}`
- Conflicto de estado/integridad (409): `{code: 'resource_has_dependencies', message, protected_count: int, protected_count_truncated: bool, protected_sample: [{type, id, public_id}]}` (cuando el backend bloquea por FK PROTECT)
- Conflicto de recurso genérico (409): `{code: 'generic_resource_protected', message}` (cuando se intenta borrar Owner/Pet genérico)
- Endpoint deprecado removido (410): `{code: 'endpoint_sunset', message}` (post-Sunset RFC 8594, e.g. `/api/organizations/<pk>/` post-2026-08-17)

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
- `PrescriptionSerializer`: `pet_public_id`, `medical_record_public_id`
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
- Interceptor response 401:
  - **Bypassa redirect** si el request fallido es el endpoint de login (`url` termina en `token/`). Sin esto, credenciales malas disparaban full page reload antes de que el toast del login se renderizara. Helper local `isLoginAttempt(config)`. Ver ADR p22.
  - Para 401 en cualquier otro endpoint: `clearTokens()` (vía `tokenStorage`) + `window.location.href = "/login"` (sesión expirada legítima).
- Interceptor response 500+: alert global "Error del servidor".

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

- Decodifica el JWT para leer `exp`, `role`, `organization`
- Programa refresh del token 5 minutos antes de que expire
- En init: refetch `/api/me/` para datos frescos de usuario y org
- Persiste tokens y user data vía `auth/tokenStorage.js` (NO `localStorage` directo — ver § Auth storage abajo).
- `login(access, refresh, remember = true)` — recibe flag de "Recordarme" y lo propaga a `setTokens()`.
- Refresh callback chequea `isLoggingOut()` antes de aplicar tokens — previene revival de sesión recién terminada (race logout/refresh). Ver ADR p22.
- Almacena `permissions` como `Set` (desde el array retornado por `/api/me/`)
- Expone helpers memoizados para control de acceso basado en capabilities:
  - `can(permCode)` — `Set.has()`, O(1). Ej: `can("invoice.create")`
  - `canAny(codes)` — `some`. Ej: `canAny(["invoice.create", "invoice.confirm"])`
  - `canAll(codes)` — `every`. Ej: `canAll(["invoice.create", "invoice.pay"])`
- `Object.freeze` sobre el `Set` para prevenir mutaciones accidentales
- Invalidacion en `logout()` y `setUserData()`: `setPermissions(new Set())`

**Regla**: nunca inferir permisos por `user.role`. Usar exclusivamente `can()`.
Esto soporta roles dinamicos donde dos usuarios con el mismo nombre de rol pueden
tener distintos permisos via RBAC en DB.

### Auth storage (`tokenStorage.js`) — ADR p22

Módulo único que centraliza acceso a auth storage. **Todo acceso a `access_token`, `refresh_token`, `user` en el frontend DEBE pasar por este módulo.**

**Invariantes (ver docstring del módulo):**

1. **No coexistencia**: tokens válidos NUNCA en `localStorage` y `sessionStorage` simultáneamente. `setTokens()` enforce wipe del other store.
2. **Read priority**: `sessionStorage > localStorage`. Sesión temporal de tab gana sobre persistente vieja.
3. **Source of truth**: presencia del `access_token` en algún store. El `auth_persist` flag es **metadata only**, nunca leído como autoridad.
4. **Logout flag**: `clearTokens()` levanta `loggingOut=true`; `setTokens()` lo limpia. Async callbacks (refresh) chequean `isLoggingOut()` antes de mutar estado.

**API:**
- `getItem(key)` — lectura con prioridad session > local.
- `setTokens({ access, refresh, remember })` — escribe al store correcto + wipea el otro.
- `setAccessToken(access)` / `setUser(user)` — actualiza en el `activeStore()` actual.
- `clearTokens()` — borra ambos stores + levanta flag de logout.
- `isLoggingOut()` — predicado para async guard.

**"Recordarme" del login:**

| `remember` | Store | Vida útil |
|---|---|---|
| `true` (default) | `localStorage` | Persiste hasta logout o expiración. Sobrevive cerrar browser. |
| `false` | `sessionStorage` | Muere al cerrar tab. No comparte sesión entre tabs (per-tab por diseño). |

**Anti-patterns prohibidos:**
- ❌ `localStorage.getItem("access_token"|"refresh_token"|"user")` fuera de `tokenStorage.js`.
- ❌ Leer `PERSIST_FLAG` para decisiones de routing — solo se escribe como metadata auxiliar.
- ❌ Bypass de `isLoggingOut()` en callbacks async que mutan estado de auth.

Grep gate sugerido (post-beta, vía ESLint custom rule): bloquear `(localStorage|sessionStorage)\.(getItem|setItem|removeItem)\(['"](access_token|refresh_token|user|auth_persist)` en archivos != `auth/tokenStorage.js`.

## Componentes compartidos

### SearchSelect

Combobox con busqueda asincrona. Debounce de 250ms. Maneja race conditions con `reqId`. Props clave: `value`, `onChange`, `onSearch`, `disabled`, `prefetchOnFocus`.

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
(Fecha/Total, sort client-side en `useMemo`). **No crear sorting por módulo**
(design-system.md §5). Deuda contenida: Inventario conserva su SortHeader local
(module CSS) — migrar junto con la unificación de su tabla, no piecemeal.

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
| **Agenda del día (`TodayAgendaList`)** | `useDayAppointments` | `GET /appointments/?date=YYYY-MM-DD` | Live, refetch al cambiar día + evento `dashboard:refresh` (ADR p35) |
| Spark + Δ de ingresos (admin) | `useFinancialSeries` | `financial/series/` | Snapshot + hoy live |
| Card "Analítica" | `useDashboardSeries` + `useFinancialSeries` | `operations/series/` + `financial/series/` | Snapshot + hoy live |
| Card "Citas por resolver" | `useAppointmentsByStatus` | `GET /appointments/status-breakdown/?from=&to=` | Live, rango |

`summary` solo expone datos **point-in-time de HOY**. No es fuente de reporting (ver `dashboard-metrics-contract.md`).

> **Agenda ya NO consume `summary.timeline`** (ADR p35). Antes la "Agenda de hoy" era un timeline horizontal alimentado por `summary.timeline` (fijo a hoy). Ahora es una mini-agenda con navegación por día vía `appointments/?date=` — el día puede ser pasado/hoy/futuro. `summary.timeline` sigue existiendo en el payload (alias legacy `appointment` + `appointments[]` con `species`/`breed`) pero el dashboard ya no lo usa; `OperationalTimeline.jsx` quedó retirado (no montado, no borrado).

### Composición

Sidebar (orden = urgencia): **Ahora** → **Citas por resolver** → **Pendientes clínicos** → **Stock crítico**.

Columna principal: **KPIs** → **Agenda del día** (`TodayAgendaList`) → **Analítica**.

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
| `/billing`          | Facturacion         | Privada      |
| `/prescriptions`    | Recetas             | Privada      |
| `/staff`            | Equipo              | Solo ADMIN   |
| `/config`           | Configuracion       | Solo ADMIN   |
