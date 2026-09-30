# B9E — readiness de activación separado de la aceptación técnica

El baseline B9D no contiene grants productivos. Este inventario no asigna clínicas ni personas ficticias. Una fixture `TEST_EVIDENCE` prueba el mecanismo B9D, pero nunca acredita un requisito humano real. Fuente: plan canónico §5.5, §7:710/731/733, §§8/11/12/15 y contrato B9D.

| Requisito para una clínica real | Estado | Evidencia externa que faltaría |
| --- | --- | --- |
| Clínica piloto, alcance READ/WRITE y tasa autorizada | PENDING_REAL | Identidad de la organización real y aprobación fechada del alcance exacto |
| Responsable y cobertura humana de Inbox | PENDING_REAL | Owner, horario y sustituto operativos |
| Protocolo/corpus clínico revisado por veterinario responsable | PENDING_REAL | Revisión profesional y versión aprobada |
| Simulacro de descubrimiento, claim, respuesta y resolución del caso humano, incluso sin aviso secundario | PENDING_REAL | Acta de simulacro por clínica y ruta de escalamiento |
| Responsable de seguridad clínica y manejo de urgencias | PENDING_REAL | Nombre/rol, protocolo de intervención y revisión del texto de guidance |
| Responsable y revisión de privacidad P-A | PENDING_REAL | Política por categoría, finalidad y plazos revisada |
| Mecanismo P-B aplicable a las categorías/plazos prometidos | PENDING_REAL | Prueba de retención/restore bajo la política aprobada |
| Canal alternativo de fallback/escalamiento validado | PENDING_REAL | Ensayo real del canal y cobertura |
| Aceptación explícita del riesgo de teléfono compartido/reciclado | PENDING_REAL | Decisión escrita del responsable de producto/privacidad |
| Evaluación real del modelo al cambiar prompt/modelo/semántica o promover autonomía | PENDING_REAL | Artefacto del candidato, responsable y acción; no reemplaza el corpus determinista |
| Cutover, versión mínima compatible y rollback por clínica/capability | PENDING_REAL | Plan operacional aprobado y ventana de drain/reconciliación |
| Gate técnico PROFILE-BETA-1 para el alcance/tasa propuestos | PENDING_REAL | Recibo íntegro PASS sin fallos, omisiones ni thresholds alterados |
| Aviso secundario E3, fairness fuerte E4 y altas compuestas E5 | NOT_REQUIRED | Son ampliaciones separadas y no prerrequisitos de esta beta acotada, salvo que el alcance futuro las exija |

No existe ningún `SATISFIED_REAL` en la evidencia accesible a B9E. El estado operativo es `PENDING_ACTIVATION_REQUIREMENTS`, con **0 clínicas activadas**. La existencia de `AgentSettings.enabled` en tests no cambia ese estado.

Rollback después de una eventual promoción: retirar/reducir el grant de release mediante pausa y drain coordinados, cerrar B0/B7B/flags de la capability afectada, identificar `TurnWork` y HTTP ya admitidos, esperar o clasificar incertidumbre, mantener sender y fencing, inspeccionar colas y reconciliar efectos ya committed antes de cualquier reabertura. No borrar `Message`, `TurnWork`, `LLMCall`, `ConversationOperation`, `AuthorizationEvidence`, `ToolExecution`, evidencia de efectos de dominio ni rastro outbound. Una reemisión incierta requiere decisión humana explícita; no reintento ciego. B9E no ejecuta este rollback en producción ni efectúa deploy.
