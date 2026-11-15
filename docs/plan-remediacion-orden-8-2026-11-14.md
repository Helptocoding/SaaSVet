# Orden 8 — Agente conversacional

Fecha: **14 de noviembre de 2026**. Estado: **PLAN ACORDADO PARA IMPLEMENTACIÓN LOCAL**. Prepara el trabajo de otro agente; no acredita remediación, despliegue ni activación del agente.

Base: [priorización, §8](plan-remediacion-priorizado-2026-10-28.md), [inventario](pendientes-documentados-2026-10-27.md) y decisiones del usuario del 14-11. Ejecución: [expediente y prompts por entrega](remediaciones/orden-8/README.md).

## 1. Decisiones vinculantes

| Tema | Decisión |
|---|---|
| Ejecutor | Claude Sonnet, un prompt autocontenido por entrega y sesión limpia. El usuario revisa entre entregas, igual que en los órdenes 6 y 7. |
| Alcance | Se implementan **G07** y **G09**, acotados. **G01, G02, G03, G04, G05, G08 y G10** quedan fuera por decisión del usuario (§2). |
| Git | Rama nueva `fix/orden-8-agente` desde `c71c0ed` (`develop` tras el orden 7). Un commit por entrega, sin push, PR, merge ni despliegue. |
| Base de datos | Cluster PostgreSQL 18 propio y desechable: `%LOCALAPPDATA%/Temp/opencode/orden8_pg18_20261114`, loopback `127.0.0.1:49938`, mediante `backend/scripts/orden8_isolated.py`. Nunca la base habitual (`localhost:5432`) ni el VPS. |
| Proveedor LLM | Ninguna prueba habla con un modelo real: el runner vacía `AGENT_LLM_*`. |
| Migraciones | Exactamente una, escrita en el prompt de E01: `agent.0030_turndecision_verdict_choices`. Solo cambia `choices` y `blank`; no genera SQL. |
| Frontend | No se toca. |
| G07 | `TurnDecision.verdict` admite solo los cinco veredictos del árbitro (`arbiter.VERDICTS`) o vacío. Vacío significa que el árbitro lanzó una excepción, lo que solo ocurre fuera del trabajo durable B3; la salida del planner sigue en `facts_produced['salida']`. La validación la aplica `full_clean()` al guardar filas nuevas. Las filas anteriores a É-F5 Fase 4 no se reescriben: la tabla es append-only. |
| G09 | No cambia código de producción. Pruebas nuevas fijan que la oferta de horarios ya compara intervalos reales (citas largas o fuera de la rejilla) y que el agente solo ofrece citas de 30 min alineadas a la apertura. La documentación del módulo pasa a decir eso. |
| ADR | Ninguno nuevo. G07 completa lo que ya decidió [ADR p56](decisions/2026-08-01-p56-perception-situation-and-turn-as-root.md) para su Fase 4 («`TurnDecision.verdict` se cierra al enum de cinco»; las filas históricas no se reescriben). G09 solo documenta el comportamiento vigente. |
| Fuera de alcance | Activar el agente, el proveedor real, la base habitual, el VPS, el despliegue, el frontend, ofrecer horarios fuera de la rejilla o duraciones por servicio, y cualquier limpieza no listada. |

## 2. Cobertura de los pendientes

| ID | Prioridad | Entrega | Cierre |
|---|---|---|---|
| G07 | P3 | E01 | Vocabulario cerrado en el modelo, valor vacío honesto cuando el árbitro falla, pruebas y documentación. |
| G09 | P2 | E02 | Pruebas de caracterización y documentación al día; queda declarado el límite de 30 min sobre la rejilla. |
| G01 | P2 | E03 | Fuera de alcance: el transcript de origen es anterior a p58/p59 y no hay datos reales para reproducirlo. Sin eval contra el modelo real. |
| G08 | P2 de diseño | E03 | Fuera de alcance: diseño pendiente antes de ampliar las capacidades del agente. |
| G02, G03, G04, G05, G10 | P3 | E03 | Fuera de alcance: extensiones de producto fuera de la beta inicial. |

## 3. Evidencia de partida

Medido el 14-11-2026 sobre `c71c0ed`.

| Fuente | Observación | Implicación |
|---|---|---|
| `planner.handle_inbound`, `_settle_commitment` | El árbitro corre en todos los turnos; sin compromiso devuelve `responder`. `_record_turn_decision` guarda su veredicto. Solo si el árbitro lanza una excepción guarda el texto libre del planner (`reply`, `silent`…). | El vocabulario ya es casi cerrado en la práctica; falta que el modelo lo exija y que el caso de fallo no invente un valor. |
| `_settle_commitment` bajo B3 | Con un `TurnChanges` activo, la excepción del árbitro se relanza y el turno falla. | El valor vacío solo aparece fuera de B3, así que el flush durable nunca guarda un veredicto inválido. |
| `OrganizationalModel.save` | Llama `full_clean()`, también en el `obj.save(force_insert=True)` del flush B3. | Añadir `choices` valida las filas nuevas sin `CHECK` en base de datos. |
| `apps/agent/tests` | Solo `test_b3_durable.py` crea una fila a mano, con `verdict='reply'`. | Única fixture a ajustar; ninguna aserción cambia. |
| `docs/modules/agent.md` | La tabla de modelos y un «Pendiente declarado» siguen describiendo `verdict` como texto libre. | Se actualizan en E01. |
| `tools._day_occupancy`, `_vet_free` | Desde `9ccc31a` (15-09) la ocupación guarda `(start_time, end_time)` de cada cita activa y un hueco se descarta si se solapa con cualquiera. | La limitación MP-5 («compara `start_time` exacto») ya no es cierta para citas largas ni fuera de la rejilla. |
| `tools._free_slots_for_day`, `SLOT_MINUTES` | Los huecos ofrecidos son de 30 min, en pasos de 30 desde la apertura de cada tramo. No existe duración por servicio en el dominio. | Límite real que queda: una ventana libre fuera de la rejilla (09:15) no se ofrece. |
| `apps/agent/tests/test_slots.py` | Las pruebas existentes solo reservan citas de 30 min en la rejilla. | E02 añade los casos de cita larga, fuera de rejilla y solape parcial. |
| ADR p56, plan F5 §Fase 4 | Ya decidieron cerrar `verdict` al enum de cinco con migración aditiva, sin reescribir filas históricas. La Fase 4 cambió el escritor, pero no el modelo. | E01 termina esa decisión; no hace falta ADR nuevo. |
| `apps.channels`, `apps.agent` completos | `apps.channels` solo: 158 pruebas en 12 min, con 1 `ERROR` de entorno en el simulacro de restauración de media, que exige una base `test_ci_*`. `apps.agent` tiene unas 1.950 pruebas y suites de procesos con la misma exigencia. | No caben en una llamada de 10 minutos ni corren aquí completos; la suite global se acredita en CI. |
| Corrida de referencia (§5 de las reglas comunes) | Llamada A: 103 pruebas OK en 2 min 39 s. Llamada B: 242 OK (skipped=1) en 2 min 57 s. | Cubre todo lo que tocan E01 y E02. |
| Validación en seco (14-11) | E01 y E02 aplicados en un worktree desechable con el código de los propios prompts: A = 107 OK y B = 246 OK (skipped=1); `sqlmigrate agent 0030` da `-- (no-op)`. Con `_vet_free` mutado a la regla antigua (inicio exacto), tres de las cuatro pruebas nuevas de G09 fallan. Los 13 bloques se reaplicaron sobre `c71c0ed` y dieron el mismo contenido en los 7 archivos. | Los prompts producen código que compila y pasa, y las pruebas de G09 no son vacías. |
| Base de pruebas sucia | En la validación, una corrida que el sistema detuvo a medias dejó filas de un `TransactionTestCase`; la siguiente dio 20 fallos en `B3LocalIntegrationTests`, que desaparecieron tras un `TransactionTestCase` que vació la base. | Las reglas comunes traen el paso de limpieza. |

## 4. Trampas que los prompts cubren

- `pg_ctl start` con la salida en un pipe no termina nunca: postgres hereda la salida.
- La primera corrida con base de datos crea la base de pruebas (unos 4 minutos).
- `apps.channels` y `apps.agent` completos tardan más que el límite de 10 minutos de la herramienta, y sus suites de procesos exigen una base `test_ci_*`. Las corridas son dirigidas y la suite global se acredita en CI.
- Una corrida interrumpida deja la base de pruebas sucia y produce fallos ajenos en `B3LocalIntegrationTests`. Las reglas comunes traen la limpieza.
- La migración viene escrita: `makemigrations --check` confirma que coincide con el modelo y `sqlmigrate` que no genera SQL.
- Un `verdict` inválido no se ve hasta el flush B3, donde tumbaría la publicación del turno. Por eso el valor de fallo es vacío y `blank=True`.
- `_settle_commitment` registra `AGENT_ARBITER_FAILED` con `logger.exception`; la prueba nueva lo captura con `assertLogs('agent.events')` para no ensuciar la salida.
- Los archivos de la copia de trabajo usan CRLF. Los bloques se aplican con Edit, sin reescribir archivos enteros.

## 5. Entregas

| Entrega | Contenido |
|---|---|
| E00 | Rama, commit de documentos, cluster aislado, línea base del agente |
| E01 | G07: `TurnDecision.verdict` con vocabulario cerrado |
| E02 | G09: pruebas de ocupación por intervalos y documentación |
| E03 | Corrida de cierre, IDs fuera de alcance, expediente |

E01 y E02 son independientes; van en serie para revisar un commit cada vez.

## 6. Verificación y límites

- Cada entrega: pruebas dirigidas en el cluster aislado, `py_compile` de los archivos Python tocados y `makemigrations --check`. Comandos exactos en las [reglas comunes](remediaciones/orden-8/prompts/00-REGLAS-COMUNES.md).
- E00 y E03 ejecutan además la corrida de referencia del agente (§3).
- La suite global de backend (más de 4.000 pruebas, incluidas las del agente y de `channels`) solo se acredita en CI cuando el usuario suba la rama.
- Sin datos reales en juego ni proveedor real. El agente sigue sin activarse (`PENDING_ACTIVATION_REQUIREMENTS`).

## 7. Estado final esperado

G07 y G09 podrán declararse **IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE** con la evidencia de `docs/remediaciones/orden-8/EVIDENCIA.md`. G01, G02, G03, G04, G05, G08 y G10 quedan **FUERA_DE_ALCANCE**. Nada de esto acredita despliegue ni activación.

## 8. Revisión entre entregas

1. El reporte trae `COMPLETA`, un hash de commit y la salida real de las pruebas.
2. `git show --stat HEAD` solo contiene archivos que el prompt autoriza.
3. Ninguna prueba se borró ni debilitó; la única fixture que cambia es la de `test_b3_durable.py` en E01.
4. Bajo `migrations/` solo aparece `agent/0030_turndecision_verdict_choices.py`, en E01.
