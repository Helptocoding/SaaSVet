# Implementación B8E — REGISTER_PET

Estado: **COMPLETED en alcance técnico B8E**, cierre 2026-09-26. Este documento
no autoriza activación. Baseline/HEAD inicial exacto:
`863841694ca25274dc83e81e24c0fe0103e86fd7`.

Implementación: `f8df61d9ec4b3fa9c64b4956acfdcb1716102cc2`, rama
`codex/b8e-register-pet`. El commit documental final incorpora esta acta y la
aceptación consolidada; su SHA se entrega en el reporte final de la ejecución.

| Aceptación | IDs únicos aprobados |
| --- | ---: |
| Histórico exacto B0–B8D | 1.726 / 1.726 |
| Dominios completos afectados | 430 / 430 |
| B8E funcionales, incluidos 28 guards | 55 / 55 |
| Corpus B8E v1 | 36 / 36 |
| B8E multiproceso y failure injection | 29 / 29 |
| Unión, eliminando solapamientos y repeticiones | **2.097 / 2.097** |

Ningún ID pendiente, skip o xfail aceptado. Los 179 IDs de dominios ya incluidos
en el histórico no se suman dos veces. Los fallos iniciales corregidos y las
interrupciones de infraestructura permanecen documentados por corrida en
[aceptación JSON](evals/b8e-acceptance-results.json). La recuperación final acreditó
125/125 + 15/15 + 117/117 IDs, sin reducir assertions. La fuente runtime final
coincide por SHA-256 con las corridas finales funcional, corpus y multiproceso.

Dominios: Patients/owners/contactos 88, importadores 78, MedicalRecord 102,
Agenda 99 y Dashboard 63. El caso Agenda que sufrió timeout se recuperó en
`recovery_ab`. `django check`, `makemigrations --check --dry-run`, `migrate --check`
y `git diff --check`: aprobados. La migración nueva se aplicó también desde una
base vacía; introspección PostgreSQL confirmó UNIQUE de operación/Pet y FKs.

Las siete métricas críticas del corpus son **0**: unauthorized_pets_created,
wrong_owner_pets_created, duplicate_pets_from_same_operation,
human_created_pets_claimed_as_agent_effect, inferred_clinical_fields_persisted,
forbidden_operation_kinds_executed y wrong_tenant_pets_created. Describen los
36 escenarios ejecutados, no una garantía universal.

Se comprobó §7 del plan canónico real, cuyo nombre termina en `2026-09md`;
asigna B8E al registro individual de mascota. Contrato congelado antes de runtime:
[contrato](contrato-register-pet-b8e.md), [ADR](decisions/2026-09-25-b8e-register-pet.md).
Se preservan y excluyen de commits las eliminaciones preexistentes
DEPLOY_VPS_PLAN.md/DEPLOY_VPS_STATUS.md y la auditoría 2026-09-10 sin seguimiento.
No hubo deploy, B9, E1–E5, P-A/P-B ni cambios de defaults productivos.

## Contrato real y autoridad

Pet exige owner y name; organization y campos de infraestructura se asignan por
el servidor. species/breed/color/legacy_id admiten blank, birth_date NULL,
sex=unknown por defecto, is_active=True, is_generic=False, extra_data=[].
No existen campos de peso, microchip, esterilización, alergias o diagnósticos en Pet.
La API humana requiere nombre válido, normaliza especie opcional de catálogo y
rechaza nacimiento futuro según el día local de organización. El modelo aplica
full_clean, tenant y auditoría thread-local. FK owner y organization PROTECT.
public_id es UUID único. Constraints adicionales: un genérico por organización y
legacy_id no vacío único por organización. Ninguna UNIQUE owner/nombre/especie.

El serializer humano admite owner_public_id explícito o alta humana anidada;
esa resolución sigue en su servicio existente. B8E solo recibe owner exacto desde
ContactIdentity.owner = Conversation.contact.owner = Goal.bound_owner =
ConversationOperation.owner = parameters.owner_id. No resuelve texto/número ni
crea propietarios. ContactIdentity conserva permiso CURRENT_OWNER, verificación,
authorization_revision y restricciones familiares B7A. El snapshot incluye UUID,
tenant, actividad, nombre visible, genérico y huella de clave telefónica del owner.
No es una nueva autoridad telefónica ni prueba de identidad física.

`patients.creation` es la frontera común mínima del POST humano y B8E. Conserva
validaciones, normalización, defaults, full_clean y auditoría. Importadores y
alta compuesta de Agenda conservan sus contratos específicos; no se refactorizan.
La deduplicación de lotes de importación no se extrapola al registro individual.

Parámetros REGISTER_PET B7A v1: **owner_id/name obligatorios**, species/birth_date
opcionales explícitos. Sex/breed/color siguen fuera del schema de esta operación.
No inferir nacimiento desde edad aproximada ni ninguna especie/raza/sexo/peso,
vacuna/microchip/enfermedad. `B6.change` admite los tres slots de definición con
fuente USER_EXPLICIT/USER_CORRECTION y dependencia de owner; cualquier cambio
incrementa binding_revision e invalida la operación anterior. record_derived no
acepta etiquetar resultados como explícitos. No se implementa extractor nuevo.

Preconditions nuevas schema 4/registration_contract 1. Snapshot y contrato entran
en digest; no rehash/backfill de operaciones antiguas. B7B exige snapshot nuevo y
muestra owner, nombre, especie/nacimiento explícitos u omitidos/desconocidos,
sexo desconocido y raza/color sin especificar. Valores persistibles no se ocultan.
La corrección exige nueva operación, propuesta y consentimiento. Una corrección
de sexo u otro campo no soportado bloquea el efecto anterior, pero no amplía schema.

## Atomicidad, duplicados e historia

Entrada exclusiva: execute_authorized_operation(operation_key, execution_context).
No parámetros nuevos al ejecutar, escrituras del LLM, endpoint/serializer directo
ni tools legacy. B8A conserva sus locks Conversation → TurnWork → ContactIdentity
→ Goal → ConversationOperation. Después Organization FOR SHARE → Owner FOR SHARE NOWAIT
→ INSERT Pet → INSERT PetRegistrationEffect. El POST humano toma organización
antes de resolver/bloquear owner. No mutex exclusivo de clínica ni owner para
registrar mascotas distintas. La fuente de cada lock es la misma conexión SQL.

La precondition toma Owner con NOWAIT porque el signal humano de cambio de teléfono
puede revocar ContactIdentity mientras mantiene Owner. Si la edición ganó, B8E
sale con rechazo temporal `precondition_infrastructure`, sin INSERT, y libera
ContactIdentity. El savepoint mantiene utilizable la transacción exterior. Esto
evita el ciclo real Owner→ContactIdentity frente a ContactIdentity→Owner. Si el
efecto ganó, la edición espera el lock compartido y su revocación posterior conserva
el Pet. Se prueban ambos órdenes usando `change_owner_phone`, sin mock del signal.

La transacción LOCAL_ATOMIC contiene guard, permiso actual, evidencia B7B,
revisiones/binding/identidad/ownership, expiry, replacement, corrección, safety,
handoff/takeover, locks y snapshot, Pet, ledger, ToolExecution y resultado. B8A
revalida autoridad después de los locks. No espera LLM, HTTP, WhatsApp ni storage.

Provenance elegida: **ledger específico** PetRegistrationEffect. Se compararon
A OneToOne nullable en Pet, B ledger y C EffectEvidence actual; B preserva mejor
la definición histórica frente al Pet mutable sin convertir el resultado genérico
en autoridad de dominio. No AppointmentMutationEffect ni event sourcing general.
operation OneToOne al UUID, Pet OneToOne, tenant, owner, digest, definición y
committed_at. FKs PROTECT; índice UNIQUE PostgreSQL arbitra operación concurrente;
trigger valida concordancia al INSERT y rechaza UPDATE/DELETE de evidencia.
Humanos/legacy no tienen fila ni backfill sintético. Migration patients.0019 aditiva.
committed_at es una observación DB dentro de la transacción, visible tras commit;
no se presenta como timestamp físico de WAL ni garantía contra pérdida eléctrica.

Idempotencia responde exactamente qué Pet creó esa operación. Detección de parecido
es otra cuestión: el dominio permite dos mascotas iguales. Una Luna creada por
recepción tras la propuesta no se reclama como propia; A puede crear otra. A y B
con los mismos parámetros siguen siendo operaciones diferentes. Ningún `.first()`
por nombre/sexo/especie/raza decide identidad. Reconcile busca únicamente operation_key.

Evidencia exacta → SUCCEEDED. Ausencia demostrada permite validar el primer efecto.
Contradicción/incompletitud → UNCERTAIN, sin blind retry. FAILED requiere rechazo
definitivo y prueba de ausencia; rechazos previos conservan DENIED/BLOCKED_BY_PRECONDITIONS
de B8A. SQL/error del adapter queda conservadoramente UNCERTAIN aun si el test
observa rollback local. Un replay posterior a una edición humana reconoce el Pet
histórico y nunca restaura campos ni repite save. El inspector muestra original y actual.
La pérdida inyectada del acknowledgement de COMMIT devuelve UNCERTAIN al llamador;
si el commit ocurrió, el estado durable sigue SUCCEEDED y la siguiente entrada
reconcilia el mismo Pet. No reescribe un posible éxito como ausencia de efecto.

## Side effects, observabilidad y rollback

No se encontraron signals Pet→MedicalRecord/Appointment/VaccineRecord/Invoice,
notificación, analítica o invalidación dashboard. auto_create_medical_record=False
permanece y corresponde a Agenda, no al alta Pet. La creación conserva los campos
de auditoría del modelo. No crea owner ni clínica/cita/facturación implícitos.

Eventos cerrados AGENT_B8E_: pet_registration_requested, succeeded,
precondition_failed, reconciled, evidence_mismatch y uncertain (cada uno con prefijo
pet_registration_). on_commit robusto; labels solo event/count/schema. Sin nombres,
teléfonos, UUIDs, IDs o texto libre. El inspector ConversationOperation readonly
muestra owner, estado/digest/reconciliación, definición histórica y Pet actual;
no agrega botones de ejecución.

Rollback funcional: cerrar REGISTER_PET y conservar B0 cerrado. Preservar Pet,
ConversationOperation, AuthorizationEvidence, PetRegistrationEffect, ToolExecution
y resultado. Nunca borrar mascota/evidencia, resetear SUCCEEDED ni desvincular
provenance. No revertir la migración sobre evidencia comprometida.

## Pruebas y reproducción

Runner `apps.agent.tests.run_b8e_acceptance` escribe inventario, journal por ID,
resultados y exit receipt por corrida. Ejecutar con DATABASE_URL explícita a
PostgreSQL local y base test_b8e_ para B8E. Las suites históricas de procesos
mantienen sus prefijos test_b8b_/test_b8c_/test_b8d_. Ejemplos desde backend:

```text
python -m apps.agent.tests.run_b8e_acceptance --suite unit --database test_b8e_acceptance --output <unit>
python -m apps.agent.tests.run_b8e_acceptance --suite processes --database test_b8e_processes --output <processes>
python -m apps.agent.tests.run_b8e_acceptance --suite corpus --database test_b8e_corpus --output <corpus>
python -m apps.agent.tests.run_b8e_acceptance --suite targeted --ids-file <ids.json> --database test_b8b_regression --output <historical>
python -m apps.agent.tests.run_b8e_acceptance --suite domains --database test_b8e_domains --output <domains>
python -m apps.agent.tests.run_b8e_acceptance --suite checks --database test_b8e_acceptance --output <checks>
```

Entorno local: Python 3.13.2, Django 6.0.5 (venv bloqueado de B8B), PostgreSQL
16.15. Puerto 35432: el puerto de pruebas previo 25432 rechazaba bind. No se
intervino el servidor instalado de 5432. Cluster de pruebas conservado
`vet-b8b-pg16-data`; recuperación natural antes de pruebas, sin reset ni fsync OFF.
El servidor se detuvo al interrumpirse una sesión y volvió a completar recovery;
el timeout de conexión de esa continuación se conserva como fallo de infraestructura.
Passwords MD5 exclusivamente para fixtures sintéticas. No proveedores productivos.

Una nueva interrupción dejó 429/430 dominios aprobados y 1.469/1.726 IDs históricos
conservadoramente acreditados. Se retiró de ese conteo un `ok` B8C cuya limpieza
final no se observó; se repite junto a los pendientes. La recuperación del cluster
anterior siguió en redo. Para continuar se creó otro cluster **vacío**, independiente,
`vet-b8e-closure-pg16-data`, puerto 35433, mismo PostgreSQL 16.15 y migraciones
completas desde cero. Se preservaron cluster/evidencias anteriores; se detuvieron
solo los runners que esperaban conexión. No se resetearon WAL/datos ni se desactivó
fsync/synchronous_commit. El nuevo cluster espacia checkpoints a 30 minutos para
pruebas locales; no es configuración productiva ni una reducción de durabilidad.

El cluster anterior terminó su recuperación natural y se cerró limpiamente sin
clientes activos. La recuperación de IDs y las corridas finales terminaron en
35433, con fsync/synchronous_commit ON. No hay test pendiente por infraestructura.

Primeros fallos preservados: ImportError por alias NAME_REGEX usado por importador,
48 errores de fixture por usar record_derived para valores explícitos; después
44/48 aprobados y cuatro casos de fixture corregidos (genérico de organización,
constraint uncertain de Message y basename del router humano). Recuperación 4/4;
cinco pruebas adicionales 5/5. El conteo funcional único es 53, no suma de corridas.
Dos verificaciones posteriores de integridad de evidencia/digest amplían ese
inventario a 55 IDs funcionales. La corrida final de corpus descubre exactamente
36 casos: se corrigió una importación que también descubría 53 funcionales, por
lo que los 89 IDs de la primera corrida no representan 89 escenarios de corpus.
Las corridas posteriores y cobertura completa se consolidan por IDs, sin presentar
repeticiones como una sola ejecución ininterrumpida.

### Matriz PET y guards

| Casos requeridos | Evidencia |
| --- | --- |
| PET-01/02 | Registro real con owner/tenant/definición exactos |
| PET-03/04/05/06 | Tenant owner/contact, snapshot, binding e identidad stale |
| PET-07/08 | Nombre ausente, campos extra, fuentes derivadas y valores no canónicos |
| PET-09/10/11 | Corrección, replacement y consentimiento expirado |
| PET-12/13 | Retry tras edición humana y dos workers de una operación |
| PET-14/15 | Alta humana equivalente y operaciones distintas con datos idénticos |
| PET-16/17 | Pets de otro owner/tenant no reutilizados |
| PET-18/19 | Provenance y digest contradictorios, UNCERTAIN |
| PET-20/21/22 | B0, flag y adapter ausente |
| PET-23/24/25 | Takeover, handoff/safety, permiso/revocación |
| PET-26/27/28 | Sin Owner/Appointment/MedicalRecord/VaccineRecord/Invoice implícitos |
| PET-29/30 | Defaults de dominio y desconocidos preservados |

28 guards específicos incluyen consentimiento pendiente/rechazado, AuthorizationEvidence
ausente, digest, propuesta no emitida, causalidad, expiry/replacement, todas las
revisiones, permiso, safety/handoff/takeover/corrección, B0/flag/consent gate,
adapter ausente/deshabilitado, modo deshabilitado y tenant. Pruebas adicionales
verifican schema legacy y modo contextual reales, no solo mocks.

### Multiproceso y failure injection

Procesos Python independientes, cada uno con conexión/backend PostgreSQL propio.
Los threads auxiliares solo leen stdout; no ejecutan negocio. PIDs y esperas Lock
se guardan en el journal `.processes.jsonl` y en aceptación consolidada.

La corrida final de 29 casos registró **58 PIDs de workers independientes** y
**16 esperas PostgreSQL `Lock`**. Ejemplos de PIDs: 332, 1756, 2156, 2272, 4076,
5208, 6728 y 6992; el JSON conserva los 58, sus IDs de prueba, resultados y los
PIDs de backend observados. Los workers matados antes del resultado conservan
su PID de proceso y frontera observada. Sumando evidencia de corridas anteriores,
hay 109 valores de PID distintos y 30 observaciones Lock; no son 109 pruebas ni
se usa esa suma para acreditar cobertura. Todas las pruebas de concurrencia del
inventario final ejecutaron procesos, no threads de negocio.

| FI | Frontera/escenario |
| --- | --- |
| B8E-FI-01 | Kill después de guard y antes de locks Patients |
| B8E-FI-02 | Kill después de lock owner y antes de INSERT |
| B8E-FI-03 | Kill tras INSERT Pet y antes de ledger |
| B8E-FI-04 | Kill tras ledger y antes de commit |
| B8E-FI-05 | Kill tras commit antes de recibir resultado |
| B8E-FI-06 | Dos workers misma operación, una evidencia/Pet |
| B8E-FI-07 | Registro humano equivalente concurrente |
| B8E-FI-08 | Corrupción controlada de provenance, UNCERTAIN |
| B8E-FI-09 | Error SQL al persistir evidencia, rollback y no blind retry |
| B8E-FI-10 | Retry tras modificaciones legítimas, sin sobrescritura |

Además: owners iguales/distintos en paralelo, dos operaciones idénticas,
evidencia concurrente contra UNIQUE, binding/identidad y corrección/revocación/
takeover/handoff en ambos órdenes. Los bloqueos anteriores impiden efecto; los
posteriores preservan negocio. Los kills son únicamente de workers de test.
Se añade pérdida de acknowledgement de COMMIT, alta humana comprometida antes
del intento autónomo y edición telefónica real de Owner en ambos órdenes: 29 IDs
multiproceso en el inventario final.

### Archivos de ejecución y migración

Runtime modificado: `agent/operation_execution.py`, `agent/pet_execution.py`,
`agent/operations.py`, `agent/operation_proposals.py`, `agent/matter_binding.py`,
`agent/admin.py`, `patients/creation.py`, `patients/serializers.py` y
`patients/models.py` bajo `backend/apps`. Migración aditiva:
`patients/migrations/0019_pet_registration_effect.py`. No se modificó ninguna
migración aplicada B0–B8D. El resto de Python cambiado corresponde a pruebas y
al runner de aceptación.

Corpus [v1](evals/b8e-register-pet-corpus-v1.json), 36 escenarios reales. Métricas
críticas: unauthorized_pets_created, wrong_owner_pets_created,
duplicate_pets_from_same_operation, human_created_pets_claimed_as_agent_effect,
inferred_clinical_fields_persisted, forbidden_operation_kinds_executed y
wrong_tenant_pets_created. Se calculan sobre resultados persistidos y assertions
del corpus; no representan garantía universal.

Regresión obligatoria: inventario exacto B8D de 1.726 IDs B0–B8D y dominios
históricos; adicionalmente Patients, importadores, MedicalRecord, Agenda y
Dashboard completos. Conserva cada ID histórico. Solo cambian assertions que
declaraban REGISTER_PET sin adapter y la captura explícita de los slots B7A;
no se relajan guards ni se eliminan pruebas. Checks: django check,
makemigrations --check --dry-run, migrate --check y git diff --check.

## Hallazgos, gates y cierre

Matriz acotada H01/H02/H05/H06/H08/H18 y H12/H13 en §13.1 del plan: consentimiento,
propuesta, grounding histórico, idempotencia, precedencia e identidad del owner
reciben evidencia B8E. No se declara cierre transversal de ninguno por esa razón.

Cinco adapters existentes, cinco productivamente OFF: CREATE B8B,
RESCHEDULE/CANCEL B8C, CONFIRM B8D, REGISTER_PET B8E. B0 cerrado,
AGENT_B7B_CONSENT_ENABLED=False, AGENT_OPERATION_EXECUTION_ENABLED={}.
PENDING_ACTIVATION_REQUIREMENTS. No deploy ni B9. No se implementaron E1–E5 ni P-A/P-B.

Riesgos no cerrados: teléfonos compartidos/reciclados, step-up, autenticación
fuerte universal, identidad física, exactly-once externo, pérdida eléctrica y
requisitos operativos/clínicos/Inbox de activación. Las pruebas locales no
autorizan tráfico productivo.

Recomendación de cierre: **COMPLETED exclusivamente B8E**, con todos los IDs
pendientes recuperados y checks aprobados. Se detiene aquí la implementación.
La decisión posterior sobre B9 queda fuera de esta entrega y no autoriza activación.
