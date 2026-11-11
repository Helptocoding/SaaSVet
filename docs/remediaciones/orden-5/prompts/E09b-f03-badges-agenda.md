# E09b — F03: badges de estado en la agenda

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Terminar la consolidación de badges de citas que empezó E09. La agenda real (`EventManagerAppointments`, en `pages/appointments.jsx`) conserva sus propios mapas `S_BADGE` y `S_LABEL`. Ahí `no_show` usa `badge-secondary`, una clase que no existe en el CSS: el badge «No se presentó» sale sin fondo ni color. La fuente única ya lo define como `badge-default` (ADR p35).

Esta entrega se añadió tras revisar E09: el plan original no incluía la agenda.

## Archivos permitidos

- `frontend/src/pages/appointments.jsx`
- `docs/modules/frontend.md` (una frase)
- Expediente del orden 5
- Solo para el commit, sin editarlos: este prompt, `docs/remediaciones/orden-5/README.md` y `docs/plan-remediacion-orden-5-2026-11-09.md` (ver Cierre)

## Paso 1. Imports en `appointments.jsx`

1. Cambia `import { statusLabel } from "../utils/appointmentStatus";` por:

   ```js
   import { statusLabel, statusBadgeClass } from "../utils/appointmentStatus";
   ```

2. Añade, junto a los demás imports de `../components/`:

   ```js
   import StatusBadge from "../components/StatusBadge";
   ```

## Paso 2. Eliminar los mapas locales

Elimina completas las constantes `const S_BADGE = { ... };` y `const S_LABEL = { ... };`, que están justo antes de `const APPOINTMENT_CATEGORIES`. No toques `APPOINTMENT_CATEGORIES` ni las paletas de color.

## Paso 3. Badge del modal de detalle

En el `modal-header` del modal de detalle de la cita, sustituye:

```jsx
<span className={`badge ${S_BADGE[appt.status] || "badge-info"}`}>
    {S_LABEL[appt.status] || appt.status}
</span>
```

por:

```jsx
<StatusBadge status={appt.status} />
```

## Paso 4. Historial de cambios de estado

En el historial (`history.map(h => (`), conserva las etiquetas `h.from_status_display || h.from_status` y `h.to_status_display || h.to_status`: vienen del backend. Cambia solo la clase:

| Antes | Después |
|---|---|
| `` className={`badge ${S_BADGE[h.from_status] \|\| "badge-default"}`} `` | `` className={`badge ${statusBadgeClass(h.from_status)}`} `` |
| `` className={`badge ${S_BADGE[h.to_status] \|\| "badge-default"}`} `` | `` className={`badge ${statusBadgeClass(h.to_status)}`} `` |

Conserva el `style={{fontSize:"10px"}}` de ambos.

## Paso 5. Listas de la agenda

Este texto aparece **exactamente 3 veces**, dentro de líneas muy largas: la lista del día, la lista agrupada por fecha y la vista lista del calendario.

```jsx
<span className={`badge ${S_BADGE[appointment.status]}`}>{S_LABEL[appointment.status]}</span>
```

Sustituye las tres por:

```jsx
<StatusBadge status={appointment.status} />
```

Usa una sustitución de texto exacto. No reformatees esas líneas ni toques nada más de ellas. Si no encuentras exactamente 3 apariciones, detente con `BLOQUEADA`.

## Paso 6. Documentación

En `docs/modules/frontend.md`, sección StatusBadge, cambia `` Migrados: `TodayAgendaList`, `AppointmentQuickModal`, `petDetail`. `` por:

```markdown
Migrados: `TodayAgendaList`, `AppointmentQuickModal`, `petDetail` y la agenda (`appointments.jsx`).
```

El resto de la frase no cambia.

## Verificación

```
grep -n "S_BADGE\|S_LABEL\|badge-secondary" src/pages/appointments.jsx
grep -c "<StatusBadge status=" src/pages/appointments.jsx
grep -c "statusBadgeClass(h\." src/pages/appointments.jsx
rtk proxy node_modules/.bin/eslint src/pages/appointments.jsx
rtk proxy node_modules/.bin/vitest run src/components/StatusBadge.test.jsx --reporter=dot 2>&1 | tail -15
pnpm run build
```

El primer `grep` no debe devolver nada; el segundo debe dar `4` y el tercero `2`.

La agenda no tiene pruebas propias. Ejecuta también la suite completa para descartar imports rotos.

Recuento total: **0 errores**. Los warnings deben seguir en 14.

## Cierre

Commit: `fix(frontend): use the shared status badge in the agenda (order 5, F03)`.

Incluye en el mismo commit, **sin editarlos**, los tres documentos que añadieron esta entrega al expediente: este prompt (`docs/remediaciones/orden-5/prompts/E09b-f03-badges-agenda.md`), `docs/remediaciones/orden-5/README.md` y `docs/plan-remediacion-orden-5-2026-11-09.md`. Antes de empezar, `git status` debe mostrarlos modificados o sin seguimiento junto con `MATRIZ.md`; cualquier otro archivo pendiente es motivo de `BLOQUEADA`.

F03 sigue `EN_CURSO` hasta E10. En «Para revisar», indica mirar en la agenda una cita «No se presentó»: ahora debe verse con fondo gris.
