# B9D — Alcance y gates de release beta

Baseline verificado antes de modificar: `4f6d199dc4f8b38e5d48582f9ee289bf8dcfdb17`.
Fecha: 2026-09-28; seguimiento 2026-09-29. Estado: COMPLETED técnico; aceptación documentada en el acta B9D.
Autoridad: plan canónico completo, §7/B9 y §§5.5, 8, 9, 11, 12, 14, 15;
R13 del mapa interno. B9 permanece IN_PROGRESS. B9E conserva R01/R06–R10/R15.

## Reconciliación previa

El plan exige una lista explícita por release y organización, intersección con
política/identidad/contrato, gates técnicos y cobertura humana antes de ampliar
cohortes. No exige un workflow administrativo, tabla cohort, estado ACTIVE,
activation_revision ni una aprobación mutable en Organization.extra_data.
READY es una conclusión del gate para un alcance, no una fila de autorización.
Terminar implementación no constituye esa conclusión ni habilita tráfico.

| Requisito literal / autoridad | Existente / gap | Cambio y prueba | Dueño |
| --- | --- | --- | --- |
| §7/B9: «Aprobar lista explícita: READs públicas, READs personales y cada WRITE adaptado.» | Effects B2, cinco adapters y flags B8; falta lista aprobada completa | Manifest de release cerrado, validación de nombres/contratos, pruebas de listas incompletas/ajenas | D mecanismo; E evidencia |
| §7/B9: «Por org, autonomía efectiva = lista del release ∩ política/identidad ∩ capacidades del contrato desplegado.» | B2/B7/B8 verifican política y contrato; no aprobación org/release | Grant explícito por org, sin wildcard; guard B8A consume la intersección antes de efecto nuevo | D |
| §7/B9: «Ampliar cohortes solo tras gates técnicos y cobertura humana» | Evidencias de componentes, sin aprobación operativa | Evidencia externa tipada y trazable por org; candidato incompleto nunca READY | D mecanismo; E aceptación |
| §7/B9: «retirar capacidad/reducir carga para rollback, conservando sender, fencing, contabilidad y datos.» | Runbooks B3/B4/B7/B8/B9B/C | Retirar del release mediante corte/drain compatible; conservar ledger/reconciliación | D |
| §7/B9: «Cierre técnico y gate operativo separados.» | Actas A/B/C ya separadas | Inspector readonly distingue aprobación del release, gates runtime y pendientes | D |
| §7/B9: «gates fallidos/skipped nunca verde.» | Runner exacto B9A; perfil integral pendiente | Evidencia técnica requiere PASS sin fallos/omisiones y artefacto candidato; faltante bloquea | D validador; E ejecución |
| §7/B9: «P-A aporta política revisada; P-B demuestra el mecanismo de retención aplicable.» | P-A/P-B pendientes | Referencia a revisión/evidencia aplicable; no implementar privacidad ni marcarla satisfecha | E/externo |
| §5.5: «Antes de abrir beta, producto debe aceptar por escrito el riesgo de teléfono reciclado/compartido desconocido.» | Riesgo abierto | Evidencia operacional explícita; ausencia bloquea | Externo |
| §7/B5: «protocolo revisado por veterinario y simulacro por clínica de descubrimiento→claim→respuesta→resolución, incluyendo ausencia/fallo de aviso.» | B5 técnico, VETERINARY_REVIEW_REQUIRED | Referencias independientes de protocolo/corpus y simulacro; no certificación clínica por software | Externo |
| §8.2: «Activar por clínica/cohorte después de gates y conservar kill switch.» | AgentSettings.enabled; B0, B7B y flags B8 | Cohorte = orgs enumeradas en release; enabled no equivale a aprobación | D |
| §11: «detener nuevas acciones → identificar trabajo/HTTP en vuelo → esperar o clasificar incertidumbre → versión mínima compatible → verificar colas → reabrir solo capacidades aprobadas.» | Fences, sender, ledger y runbooks existentes | Sin hot reload de aprobación ni nueva API; nueva aprobación requiere operaciones posteriores a ella | D |
| §14: «Las columnas de B9/E5 son escenarios de activación independientes, no permisos acumulados automáticamente» | Altas compuestas no adaptadas | Rechazar capabilities sin contrato; ninguna apertura por completar una fase | D |
| §7/B9 PROFILE-BETA-1 y medición completa; EVAL/COST/SCALE integral | A/B/C primitives aceptadas | No ejecutar en D; evidencia técnica sigue ausente en release productivo | E |

## Autoridad única y evidencia

La lista aprobada es un valor inmutable en código de release, revisado junto
con su artefacto; producción comienza vacía. No se carga desde env, FAQ, LLM,
JSON arbitrario, API o settings mutables. Cada grant enumera org/capabilities y
referencias opacas a evidencia humana con autoridad, fecha y revisión. El material
privado se conserva en el registro operativo autorizado, no en logs o prompts.
La validación comprueba estructura/procedencia declarada y alcance, no la verdad
clínica/legal de documentos externos. La revisión humana de esos artefactos es
obligatoria al aprobar el release. Fixtures nunca son evidencia real.

Requisitos operativos: selección de piloto/alcance/tasa, responsable y cobertura
Inbox, revisión veterinaria del protocolo/corpus, simulacro Inbox, revisión de
privacidad y mecanismo P aplicable, canal alternativo validado, aceptación del
riesgo de identidad, cutover/versión mínima/rollback y aprobación humana del alcance.
La validación de fallback significa evidencia del ensayo humano de la ruta
prevista, incluso sin aviso secundario; una dirección/teléfono no acredita ensayo.
El plan no exige que responsables externos sean Users. No se inventan identidades
ni se promete detectar automáticamente su ausencia; cambio/pérdida de cobertura
requiere retirar/reducir el alcance por el procedimiento operacional existente.

La evidencia técnica integral pertenece a B9E: perfil, CI crítico/corpus y eval
del candidato. B0–B9C son implementación demostrada, no sustituyen esos artefactos.
Sin ellos el candidato es PENDING_ACTIVATION_REQUIREMENTS. No hay un booleano ready.

## Integración y límites

READ_PUBLIC/READ_PERSONAL/CONTROL mantienen sus rutas existentes bajo B0 y
sus restricciones actuales; consulta pública y request_human no quedan bloqueados
por una falta de consentimiento WRITE. El manifest describe qué READ puede
aprobarse como autonomía, no elimina la disponibilidad anterior. No se añade
un mecanismo de validación humana previa a cada READ ni se afirma que ya exista.
Una configuración legacy `enabled=True` puede conservar READ bajo B0/política
previos aunque el release B9D esté vacío. Por eso B9E debe verificar esa
configuración y el alcance READ explícitamente antes de promoción operacional;
el manifest no se presenta como una nueva barrera runtime para READ.
El manifest no es un permiso de identidad y no concede acceso al dominio.

WRITE nuevo pasa exclusivamente por execute_authorized_operation: validación de
contexto/witness, definición/consentimiento/permiso, reconciliación, autoridad
B3/B5/B6/B7, B0/registry/flags/adapter y aprobación org/release, preconditions y
efecto local atómicos. Ledger previo sigue reconciliable con gates cerrados.
La aprobación no cambia cupo B9C, budget B9B, witness, epochs ni consentimiento.

No se añade persistencia/migración: las organizaciones legacy carecen de grant y
siguen sin WRITE autónomo incluso si enabled estaba encendido. El runtime no
puede autocertificarse: catálogo cerrado, sin writer ni endpoint de aprobación.
RBAC de Inbox/AgentSettings se conserva; enabled=True solo configura disponibilidad,
no rellena evidencia ni concede el grant. CLI de inspección usa acceso operacional
al management command, exige organización explícita y no muta estado.

Retiro/reactivación del release no es una mutación concurrente en DB. No hot reload
ni coexistencia de writers con diferentes listas: pausa/drain/corte §8/11. Un
proceso viejo no queda cercado por actualizar un archivo en otro proceso. Antes
de reabrir se usa nueva aprobación fechada; una operación anterior a esa aprobación
no puede empezar un efecto aunque conserve AUTHORIZED. Sin activation_revision.
Efectos committed no se compensan; HTTP ya admitido conserva realidad externa.
La prueba PG verifica el gate dentro de B8A, su composición y el ledger; carreras
administrativas de un nuevo modelo/endpoint y migración B9D no aplican.

Kill switches existentes: B0 global WRITE, AgentSettings.enabled por org,
AGENT_B7B_CONSENT_ENABLED y AGENT_OPERATION_EXECUTION_ENABLED por kind; safety B5
con su política propia. Ninguno puede ampliar la lista del release por sí solo.
La evidencia de pérdida de requisitos se aplica retirando aprobación por corte
controlado, no cambiando un checkbox de readiness en caliente.

## Aceptación prevista

Validación positiva/negativa de release, cada requisito faltante, evidencia de
test rechazada como real, scope de org/capability, contratos no adaptados, legacy,
cinco WRITE, B0/B7/B8, operaciones anteriores/nuevas tras aprobación y replay
committed; inspector readonly y ausencia de superficie de autocertificación.
Regresión exacta 2.309 IDs + nuevos, sin pendientes, y checks Django/migraciones/Git.
Corpus específico versionado y recibo por ID. No PROFILE-BETA-1 ni B9E en esta entrega.

## Trazabilidad técnica B0–B9C

| Base | Autoridad reutilizada; B9D no la sustituye |
| --- | --- |
| B0 | Contención global de WRITE y política previa de READ/CONTROL |
| B1 | TurnContext y procedencia causal, sin reinterpretar historia como consentimiento |
| B2 | Catálogo de efectos, ToolOutcome y grounding del resultado |
| B3 | TurnWork, claim/token/lease, ownership_epoch y locks transaccionales |
| B4 | Sender durable; queued, accepted y delivered son hechos distintos |
| B5 | Caso humano, safety, claim/takeover y precedencia humana |
| B6 | Goal, binding y sus revisiones; selección no concede permiso |
| B7A/B7B | Operation, digest y AuthorizationEvidence causal vigente |
| B8A | Única frontera autónoma, permisos, preconditions, reconciliación y ledger |
| B8B–B8E | Cinco adapters locales atómicos y evidencia de sus efectos |
| B9A | Harness HTTP/worker/sender y recibos por ID |
| B9B | Reservas/calls/usage por TurnWork, persistentes en retry/restart |
| B9C | Un trabajo con autoridad por org y topología de release acotada |

El orden del worker no se reemplaza por una lista conceptual de gates: la
admisión B9C ocurre al adquirir el witness B3; B9B reserva antes de cada llamada
LLM y B5 puede resolver safety sin esa llamada. Una vez obtenido consentimiento,
B8A bloquea las filas Conversation→TurnWork→Contact→Goal→Operation; comprueba
definición, consentimiento/evidencia y permiso, reconcilia resultados históricos,
comprueba autoridad vigente y luego B0→registry→flags→B7B→adapter→release.
Después bloquea/valida dominio, revalida scope/autoridad y confirma efecto/ledger
en la transacción, con deadline/expiración al commit. El inspector es un snapshot
explicativo; su lista de motivos no es un algoritmo alternativo de autorización.

`AgentSettings.enabled` conserva su comprobación en admisión del worker; no se
promete que togglearlo cancele atómicamente una ejecución ya admitida. La retirada
del release exige el drain descrito arriba. La aprobación fechada debe referir al
commit probado y al alcance exacto; el validador no verifica Git, firmas ni la
existencia del documento externo. Esas verificaciones pertenecen al aprobador y
al corte de release. Una cadena SHA con forma correcta no prueba aceptación.
