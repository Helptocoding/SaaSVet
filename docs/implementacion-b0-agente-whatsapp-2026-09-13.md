# B0 — Contención y prerrequisitos del agente WhatsApp

Fecha: 2026-09-13. Alcance: [B0 del plan](plan-implementacion-auditoria-agente-whatsapp-2026-09md).
Estado: implementación técnica B0 validada localmente. Activación: **PENDING_ACTIVATION_REQUIREMENTS**. Sin despliegue ni ampliación de beta.

## Límite del encargo

Este cambio implementa exclusivamente B0. No adelantar B1–B9 por oportunidades de mejora. Cualquier descubrimiento ajeno se registra como dependencia/riesgo. El siguiente encargo requiere una fase explícita y se evalúa solo contra sus criterios.

Ciclo acordado: implementar fase → tests → aceptación → documentación/ADR → desviaciones → commit. El commit de B0 no habilita automáticamente la siguiente fase.

No se crean modelos, migraciones, flags de autonomía, propuestas versionadas, claims/leases, ownership, outbox nuevo, resultados tipados, procesamiento multimedia ni nuevas reglas de detección de urgencias.

## Comportamiento de esta entrega

- Las siete escrituras actuales (crear/confirmar/cancelar/reprogramar cita; alta cliente+mascota, mascota+cita y mascota) están contenidas en `intake.CONTAINED_WRITES`. El catálogo por conversación las oculta; `run_tool` las deniega aunque el modelo las fuerce. El gate exige revisar esta lista si cambia el registro.
- `policy.evaluate` deriva pendientes heredados antes de interpretar su respuesta. `planner._commit_pending` también deniega su ejecución directa. La suspensión y la cola usan los mecanismos existentes; no se inventa una autorización ni se considera seguro el JSON antiguo.
- Un intento de escritura termina con plantilla de contención y handoff existente. Staff realiza la operación por las superficies de dominio actuales; no se acepta un write del bot para revisarlo después.
- Se conservan READs y controles dentro de sus restricciones actuales. READ personal exige además el helper existente `identity.is_verification_current`; no se introduce autenticación nueva. Abrir READ pública fuera de intake y modificar la frontera posterior al recibo pertenecen a B2.
- El filtro temporal de salida bloquea las expresiones clínicas ya reconocidas, afirmaciones de WRITE del corpus, importes con símbolo monetario y avisos humanos no respaldados del corpus. Deriva inmediatamente a plantilla limitada/humano, sin pedir otra redacción al mismo modelo. No es grounding semántico ni detección clínica completa.
- Las plantillas modificadas no afirman aviso/lectura humana ni tiempo de respuesta. Urgencias conserva detección/prioridad actuales, pero la orientación no presupone una clínica abierta; utiliza únicamente teléfono configurado.
- `alerts.notify_urgent_handoff` devuelve aceptación HTTP. El evento registra `alert_provider_accepted`, no `alert_delivered`. El texto libre `detail` ya no sale al webhook; permanece la firma para compatibilidad de callers. No hay aviso durable, acuse humano ni retry nuevo.

## Contratos mínimos acordados, todavía sin implementación

El detalle autoritativo está en §4–§5.3 del plan. Esta acta fija sus fronteras y entregas; no congela schemas opcionales.

| Contrato | Productor → consumidores | Regla mínima | Fase que lo materializa |
| --- | --- | --- | --- |
| C1 turno acotado | Entrada desde Message → policy/planner/proyecciones | Un mismo conjunto causal/cursor; herramientas reciben argumentos/autoridad mínimos, no un objeto global | B1; witness al integrar B3 |
| C2 operación exacta | Confirmations → consentimiento → API/recibo | Interpretación no autoriza; nueva fila por cambio de propuesta; emisión derivada de Message | B7A/B7B y cada adaptador B8 |
| C3 resultados | Adaptador HTTP → renderizadores/planner | Vacío, recorte, error y efecto confirmado distintos; números coincidentes y tool_ran no son prueba | B2; escrituras en B8 |
| C4 procesamiento/ownership | Worker → fronteras de efectos/finalización | Un token de claim y epoch de ownership; incompleto no significa completado | B3; API en B8 |
| C5 publicación/envío | Finalización → Message → sender | Encolado, aceptado y entregado distintos; incertidumbre visible, sin promesa exactly-once | B3/B4 |
| C6 atención humana | Escalamiento → Inbox/owner/operación | Crear, avisar, tomar, responder y resolver son hechos distintos | B5; extensiones E3 |

I01–I14 son criterios del plan, no catorce garantías ya entregadas. B0 aporta contención en I01/I04/I05/I06/I13 dentro de las rutas probadas. No cierra H01–H20 ni acredita I08–I11.

Los tiers describen interacción, sin conferir permiso. Una UX de confirmación no impone una FSM de conversación. B0 no elige un nuevo código de confirmación, modelo de autorización ni número de pasos.

## Harness y corpus

`backend/apps/agent/tests/harness.py` incorpora `PersistedTurnHarness`, `ControlledTransport` y `FailureBarrier`. Persiste inbounds PENDING, ejecuta policy/planner y observa salientes encolados. Mantiene el helper histórico `run_turn`; no lo convierte silenciosamente en un worker.

Los snapshots comparan todos los valores de Owner/Pet/Appointment, incluyendo otros tenants, y las llamadas HTTP. Las pruebas de dispatch/commit colocan además handlers que fallan si llegan a invocarse. Efectos conversacionales permitidos (handoff, mensajes y diagnóstico) se verifican separadamente.

Barreras disponibles: inbound persistido, antes/después de planner y antes/después de proveedor. Son puntos del harness; no prueban atomicidad de la aplicación. B3 conectará claim/recuperación reales, B4 Meta/sender y B8 API/ledger. No usar una respuesta simulada como evidencia de entrega.

El corpus `tests/fixtures/b0_critical.json` contiene los siete WRITE, seis respuestas adversariales/declarativas y cinco salidas inseguras. IDs/versiones esperados están fuera del fixture para impedir que vaciarlo dé verde. `CriticalB0Runner` exige el manifiesto de los 17 métodos, comprueba cuántos se ejecutaron y rechaza suite incompleta/vacía, skips y expected failures. El workflow ejecuta el módulo explícitamente: eliminarlo u omitir escenarios hace fallar el job backend. La configuración remota de branch protection debe exigir ese job; este cambio local no demuestra que esté configurada.

Los tests que necesitan ejercitar handlers, precondiciones, slots o confirmaciones **inactivos** llevan `@legacy_write_component` y el tag del mismo nombre. Solo durante esas clases/métodos, una sustitución de test vacía la lista de contención; conserva las comprobaciones de identidad, permisos, precondiciones y efectos reales del componente. El cleanup restaura la frontera. No es configuración de aplicación, no habilita tráfico real ni demuestra autorización segura del flujo heredado. Los tests de catálogo/despacho vigente se actualizan a B0 y no usan ese decorador. El módulo crítico tampoco lo usa: comprueba la lista completa y exige cero invocaciones/efectos WRITE. No contar las pruebas de componentes inactivos como evidencia para activar autonomía.

Esta separación conserva cobertura útil del código que B0 debe mantener, sin silenciar casos con skip/xfail ni convertir todos los tests de negocio en la misma aserción de «denegado». B7/B8 deberán adaptar o retirar expresamente los contratos heredados cuando implementen sus sustitutos.

Comando reproducible desde backend con PostgreSQL **de pruebas** configurado:

```bash
python manage.py test apps.agent.tests.test_b0_containment --testrunner apps.agent.tests.harness.CriticalB0Runner
```

## Matriz inicial de locks

Inventario limitado a fronteras modificadas. No es una reconstrucción del worker ni acredita exclusión entre procesos.

| Frontera tocada | Sincronización de B0 | Límites/dependencia |
| --- | --- | --- |
| Catálogo/dispatch | Lectura de constante y validaciones existentes; no lock nuevo | Proceso viejo conserva código anterior hasta detenerlo |
| Pending en policy/commit | Se rechaza antes del handler; se reutiliza suspensión/handoff existente | No convierte suspensión en fencing; B3 coordina ownership |
| Salida bloqueada | Handoff y enqueue actuales | No se vuelve atómica la finalización/outbox; B3/B4 |
| Alerta urgente | HTTP síncrono actual, sin lock/lease nuevo | No acredita entrega ni permite asumir reintento idempotente; B5 |

No mover HTTP entre transacciones ni agregar locks especulativos en B0. La matriz se amplía cuando cada fase toca una frontera real.

## Registro operativo y gates externos

**Estado: `PENDING_ACTIVATION_REQUIREMENTS`.** El usuario confirmó que los datos operativos todavía no están definidos formalmente. No bloquean implementación ni pruebas de B0; sí bloquean activar el agente con tráfico real de una clínica piloto. No se inspeccionó producción ni se inventaron clínicas, responsables o destinos. El desarrollador/operador del SaaS no cubre automáticamente ningún rol.

| Clínica del piloto | Capacidades admitidas | Responsable Inbox/cobertura | Responsable protocolo veterinario | Responsable privacidad | Fallback ya configurado | Activación |
| --- | --- | --- | --- | --- | --- | --- |
| PENDIENTE DE DEFINIR / CONFIRMAR | Máximo: READ restringida y atención humana; WRITE autónomo cerrado | PENDIENTE DE ASIGNAR | PENDIENTE DE ASIGNAR | PENDIENTE DE ASIGNAR | PENDIENTE DE DEFINIR Y VALIDAR por clínica | PENDING_ACTIVATION_REQUIREMENTS |

Completar una fila por cada clínica piloto y conservar evidencia de validación:

- [ ] Clínica identificada y confirmada para el piloto.
- [ ] Responsable de Inbox asignado y cobertura acordada.
- [ ] Responsable de protocolo veterinario / seguridad clínica asignado.
- [ ] Responsable de privacidad asignado.
- [ ] Canal alternativo de escalamiento/fallback definido, configurado y validado para esa clínica.
- [ ] Requisitos técnicos y operativos de las fases aplicables aprobados antes de admitir tráfico real.

No rellenar nombres, teléfonos, correos, WhatsApp ni otros contactos con ejemplos o supuestos. Completar este checklist no abre capacidades WRITE: se conservan sus gates por fase.

La orientación provisional no es un protocolo clínico aprobado. No ampliar beta sin protocolo/cobertura de B5, criterios por capacidad de B9 y política de datos P-A. No inventar urgencias 24h, horarios, teléfonos ni SLA humano.

B0 no introduce una cola de aprobación previa de respuestas LLM. «Supervisión» no significa que exista esa función ni que baste revisar después una respuesta clínica: hasta aprobar los gates aplicables, la atención real debe quedar a cargo del staff mediante Inbox con autonomía deshabilitada. Las pruebas locales pueden ejercitar las READ restringidas sin habilitar tráfico real.

El perfil reproducible de carga queda fijado por `PROFILE-BETA-1` de B9 en el plan: 2 planners, 1 sender, polling ≤1 s; 3 orgs; 30 s de calentamiento + 300 s medidos; dos orgs sanas con 1 inbound/10 s y una ruidosa con 1/s distribuido en conversaciones; LLM 0.5 s, READ 0.1 s, Meta 0.2 s; ensayos separados LLM 10 s, Meta 2 s, webhook duplicado y saturación con guidance detectable. En perfil base/bloqueo LLM, p95 de persistencia inbound sano a claim ≤10 s, de persistencia de guidance detectable a dispatch ≤5 s y de outbox committed a dispatch ≤5 s con proveedor base. Meta lento exige durabilidad/concurrencia acotada, no ese mismo SLO. §7/B9 conserva la especificación completa y sus muestras/errores. **B0 no ejecuta carga ni implementa scheduler/medición B9.**

## Despliegue y rollback

Sin migración, backfill ni modificación de datos legacy. Esta tarea no despliega.

Para desplegar de forma controlada, detener admisión/procesamiento autónomo con el kill switch existente y parar todos los workers de la versión anterior antes de arrancar la nueva. Confirmar que no quedan procesos antiguos y comprobar BASE-01/02 en entorno de ensayo. Reanudar únicamente capacidades/organizaciones autorizadas con cobertura real. Cambiar solo la web/API mientras un worker viejo sigue activo no aplica esta contención.

Antes de reanudar el sender, revisar los salientes pendientes de la versión anterior: el filtro B0 solo gobierna texto generado por el código nuevo, no reescribe la outbox histórica. Mantener el envío detenido si no se puede determinar su tratamiento seguro; no borrar evidencia ni reenviar por suposición. La recuperación y reconciliación sistemáticas corresponden a B3/B4.

Rollback funcional: mantener AgentSettings.enabled deshabilitado y workers antiguos detenidos hasta disponer de una versión compatible que preserve la denegación de WRITE y el copy honesto. Un git revert que reabra escrituras no es rollback aceptable. Los handoffs/messages/ToolExecution nuevos usan schema existente: permanecen como evidencia; no borrarlos ni convertir pendientes suspendidos en autorizados. No existe flag para retirar guards.

## Validación corta de aceptación

| Criterio | Evidencia exigida | Estado |
| --- | --- | --- |
| BASE-01 | Siete tools forzadas, siete selecciones planner y seis commits legacy; cero efectos/HTTP WRITE; READ pública y humano disponibles en ruta habilitada; identidad vencida denegada | PASS: módulo crítico, 17 tests |
| BASE-02 | Cinco salidas del corpus sustituidas; READ no acredita WRITE/precio; alerta 204/500/timeout sin claim de lectura ni exportación de detail; teléfono configurado/ausente | PASS: módulo crítico, 17 tests |
| BASE-03 | Fixture ausente/incompleto, fallo, suite vacía, skip y xfail producen fallo; job explícito | PASS: módulo crítico sin skips; workflow preparado, ejecución remota no realizada |
| Compatibilidad | Repetición limitada a los módulos afectados; chequeo de migraciones | PASS: 373 tests, 0 fallos/errores, 1 skip heredado fuera de B0; makemigrations --check --dry-run: No changes detected |

Validación local con Python 3.13.2, Django 6.0.3 y PostgreSQL 18.3 aislado (CI conserva PostgreSQL 16). Se aplicaron únicamente migraciones existentes a la base efímera de tests; no se crearon migraciones ni se accedió a producción. El runner final ejecutó los 17 tests críticos sin omisiones.

La repetición de compatibilidad usó estos módulos (373 tests; incluye el corpus B0, no sumar ambos conteos como casos únicos):

```bash
python manage.py test \
  apps.agent.tests.test_commit_preconditions apps.agent.tests.test_planner \
  apps.agent.tests.test_regression_f2 apps.agent.tests.test_tools \
  apps.agent.tests.test_write_tools apps.agent.tests.test_clinic_context \
  apps.agent.tests.test_corpus_conversacional apps.agent.tests.test_f5_fase1 \
  apps.agent.tests.test_family_link apps.agent.tests.test_intake_capabilities \
  apps.agent.tests.test_policy apps.agent.tests.test_regression_suite \
  apps.agent.tests.test_w0_hardening apps.agent.tests.test_w1_experience \
  apps.agent.tests.test_f5_fase5 apps.agent.tests.test_b0_containment
```

Tras el último ajuste de plantilla/política se ejecutaron otros 17 tests, todos PASS: `test_policy.BudgetAndScopeTests`, `test_tier0` y `test_w1_experience.Tier0TemplatesPassTheGuardsTests`. `git diff --check` pasó. La aceptación B0 usa LLM y proveedores simulados; no prueba servicios reales. No se modificó configuración productiva.

El skip existente es `test_regression_f2.Int21Tests.test_21_05_bis_new_pet_existing_owner`: escenario INT-21-bis pendiente desde PR-17a. No pertenece al corpus B0, no se eliminó/silenció por esta entrega ni acredita alta autónoma de mascotas; esa capacidad sigue cerrada. No se volvió a auditar el hallazgo asociado. La suite amplia inicial no se repitió completa: tras sus resultados se verificaron los módulos afectados, conservando el resultado de los no modificados.

La suite crítica es evidencia de esos casos, no estimación de sensibilidad clínica ni cierre de los hallazgos.

## Desviaciones y riesgos fuera de alcance

- B0-D01: el grafo devolvió posiciones desactualizadas en símbolos concretos; se leyeron solo las funciones necesarias desde sus archivos. No se reindexó ni recorrió el módulo.
- B0-D02: se toca `planner.py` aunque B0 enumeraba principalmente tools/intake/policy/guards: el pending legacy llama al commit directamente y el texto final se publica aquí. Son las dos fronteras necesarias para aplicar contención, sin cambiar el diseño del planner.
- B0-D03: READ pública para contacto sin ruta, interpretación de urgencias con humano activo, riesgos de concurrencia y API con credenciales AGENT quedan en B2/B3/B5/B8. No se corrigen por oportunidad.
- B0-D04: la detección léxica de salida es cobertura limitada. Paráfrasis clínicas/no respaldadas pueden escapar. Solo piloto con revisión humana y sin ampliación autónoma; B2/B5 deben sustituir la evidencia débil.
- B0-D05: el usuario confirmó que clínicas, responsables y fallback no están formalmente definidos. Estado `PENDING_ACTIVATION_REQUIREMENTS`; no bloquea desarrollo/tests, sí activación con tráfico real.
- B0-D06: la primera suite amplia ejecutó 813 tests (97 fallos, 48 errores, 1 skip fuera del corpus crítico) antes de adaptar las expectativas a B0. Los fallos de compatibilidad se agrupan en escrituras ahora contenidas, fixtures sin `verified_at`, copy e inventario de plantillas. Se conserva la cobertura de componentes inactivos con opt-in explícito y se actualizan las pruebas del comportamiento vigente. Ese resultado inicial no se presenta como verde ni como nueva auditoría de H01–H20.
