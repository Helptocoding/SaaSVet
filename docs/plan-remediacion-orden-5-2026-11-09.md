# Orden 5 — Calidad del frontend y experiencia de uso

Fecha: **9 de noviembre de 2026**. Estado: **PLAN ACORDADO PARA IMPLEMENTACIÓN LOCAL**. Prepara el trabajo de otro agente; no acredita remediación ni despliegue.

Base: [priorización, §5](plan-remediacion-priorizado-2026-10-28.md), [inventario](pendientes-documentados-2026-10-27.md), [deuda fase 4](deuda/fase4-prioridad-baja.md), [P1-4](p1-4-frontend-reliability.md) y decisiones del usuario del 09-11. Ejecución: [expediente y prompts por entrega](remediaciones/orden-5/README.md).

## 1. Decisiones vinculantes

| Tema | Decisión |
|---|---|
| Ejecutor | Claude Sonnet, con un prompt autocontenido por entrega. El usuario los pasa uno a uno y revisa entre ellos, porque el metaprompt único del orden 4 necesitó cuatro continuaciones. |
| Alcance | Los ocho IDs: F01, C3, C4, C5, C6, F02, F03 y F04. |
| Git | Rama nueva `fix/orden-5-calidad-frontend` desde `c3f42ba`. Un commit por entrega, sin push, PR, merge ni despliegue. |
| Lint, política | Triage por sitio. Se corrige lo que es estado derivado o reseteo. Lo que es sincronización legítima lleva `eslint-disable-next-line <regla> -- <motivo>`. Bajar reglas a warning queda excluido. |
| Lint, gate | Al cerrar, `lint` bloquea CI **solo por errores**. Los warnings `exhaustive-deps` siguen visibles y no se tocan, porque añadir dependencias cambia cuándo corren los efectos (P1-4). |
| `frontend/standalone` | Se excluye de ESLint con `globalIgnores`. Está ignorado por git y CI nunca lo ve. Borrarlo queda fuera de alcance. |
| C3 | Se mueve `AuthProvider` a `auth/AuthProvider.jsx` y `authContext` conserva contexto y hook. **Sustituye el criterio escrito en la deuda**, que pedía crear `useAuth.js` y repuntar unos 58 archivos, 20 de ellos `vi.mock`. Igual para `ActivationProvider`. |
| C4 | Una sola fuente de `sum/remaining/change`: `paymentSummary` en `utils/payments.js`. `paymentLinesValid` conserva su suma propia, que tiene otro contrato. |
| `allowPartial` | Se retira por completo en una entrega propia. Es código muerto que contradice la regla de total exacto (ADR p30 rev). Implica cambiar únicamente las aserciones de pago parcial. |
| F03, badges | `StatusBadge` es solo para citas. Se migran `petDetail` y `AppointmentBreakdown` (E09), y la agenda `appointments.jsx` (E09b, añadida tras revisar E09). `billing` y `cash` muestran estados de cobro y de caja: la lista documentada estaba equivocada y se corrige. |
| F03, tabla | La tabla de Inventario migra a `.table-wrap`/`.table` y al `SortHeader` compartido. Adopta el CSS real: encabezado claro y sin cebra, como Cobros. `design-system.md` se corrige porque describe un encabezado oscuro que `global.css` ya no aplica. |
| Código muerto | Se borra el componente `Appointments` de `pages/appointments.jsx` (648 líneas sin importadores), su export con nombre, `ApptBadge` y `apptHour`. |
| F02 | Se extraen tal cual a `components/billing/` `RefundModal`, `DispenseLotSelect` y `PrescriptionDispensePanel`. Las pruebas de caracterización llegan después de moverlos, sin cambiar lógica. |
| Fuera de alcance | Backend, migraciones, bases de datos, VPS, dependencias, rediseños y limpieza no listada. Sin ADR nuevo: ningún cambio altera arquitectura, persistencia ni reglas críticas. |

## 2. Cobertura de los ocho pendientes

| ID | Prioridad | Entrega | Cierre |
|---|---|---|---|
| F01 | P2 | E00, E05–E08, E12 | App con 0 errores de lint, cada supresión con motivo, gate bloqueante de errores en CI. |
| C5 | P2 | E02 | Select, importe y botón de quitar con nombre accesible; pruebas por rol y nombre. |
| C4 | P2 | E02, E03 | Sin matemática inline en el editor; `allowPartial` retirado. |
| C3 | P2 | E04 | Archivos de contexto sin componentes; `AuthProvider` y `ActivationProvider` exportan solo componentes. |
| C6 | P3 | E01 | Docstring fiel a la implementación, sin tocar código. |
| F04 | P3 | E01 | «Usuario» en lugar de «Username» en alta de organización. |
| F03 | P3 | E09, E10 | Badges de citas consolidados; un solo `SortHeader`; una sola tabla. |
| F02 | P3 | E11 | Tres subcomponentes en archivos propios, con pruebas de caracterización. |

## 3. Evidencia de partida

Medido el 09-11-2026 sobre `c3f42ba`, working tree limpio, CI de la rama en verde.

| Fuente | Observación | Implicación |
|---|---|---|
| `eslint .` | 197 errores y 20 warnings: `standalone` 136/1 (129 en `dist`), app 61/18, `__smoke__` 0/1. | El dato de 198 del inventario incluía ruido local. CI solo ve la app. |
| Reglas en app | `set-state-in-effect` 34, `immutability` 8, `no-empty` 6, `no-unused-vars` 4, `preserve-manual-memoization` 4, `only-export-components` 2, `refs` 2, `purity` 1. | Ver §4. |
| Vitest completo | 814 pruebas: 810 pasan y 4 fallan por `Test timed out in 5000ms` en `pages/inbox/index.test.jsx`, tras 429 s en paralelo. El archivo solo pasa 93/93. | Son timeouts por carga, no regresiones. Regla en los prompts. |
| `PaymentLinesEditor` | `sum/remaining/change` inline; sin nombres accesibles. | C4 y C5. |
| `paymentLinesValid` | Suma solo positivos tras rechazar negativos. El editor suma todo, incluidos negativos (`Ingresado $-50.00`, anclado por test). | No unificar esa suma. |
| `allowPartial` | Ningún caller lo activa: `payAllowPartial` es `false` constante. El texto menciona el estado «confirmada», ya retirado. | Se retira. Es un parámetro posicional: sus callers se corrigen a la vez. |
| `authContext` | 59 archivos lo mencionan, 20 con `vi.mock`. Solo `App.jsx` y `authContext.logout.test.jsx` importan `AuthProvider`. | Por eso se mueve el Provider. |
| `StatusBadge` | Usado solo para citas. `petDetail` tiene un mapa de 3 estados: `confirmed`, `in_progress` y `no_show` salen con badge vacío. | Bug visible que F03 corrige. |
| `billing.jsx` | 1439 líneas. Sin ninguna prueba. | F02 mueve primero y prueba después. |
| `billing.jsx:365` | `const updated = await toast.promise(...)` usa el patrón que `frontend.md` documenta como incorrecto. `handleDispensed` ignora su argumento, así que hoy no causa daño. | No se cambia en F02. Registrado como observación. |
| `global.css` frente a `design-system.md` | El CSS tiene encabezado `--c-surface-2` sin cebra; la doc dice `--ink` con cebra. | Se corrige la doc. |
| `appointments.jsx` | Default export `EventManagerAppointments`. `Appointments` (949–1596) solo tiene un export con nombre sin importadores. | Código muerto; concentra 3 errores de lint. |

## 4. Triage de F01: los 61 errores

Cada veredicto se **validó en memoria** el 09-11 aplicándolo con `ESLint.lintText` sobre el código actual, sin escribir en el repositorio. El resultado dejó solo 3 errores: los 2 `only-export-components` que resuelve C3 y `apptHour`, que se elimina junto al componente muerto. Los prompts contienen el cambio exacto de cada sitio.

| Veredicto | Sitios | Motivo |
|---|---|---|
| Separar archivo | `authContext`, `activationContext` | C3. |
| Eliminar | `appointments.jsx` (componente muerto), estados `unitChoices`/`unitsLoaded` de inventario, import `useAuth` de config, prop `labelByKey` de `ReviewPanel` | Código sin uso. |
| Corregir | 5 gráficas con color CSS (estado inicial perezoso), `PreviewStep` (`selected` inicial perezoso), `AppointmentList` (reset durante render), `useAgendaTour` (ref en efecto), `MultiPresentationAnimation` (orden de declaración), `staff`, `inventory`, `medicalRecords/index` (función hoisted) | Estado derivado, reseteo o uso antes de declarar. |
| Comentar `catch` | 5 en config y 1 en agenda | `toast.promise` ya informó; un bloque vacío con motivo no es error. |
| Suprimir con motivo | Hooks de datos, auth, sincronización con DOM, props o URL, señales del router, `petDetail` | Sincronización legítima con un sistema externo. |

## 5. Trampas que los prompts cubren

- `paymentLinesValid` usa parámetros posicionales: retirar `allowPartial` sin actualizar a sus callers desactivaría el cambio en efectivo sin ningún error visible.
- `no-unused-vars` ignora nombres en mayúscula (`varsIgnorePattern: '^[A-Z_]'`): lint no detecta componentes ni imports en mayúscula sin uso.
- Una directiva `eslint-disable-next-line` va en la línea inmediatamente anterior a la reportada; en `StockEntryModal` hoy está debajo y no surte efecto.
- `inventory.module.css` lo importan también `StockEntryModal` y `ReceptionsModal`. Ninguno usa las clases de tabla, comprobado el 09-11.
- `react-hooks/set-state-in-effect` informa una vez por efecto: la directiva cubre el efecto completo.

## 6. Entregas

| Entrega | Contenido | Errores de lint al terminar |
|---|---|---|
| E00 | Rama, commit de documentos, exclusión de `standalone`, línea base | 61 |
| E01 | C6 y F04 | 61 |
| E02 | C4 y C5 | 61 |
| E03 | Retiro de `allowPartial` | 61 |
| E04 | C3 | 59 |
| E05 | F01: auth y hooks | 50 |
| E06 | F01: componentes, dashboard y tours | 34 |
| E07 | F01: `appointments`, `inventory`, `petDetail`, `staff` | 18 |
| E08 | F01: `config`, `analytics`, `imports`, `medicalRecords` | 0 |
| E09 | F03: badges de citas | 0 |
| E09b | F03: badges de la agenda (añadida tras revisar E09) | 0 |
| E10 | F03: tabla de Inventario y `SortHeader` | 0 |
| E11 | F02: dividir `billing.jsx` | 0 |
| E12 | Gate de CI, salvaguarda de supresiones, documentos y cierre | 0 |

El orden importa: C3 precede a la limpieza de auth para que las supresiones caigan en el archivo definitivo, y E03 precede a E11 para mover código ya limpio.

## 7. Verificación y límites

- Cada entrega: lint de los archivos tocados, pruebas dirigidas y, cuando cambian imports, build. Comandos exactos en las [reglas comunes](remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md).
- E00, E04, E08, E09b y E12 ejecutan además la suite completa.
- La verificación visual de E10 y de las gráficas de E06 puede quedar a cargo del usuario si el agente no dispone de backend y navegador. Se declara como pendiente; no se afirma.
- Sin datos reales en juego: ninguna entrega usa base de datos.
- Las líneas citadas corresponden a `c3f42ba` y se desplazan entre entregas: el agente localiza por símbolo o por texto.

## 8. Estado final esperado

F01, C3, C4, C5, C6, F02, F03 y F04 podrán declararse **IMPLEMENTADOS_Y_VERIFICADOS_LOCALMENTE** únicamente con la evidencia de `docs/remediaciones/orden-5/EVIDENCIA.md`. Eso no acredita despliegue. El gate de CI solo queda probado cuando el usuario suba la rama.

## 9. Revisión entre entregas

Antes de lanzar la siguiente entrega, comprobar:

1. El reporte trae `COMPLETA`, un hash de commit y la salida de los comandos.
2. `git show --stat HEAD` solo contiene archivos que el prompt autoriza.
3. El recuento de errores coincide con §6.
4. Ninguna aserción se debilitó ni se añadió `.skip`, salvo las de pago parcial en E03.
5. Las supresiones nuevas llevan ` -- motivo`.
