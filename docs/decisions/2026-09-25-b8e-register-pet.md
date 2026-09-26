# ADR B8E — creación individual e histórica de Pet

Fecha: 2026-09-25. Decisión congelada antes del runtime. Baseline
`863841694ca25274dc83e81e24c0fe0103e86fd7`.

| Alternativa | Evaluación |
| --- | --- |
| A: OneToOne nullable en Pet | Unicidad mínima, pero el Pet mutable no conserva la definición original; necesita snapshot adicional protegido y mezclaría estado mutable con evidencia histórica |
| B: ledger específico | Una fila por operación y Pet, snapshot original inmutable, tenant/digest/FKs protegidos; humanos/legacy siguen sin evidencia |
| C: EffectEvidence actual | Es valor tipado del resultado, no evidencia independiente de dominio; ToolExecution tampoco demuestra INSERT exacto |

Se elige B, PetRegistrationEffect. Es la frontera mínima que preserva identidad
histórica tras edición de Pet sin atribuir altas humanas al agente. No reutilizar
AppointmentMutationEffect ni introducir event sourcing general. Trigger PostgreSQL
valida definición/tenant/digest/owner/Pet al INSERT y protege evidencia inmutable;
unicidad de UUID es defensa final de idempotencia. Sin backfill ni migraciones
destructivas. Pet sigue editable por vías humanas.

Servicio mínimo patients.creation compartido con serializer humano. Parámetros v1
intactos; preconditions schema 4 incluye snapshot de owner/contrato de registro y
renderer visible nuevo. Legacy no adquiere autorización. Bloquear procedencia
inferida al preparar registro; no ampliar a sexo/raza/peso ni altas compuestas.

Locks B8A intactos seguidos por Organization/Owner FOR SHARE; sin exclusividad de
clínica ni deduplicación semántica inventada. Humano equivalente y operaciones
distintas pueden crear Pets distintos. Guard/efecto/ledger/resultado son atómicos.
UNCERTAIN reconcilia, no reintenta a ciegas. Rollback solo cierra feature.

Revalidación del orden real: el signal de Owner al cambiar teléfono puede bloquear
ContactIdentity para revocarla. La precondition B8E toma Owner FOR SHARE NOWAIT;
Owner ocupado causa rechazo temporal sin INSERT, libera ContactIdentity y evita
el ciclo Owner→Contact frente a Contact→Owner. No se refactoriza el signal humano
ni se espera bajo locks B8A. Altas distintas mantienen compatibilidad FOR SHARE.

Aceptación técnica completada el 2026-09-26: 55 funcionales, 36 corpus y 29
multiproceso B8E; 1.726/1.726 IDs B0–B8D y 430/430 dominios, 2.097 únicos en la
unión. Checks Django/migraciones/diff aprobados. Evidencia por ID en el
[acta](../implementacion-b8e-agente-whatsapp-2026-09-25.md) y
[aceptación](../evals/b8e-acceptance-results.json). Producción OFF, B0 cerrado,
PENDING_ACTIVATION_REQUIREMENTS, sin deploy ni B9.
