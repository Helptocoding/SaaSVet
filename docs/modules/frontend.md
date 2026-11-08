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
- **Precondición de cita vencida (409)**: `{code: 'appointment_changed', message, current: {status, date, start_time}}` (INV-A, ADR p57). La cita cambió desde que se leyó. **No es un error técnico**: la UI recarga la cita, muestra qué cambió y deja al usuario decidir. **Nunca** auto-reintentar ni reenviar sin `expected_state`. **Desde F5 Fase 2 el frontend SÍ la envía** — ver § Precondición de estado en citas
- **Cliente ya existente (409)**: `{code: 'owner_exists', message, candidate: {public_id, name}}` (INV-B/INV-C, ADR p57). El teléfono ya tiene expediente y ese camino no puede reutilizarlo. **No es un error técnico.** El **registro rápido de citas** (`create-with-patient`) solo lo produce si envía `require_new_owner` — hoy el frontend **no** lo envía, así que su comportamiento no cambia: sigue reutilizando el expediente del cliente que vuelve. En el **alta de mascota** (`POST /api/pets/`) la UI debe preguntar «¿es este cliente?» con `candidate.name` y, si el usuario confirma, **reenviar en modo referencia** (`{owner_public_id: candidate.public_id}` en vez de `{owner: {name, phone}}`); si no, corregir el teléfono. Al **cambiar un teléfono** significa que ese número ya es de otro cliente: cero escrituras (tampoco los campos de la mascota, si venía por `PATCH /api/pets/`). **Nunca** reintentar el mismo payload
- **Cliente ambiguo (409)**: `{code: 'owner_ambiguous', message, candidate_count: int}` (INV-C, ADR p57). Ese teléfono tiene **dos o más** expedientes y el sistema **no elige**. **No hay candidato en el cuerpo a propósito** — ofrecerlo sería sugerir la elección prohibida. La UI muestra que el dato está por ordenar y no ofrece ninguna acción de «continuar igual»; la salida es corregir los expedientes duplicados desde Clientes
- **Caso de identidad (409)**: `{code, message}` con `code` ∈ `no_identity_case` · `verification_required` · `owner_changed` · `already_linked` (FLUJO-C, ADR p57 §5.5). Los produce la bandeja al **verificar** o **autorizar**. `verification_required` es el más frecuente y **no es un error del usuario**: falta registrar una verificación aprobada *de ese mismo caso y candidato* antes de poder vincular — por eso el botón «Autorizar vínculo» sale deshabilitado hasta que la haya
- **Conflicto al liberar (409)**: `{code: 'release_conflict', reason, message}` (F3, ADR p57 §5.6). La conversación cambió mientras se liberaba. La bandeja **recarga el caso y vuelve a preguntar**; **nunca** reintenta en bucle — el backend ya reintentó una vez, y dos vueltas con el mundo moviéndose significan que hay otra persona operando. `reason` ∈ `suspension_changed` · `state_changed` · `claim_changed` · `turn_in_progress` · `handoff_changed`
- **Turno en vuelo (409)**: `{code: 'turn_in_progress', message}` (F3). El asistente está respondiendo justo ahora; se reintenta en segundos. No es un error del usuario
- **Horario ocupado (400)**: `{code: 'slot_taken', message, errors: {error: [message]}}` (INV-D, ADR p57). El veterinario ya tiene una cita activa en ese intervalo, lo detecte el pre-chequeo o lo rechace la restricción de PostgreSQL. Aplica también a la **atención sin cita** y a la **reactivación** de una cita cancelada; la UI ofrece otro horario u otro veterinario. **No existe bandera de forzado**. El cuerpo es un superset del 400 anterior → `apiError` ya lo resuelve por `errors{}` sin cambios
- Endpoint deprecado removido (410): `{code: 'endpoint_sunset', message}` (post-Sunset RFC 8594, e.g. `/api/organizations/<pk>/` post-2026-08-17)
- Demo en reset (503): `{code: 'demo_resetting', message}` + header `Retry-After` (solo **escrituras** de la org demo durante un reset automático; las lecturas pasan — ADR p49). Tenants reales nunca lo reciben.

Frontend debe distinguir por `code` field, no por status code. El handler `apiError` ya extrae `message` correctamente. Para mostrar acción específica (e.g. "este registro tiene 5 mascotas asociadas"), parsear `protected_count` y `protected_sample`.

### WhatsApp Inbox: media entrante privada (MED-01..05 / RPL-07, 22-10)

`Message.media` añade UUID, status, MIME, tamaño, filename, expires_at y dimensiones/
duración opcionales. No expone keys ni IDs de Meta. `getInboxMedia` usa el cliente
autenticado con responseType blob y AbortSignal. `useMediaUrl` comparte URLs por
usuario/clínica/UUID con refcount, abort y revoke; respuestas tardías no cambian
el hilo actual. Los deltas detectan cambios de media sin tocar el Message.

`MediaBubble` carga imagen/sticker al aproximarse al viewport, abre lightbox
nativo con Escape y retorno de foco, y conserva su blob durante la interacción.
Audio/video/documento e imágenes grandes requieren clic y muestran peso; sin
autoplay. Descarga documental por blob, caption una vez, y estados de recepción,
fallo, retry explícito y expiración 410 sin bucle. La lista usa tipo/filename para
archivos sin caption. No cambia composer ni autorización de envío.

170 pruebas PostgreSQL y 257 frontend únicas PASS en evidencia compuesta; build, lint y Chromium
escritorio/móvil PASS. [Expediente](../evals/inbox-phase3-2026-10-22/README.md).
Native replies conectadas al proveedor tras admisión B4; Meta/recepción reales
siguen aplazados. M2/M3/M4 pendientes de aplicar a base habitual/preview y media
apagada por defecto; ver [runbook](../runbooks/inbox-media.md).

### WhatsApp Inbox: citas y salto al original (WA-RPL-06 + WA-RPL-04)

`ReplyQuote` representa un nivel de cita dentro de mensajes entrantes y salientes,
con autor existente, extracto, tipo/icono de media y «Mensaje no enviado» para
failed/discarded. Una referencia null o inválida no genera bloque. El contenido
se interpreta como texto; el respaldo no inventa un archivo ni su contenido.
El botón admite teclado/táctil y solo se deshabilita mientras busca ese destino.
Leer una cita requiere view; no concede permisos de envío y funciona en archivo.

`useThreadHistory.jumpToMessage` usa el PK, independiente de client_message_id:
si está cargado no pide HTTP; si falta consulta exclusivamente `around`, fusiona
por ID y conserva estados ya recibidos y la cadena before. El floor firmado solo
se amplía hacia atrás; una página intermedia no lo adelanta. El siguiente delta
reconcilia el intervalo ampliado según el contrato de PERF-03, sin cambiar la API.

El efecto de layout comparte la autoridad de scroll con HIST-02: la intención
explícita centra/enfoca el original y resalta dos segundos, con movimiento reducido
respetado. No cuenta la ventana histórica como llegada ni consume avisos reales.
Durante el resaltado no dispara scrollback automático ni pierde un destino oculto
revelado por around solo porque no figure en el rango operacional. Una retirada
explícita sigue ganando. Ir al final cancela la búsqueda/resaltado y recupera su
propia intención.

Un salto aborta el GET corriente previo y pausa nuevos polls del transcript mientras
busca, conservando el cursor. No aplica metadatos de sesión de la página around.
Salto posterior, cambio de hilo y unmount abortan/invalidan respuestas antiguas;
404 o fallo mantienen mensajes y borrador y permiten pulsar de nuevo para reintentar.

[Evidencia RPL-06/04](../evals/inbox-rpl-06-04-2026-10-22/README.md): 128 pruebas
frontend únicas PASS (45 nuevas, 83 afectadas), build, lint y Chromium escritorio/
móvil con API sintética PASS. Conjunto mínimo inseparable: sin el bloque pulsable
de RPL-04 el salto de RPL-06 quedaría sin interacción en la pantalla.
Corte histórico RPL-06/04: sin cambios backend/M2/M3 en ese corte. RPL-07
y MED se completaron después, según la sección anterior; Meta real sigue aplazada.

### WhatsApp Inbox: composer de respuesta citada (WA-RPL-05)

La acción «Responder» acompaña a «Copiar» en el contexto de cada burbuja:
aparece con hover/foco y permanece accesible en táctil. Solo con permiso send y
sesión vigente; una ventana cerrada o un ID temporal deshabilitan seleccionarla.
Un mensaje confirmado con PK permite responder aunque conserve client_message_id.

`replyTarget` mantiene una única cita, con autor y extracto de hasta 80 puntos
Unicode. Se muestra sobre el campo, en una línea con elipsis, sin interpretar HTML.
Elegir otra sustituye la anterior y enfoca el composer sin borrar su texto.
Escape o × cancelan conservando borrador; cambiar de persona/cuenta o episodio
retira la cita. Un poll del mismo episodio o pulsar la fila ya elegida la conservan.

Al enviar, cada intento captura su `replyToId` y el optimista conserva `reply_to`.
Texto y chip se limpian inmediatamente; los reintentos mantienen ID y key propios
sin consumir una cita nueva ni una respuesta tardía limpiar el hilo siguiente.
Enter envía; Shift+Enter y composición IME no envían. Continúan los guards de
ventana y los AbortSignal existentes.

El adaptador amplía las opciones actuales:
`sendInboxMessage(sessionId, body, key, {signal, replyToId})`. Conserva compatible
el cuarto argumento de cancelación; agrega `reply_to_id` al cuerpo solo si hay
cita. La validación definitiva sigue en la API de RPL-03. RPL-07 ya conecta
el contexto nativo Meta, conservando los guards B4; falta validación real.

[Evidencia RPL-05](../evals/inbox-rpl-05-2026-10-21/README.md): 61 pruebas frontend
únicas PASS (27 nuevas, 34 afectadas), build, lint y Chromium escritorio/móvil PASS
con API sintética. Un fixture corrigió su reloj y se repitió solo ese caso; recibos
originales conservados. Citas en burbujas y jump quedan para RPL-04/06, respectivamente.

### WhatsApp Inbox: asignar a compañeros (WA-ASN-01)

La cabecera muestra «Asignar a…» con `agentinbox.claim` en una sesión abierta.
`ThreadAssignment` consulta el directorio solo al abrir; ofrece selección, confirmación,
cancelación, carga, vacío y reintento de error. Reabrir revalida la lista y limpia la
selección. El selector móvil permanece dentro de pantalla y tiene controles de 44 px.

Al confirmar se envía el UUID del objetivo contra el episodio vigente. Comparte el
guard de Tomar/Liberar para impedir acciones simultáneas; deshabilita durante turno
activo o petición. Refresca lista/transcript al completar y conserva el borrador.
El error mantiene la elección para corregir/reintentar. Cambiar de hilo o sesión,
o salir del Inbox, descarta respuestas tardías; cerrar/cambiar cancela el GET del
directorio. Un POST ya recibido puede haber aplicado la asignación aunque su vista
se haya cerrado: no se afirma cancelación de esa escritura.

Asignar no acusa recibo de un handoff ni manda push. El responsable aparece en
«Atiende»; otros empleados reciben el cambio por su polling habitual.
[Contrato API](agent.md) y [evidencia ASN-01](../evals/inbox-asn-01-2026-10-21/README.md).

### WhatsApp Inbox: búsqueda de contactos (WA-SRCH-01)

Input de tipo search sobre la lista, con etiqueta «Buscar conversaciones»,
consulta de nombre/teléfono/cliente en servidor y mínimo dos caracteres tras
recortar espacios. Espera 250 ms desde la última modificación; la limpieza con
Escape o «Limpiar búsqueda» es inmediata y conserva segmentos y foco.
Ctrl/Cmd+K enfoca y selecciona el texto; el listener y el debounce se eliminan
al desmontar el Inbox. No captura Escape fuera del buscador.

Cambiar la consulta efectiva reutiliza el reinicio de FIL-01: aborta el GET,
invalida respuestas anteriores, limpia páginas/cursores y vuelve al inicio.
Paginación, reintento y polls llevan `q` junto con los segmentos. Visibilidad
oculta sigue pausando GETs y al volver se consulta el último texto. El chat y el
borrador permanecen abiertos aunque su contacto deje de aparecer en la lista.
«Sin coincidencias» sugiere otro nombre/teléfono o ampliar filtros.
El panel de lista móvil admite el buscador sin ocultar los controles de filtro.
[Contrato API](agent.md) y [evidencia SRCH-01](../evals/inbox-srch-01-2026-10-21/README.md).

### WhatsApp Inbox: segmentos de lista (WA-FIL-01)

Chips «Sin atender», «Esperando cliente», «Urgentes» y «Míos» sobre la lista,
con `aria-pressed`, foco visible y objetivo táctil de 44 px. Los estados de
atención son excluyentes y pulsar el activo lo desactiva; urgencia y responsable
se combinan con AND y conservan la opción Activas/Archivadas.

Los filtros se envían al servidor en todos los GET, incluidas páginas y polls.
No se filtran localmente los resultados. Cambiar un segmento aborta el GET previo,
invalida su revisión, vacía páginas/cursores y carga desde offset cero. Las
respuestas tardías no repueblan el segmento nuevo; cada página conserva su cursor.
Se mantienen el chat abierto, su historial y borrador. «Sin coincidencias» indica
que se pueden desactivar filtros; un error permite reintentar con los mismos
parámetros. El total de no leídos no se interpreta como tamaño del segmento.
[Contrato API](agent.md) y [evidencia FIL-01](../evals/inbox-fil-01-2026-10-21/README.md).

### WhatsApp Inbox: polling incremental (WA-PERF-03)

Tras el GET inicial, la lista guarda un cursor y su página por offset. Refresca
con `since`, combina upserts/retiradas por contacto+cuenta y aplica el orden del
servidor. Publica juntas todas las páginas cargadas; mover un hilo entre páginas
no lo borra ni duplica. Paginación, total unread y estados vacíos conservan su
contrato. «Cargar más» aborta un poll de fondo pendiente antes de cargar la página.

El transcript usa un cursor propio y combina cambios por ID en el historial
acumulado. Conserva metadatos cuando el delta no los modifica; aplica null al
archivar. `useThreadHistory` mantiene el límite opaco `sync_floor` del servidor
y lo amplía al cargar anteriores. `range_ids` reconcilia retiradas al ampliar el
rango; las retiradas explícitas tampoco reviven por una respuesta histórica tardía.
El mecanismo de ancla de HIST-02 conserva lectura, contador nuevo y borrador.

Cada recurso tiene una sola petición activa. Cambio de hilo/filtro o desmontaje
aborta e invalida continuaciones. Pestaña oculta pausa los polls; al volver intenta
delta con su cursor vigente. Se mantienen las cadencias de 20 s/10 s y el reloj
visible de WIN-01. La lectura UNR-02 sigue requiriendo foco y visibilidad.

`invalid_sync_cursor` o un delta inconsistente provoca un único GET completo de
recuperación. El transcript conserva su rango firmado y reconcilia el full con
`reset_range`, sin perder mensajes entre el rango anterior y una ráfaga nueva.
Errores HTTP ordinarios mantienen datos/cursor y reintentan en el siguiente poll
con los avisos existentes; no añaden un bucle de recuperaciones.

El backend puede devolver full con cursor null si no dispone de caché. El cliente
conserva esa recuperación compatible y vuelve al delta al recibir un cursor.
[Contrato técnico](../decisions/2026-10-21-p60-perf03-cursors.md) y
[pruebas/Chromium PERF-03](../evals/inbox-perf-03-2026-10-21/README.md).

### WhatsApp Inbox: contexto del cliente (WA-CTX-01)

`ThreadContextPanel` añade un panel plegable bajo la cabecera, también en hilos
archivados y para usuarios con view sin send. Solo consulta `/context/` al abrir
o reintentar: carga y error propios, sin bloquear transcript ni borrador. Cerrar,
cambiar de hilo o desmontar aborta e ignora respuestas tardías. Cambios de los
metadatos de identidad recibidos por el poll reinician el panel; un poll normal
no vuelve a consultar su contexto. Reabrir obtiene datos nuevos.

Muestra nombre/teléfono del cliente vinculado, mascotas con especie y fecha/estado
de última cita, además de estados vacíos explícitos. La fecha es un calendario
local ya decidido por backend: no se desplaza al día anterior por la zona del
navegador. Los nombres se renderizan como texto React y el teléfono usa `tel:`
solo cuando es válido.

«Abrir expediente» requiere `patient.retrieve` y navega con el UUID de esa mascota
a la ruta existente `/pets/:id`, que conserva sus propios permisos. Desde un chat
abierto son dos clics: desplegar contexto y elegir mascota; homónimos conservan
UUID distintos. El panel tiene scroll propio y no carga historia clínica al Inbox.
[Pruebas y Chromium CTX-01](../evals/inbox-ctx-01-2026-10-21/README.md).

### WhatsApp Inbox: ventana preventiva (WA-WIN-01)

El composer usa `conversation.session_window_open` y
`conversation.session_window_expires_at` del transcript vigente. Con menos de
12 h muestra «Respondes dentro de la ventana de 24 h · cierra en 7 h 12 min»;
desde 12 h no añade banda. Calcula duración desde el timestamp absoluto y
redondea minutos hacia arriba, sin depender de la zona horaria del navegador.

El reloj visible compartido se actualiza cada minuto y al volver a la pestaña.
Un timeout de vencimiento cierra la UI entre esos ticks. Si llega un payload ya
vencido, lo corrige de inmediato. Un false del servidor prevalece incluso si el
reloj local indica un vencimiento futuro. Faltan datos/fecha válida → composer
bloqueado con explicación; no inventa una ventana abierta.

Al cerrar, deshabilita textarea y Enviar, conserva borrador y ofrece esperar un
nuevo mensaje del cliente o llamar con tel: válido. El handler de clic/Enter
revalida el reloj para cubrir timers demorados por suspensión. El sender conserva
la validación final de autoridad y ventana; la UI no garantiza admisión de un envío
que expire mientras está en cola. La renovación por poll habilita la respuesta
con el mismo borrador. Archivado o usuario sin send: no muestra composer ni banda.
Se conserva la cancelación de respuestas de otro hilo y los replays idempotentes.

[Pruebas y Chromium WIN-01](../evals/inbox-win-01-2026-10-21/README.md).

### WhatsApp Inbox: reintento de fallos conocidos (WA-RETRY-01)

Las burbujas salientes FAILED de la sesión vigente ofrecen «Reintentar» a quien
tenga `agentinbox.send`. Usan el UUID del episodio del mensaje y su ID original;
no sustituyen un episodio histórico por el vigente. El POST conserva la clave
original si existe y no envía texto editable. UNCERTAIN y evidencia de aceptación,
entrega o lectura no ofrecen esta acción. El servidor vuelve a validar su autoridad.

La acción muestra «Reintentando…» y bloquea doble clic. Su confirmación actualiza
la misma burbuja sin borrar el borrador ni duplicarla. Un poll con avance de entrega
gana a un PENDING tardío; GETs anteriores al acuse del retry quedan invalidados.
Cambiar de hilo o desmontar aborta la petición e ignora continuaciones tardías.
Un aborto no revoca una transición que el servidor ya haya confirmado.

Fallo de ventana conocido o 400 `window_closed` muestra «Ventana de WhatsApp
cerrada — llámala al {teléfono}» con enlace tel: cuando el número es válido.
Otros errores conservan el mensaje y permiten un nuevo clic explícito. La acción
`failed-local` conserva su flujo idempotente previo. La banda/countdown general
de ventana queda implementada en WA-WIN-01, descrita arriba.
[Pruebas y Chromium RETRY-01](../evals/inbox-retry-01-2026-10-21/README.md).

### WhatsApp Inbox: lectura del staff (WA-UNR-02)

La fila muestra `unread_count`; Activas muestra `unread_total` del servidor,
incluidos hilos fuera de las páginas cargadas. Un cero no se sustituye por el
antiguo indicador binario. Si una respuesta legacy no tiene el campo numérico,
la fila conserva el punto previo.

El transcript usa el marcador y los destinos de lectura proyectados por el
backend para la página vigente. «Mensajes nuevos» aparece antes del primer
entrante nuevo mostrado, sin marcar sesiones históricas. Desaparece tras un
POST confirmado o al recibir un marcador más reciente. La inserción y retirada
capturan el ancla de HIST-02 y participan en su efecto único de scroll.

`useThreadRead` espera 1,5 s desde el último destino recibido. Solo envía con
`document.visibilityState === 'visible'` y `document.hasFocus()`, comprobados
también al vencer el timer. Blur, ocultación, cambio de hilo o desmontaje cancelan
el debounce y abortan la petición en vuelo. Una respuesta vieja de A→B→A no
publica estado en la nueva apertura. Un aborto no revoca una escritura que el
servidor ya haya confirmado. Solo hay un POST en vuelo y no se repite un id confirmado.

Usa `agentinbox.view`: no exige send ni claim. Los errores se reintentan
silenciosamente en el siguiente poll del transcript, sin toast ni bucle inmediato.
Un acuse invalida GETs anteriores y refresca las páginas de lista ya cargadas
para que una respuesta antigua no reviva el contador. La lectura propia no
equivale al estado READ de entrega de WhatsApp.

[Pruebas y Chromium](../evals/inbox-unr-02-2026-10-21/README.md).
La integración usa M3 de UNR-01; este corte no la aplica a la base de trabajo.

### WhatsApp Inbox: tiempo, entrega y envío optimista (ADR p60)

El Inbox usa la zona horaria de la organización publicada por `/me/` como
`user.organization_timezone`; `orgTz` valida el identificador IANA y cae de
forma segura en `America/Mexico_City`. La lista usa `fmtTimeOrg`, las burbujas
`clockTimeOrg` y el transcript se agrupa con `groupMessagesByDay`/
`dayLabelOrg`. Todos reciben una sola referencia temporal, renovada cada 60 s,
para que `Hoy`/`Ayer` y la hora no discrepen al cruzar medianoche.

`DeliveryTicks` se renderiza solo en salientes y expone estado accesible por
`aria-label` y `title`: `pending` (reloj), `sent` (una marca),
`delivered`/`read` (dos marcas; lectura en verde), y
`failed`/`discarded`/`failed-local` (advertencia). Los entrantes no muestran
marcas. El código y sus pruebas viven en
`src/pages/inbox/DeliveryTicks.jsx` y
`src/pages/inbox/DeliveryTicks.test.jsx`.

El envío humano cumple este contrato:

- el cliente genera `X-Idempotency-Key` antes del `await`;
- backend devuelve `client_message_id` de solo lectura en POST/replay/GET,
  únicamente para salientes `human_staff`;
- el overlay optimista está separado del transcript servidor y se indexa por
  `(sessionId, client_message_id)`, con un máximo global de 20 intentos;
- GET y `201` reconcilian **solo** por `client_message_id`: está prohibido
  deduplicar por cuerpo, autor o cercanía temporal porque dos Enter pueden ser
  dos mensajes legítimos;
- un 4xx retira el optimista y muestra el error; red o 5xx lo conserva como
  `failed-local`, y «Reintentar» reutiliza exactamente la misma clave;
- cambio de hilo, secuencia A→B→A y desmontaje están protegidos por revisión
  de selección y `AbortController`; un resultado viejo no puede borrar el
  borrador ni reinstalar la sesión de otro hilo.

Pruebas dirigidas: `src/pages/inbox/index.test.jsx`,
`src/api/inbox.test.js`, `src/utils/datetime.test.js` y los tests de
`DeliveryTicks`. La representación de estados está implementada; el gate E2E
de ticks reales contra el sandbox de Meta continúa pendiente y no debe
declararse cerrado solo con pruebas unitarias.

El composer (WA-CMP-01) ajusta su altura al contenido entre 40 y 120 px; por
encima mantiene scroll interno. Conserva el límite de 4000 caracteres y muestra
el contador sólo al superar 3600, con advertencia desde 3800. La altura también
se recalcula al vaciarse por envío o cambio de hilo, sin cambiar la correlación
ni la idempotencia del envío. Evidencia dirigida en
[`inbox-cmp-01-2026-10-20`](../evals/inbox-cmp-01-2026-10-20/README.md).

WA-PERF-02 consume `{results, has_more, next_offset}` y permite cargar más de
100 hilos mediante «Cargar más», con cantidad cargada y aviso explícito.
Deduplica por contacto/cuenta y conserva el orden entregado por la API.
El refresco vuelve a consultar todas las páginas cargadas y las aplica juntas;
un fallo parcial retiene las filas y el borrador. La carga adicional tiene
error/reintento persistente y bloqueo de doble clic. Cambiar de filtro reinicia
el desplazamiento e invalida peticiones anteriores; ocultar/desmontar evita
continuaciones del refresco. El título sigue contando sólo hilos cargados.
[Evidencia dirigida PERF-02](../evals/inbox-perf-02-2026-10-21/README.md).

WA-GRP-01 agrupa visualmente mensajes consecutivos del mismo autor con separación
inferior a cinco minutos, siempre dentro de cada día de la clínica. Los entrantes
pertenecen al contacto del hilo; los salientes distinguen agente, sistema y cada
empleado por `human_author_public_id`. Sin UUID humano, incluido el optimista antes
de confirmación, se mantiene una burbuja separada. Ningún mensaje pierde cuerpo,
hora, estado o reintento; esta agrupación nunca deduplica ni altera los datos.
[Evidencia dirigida GRP-01](../evals/inbox-grp-01-2026-10-20/README.md).

WA-CPY-01 añade copia del cuerpo original y del teléfono mediante Clipboard API
con toast de éxito/error. La acción de mensaje aparece con hover/foco y siempre
en táctil; el teléfono incluye `tel:` y puede recuperarse de la fila seleccionada
si el hilo está archivado. `MessageBody` usa `tokenizeMessageUrls` para convertir
sólo HTTP/HTTPS válidos en nodos React con `target="_blank"` y
`rel="noopener noreferrer"`, manteniendo HTML literal y puntuación exterior.
No usa HTML del proveedor ni altera el cuerpo copiado o enviado.
[Evidencia dirigida CPY-01](../evals/inbox-cpy-01-2026-10-20/README.md).

WA-TAB-01 usa `useInboxTitle`: al ocultar o desenfocar, el título muestra el
número de hilos con `has_unanswered` del último poll. Se restaura al recuperar
foco/visibilidad, cuando no quedan pendientes y al desmontar. No agrega requests,
sonidos ni notificaciones; el conteo sigue siendo de hilos sin responder, no
unread por empleado (UNR-01/02 pendiente).
[Evidencia dirigida TAB-01](../evals/inbox-tab-01-2026-10-20/README.md).

WA-VIS-01 comparte `hooks/usePollingWhenVisible` entre lista (20 s) y transcript
(10 s). Ocultar detiene intervalos; volver refresca ambos inmediatamente. No
consulta al montar oculto, usa el filtro/hilo vigente al regresar y retira sus
listeners al salir. Un GET iniciado visible puede terminar oculto; no se inician
nuevos polls. El callback conserva su manejo de respuestas y errores. Métricas de
carga única, acciones explícitas y reloj de fechas mantienen sus contratos.
[Evidencia dirigida VIS-01](../evals/inbox-vis-01-2026-10-21/README.md).

WA-VER-01 muestra `ContactVerificationBadge` en lista y cabecera a partir de
`contact_verification`: staff/chat confirmado → «Verificado»; phone_match →
«Teléfono coincide» con explicación de que aún no verifica identidad; unknown o
valor desconocido → sin badge. Funciona sin sesión activa y refleja la retirada
del nivel en polls posteriores. Es informativo; no concede permisos ni sustituye
los guards de identidad del backend.
[Evidencia dirigida VER-01](../evals/inbox-ver-01-2026-10-21/README.md).

WA-LDE-01 distingue carga inicial, vacío y error en ambos paneles. Tras dos
fallos consecutivos muestra «Sin conexión — reintentando…» con reintento manual;
el polling vigente permite recuperar automáticamente y reinicia el contador al
éxito. Conserva lista, historial y borrador durante fallos. El reintento manual
queda deshabilitado mientras está pendiente. Respuestas tardías de otra selección
o filtro se descartan. `InboxLoadState` reutiliza `EmptyState` con semántica de
alerta y skeleton local; no cambia contratos API.
[Evidencia dirigida LDE-01](../evals/inbox-lde-01-2026-10-21/README.md).

WA-AGT-01 muestra «El asistente está respondiendo…» cuando la conversación del
transcript tiene `agent_processing === true`. Deshabilita Tomar/Acusar recibo y
Liberar con explicación; el siguiente poll exitoso los habilita al terminar.
No hereda el estado de la fila de lista, conserva permisos y no interpreta el
chip como bloqueo de servidor. Es una proyección con la cadencia actual de 10 s.
[Evidencia dirigida AGT-01](../evals/inbox-agt-01-2026-10-21/README.md).

WA-GTF-01 encapsula el área de lectura en `ThreadViewport`: botón «Ir al final»
si la distancia al fondo supera 200 px; scroll exclusivo del panel y foco
conservado en el historial, sin mover la página. Disponible en hilos archivados;
el estado se reinicia al cambiar de hilo. En móvil el viewport se acota a 58vh
(mínimo 340 px) para permitir scroll interno. HIST-02 centraliza el anclaje de
anteriores y llegadas nuevas y reutiliza el control para mostrar su contador.
[Evidencia dirigida GTF-01](../evals/inbox-gtf-01-2026-10-21/README.md).

WA-HIST-01 separa metadatos y mensajes servidor en `useThreadHistory`. Carga
páginas mediante `next_before` al llegar a menos de 160 px del inicio, fusiona
por ID y ordena por fecha/ID, conservando páginas previas durante el poll.
Al insertar anteriores captura la posición actual y compensa el aumento de
altura antes de pintar; el cursor de lectura no se adelanta con el poll.
No sustituye metadatos vigentes por los de una respuesta histórica.

Muestra carga local, error persistente y reintento del mismo cursor. Cambiar de
hilo o desmontar aborta la petición; una revisión descarta resultados antiguos,
incluido A→B→A. Desde 500 mensajes deja de cargar automáticamente y exige
«Cargar anteriores»; la carga manual conserva los mensajes ya leídos. Página
vacía o cursor repetido detienen la paginación. Al agotarla muestra «Inicio del
historial disponible», referido a los datos conservados por el sistema.
`getThreadMessages` admite `{signal}` como cuarto argumento opcional.
[Evidencia dirigida HIST-01](../evals/inbox-hist-01-2026-10-21/README.md).
WA-HIST-02 centraliza el scroll en un único layout effect de `useThreadHistory`.
Captura posición y ancla visible antes de actualizar mensajes servidor u
optimistas. A 80 px o menos del fondo sigue la llegada; leyendo arriba conserva
el ancla, incluso al coincidir poll y scrollback, y muestra «N mensajes nuevos».
La pill tiene anuncio accesible, retorna suavemente al fondo y conserva el
foco en el historial. Bajar manualmente al umbral de fondo limpia el contador.

El contador sólo incorpora identidades nuevas posteriores a la carga inicial:
ignora históricos y cambios de estado; reconcilia un optimista y su confirmación
por `client_message_id`. Al cambiar de hilo reinicia su estado. Es local a la
lectura actual; no sustituye UNR por empleado ni el polling incremental PERF-03.
[Evidencia dirigida HIST-02](../evals/inbox-hist-02-2026-10-21/README.md).

WA-PERF-02 consume `{results, has_more, next_offset}` y permite cargar más de
100 hilos mediante «Cargar más», con cantidad cargada y aviso explícito.
Deduplica por contacto/cuenta y conserva el orden entregado por la API.
El refresco vuelve a consultar todas las páginas cargadas y las aplica juntas;
un fallo parcial retiene las filas y el borrador. La carga adicional tiene
error/reintento persistente y bloqueo de doble clic. Cambiar de filtro reinicia
el desplazamiento e invalida peticiones anteriores; ocultar/desmontar evita
continuaciones del refresco. El título sigue contando sólo hilos cargados.
[Evidencia dirigida PERF-02](../evals/inbox-perf-02-2026-10-21/README.md).

WA-GRP-01 agrupa visualmente mensajes consecutivos del mismo autor con separación
inferior a cinco minutos, siempre dentro de cada día de la clínica. Los entrantes
pertenecen al contacto del hilo; los salientes distinguen agente, sistema y cada
empleado por `human_author_public_id`. Sin UUID humano, incluido el optimista antes
de confirmación, se mantiene una burbuja separada. Ningún mensaje pierde cuerpo,
hora, estado o reintento; esta agrupación nunca deduplica ni altera los datos.
[Evidencia dirigida GRP-01](../evals/inbox-grp-01-2026-10-20/README.md).

### Manejo centralizado de errores de formularios

- Utilities:
  - `src/utils/handleFormError.js`: centraliza la lógica para mapear errores DRF a `formErrors` y mostrar toasts globales.
  - `src/utils/mapFieldErrors.js`: normaliza la respuesta de errores DRF a claves planas (soporta colisiones y nested keys).

- Enrutamiento: `{code, errors: {campo: [...]}}` y `{campo: [...]}` van al formulario; `{code, message}` va a un toast, incluidos `403` y `409`. Sus datos extra, como `candidate`, nunca son campos. Dentro de `errors`, `error`, `detail` y `non_field_errors` también van al toast, porque ningún campo los pinta.

- Convenciones obligatorias:
  - Todos los formularios POST/PATCH deben usar `handleFormError(err, setFormErrors)` dentro del `catch`.
  - Al abrir un modal con formulario limpiar errores: `setFormErrors({})`.
  - Usar modo merge limpiando las claves a reemplazar antes de fusionar para evitar errores "stale".

Implementación pragmática en CI:
- El script `scripts/check-handle-errors.sh` detecta archivos con `catch(` en `frontend/src` y filtra aquellos que no importan `handleFormError`.
- Mejoras futuras: pasar a análisis AST para evitar falsos positivos (recomendado a mediano plazo).

### Precondición de estado en citas (INV-A — ADR p57, F5 Fase 2)

Toda mutación de una cita existente viaja con **`expected_state`**: la tupla
`{status, date, start_time}` que el usuario tenía **en pantalla** cuando decidió
actuar. El dominio la compara contra la fila bloqueada, dentro de la misma
transacción que escribe, y responde `409 appointment_changed` si difiere. Es lo
que impide que dos personas —o una persona y el asistente de WhatsApp— se pisen
en silencio: sin ella, gana quien guarda último.

```javascript
import { updateAppointmentStatus, expectedStateOf } from "../api/appointments";

// La cita YA CARGADA es el último argumento — no se relee antes de guardar.
await updateAppointmentStatus(token, appt.public_id, "canceled", appt);
```

**Desde la Fase 3 es OBLIGATORIA**: omitirla es `400 precondition_required` y
cero escrituras. Ya no hay un modo «sin precondición» al que caer.

**Se construye desde la cita ya cargada, nunca releyéndola justo antes de
guardar.** Releer produciría el estado de *después* y la precondición no diría
nada — sería un compare-and-swap contra uno mismo. `expectedStateOf` devuelve
`{}` si la cita no trae la tupla completa; con el gate activo eso ya no «pasa
sin precondición», sino que **falla ruidosamente**, que es lo que se quiere:
una pantalla que no sabe qué estaba mostrando no debería poder escribir.

Lo envían: `updateAppointment`, `updateAppointmentStatus` y `assignPatient`.
`POST` y `walk-in` no (no hay estado previo que comparar).

**Al recibir el 409** — dos utilidades en `utils/apiError.js`:

```javascript
if (isAppointmentChanged(err)) {
    const current = appointmentChangedCurrent(err);   // el estado REAL
    await loadAppointments();                          // recargar
    // …y decirle al usuario QUÉ cambió, para que vuelva a decidir
}
```

Regla corta y sin atajos: **recargar y volver a preguntar, jamás reintentar**.
Reintentar sin `expected_state` es exactamente la sobrescritura que la
precondición existe para impedir. Tampoco se degrada a último-escritor-gana
tras N conflictos, ni se silencia el 409 confirmando que quedó hecho.

El mensaje nunca es «error al guardar»: dice el estado real (vía `statusLabel`,
la fuente única de etiquetas), porque quien lo lee tiene que decidir otra vez.

**`deleteAppointment` se retiró.** `DELETE /appointments/<id>/` está deprecado a
favor de `PATCH /<id>/status/`, que es la vía con auditoría y precondición. No
tenía consumidores, así que dejar la función viva solo invitaba a reintroducir
la vía deprecada.

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

**Cierre de sesión:** `useAuth().logout` envía el refresh a `POST /api/token/logout/` (blacklist) antes de limpiar el almacenamiento, sin esperar respuesta: si falla, la sesión local se cierra igual. Las rutas internas (refresh fallido, `/me/` rechazado) cierran sin llamar al endpoint. **El access token sigue siendo válido hasta expirar (15 min)**: revoca el refresh, no la sesión entera.

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

### Recepciones según el servidor (orden 4, I01)

`components/ReceptionsModal.jsx` no lee nada del navegador: consulta `GET /inventory/receptions/` sin ningún
identificador, así que sirve también en una sesión recién iniciada en un navegador vacío.
`api/inventory.js::receiveStock(presentación, captura, operationId)` prepara y después ejecuta; `localStorage`
guarda como mucho un atajo de reintento (fallar al escribirlo o perderlo no cambia nada).

- Se abre desde el botón «Recepciones» y desde el aviso de pendientes, que `pages/inventory.jsx` carga del servidor.
- **Nunca elige por el usuario**: ni con una sola candidata; resolver exige seleccionarla y confirmar.
- `allowed_actions` lo decide el servidor. Las recepciones identificadas usan siempre la identidad recuperada;
  «Registrar una recepción nueva» es otra acción, con otra identidad.
- Mostrar `applied_lines` como lo que entró y `current_balance` como saldo acumulado: **nunca** presentar el segundo
  como cantidad de la operación.
- Un `409` no se reintenta: se recarga el detalle y se muestra lo que el servidor sabe ahora.
- Refrescar tras resolver sin pasar por `loading` de la página, o se desmonta el panel con la evidencia.

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
