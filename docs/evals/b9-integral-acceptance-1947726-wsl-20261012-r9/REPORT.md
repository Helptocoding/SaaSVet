# B9E — r9 cerrada: PENDING por entorno y evidencia final incompleta

Decisión del **13-10-2026, America/Mexico_City**, para
`194772677ca4e9fe1a1dec7f4dafa48396a6c583` en `codex/e4-capacity-scheduling`.
La campaña preparada el 12-10 terminó por el guard original de disco durante
la suite completa. **Nueve gates completos PASS**, incluidos el corpus dirigido
**87/87** y B0/B3/B4/B5. La aceptación integral queda **PENDING**.

## Resultados conservados

| Bloque | Gate | IDs/check | Duración del comando (s) |
|---|---|---:|---:|
| directed | PASS | 87 | 1141.479 |
| django-check | PASS | check | 5.131 |
| migration-drift | PASS | check | 6.176 |
| migrate | PASS | check | 148.257 |
| billing-schema | PASS | check | 6.225 |
| b0 | PASS | 17 | 163.583 |
| b3 | PASS | 42 | 374.893 |
| b4 | PASS | 68 | 1318.834 |
| b5 | PASS | 37 | 427.132 |
| full | PENDING, interrumpido | 2.679/3.331 IDs observados | 7289.097 |
| Frontend, seguridad y auditorías advisory | NOT_EXECUTED | 0 | — |
| BASE, BLOCKED_LLM, META_SLOW, DUPLICATE, SATURATION | NOT_EXECUTED | 0 | — |

Los cinco recibos completos de pruebas contienen **251 IDs PASS únicos**.
La suite completa conserva **2.666 PASS, 10 FAIL, 1 ERROR y 2 SKIP**; faltan
**652 IDs** y el recibo final. Sumando las observaciones completas y parciales
hay **2.930 registros sobre 2.723 IDs únicos**, con 207 solapes. Esos totales
describen evidencia observada y no equivalen a una regresión completa aprobada.
Cada bloque tuvo una única corrida formal; no hubo reintentos de pruebas.

Los [recibos por bloque](block-status.json), [conteos deduplicados](execution-summary.json)
y [journal parcial clasificado](full-partial-receipt.json) conservan el detalle.
Las duraciones anteriores son las del comando monitorizado, no las del runner interno.

## Parada y límites de la evidencia

El [STOP original](STOP.json) indica `Backing disk reserve exhausted`, fase
`full`. El primer incumplimiento monitorizado fue a **2026-10-13T07:23:17Z**
(01:23:17 del 13-10 en México): **708,132,864 bytes**, unos **0.66 GiB**,
frente al mínimo de 1 GiB. El recibo del comando registra **267,816,960 bytes**
(unos **255 MiB**) tras la terminación, exit **-9**.
El espacio disponible se recuperó después; no se conoce la causa de la caída y
esa recuperación no valida el bloque interrumpido.

En los monitores formales conservados no se agotó la reserva de memoria de
2 GiB ni se superó el guard de reloj de 1 s. Durante full, Windows tuvo un mínimo
de **2.238 GiB**, y la desviación máxima de
reloj fue **0.000214918 s**. La solicitud de
actividad apareció `ACTIVE_CONFIRMED` en todos los checks. Esto describe las
muestras conservadas, sin afirmar continuidad durante el reinicio posterior.

Windows conserva eventos Kernel-Power 41 y EventLog 6008 de un reinicio
inesperado, con arranque registrado el 13-10 a las 18:08 de México. Los timestamps
del mensaje histórico y del journal se conservan sin inferir una cronología
exacta del apagado ni una causa. Al retomar, tres JSON finales estaban rellenos
de bytes NUL: `invocation-formal.json`, `dependency-check-after-full.json` y
`seal-check-after-full.json`. `invocation-formal.log` tiene una cola de 107 NUL.
Se preservan sus bytes originales; no se fabricaron recibos finales sustitutos.
Véanse [daños observados](damaged-receipts.json), [eventos del host](host-restart-evidence.json)
y [clasificación](incident-classification.json).

La suite fue interrumpida antes de imprimir las trazas finales de unittest.
Los 10 fallos y el error son observaciones reales del journal; su causa sigue
sin clasificar. No se atribuyen al disco, no se descartan por ser tests legacy
y no se convierten en PASS. El journal carece de timestamps por ID para probar
la relación temporal exacta de cada terminación con el incidente.

- `FAIL` — `apps.agent.tests.test_regression_f2.Int20Tests.test_20_01_offer_then_create`
- `FAIL` — `apps.agent.tests.test_regression_f2.Int20Tests.test_20_02_all_slots_direct_to_confirm`
- `FAIL` — `apps.agent.tests.test_regression_f2.Int20Tests.test_20_03_b5_race_slot_taken`
- `FAIL` — `apps.agent.tests.test_regression_f2.Int20Tests.test_20_04_modification_makes_new_pending`
- `FAIL` — `apps.agent.tests.test_regression_f2.Int20Tests.test_20_06_expired_confirmation_never_executes`
- `ERROR` — `apps.agent.tests.test_regression_f2.Int20Tests.test_20_09_b6_fixed_vet_used`
- `FAIL` — `apps.agent.tests.test_regression_f2.Int23Tests.test_23_01_cancel_happy_with_retention`
- `FAIL` — `apps.agent.tests.test_regression_f2.Int23Tests.test_23_02_cancel_requires_paraphrase`
- `FAIL` — `apps.agent.tests.test_regression_f2.Int24Tests.test_24_01_reschedule_happy`
- `FAIL` — `apps.agent.tests.test_regression_f2.Int24Tests.test_24_04_reschedule_race_slot_taken`
- `FAIL` — `apps.agent.tests.test_regression_suite.ReadFlowTests.test_int11_price_flow`

Skips identificados, sin usarlos para cubrir requisitos pendientes:

- `apps.agent.tests.test_regression_f2.Int21Tests.test_21_05_bis_new_pet_existing_owner`: INT-21-bis (mascota nueva de cliente existente) sin tool en PR-17a; el alta reusa create-with-patient — pendiente de PR futuro.
- `apps.analytics.tests.test_snapshot_v1.VisibilityPolicyFutureProofTests.test_visibility_excludes_voided_when_policy_is_excluding_voided`: Placeholder for historical_excluding_voided policy (ADR required)

## Integridad y cierre

Los nueve bloques completados conservaron sus checks de integridad válidos.
Después del reinicio se comprobaron de nuevo **3.332 fuentes**, **13.508 archivos
de dependencias** y **108 archivos del sello**, todos sin diferencias. Son
recibos nuevos de recuperación; no sustituyen los dos checks finales dañados.
El candidato, sus locks, los tests y los helpers evaluativos sellados no cambiaron.

El primer cleanup encontró PostgreSQL apagado. Se arrancó exclusivamente el
clúster privado para conservar propiedad, conexiones, transacciones y tablas
por SQL. El arranque superó el timeout de pg_ctl pero terminó su recuperación;
se comprobó que estaba listo antes de continuar. Se conservaron los intentos
fallidos del cierre, incluido un inventario que contó su propio wrapper RTK.
El [cleanup final](cleanup.json) retiró las bases propias, apagó PostgreSQL,
cerró el puerto 35479 y eliminó únicamente el workspace exacto de r9.
No se ejecutaron tests durante la recuperación.

WSL está `active/running/enabled` para systemd-timesyncd, igual al estado
original. Los PIDs originales del observador y la solicitud de actividad están
ausentes. Faltan los recibos de cierre normal de esos procesos y del guardián;
no se afirma que sus bloques finally terminaran ni que se probara la llamada
explícita de restauración del thread. Véanse [estado del reloj](clock-restoration.json)
y [ausencia de procesos](monitor-closure-after-restart.json). W32Time y las
políticas globales de energía/pantalla no se modificaron.

Se verificaron **1623 archivos de nueve campañas anteriores** sin cambios,
además de los tres cambios ajenos registrados. El reporte inicial de r9 anterior
a su reanudación sigue en [su copia histórica exacta](preparation-history/REPORT-before-resumption.md).
La nueva documentación de recuperación queda fuera del evaluador sellado.

## Decisión y conservación

La [matriz R01–R15/I01–I14](candidate-decision.json) usa solamente esta campaña:
cobertura dirigida PASS donde existe recibo, regresión integral y PROFILE
pendientes. Activación **PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING con
limitación aceptada y cero nuevos intentos físicos; E/P/UX y aprobaciones
operativas/privacidad siguen separados. Sin commits, push, despliegue ni activación.

Una campaña nueva exige decisión separada y un volumen que sostenga la reserva
original de 1 GiB con margen para preparación y fluctuaciones, además de
continuidad del host y nuevo preflight. Esta campaña queda cerrada y no se reanuda
desde el punto de corte. Los fallos parciales siguen disponibles para un diagnóstico
separado. [Requisitos para avanzar](environment-remediation.json).

[Índice y recuperación](README.md). El resultado del empaquetado y de la selección
Git explícita se acredita en los recibos de entrega enlazados allí; no implica un commit.
