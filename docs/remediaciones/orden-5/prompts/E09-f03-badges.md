# E09 — F03: badges de estados de cita

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Consolidar los estados de cita en la fuente única `utils/appointmentStatus.js`. Corrige un bug visible: `petDetail` solo conoce 3 de los 6 estados, y `confirmed`, `in_progress` y `no_show` salen con el badge vacío.

**Solo aplica a citas.** `billing.jsx` y `cash.jsx` muestran estados de cobro y de caja; `useAppointmentsByStatus` usa etiquetas en plural para gráficas. No los toques.

## Archivos permitidos

- `frontend/src/pages/petDetail.jsx`
- `frontend/src/pages/petDetail.test.jsx` (nuevo)
- `frontend/src/components/dashboard/AppointmentBreakdown.jsx`
- `frontend/src/components/dashboard/AppointmentBreakdown.test.jsx` (nuevo)
- `frontend/src/components/StatusBadge.test.jsx` (nuevo)
- `docs/modules/frontend.md` (una frase)
- Expediente del orden 5

## Paso 1. `petDetail.jsx`

1. Añade `import StatusBadge from "../components/StatusBadge";`.
2. Elimina las constantes locales `STATUS_BADGE` y `STATUS_LABEL`.
3. Sustituye:

   ```jsx
   <span className={STATUS_BADGE[appt.status] || "badge badge-default"}>
       {STATUS_LABEL[appt.status]}
   </span>
   ```

   por `<StatusBadge status={appt.status} />`.

## Paso 2. `AppointmentBreakdown.jsx`

1. Añade `import { statusLabel } from "../../utils/appointmentStatus";`.
2. Elimina la constante `STATUS_LABELS`. Conserva `PILL_CLASS`: son pills, no badges.
3. Cambia `STATUS_LABELS[selectedStatus]` por `statusLabel(selectedStatus)` y `STATUS_LABELS[status]` por `statusLabel(status)`.

## Paso 3. Pruebas

`src/components/StatusBadge.test.jsx`: con `it.each`, para los seis estados comprueba la etiqueta y la clase.

| status | etiqueta | clase |
|---|---|---|
| `scheduled` | Programada | `badge-info` |
| `confirmed` | Confirmada | `badge-purple` |
| `in_progress` | En consulta | `badge-warning` |
| `done` | Completada | `badge-success` |
| `canceled` | Cancelada | `badge-danger` |
| `no_show` | No se presentó | `badge-default` |

Añade un caso de estado desconocido: muestra el valor crudo y clase `badge-default`.

`src/components/dashboard/AppointmentBreakdown.test.jsx`: envuelve en `MemoryRouter`. Con `statusOrder={["confirmed","no_show"]}`, `totals={{confirmed:2,no_show:1}}` y `byStatus={{confirmed:{items:[]},no_show:{items:[]}}}`, comprueba `Confirmada (2)` y `No se presentó (1)`. Con `selectedStatus="confirmed"`, comprueba que el título también contiene `Confirmada (2)`.

`src/pages/petDetail.test.jsx`: regresión del bug.

- Simula `../api/pets` (`getPet` resuelve un objeto con `name`, `species`, `birth_date`, `owner_name`), `../api/medicalRecords` (`getMedicalRecords` resuelve `[]`), `../api/client` (default con `get` que resuelve `{ data: [...] }`) y `../auth/authContext` (`useAuth` devuelve `{ token: "t", user: { id: 1 }, initializing: false }`).
- Simula `../components/ImportedDataSection` con un componente vacío.
- Renderiza en `MemoryRouter` con `initialEntries={["/pets/abc"]}` y una `Route` `/pets/:id`.
- Devuelve tres citas con estados `confirmed`, `in_progress` y `no_show`.
- Pulsa la pestaña cuyo nombre empieza por `Citas` y comprueba los textos `Confirmada`, `En consulta` y `No se presentó`.

No simules `StatusBadge` ni `appointmentStatus`.

## Paso 4. Documentación

En `docs/modules/frontend.md`, sección StatusBadge, sustituye la frase que empieza con `Migrados a \`StatusBadge\`` por:

> Migrados: `TodayAgendaList`, `AppointmentQuickModal`, `petDetail`. `AppointmentBreakdown` usa `statusLabel` con pills propias. `billing` y `cash` muestran estados de cobro y de caja, fuera de este componente.

## Verificación

```
rtk proxy node_modules/.bin/vitest run src/components/StatusBadge.test.jsx src/components/dashboard/AppointmentBreakdown.test.jsx src/pages/petDetail.test.jsx --reporter=dot 2>&1 | tail -15
rtk proxy node_modules/.bin/eslint src/pages/petDetail.jsx src/pages/petDetail.test.jsx src/components/dashboard/AppointmentBreakdown.jsx src/components/StatusBadge.test.jsx
pnpm run build
```

Recuento total: **0 errores**.

## Cierre

Commit: `fix(frontend): show every appointment status on the pet record (order 5, F03)`.

F03 queda `EN_CURSO` hasta E10.
