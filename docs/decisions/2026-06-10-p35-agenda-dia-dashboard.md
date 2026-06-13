# ADR p35: Agenda del día en el Dashboard — appointment cards + navegación por día

**Fecha**: 2026-06-10
**Estado**: Implementado

## Contexto

La sección "Agenda de hoy" del Dashboard era un **timeline horizontal** (`OperationalTimeline.jsx`)
alimentado por `summary.timeline` (`GET /api/v1/dashboard/summary/`). Dos limitaciones:

1. **Fijo a hoy**: `summary.timeline` se construye en `_build_timeline_slots` con
   `org_today_local` — no acepta otra fecha. No había forma de ver ayer ni próximos días.
2. **UX de lectura indirecta**: puntos sobre un eje de horas obligaban a interpretar; no
   respondía rápido "quién sigue / qué necesita". La tabla "Próximos turnos" debajo del
   timeline ya era media lista — señal de que la lista era el patrón correcto.
3. **Colisión de slots**: `_build_timeline_slots` emitía solo `slot_appts[0]` por bucket de
   30 min → en una lista, citas en la misma franja desaparecían.

## Decisión

Reemplazar el timeline por una **mini-agenda operativa** con navegación por día, patrón
**appointment cards**, reutilizando infraestructura existente (sin endpoint nuevo).

### Fuente de datos — endpoint existente

`GET /appointments/?date=YYYY-MM-DD` (`AppointmentListCreateView`, ya soportaba `?date=` vía
`filter_by_local_day`). Devuelve `AppointmentSerializer` completo (incluye `owner_name`),
org-scoped, cubre pasado/hoy/futuro. Vía hook nuevo `useDayAppointments(date)` — thin wrapper
sobre `getAppointments` con loading/error/refetch + listener `dashboard:refresh`.

Alternativas descartadas:
- **`summary?date=`** → requería backend (timeline hardcoded a hoy).
- **`status-breakdown` from=to=día** → cero backend pero sus items **no traen `owner_name`**;
  la card quedaría sin tutor.

### Cambios de contrato (backend, aditivos)

1. **`AppointmentSerializer` expone `walk_in`** (`read_only`). El campo ya existía en el modelo
   (`editable=False`, `db_index=True`); solo se añade a `fields`/`read_only_fields`. Sin modelo,
   sin migración, sin permisos. Lo usa la card para el marcador `●` walk-in.
2. **`summary.timeline` ahora trae `appointments[]`** (todas las del bucket) además del alias
   legacy `appointment` (= primera), y cada cita incluye `species`/`breed`. Cambio aditivo
   hecho durante la exploración; **el dashboard ya no consume `timeline`** (la agenda usa
   `appointments/?date=`), pero se deja por compat. `OperationalTimeline.jsx` queda **retirado**
   (no montado, no borrado).

### Frontend

- **`TodayAgendaList`** (reescrito): dueño de `selectedDate`, date strip, fetch por día, conteo,
  empty state. `index.jsx` solo compone (`<TodayAgendaList />` sin props).
- **`AgendaDateStrip`**: mes/año etiqueta (contexto, no botón) + flechas `←/→` que navegan
  **semanas** (no meses) flanqueando 7 chips Lun→Dom. Reencuadre a la semana de la selección
  vía **remount** (`key={isoDate}`), evitando `useEffect`+`setState` (regla
  `react-hooks/set-state-in-effect`).
- **`StatusBadge` + `utils/appointmentStatus.js`**: fuente única visual de estados (antes
  duplicada por componente). Migrados: `TodayAgendaList`, `AppointmentQuickModal`.
- **`AppointmentQuickModal`** (extendido): única fuente de acciones. Se agregan Confirmar
  (`scheduled→confirmed`), Cancelar (`→canceled` con `useConfirm`) y Ver expediente (`done`).
  Reusa `updateAppointmentStatus` y navegación existentes.

### Reglas fijadas

- **`isLate`** ("Pendiente desde hace N min"): solo si `selectedDate==hoy` **y** status
  `scheduled|confirmed` **y** `now > start_time`. Nunca `done`/`canceled`/`no_show`.
- **`isNow`** (resaltado + "Ahora"): solo si día==hoy y status `in_progress`.
- La card muestra **máximo 2 líneas** (mascota·tutor / motivo). Especie/raza/veterinario viven
  en el modal, no en la lista.
- Las acciones viven **solo** en `AppointmentQuickModal` (sin acciones inline ni permisos en la
  lista). Cualquier lista de citas abre ese modal.
- NO volver al timeline.

## Consecuencias

- Recepción puede revisar ayer/hoy/próximos días desde el Dashboard sin ir a Citas.
- Cero endpoint nuevo; un GET por día + refetch en `dashboard:refresh`.
- `summary.timeline` queda como deuda muerta (alias legacy); su limpieza es post-beta.
- TZ: fechas con `Date` local del browser; backend filtra por día local de la org. Posible
  desfase browser≠org tz — aceptado, consistente con `PendingFollowUp`/`statusBreakdown.js`.
- `StatusBadge` sin migrar aún en `billing`/`cash`/`petDetail`/`appointments` (deuda contenida,
  no piecemeal).

## Restricciones respetadas

Sin tocar modelos, estados de citas ni permisos. `walk_in` es la única adición de contrato
backend (campo read_only ya existente en el modelo).
