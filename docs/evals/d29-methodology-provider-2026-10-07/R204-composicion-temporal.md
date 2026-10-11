**R2-04 — calendario final propuesto; no ejecutado**

El reclaim individual permanece acreditado. No se lo repite como prueba autónoma ni se reinicia su evaluación. Una nueva ejecución de la combinación deberá reproducir un crash real como precondición: un receipt histórico no puede suministrar un work vivo en la nueva DB.

La propuesta conserva la ventana base de 360 s, el seguimiento íntegro de 240 s, los 900 s del lease natural, dos planners y un sender. No requiere ampliar población, modificar pacing ni generar una nueva base. Introduce un inventario inicial de fallo capturado y un anclaje de la ventana base al lease observado; esas dos condiciones necesitan aprobación como extensión del escenario.

Sea C el `claimed_at` real del work inicial, L su `lease_expires_at` observado, y P la cadencia exacta derivada del receipt: `60 / 1,9607508002652434 = 30,60052302 s` aproximadamente. Los cálculos del conductor deben usar la representación exacta ya sellada y registrar brackets DB/monotónico, no los decimales redondeados de esta tabla.

| Fase | Anclaje propuesto | Qué sucede físicamente |
|---|---|---|
| Inicio de captura | Antes del primer inbound | Conexiones, participantes, reloj y testigos independientes identificados. La edad del input previo a C también se conserva. |
| Preparación finita | Ingress → READY natural → claim | Un mensaje ordinario en uno de los tres slots de A; claim con membership/contexto reales, outer commit y reserva durable conforme a la primitiva acreditada. |
| Crash | Después del outer commit, a tiempo observado | Terminar el proceso propietario, acreditar exit OS y desaparición de su backend. Ningún deadline, token o presupuesto se reescribe. |
| Espera natural | Hasta S = L − P | Sin nueva oferta base todavía. Preparar los participantes que consumirán la ventana; no usar su arranque tardío para controlar qué planner gana el reclaim. |
| Inicio base | S ≈ C + 869,39947698 s | Corte DB inicial y oferta desde el calendario equilibrado base original. Dos planners y un sender ya listos. Primeras aceptaciones de ambas orgs deben ocurrir antes del reclaim. |
| Expiry | L = C + 900 s, comprobado en DB | El lease vence por paso de tiempo real. La oferta base continúa. El reclaim debe surgir del polling ordinario, no de un claim directo del conductor. |
| Fin de oferta | S + 360 s ≈ C + 1229,39947698 s | Corte real; no se agregan inputs ordinarios después. |
| Fin de seguimiento | S + 600 s ≈ C + 1469,39947698 s | Conservar los 240 s completos aunque la cola drene antes. Corte final de obligaciones, recovery, outbound y cleanup. |

La duración total es aproximadamente 24 min 29,4 s desde C, más el ingreso previo a C y el cierre. No son 24 minutos de oferta: sólo hay una ventana de oferta de 360 s. No hay sweep, nivel nuevo ni extrapolación de capacidad.

**Concurrencia y estado.** El proceso del preámbulo ocupa uno de los dos slots de planner. Primero se confirma su muerte y luego se crea su reemplazo; el otro slot y el sender completan el conjunto. Nunca hay tres planners vivos por conveniencia de la fixture. No hay barrera de polls alrededor de L. El input de fallo usa un slot ya incluido en las tres conversaciones de A; los inputs posteriores a su primer claim son W2 y se conservan como tales. El work recuperado mantiene context_at, membership, cursor, límites y consumos acumulados. Su deadline de turno de 720 s tampoco cambia: no se exige inventar una nueva llamada LLM tras el reclaim si su resolución natural es terminal.

**Qué demuestra el calendario y qué no.** La desigualdad `S < L < S+360` demuestra solamente que el diseño permite que el expiry caiga dentro de la oferta. No prueba que el proceso haya reclamado allí ni que el generador haya emitido la carga. No es posible entregar una observación física futura sin ejecutar; hacerlo contradiría la pausa que has indicado. Por ello la acreditación del solapamiento sigue pendiente.

Antes de ejecutar se rechaza el plan si el lease observado no conserva 900 s, si el arranque ya perdió la ventana prevista, si se necesita cambiar alguna tasa/ventana, si el número de slots no es dos, si la captura comenzó después del ingreso o si falta procedencia de la base. No se mueve S hacia adelante para salvar un arranque tardío: ese intento no demuestra esta composición.

Durante la futura ejecución, estos testigos son obligatorios:

1. Brackets del corte inicial/final de oferta, ledger completo de emisiones, ACK/commit de cada aceptación y comparación con el calendario original. Calendarizar una llegada no cuenta como emitirla.
2. Expiry original y bracket del **commit de reclaim**, con `L <= reclaim_lo <= reclaim_hi < fin_oferta_lo`. También debe ser posterior al inicio observado de oferta. No basta ver un token nuevo en una consulta posterior.
3. Aceptaciones durables de **ambas** orgs antes y después del reclaim dentro de la ventana; además, continuidad del emisor y progreso/obligaciones ordinarios concurrentes. Dos inputs aislados que rodean un reclaim no sustituyen el gate completo de pacing/carga.
4. Same work/membership/contexto, attempts incrementado por la primitiva, token nuevo, budget no reiniciado y old witness fenced. Estos checks se preservan como invariantes de la combinación, sin revocar el resultado individual ya aceptado.
5. PID/slots en todos los cortes, clocks estrictos, pertenencia por tenant, ausencia de HTTP en transacción y evidencia de destinos contenidos. Inventario del preámbulo separado de la demanda base; ninguna obligación se excluye por ser incómoda para el resultado.
6. Seguimiento completo de 240 s, resolución/drain o censura explícita y cleanup. Una espera elevada de la org afectada por el work de fallo se informa íntegra; no se le aplica una excepción comercial inventada ni se restan los segundos del preámbulo.

PASS de infraestructura/frontera compuesta sólo con todos esos testigos y verificadores correspondientes. Si el reclaim ocurre fuera de la ventana, si no hubo oferta real concurrente, si queda una frontera sin observar o si el drain exigido no se resuelve, `NOT_ACCREDITED`; reloj/captura/plan inválidos añaden `INVALID_RUN`. No se extiende la oferta ni se reduce el lease para convertirlo en PASS.

La composición es físicamente admisible según las primitivas actuales, pero el solapamiento **aún no ha sido observado**. Queda autorizable como un único probe compuesto después de aprobar este diseño, sin repetir un probe individual adicional de reclaim.
