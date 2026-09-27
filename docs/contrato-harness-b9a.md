# B9A — Harness de aplicación bajo contención

Baseline: `55d122bcfb26f41b7f23ce0bb523b464017f3a4c`.
Fecha: 2026-09-26. B9A es un hito interno de B9, sin alcance contractual propio.
Autoridad y asignación única: [mapa B9A–B9E](mapa-interno-b9-2026-09-26.md).
Este contrato desarrolla únicamente R02/R14; no cambia §7/B9 del plan.

## Fronteras

`tests.harness.ApplicationHarness` exporta el conductor de
`tests/b9a_harness.py`. Los helpers históricos de planner siguen siendo pruebas
de componente y conservan sus contratos. El nuevo conductor usa:

1. Django Client → middleware/URL `/hooks/whatsapp/` → verificación HMAC Meta,
   proyección del evento, recepción/persistencia Message y recibo causal B7B.
2. `run_agent_worker --once --mode planner` → selector real → claim/lease B3 →
   TurnContext del membership persistido → safety/B5 → planner/policy/B6.
3. Proveedor LLM real de la aplicación, parser y retry reales, con respuesta
   HTTP determinista en `requests.Session.request`. Las tools READ conservan
   RequestsTransport, JWT AGENT y stack Django/DRF/RBAC/dominio real.
4. Consolidación B3 con witness/CAS → B6 persistido → preparación B7A → propuesta
   B7B canónica o respuesta normal → Message pending + completion en commit.
5. `run_agent_worker --once --mode sender` → B4 recovery/claim/admission →
   Meta provider/transport real → wire controlado → aceptación/CAS durable.
6. Webhook firmado de status → correlación tenant/account/wamid y reconciliación
   B4. Los acuses delivered/read son señales simuladas; no prueban delivery Meta.

El HTTP de aplicación atraviesa Django/DRF en proceso, sin socket ni proxy TLS.
No se llama a la view o servicio para reemplazar una petición. El proceso del
worker usa su propia conexión PostgreSQL en la suite multiproceso; el loopback
DRF está en ese proceso. No se ensayan nginx, red, DNS ni infraestructura Meta.

### Sustituciones exactas

| Frontera | Sustitución | Componentes que siguen ejecutándose |
| --- | --- | --- |
| Wire LLM | JSON compatible, tool calls, excepción Timeout o respuesta inválida | Selección de proveedor, parser, planner, retry y tools |
| Wire Meta | JSON accepted, HTTP rejected, timeout o proceso terminado antes de recibir resultado | Provider Meta, B4 admission, fencing, estados y evidence |
| Transporte HTTP interno | Petición reencaminada a Django Client | Rutas, autenticación JWT, serializers, RBAC y servicios READ |
| Planificación de pruebas | Retirar debounce/adelantar next_attempt o lease en fixtures explícitas | Selector, membership, claim, attempts y validación del witness |
| Gates WRITE | Context manager exclusivo de test: B7B/flags y contención temporal | Todas las preconditions, consentimiento y guard B8A |

No se sustituye el guard, adapter, servicio WRITE, planner, worker, sender ni
reconciliación. El wire acepta solo dos hosts externos `.invalid` y el host interno
`b9a.internal.test`, reencaminado a Django Client. El runner desactiva Sentry,
Redis y healthchecks externos.
Nunca se requieren credenciales comerciales. No se crean tablas para instrumentar
pruebas, nuevas migraciones, operaciones, cupos, presupuesto ni readiness.

## WRITE completo y correcciones de integración

La confirmación pasa por otro HTTP inbound con referencia al wamid realmente
aceptado. `client_reply` rechaza una propuesta pending/uncertain sin evidencia
válida. La recepción registra el recibo B7B antes del worker. El worker reconoce
la respuesta y `finalize_turn` llama a `evaluate_turn` bajo witness. B7B persiste
AuthorizationEvidence; `consent_execution_output` invoca exclusivamente
`execute_authorized_operation`. B8A vuelve a validar autorización, identidad,
binding, ownership, permisos, TTL, safety/handoff y dominio. Solo EffectEvidence
válida permite construir un recibo de éxito. Este vuelve a recorrer B4.

El baseline terminaba el worker en AUTHORIZED, sin consumidor de B8A. La conexión
anterior es necesaria para componer R02; no es una segunda frontera WRITE.
El gate preliminar conserva la respuesta de consentimiento sin efecto cuando
el release está cerrado. La tool legacy y el POST con identidad AGENT continúan
denegados por B8A. Una respuesta rechazada/incierta no afirma éxito ni reintenta
el adapter a ciegas. Su texto pide revisión; no afirma haber notificado al equipo.

Además, `check_appointment_slot` conservaba disponibilidad pero omitía la fecha
de observación al derivar su resultado. Ahora marca cuándo terminó esa lectura;
B6/B7A pueden conservar su procedencia. La precondition que exige observed_at
sigue vigente. La suite no rellena ese timestamp para simular una tool válida.

La propuesta deja de prometer que confirmar nunca ejecuta: aclara que cualquier
efecto exige permisos y condiciones vigentes. El snapshot de propuesta sigue
siendo evidencia exacta y el consentimiento no concede permisos por sí solo.

### Alcance de los cinco guiones

| Kind | Entrada y fixture previa | Efecto/evidencia reales |
| --- | --- | --- |
| CREATE_APPOINTMENT | Solicitud con mascota, fecha, hora y motivo; slot por HTTP | Appointment.source_operation y resultado B8B |
| RESCHEDULE_APPOINTMENT | Appointment sintética previa; consulta/selección singular y slot nuevo | AppointmentMutationEffect, horario y auditoría B8C |
| CANCEL_APPOINTMENT | Appointment sintética previa; consulta y selección singular | Estado canceled y AppointmentMutationEffect B8C |
| CONFIRM_ATTENDANCE | Selección explícita del asunto B6 ya implementado; nueva lectura tras cambiar kind | Declaración contextual citando propuesta; confirmed y ledger B8D |
| REGISTER_PET | Campo pet_name explícito capturado con B6.change y fuente HTTP/C1 real | Pet y PetRegistrationEffect B8E, sin Owner/cita implícitos |

El baseline no tiene opener léxico de asistencia ni extractor de datos de mascota
completo. Esas dos fixtures preparan el asunto/dato, nunca Operation, emisión,
consentimiento o efecto. Desde la preparación de propuesta en adelante el camino
es real. No se presenta esta evidencia como soporte universal de lenguaje natural
ni se amplía B6/E1/E5 para conseguirlo. La detección clínica permanece B5.

## Transacción, locks y fallos

La transacción exterior B3 contiene consentimiento + guard/efecto local + ledger
+ recibo + completion. Se conserva Conversation → TurnWork → ContactIdentity →
Goals (orden PK) → Operations (orden PK) de B7B; B8A reentra con el mismo witness
y luego toma los locks de cada adapter B8. No hay IO LLM/Meta bajo esta transacción.
En B8E se conserva Organization FOR SHARE → Owner FOR SHARE NOWAIT y sus reglas
contra el ciclo con revocación de teléfono. No se modifica el lock order de dominio.

Error SQL al insertar el recibo revierte autorización/efecto/ledger/completion.
La recuperación usa el mismo TurnWork y nuevo token. Commit ya observado evita
republicar; otro inbound con el mismo wamid no crea otro trabajo. Un worker vivo
con token antiguo no puede publicar tras la recuperación. B4 sigue distinguiendo
claim de admission y nunca reenvía ciegamente una aceptación incierta.

Ante aceptación externa con respuesta local perdida, la prueba termina el proceso
después de la señal del fake, antes de guardar el resultado. B4 recupera uncertain.
Sin wamid conocido localmente, un status no permite inventar correlación. Una
fixture uncertain con ID previamente observado sí se reconcilia por webhook firmado.
Son pruebas de proceso/SQL; no certifican pérdida eléctrica o exactly-once remoto.

## Etapas, evidencia y determinismo

- `response_generated`: observación volátil de texto candidato en los puntos
  reales de generación/publicación. Incluye alternativas sustituidas y reintentos;
  no es un contador durable de billing ni se deriva de filas Message.
- `outbound_queued`: Message outbound persistida, aunque aún no admitida/enviada.
- `provider_accepted`: timestamp B4 tras respuesta válida del wire controlado.
- `delivered`/`read`: solo timestamps obtenidos del webhook de status simulado.
- `sent`: alias de aceptación del modelo actual; nunca evidencia nueva de delivery.

Se observan llamadas mediante `sys.setprofile`, sin reemplazarlas. Cada happy path
comprueba que el caller del guard sea runtime y que se alcance el adapter real.
Message/TurnWork/Operation/AuthorizationEvidence/ToolExecution/provenance aportan
la evidencia durable. Los journals JSONL contienen etapas y estados, no prompts,
teléfonos o nombres. Los procesos registran PID del intérprete y de PostgreSQL.
Los threads auxiliares solo leen pipes; no ejecutan negocio.

Las fechas de cita son relativas al día del servidor (+3 días), horario UTC de
fixture abierto toda la semana, sin dependencia del día laboral. Las pruebas de
recuperación controlan explícitamente lease/debounce/backoff, sin esperar su TTL.
Los relojes DB de evidencia no se falsifican. Los timeouts y barreras tienen límites
de infraestructura; excederlos es fallo, nunca skip verde. No se usa aleatoriedad
para decidir resultados ni Internet/datos productivos.

## Comandos y aceptación

### Correspondencia de escenarios del encargo

Los IDs siguientes identifican escenarios; no son fases nuevas ni métricas del
gate integral B9. Los nombres completos ejecutados se conservan en el recibo de
aceptación. Prefijo funcional: `test_b9a_e2e.B9AE2ETests`; procesos:
`test_b9a_processes.B9AProcessTests`.

| Escenario | Evidencia ejecutable |
| --- | --- |
| E2E-01 READ pública | `test_e2e_01_public_read_queued_accepted_delivered_read_are_distinct` |
| E2E-02 READ personal | `test_e2e_02_personal_read_uses_authenticated_domain_http` |
| E2E-03 duplicado inbound | `test_e2e_03_duplicate_signed_http_is_one_message_and_work`; dos procesos HTTP |
| E2E-04 mensajes consecutivos | `test_e2e_04_burst_membership_then_next_turn` |
| E2E-05 caption/reply/action | `test_e2e_05_caption_reply_and_action_projection` |
| E2E-06 retry worker | Error SQL antes de publicación, kill tras claim y kill antes de publicación |
| E2E-07 accepted | E2E-01 y los cinco recibos WRITE; timestamp B4 distinto de queued |
| E2E-08 failed | `test_e2e_08_sender_known_failure` |
| E2E-09 uncertain/reconciliation | Timeout sin retry ciego, status sin correlación y fixture correlacionada |
| E2E-10 handoff | `test_e2e_10_human_request_keeps_case_and_honest_output` |
| E2E-11 takeover | Durante LLM y después de propuesta confirmable; endpoint Inbox real |
| E2E-12 safety | `test_e2e_12_safety_precedes_llm_and_normal_write` |
| E2E-13 propuesta causal | Los cinco `test_e2e_write_*`; pending primero, aceptación B4 después |
| E2E-14 consentimiento válido | Los cinco `test_e2e_write_*`; token o declaración contextual de asistencia |
| E2E-15 no causal | Cliente rechaza pending y HTTP de confirmación temprana no autoriza |
| E2E-16 corrección | `test_e2e_16_correction_retires_old_proposal_before_effect` |
| E2E-17 confirmación duplicada | `test_e2e_17_duplicate_confirmation_and_worker_do_not_repeat_effect` |
| E2E-18 worker duplicado | Dos procesos compiten por claim; retry tras commit y fencing de lease antigua |
| E2E-19 sender duplicado | Repetición secuencial y dos procesos; una admisión/llamada |
| E2E-20 aislamiento | Mismo contact/wamid en dos tenants, propuesta cruzada rechazada y progreso independiente |

También se comprueban firma/payload/handshake/account, provider LLM inválido y
timeout/retry real, guard B8A con definición inactiva, B0/flags cerrados, y rollback
de consentimiento/efecto cuando falla SQL al publicar el recibo. No se cuentan
estos escenarios como aceptación de COST/SCALE/PROFILE-BETA-1.

La definición inactiva es una inyección SQL deliberada después de crear/publicar
la propuesta real. Los dos managers ORM impiden modificar definiciones. El test
no abre esa API: comprueba que B8A rechaza también un registro contradictorio
almacenado, aun con consentimiento causal. Esta fixture negativa no participa en
los cinco happy paths.

`agent_eval --application-e2e` selecciona READ pública/personal y deduplicación.
`agent_eval_conversations --application-e2e` selecciona el conjunto conversacional
B9A, incluidos WRITE con fixtures. Ambos lanzan el mismo runner en proceso aparte,
base PostgreSQL local con nombre explícito `test_b8b_b9a_*` y artefacto requerido.
El ciclo Django de tests permite commits/limpieza reales y evita envolver sender
en el rollback de los evals antiguos. Fallo, interrupción, skip o ausencia de
receipt no se convierten en éxito. El modo histórico queda rotulado como diagnóstico
de planner; su score no acredita B9. La promoción con LLM real pertenece a B9E.

El [acta](implementacion-b9a-agente-whatsapp-2026-09-26.md) registra resultados por
ID y limitaciones. B9 sigue IN_PROGRESS. B9B–B9E, PROFILE-BETA-1, EVAL/COST/SCALE,
E1–E5 y P-A/P-B quedan fuera de esta entrega. PENDING_ACTIVATION_REQUIREMENTS,
B0 cerrado, B7B=False y execution flags={} permanecen. No se despliega.

## Extensión B9 de presupuesto operativo (2026-09-27)

El wire LLM exige observar una LLMCall admitida bajo el witness B3 antes de
simular la respuesta. Se conserva la aserción de HTTP fuera de transacción.
Los escenarios B9B reutilizan el conductor, con usage normal/ausente/malformado,
error, timeout y retry. La traza observa admit/record sin reemplazar el servicio
ni editar directamente su evidencia. El fake ya acepta estos payloads y errores;
no necesita pricing ni fallback ficticio. La aceptación se registra separadamente
de los 45 IDs B9A y no acredita el perfil integral.
