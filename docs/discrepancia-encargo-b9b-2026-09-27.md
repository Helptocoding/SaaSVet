# B9B — Preflight bloqueado por discrepancia contractual

Fecha: 2026-09-27. Estado del encargo: **BLOCKED antes de implementar**.
B9 canónica: **IN_PROGRESS**. No se modifica el plan ni el mapa de progreso.

## Baseline y cambios preexistentes

HEAD verificado: `ccd49844e6e777395517a0527f564faf7fc5b0f2`, exactamente el solicitado.
Estado inicial registrado:

```text
 D DEPLOY_VPS_PLAN.md
 D DEPLOY_VPS_STATUS.md
?? docs/auditoria-agente-conversacional-veterinario-2026-09-10.md
?? docs/discrepancia-encargo-b9-2026-09-26.md
```

Todos se preservan. El único archivo añadido por este preflight es este informe.
No hay commits, cambios de runtime, configuración, migraciones ni datos.

## Autoridades leídas

- §7/B9 completo de `plan-implementacion-auditoria-agente-whatsapp-2026-09md`, líneas 703–732.
- `mapa-interno-b9-2026-09-26.md` completo, incluida su extracción literal de B9.
- `contrato-harness-b9a.md` e `implementacion-b9a-agente-whatsapp-2026-09-26.md` completos.
- Encargo adjunto B9B y reglas RTK del proyecto.

El mapa asigna R03/R05/R11 a B9B. La restricción de R12 también obliga a B9B.

## Discrepancias que activan el STOP del encargo

1. **Unidad y alcance del presupuesto.** B9 requiere presupuesto operativo por
   TurnWork, reserva de llamadas/cupo bajo witness y límites fijos. El encargo §9
   pide descubrir y respetar esa unidad, pero §10 exige periodo con timezone,
   rollover y frontera; §30 exige inspector por tenant/periodo; §36–37 exigen
   aceptación de fronteras de periodo y cambios de budget. B9 no define un
   periodo monetario ni una autoridad de gasto por clínica. Implementarlos
   supondría ampliar el contrato; omitirlos incumpliría esas obligaciones del
   encargo. La atribución tenant-scoped y la medición de coste sí son compatibles.
2. **Estados y alcance económico.** §6 pide una máquina de estados durable y
   §7/24 modelan reserva/consumo/liberación de coste como autoridad de admisión.
   El plan exige reutilizar LLMCall y contadores por trabajo y dice expresamente
   «no nuevos estados, tabla de billing ni presupuesto global distribuido».
   Una representación equivalente dentro de los datos permitidos podría ser
   viable, pero no autoriza introducir estados o un ledger de billing separado.
   Es necesario acotar el encargo a esa representación y al cupo por turno.
3. **Garantías canónicas omitidas como requisitos explícitos.** El encargo no
   exige expresamente actualizar reservas bajo el witness B3 ni conservar las
   llamadas admitidas frente al rollback del intento. Sus reglas de deduplicación
   y liberación no sustituyen esos requisitos, ni los máximos timeout/calls/tokens
   por turno. Deben conservarse aunque se conozca coste cero o no haya dispatch.
4. **Identidad del hito.** §44 dice literalmente «Mantén explícito B9B = B9
   canónico completo», mientras §0/45/47 y el mapa establecen que B9B es solo un
   hito interno y que B9 seguirá IN_PROGRESS. No se puede documentar esa igualdad.

No se afirma que pricing versionado o conservar usage detallado estén prohibidos;
el bloqueo corresponde a obligaciones de alcance y aceptación incompatibles o
sin definición canónica, y a garantías obligatorias omitidas. No se diseña una
tabla monetaria para intentar resolver la contradicción.

## Extracción literal de los requisitos asignados a B9B

Plan, cambio técnico 2 (línea 714):

> metrics.py, llm.py y operation_authorization.py::_classify/_verify/_persist_llm_call: registrar todas las llamadas/roles/retries y límites de timeout/calls/tokens máximos por turno. Coste/usage desconocido no es cero. Reusar LLMCall; correlación a TurnWork nullable se introduce con este consumidor. Un intento recuperado cuenta llamadas anteriores del mismo trabajo al aplicar presupuesto; no otorgar cupo infinito por restart.

Plan, cambio técnico 4 (línea 716):

> Presupuesto por turno con reserva de llamadas/cupo máximo antes de llamar, actualizada bajo witness; rollback de intento no repone llamadas ya admitidas. No reservas distribuidas de gasto diario ni cuotas globales de urgencias ahora. Si los límites fijos no pasan el perfil, reducir alcance o ejecutar el mecanismo concreto E4 justificado por medición.

Plan, datos/migración (línea 727):

> FK LLMCall→TurnWork si falta; contadores de llamadas/cupo reservado por trabajo solo para presupuesto operativo (default 0 para nuevos; legacy desconocido no inventado). Reusar configuración existente o constantes de release para límites fijos; no nuevos estados, tabla de billing ni presupuesto global distribuido. Uso desconocido se expone y admite fallback conservador.

Plan, tests (línea 725):

> EVAL-01/02: fila queued no delivered, stub no responde a pending, release incompleto no aprobado. COST-01: planner+authorizer+verifier+retry+timeout contados; restart no reinicia presupuesto. SCALE-01: org ruidosa no ocupa todos los planners y sender progresa con LLM bloqueado; SCALE-02: timeout/Meta lento no pierden guidance ni abren permiso. Archivos test_metrics.py, test_llm.py, test_worker.py, test_regression_suite.py y test_corpus_conversacional.py; escenario de carga nuevo propuesto en tests del agente. Contratos se prueban por capa y un conjunto acotado E2E, no producto cartesiano de todos los fallos/tools.

La extracción completa de B9, incluidos perfil, observabilidad, medición,
documentación, riesgos y rollback, ya está en el mapa interno leído. El dueño de
la aceptación integral EVAL/COST/SCALE y del perfil continúa siendo B9E.

## Cobertura del reporte solicitado (§46)

| Puntos | Resultado de este preflight |
| --- | --- |
| 1–2 | Encargo B9B BLOCKED; B9 canónica IN_PROGRESS. No se cambia el progreso versionado. |
| 3–5 | Baseline exacto anterior; cero commits; cuatro cambios preexistentes preservados. |
| 6 | R03/R05/R11, con restricciones de R12; extracción anterior. |
| 7–10 | Inventario runtime, abstracción e identidades no inspeccionados/diseñados: se activa STOP contractual antes de implementar. |
| 11–20 | Sin modelos, migraciones, estados, keys, autoridad, atribución, pricing, moneda o schema nuevos. |
| 21–28 | Algoritmo, periodo, locks, integridad, timeout, retry, fallback y unknown usage pendientes del encargo corregido; no hay garantías nuevas demostradas. |
| 29–32 | Sin reconciliador, inspector, métricas o persistencia de PII nuevos. |
| 33–40 | Sin E2E accounting, tests, procesos PostgreSQL, inyecciones, corpus, métricas ni evidencia COST B9B ejecutados. No se iniciaron clusters ni workers. |
| 41–43 | B9A documenta 45/45 y baseline total de 2.236 IDs únicos aceptados. Evidencia histórica leída, no repetida ni atribuida a B9B. Cero IDs B9B ejecutados. |
| 44–45 | No se ejecutan checks Django/DB ni inspección PostgreSQL: no hay implementación ni migraciones. La comprobación de whitespace documental se registra al terminar. |
| 46 | No hay cambio funcional que revertir; no se modifica ni elimina evidencia contable. |
| 47–49 | Solo este informe; discrepancias anteriores; el riesgo pendiente es implementar fuera del contrato. |
| 50–51 | Sin cambio de gates. El acta baseline registra B0 cerrado, B7B=False, execution flags={} y PENDING_ACTIVATION_REQUIREMENTS; no se inspecciona producción en este preflight. |
| 52–53 | Sin deploy, activación de clínicas, PROFILE-BETA-1 ni implementación B9C/B9D/B9E. |
| 54 | No iniciar B9C: primero resolver el alcance del encargo B9B y completar su aceptación. |

## Resolución necesaria

Reformular B9B como reserva durable de llamadas/cupo por TurnWork bajo witness,
reutilizando LLMCall, contando roles/retries/timeouts y conservando consumo
admitido tras rollback/restart. Atribución tenant y uso/coste desconocido siguen
siendo obligatorios. Retirar la exigencia de periodos monetarios y de estados o
billing nuevos; corregir B9B = B9 canónico completo. No se enmienda el plan para
acomodar el encargo. Este informe no autoriza ni inicia implementación.
