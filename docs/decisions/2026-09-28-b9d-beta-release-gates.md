# B9D — Aprobación por release sin workflow de activación

Estado: aceptado técnicamente; B9 y aprobación operativa pendientes. Baseline `4f6d199dc4f8b38e5d48582f9ee289bf8dcfdb17`.
Autoridad: R13 del mapa, §7/B9 deploy/rollback y §§8/11/14 del plan canónico.

La implementación de cinco adapters no acredita aprobación por organización.
B0, registry, consentimiento y execution flags ya son gates distintos; duplicarlos
en otra tabla de activación crearía una autoridad que el plan no prescribe.

La lista aprobada reside en un valor de release inmutable y vacío por defecto.
Enumera capabilities READ/WRITE y organizaciones, con evidencia externa mínima
por requisito: org, autoridad, fecha, referencia, revisión y resultado. Cada
aprobación pertenece al artefacto candidato y versión mínima declarados. El código
valida estructura, scope, presencia y fallos/omisiones; el aprobador de release
comprueba el contenido de las referencias. No se presenta esa validación como
revisión veterinaria, de privacidad ni ejecución de PROFILE-BETA-1.

No nuevas tablas, campos, migraciones, flags, estados persistentes o writers
administrativos. READY se deriva; no existe ACTIVE persistido. La lista no concede
consentimiento/identidad ni elude preconditions. La frontera única B8A añade el gate
antes de efectos nuevos y después de la reconciliación histórica. El inspector
CLI no escribe y no ofrece activación, bypass o enable-all. La selección de piloto
es parte de la evidencia y no activa por sí sola. Las rutas READ/CONTROL existentes
de B0 conservan acceso/política propios; autonomía READ requiere aprobación de
release y despliegue autorizado por el gate operacional.

Retirar aprobación es un cambio de release mediante pausa, drain, corte de todos
los writers y verificación de colas. No se promete revocación en caliente entre
procesos con versiones distintas. El procedimiento es obligatorio antes de
reactivar, y la nueva aprobación debe tener una fecha nueva. El guard compara
esa fecha con created_at inmutable de la operación: una operación preparada
antes no inicia efectos. Esto evita otra revision y preserva autorización,
digest, binding_revision, identity_revision, ownership_epoch y ledger existentes.

No cambia el significado histórico de enabled: es disponibilidad del subsistema,
no una certificación de beta. Pausar mediante ese kill switch no constituye una
nueva aprobación. La retirada/reapertura de autonomía usa el corte de release;
no basta togglear enabled. B9B y B9C no se modifican ni se reinicia presupuesto.
Los efectos ya committed siguen reconciliables con aprobación retirada. Sender
conserva sus garantías y límites respecto a HTTP previamente admitido.

No hay carrera administrativa de un estado nuevo: la fuente es constante por
proceso, fuera de una transacción de edición de DB. Los tests PostgreSQL cubren
la decisión en B8A, aislamiento, los cinco efectos y rollback SQL. Las carreras
de autoridad/dominio existentes se reejecutan en la regresión, sin presentarlas
como una aprobación operativa. Fixtures TEST_EVIDENCE son rechazadas por la
política productiva; tests abren explícitamente el entorno de evidencia sintética,
igual que B0/consentimiento/flags, sin sustituir evaluator, guard o adapter.

El [contrato](../contrato-beta-release-b9d.md) y la
[extracción literal](../evals/b9d-requirements.json) explican alternativas y límites.
Aceptación integral B9E y aprobaciones externas pendientes. B0 cerrado,
B7B=False, execution flags={}, cero grants productivos, sin deploy.
