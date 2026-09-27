# ADR — B9A compone las fronteras existentes

Fecha: 2026-09-26. Estado: aceptada para implementación bajo contención.

## Decisión

Aplicar R02/R14 del [mapa interno](../mapa-interno-b9-2026-09-26.md) sin cambiar
B9 canónica. Conducir Django HTTP, worker B3 y sender B4 reales y sustituir el
wire LLM/Meta. Usar PostgreSQL y fixtures comprometidas; un rollback envolvente
no representa la visibilidad del worker ni permite despachar con B4.

Mantener los helpers de componente para la regresión histórica. Los comandos
existentes incorporan un modo explícito que ejecuta los mismos guiones con el
ciclo de test aislado; el modo de planner queda identificado como diagnóstico.
No crear otro servicio/adapter de prueba que suplante la arquitectura productiva.

El baseline no conectaba el resultado de B7B con B8A en el worker. Añadir esa
conexión dentro de `finalize_turn`, con flags/contención cerrados y guard único.
Efecto local, evidencia y recibo comparten el commit B3. El resultado derivado
de slot conserva su observación temporal; no retirar esa precondition de B7A.

## Consecuencias

Se puede distinguir generación, queue, aceptación y señal de delivery y detectar
fallos que los tests aislados no veían. Las fixtures de asunto de asistencia y
datos de mascota son explícitas: no demuestran extractores inexistentes.
Una llamada controlada a Meta no demuestra entrega externa. El kill de proceso
no certifica durabilidad ante pérdida eléctrica. No cambia identidad, privacidad,
retención, permisos de activación, presupuesto o concurrencia operativa.

Contrato y locks: [harness B9A](../contrato-harness-b9a.md). La aceptación técnica
requiere todos los IDs B9A e históricos y checks; hasta entonces permanece PARTIAL.
B9 canónica continúa IN_PROGRESS y producción cerrada. Rollback funcional:
mantener los gates cerrados y volver a un lector compatible B8E, preservando toda
la evidencia; no revertir effects ni borrar operaciones. No hay migración B9A.

Aceptación 2026-09-27: B9A COMPLETED técnico; 45 IDs propios y 2.097 históricos
aprobados, con recuperaciones documentadas. B9 permanece IN_PROGRESS.
