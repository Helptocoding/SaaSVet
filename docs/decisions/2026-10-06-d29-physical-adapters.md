# D29: adaptadores físicos, inspección previa

Baseline obligatorio: `825db75df68bf076929fa787e77beefe96803350`.
Estado de partida: `CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY`.
Este documento añade el plan de acreditación física finita; no modifica D29-v1,
E4, B8/B9 ni la aceptación de niveles. E permanece sin definir.

Se inspeccionaron runner/evidence/controller/assessment/recipes/execution/
scenario_observations, sus 55 pruebas, los receipts del controlador y D29-v1.
El grafo indexado contiene las primitivas del baseline; los módulos D29 nuevos
no están indexados y se leyeron directamente. También se inspeccionaron claim,
quiet-window, ownership, worker, sender, consentimiento y execution guard.

| Caso | Frontera y control físico | Evidencia e invariantes | Cleanup y piezas parciales |
| --- | --- | --- | --- |
| R1-07 | Ingest real, deadline DB natural, claim exterior y membresía W1/W2. Antes/alrededor/después del deadline, sin poll y fixture legacy NULL separado. | Journal completo + census; corrección conserva origen; W2 no entra en W1; duplicado no crea obligación; cruce temporal conserva intervalo, nunca instante ficticio. | DB privada por variante; runner.accredit ya contiene parte de W1/W2/duplicado. No reutilizar fixture que borra available_at. |
| R2-03 | Proceso hijo con membresía preparada en transacción exterior, barrera antes de COMMIT y terminación real del proceso. | Journal truncado conservado, PID/backend, desaparición de sesión, consulta independiente que prueba ausencia de work/binding, nuevo claim posterior. La captura truncada no se convierte en journal válido. | Terminar hijo y comprobar backend desaparecido, rollback DB automático; aislamiento por clon. No había kill adapter. |
| R2-04 | Hijo detenido después de claim exterior duradero, terminación real y expiración natural de lease antes de reclaim. | Visibilidad independiente antes de kill, lease original, rechazo pre-expiry, mismo work/members/context/budget, token nuevo; testigo viejo no publica. | Hijo/backend cerrados, clon eliminado. Pruebas B3 existentes adelantan lease: no sirven para esta acreditación. |
| R2-05 | Error en provider contenido después de admisión LLM real; worker fail handler y backoff natural; retry y agotamiento real. | Admisiones y budgets duraderos, due DB sin modificar, misma membresía/work; intentos acumulativos y terminal FAILED, sin éxito inventado. | Provider parcheado solo en proceso, clon eliminado; no usar retry_due del harness. |
| R2-06 | Parada y nuevo proceso con pending + PROCESSING duraderos. | PIDs distintos, census antes/después, recuperación al deadline original, nueva obligación pending separada y presupuesto/historia retenidos. | Reap de todos los hijos, backend desaparecido y clon eliminado. Participants anterior solo soporta arranque/parada normal. |
| R2-07 | Locks PostgreSQL independientes de org y Message, espera pg_stat_activity/pg_locks, rollback exterior/savepoint y pérdida de ACK después de COMMIT real. | Miss observado antes de release; wait de transacción real; binding preparado luego ausente; ACK resuelto por otro backend y membresía/token verificados. | Finally libera lock y cierra peers/hijos; clon eliminado. runner.accredit ya contiene rollback y ACK; no había control de locks. |
| R2-08 | Ingest safety real y endpoint humano claim, antes/después de claim y W1 PROCESSING/W2 READY. | Inventario ordinario previo, epoch avanzado, handoff/estado duraderos, testigo previo fenced sin salida; interrupciones conservadas como excepción y no éxito ordinario. | HTTP vía cliente Django local; no envío de guidance ni alert externo; clon eliminado. Helpers B5 existentes no conservan deadlines naturales. |
| R2-10 | Preparación/propuesta/recibo/consentimiento reales y guard negativo; TTL/autoridad expirados, scope ajeno y gate cerrado. | Motivo exacto del rechazo, autoridad causal previamente válida, reloj DB real, efectos Appointment/Pet/ledger sin cambios y ninguna llamada externa. | Gates WRITE permanecen cerrados; fixture y DB privadas. Tests B8 que parchean db_now no acreditan expiración física. |

Las 36 variantes se inventarían por separado. Un receipt PASS de replay no se
utiliza como evidencia. Los nueve adaptadores existentes se ejecutarán en un
check finito de sus fronteras; sus requisitos de carga CONFIRMED_BASE y aceptación
de niveles seguirán pendientes de caracterización. Si ese requisito impide
cerrar un escenario completo, se conservará FULL_LIVE_MATRIX_NOT_READY y se
declarará explícitamente: no se sustituye una base confirmada por una tasa inventada.

Las barreras de proceso, wrappers de conexión, providers y clientes locales se
instalan únicamente en las herramientas de prueba. Ningún deadline, lease,
backoff, presupuesto, reloj o archivo de runtime se acorta para acelerar pruebas.
Cada ejecución tiene clon nuevo, run ID, hashes de fuentes, receipt verificable
por lectura posterior y registro de errores. Se conserva toda evidencia fallida.
