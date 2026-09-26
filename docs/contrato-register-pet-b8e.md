# Contrato B8E — REGISTER_PET

Congelado antes de implementar, 2026-09-25. Baseline/HEAD verificado:
`863841694ca25274dc83e81e24c0fe0103e86fd7`. §7 del plan real
`plan-implementacion-auditoria-agente-whatsapp-2026-09md` asigna B8E al alta
individual de mascota; la diferencia de extensión está documentada en el plan.
Cambios ajenos preservados: eliminaciones DEPLOY_VPS_PLAN.md y DEPLOY_VPS_STATUS.md;
auditoría 2026-09-10 untracked. No B9, E1–E5, P-A/P-B ni despliegue.

## Dominio comprobado

Pet hereda public_id UUID único, organization PROTECT, auditoría created/updated_at,
created/updated_by y is_active=True. Owner es FK PROTECT obligatoria. name es
CharField(255) obligatorio. species(100), breed(100), color(100), legacy_id(64)
admiten blank y default ''. birth_date admite NULL; sex=male/female/unknown,
default unknown; is_generic=False y extra_data=[]. No hay peso, microchip,
esterilización, alergias, diagnósticos ni vacunas en Pet.

Pet.clean exige mismo tenant del owner; OrganizationalModel.save ejecuta full_clean
y auditoría thread-local. La API PetSerializer exige nombre (letras, números,
acentos, espacios, apóstrofes y guiones), recorta bordes; especie opcional validada
contra SPECIES_CHOICES y normalizada lower/strip; nacimiento opcional no futuro
según día local de clínica. El comentario antiguo del modelo que exige especie
en alta manual está desactualizado frente a serializer, tests y UI.

PetViewSet POST usa PetSerializer.create dentro de atomic. Dos modos humanos:
owner_public_id elegido explícitamente, o owner anidado resuelto por el servicio
de identidad/deduplicación de clientes. B8E solo usa la FK owner ya autorizada.
La UI pets.jsx muestra nombre obligatorio y resto opcional; no es autoridad.
La creación común mínima se extrae a patients.creation, conservando validaciones,
defaults, tenant, full_clean y auditoría; no refactor transversal de importación
ni alta compuesta de Agenda.

No signal Pet→MedicalRecord, vacuna, cita, factura, notificación ni cache dashboard.
auto_create_medical_record=False sigue vigente y pertenece a transición de Agenda,
no a alta Pet. Las relaciones entrantes Appointment, MedicalRecord, VaccineRecord,
Prescription e Invoice protegen el Pet; no se materializan al registrarlo.
Importación crea directamente Pet y aplica deduplicación específica del lote por
owner/nombre normalizado/especie, más legacy_id. Esa política no es identidad global.
Constraints Pet: public_id único, un genérico por org y legacy_id no vacío único
por org. No constraint por nombre, especie, raza ni sexo.

## Parámetros y clasificación

Se conserva schema de parámetros B7A v1: owner_id, name; species y birth_date
opcionales. No se amplía a sex/breed/color. No argumentos nuevos en execute.

| Categoría | Datos |
| --- | --- |
| A obligatorios autorizados | owner_id exacto del binding B6, name canónico no vacío |
| B opcionales explícitos | species de catálogo, birth_date ISO concreta no futura |
| C defaults humanos deterministas | is_active=True, is_generic=False, public_id/auditoría; sex=unknown, breed/color/legacy_id='', extra_data=[] |
| D desconocidos | species omitida='', birth_date omitida=NULL; raza/color vacíos y sexo unknown no afirman hechos clínicos |
| E no permitidos | owner nuevo/cambiado, cita, historial, vacunas, peso, microchip, sexo/raza/color explícitos, datos de importación o clínicos |

Datos semánticos siguen B6 con fuente causal; B8E exige procedencia explícita de
usuario para nuevos campos registrables, nunca SYSTEM_DEFAULT/TOOL_RESULT/DERIVED
para inferirlos. No convierte edad en fecha, parecido en raza ni lenguaje ambiguo
en hechos. Consentimiento muestra todos los valores persistibles y desconocidos.
Corrección significa otra operación/propuesta/consentimiento; nunca editar AUTHORIZED.
B6.change admite los tres slots pet_name/pet_species/pet_birth_date como cambios
explícitos dependientes del owner: incrementa binding_revision e invalida lo previo.
record_derived conserva su contrato y no puede etiquetar un resultado como explícito.
No se añade extracción de lenguaje natural ni un nuevo colector conversacional.

## Identidad, snapshot y propuesta

Conversation.contact→ContactIdentity.owner debe coincidir con Goal.bound_owner,
Operation.owner y parameters.owner_id. CURRENT_OWNER conserva permiso B7A,
TTL/verificación/revisión y restricción familiar. Teléfono no selecciona owner.
Nuevas definiciones usan preconditions schema 4, registration_contract=1 y snapshot
del owner (PK, UUID, tenant, nombre visible, actividad, genérico y huella de clave
telefónica), incluido en digest. Protege también cambios humanos del expediente;
no se copia teléfono al texto. Legacy schema 1 sigue verificable pero no ejecutable.
No backfill, rehash ni consentimiento retroactivo. B7B muestra nombre del owner,
nombre Pet, especie/nacimiento explícitos o pendientes y sexo desconocido,
raza/color sin especificar. Los datos omitidos permanecen desconocidos.

## Atomicidad y locks

Única entrada execute_authorized_operation(operation_key, ExecutionContext).
B8A: Conversation → TurnWork → ContactIdentity → Goal → ConversationOperation.
Después Organization FOR SHARE → Owner FOR SHARE → INSERT Pet → ledger. Locks
compartidos protegen actividad/zona/datos sin mutex exclusivo de clínica ni owner.
El lock de Owner en la precondition B8E usa NOWAIT: Owner.save emite un signal
que puede revocar ContactIdentity al cambiar teléfono, en orden inverso al guard.
Si una edición humana mantiene Owner, B8E rechaza temporalmente antes del efecto
y libera identidad; no espera creando un ciclo. Las altas humanas conservan espera
normal. Reintentar exige todavía autorización vigente; no se abre UNCERTAIN.
Servicio humano de referencia comparte locks de dominio; no adquiere identidad
conversacional. Los mismos owners pueden registrar mascotas distintas en paralelo.
Guard final, relación/permiso/snapshot, INSERT, evidencia, ToolExecution y resultado
comparten LOCAL_ATOMIC. No HTTP, LLM, storage ni notificación remota dentro.

## Duplicados, evidencia y reconciliación

Ledger PetRegistrationEffect inmutable: operation OneToOne a operation_key,
organization, owner, Pet OneToOne exacto, digest, definición original y committed_at.
FKs PROTECT; constraint PostgreSQL y trigger verifican tenant/owner/kind/digest,
definición y Pet al INSERT; UPDATE/DELETE de evidencia prohibidos. Humano/legacy
no tienen fila, no reciben provenance sintética. No AppointmentMutationEffect.

Reconcile global por UUID distingue ausencia, evidencia exacta y contradicción.
Solo evidencia exacta histórica concede SUCCEEDED. Ausencia permite validar
primer efecto; contradicción/incompletitud → UNCERTAIN sin blind retry.
Retry tras edición humana devuelve Pet exacto y definición histórica sin UPDATE.
Una Luna humana no es evidencia de A; A puede crear otra Luna porque el dominio
lo permite. A y B con parámetros iguales son operaciones diferentes. Unicidad de
operación en DB impide dos efectos comprometidos de A; el guard serializa A.
FAILED requiere causa definitiva y ausencia probada; rechazos previos conservan B8A.
committed_at se observa dentro de transacción y solo se expone tras commit; no es
timestamp físico WAL ni garantía frente a pérdida eléctrica.

## Gates, rollback y aceptación

Cinco adapters implementados no significa activados: B0 cerrado,
AGENT_B7B_CONSENT_ENABLED=False y AGENT_OPERATION_EXECUTION_ENABLED={}.
PENDING_ACTIVATION_REQUIREMENTS. Rollback cierra REGISTER_PET preservando mascotas,
operaciones, autorización, provenance y resultados; no DELETE/reset/compensación.
Cierre exige PET-01..30 adaptados al schema real, guards B8A, procesos PostgreSQL
independientes, FI-01..10, corpus versionado y regresión exacta B0–B8D/dominios.
Métricas solo describen corpus ejecutado. No cierra identidad física/fuerte,
teléfonos compartidos/reciclados, step-up, exactly-once externo ni gates operativos.
