# Diagnóstico acotado de r9 — 13-10-2026

**Los 11 resultados problemáticos se reproducen: 10 FAIL y 1 ERROR.**
Se ejecutó una única suite de 11 IDs sobre el candidato
`194772677ca4e9fe1a1dec7f4dafa48396a6c583`, con Python 3.13.2, Django 6.0.5, PostgreSQL 16.15 privado y el lock original.
No hubo incidente invalidante de recursos o reloj. Este diagnóstico identifica
problemas reproducibles con margen suficiente; la caída de disco de r9 no es
necesaria para reproducirlos.

No es una nueva campaña integral ni sustituye sus gates. r9 conserva PENDING,
sus recibos dañados y todos sus resultados originales. Frontend, seguridad y
PROFILE no se ejecutaron aquí. No se cambió producto, tests, fixtures o umbrales.

## Qué se observó

| Test | Resultado | Clasificación observable |
|---|---|---|
| test_regression_f2.Int20Tests.test_20_01_offer_then_create | FAIL | PROPOSAL_STATE_EXPECTATION_NOT_MET |
| test_regression_f2.Int20Tests.test_20_02_all_slots_direct_to_confirm | FAIL | PROPOSAL_STATE_EXPECTATION_NOT_MET |
| test_regression_f2.Int20Tests.test_20_03_b5_race_slot_taken | FAIL | SLOT_RACE_COMMIT_BRANCH_NOT_REACHED_AS_EXPECTED |
| test_regression_f2.Int20Tests.test_20_04_modification_makes_new_pending | FAIL | PROPOSAL_STATE_EXPECTATION_NOT_MET |
| test_regression_f2.Int20Tests.test_20_06_expired_confirmation_never_executes | FAIL | EXPIRY_BRANCH_NOT_REACHED_AS_EXPECTED |
| test_regression_f2.Int20Tests.test_20_09_b6_fixed_vet_used | ERROR | APPOINTMENT_CREATION_PRECONDITION_NOT_MET |
| test_regression_f2.Int23Tests.test_23_01_cancel_happy_with_retention | FAIL | PROPOSAL_STATE_EXPECTATION_NOT_MET |
| test_regression_f2.Int23Tests.test_23_02_cancel_requires_paraphrase | FAIL | PROPOSAL_STATE_EXPECTATION_NOT_MET |
| test_regression_f2.Int24Tests.test_24_01_reschedule_happy | FAIL | PROPOSAL_STATE_EXPECTATION_NOT_MET |
| test_regression_f2.Int24Tests.test_24_04_reschedule_race_slot_taken | FAIL | SLOT_RACE_COMMIT_BRANCH_NOT_REACHED_AS_EXPECTED |
| test_regression_suite.ReadFlowTests.test_int11_price_flow | FAIL | STATIC_CONTRACT_CONFLICT_PRICE_RENDERING |

Seis tests WRITE no llegan a `awaiting_confirmation`: cinco devuelven
`planner_reply` y uno `reply`. Otros dos esperan `commit_slot_taken` y reciben
`reply`; el de vencimiento espera `confirm_expired` y recibe `reply`. El décimo
caso WRITE lanza `Appointment.DoesNotExist` antes de verificar el veterinario.
Estas trazas muestran fallos de las expectativas de la regresión; no prueban
por sí solas una escritura indebida, una carrera mal resuelta ni la ejecución
de una confirmación vencida.

La hipótesis de incompatibilidad del fixture F2 con B6 tiene apoyo estático:
`legacy_write_component` sustituye fronteras de confirmación, pero
`goals.capture` conserva la exigencia de evidencia de binding para los parámetros.
El guion legacy aporta parte de ellos mediante una llamada de herramienta
scripted. Faltan valores internos de la llamada que falla para cerrar la causa
exacta; no se declara que todos los casos WRITE sean tests obsoletos ni un defecto
de producto. El siguiente trabajo debe distinguir esos dos casos con cambios
explícitos y comprobables, sin rebajar las garantías de B6.

En precio hay una discrepancia concreta de contrato: el test pide
`T0_GUARD_BLOCKED` y ausencia de `350`, mientras la respuesta real es
**`Consulta general: $350.00 MXN.`**. El código actual reemplaza la prosa libre
del modelo por un render de datos READ validados. Los tests B2 del mismo candidato
exigen precio y moneda del catálogo; B0 bloquea precios no respaldados por esa
lectura. Por eso esta aserción legacy contradice el renderer vigente. Corregirla
requiere conservar la prueba de que la prosa sensible del LLM no se emite y de
que el precio corresponde al servicio/moneda; no basta con quitar el assert.

[Clasificación por ID y límites](diagnostic-classification.json) ·
[Tracebacks persistidos por ID](diagnostic.ids.jsonl) ·
[Recibo de la suite](diagnostic.results.json) ·
[Recibo del proceso](diagnostic.command.json) ·
[Fuentes exactas usadas para la clasificación](source-evidence.json).

El valor `exit_code: 11` del recibo de suite conserva el retorno de
`DiscoverRunner.suite_result` (10 fallos + 1 error). El proceso de tests terminó
con **exit 1**. El controlador/capturador terminó con **exit 0** al haber guardado
correctamente ese resultado; ese cero no significa tests aprobados.

## Validez y cierre

El proceso monitorizado tardó **192.960 s**, incluida
la creación/migración/destrucción de la base. unittest reportó 11 tests en
21,280 s; el recibo del runner cubre un intervalo más amplio.
En 187 muestras, el mínimo de RAM libre fue
**3.739 GiB en Windows** y
**6.957 GiB en WSL**; C: mantuvo al menos
**9.689 GiB**. Desviación máxima de reloj:
**0.000002041 s**. Se conservaron los umbrales de
2 GiB de RAM, 1 GiB de disco y 1 s de reloj. Los tracebacks se guardaron y
sincronizaron al disco al producirse cada fallo.

Las **3.332 fuentes**, **13.508 dependencias** y **18 archivos de sello** pasaron
las comparaciones antes y después. El scope fue exactamente los 11 IDs
autorizados: sin omisiones, skips, xfail o pruebas adicionales.

Cleanup PASS: Django retiró la base de tests al terminar; se guardó el inventario
SQL y se retiró la base de control, PostgreSQL, el puerto 35480 y el workspace
propio. El observador cerró y la solicitud temporal de actividad restauró el
estado original de su thread. systemd-timesyncd permaneció active/running/enabled;
no se pausó sincronización ni se cambió W32Time o una política global de energía.
Se comprobaron **1966 archivos anteriores**, incluidos los de r9, sin cambios,
además de los tres cambios ajenos del checkout. El acta anterior sigue intacta.

## Qué hace falta para avanzar

Reconciliar las expectativas legacy con el contrato actual: confirmar y resolver
el origen de los casos WRITE sin debilitar B6, y actualizar la prueba de precio
para distinguir datos validados de prosa no respaldada. Eso constituye un encargo
de corrección separado y produce un candidato nuevo si cambian tests o producto.
Una nueva aceptación integral se decide después de esas correcciones y de su
verificación; el espacio recuperado por sí solo no elimina estos fallos.

No hubo commits, push, despliegue o activación. R1-04 y los requisitos de
activación/operación/privacidad siguen como estaban. La evidencia nueva se
conserva en un paquete propio con recuperación verificada y selección Git
explícita: [índice de recuperación](RECOVERY.md).
