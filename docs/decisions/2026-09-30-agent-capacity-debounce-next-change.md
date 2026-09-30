# Decisión de arquitectura y capacidad tras E4 PARTIAL

Fecha: 2026-09-30. Corte documental revisado:
`4adcb4ad3cca768ddde7ee7be54a4cc37426e78d`.
Candidato de runtime: `7e5aa9e8cec4f6fa08ecd92870c19560c91bb469`.
Estado de este documento: **análisis terminado; propuesta sin implementar**.

**Decisión: KEEP del selector E4 como mejora independiente. El siguiente
cambio recomendado es hacer irreversible la elegibilidad de la ráfaga
pendiente una vez vencida su espera, incorporando las correcciones recibidas
antes del claim al mismo contexto. Requiere una enmienda explícita de B3/C4
y W1; no está autorizado implícitamente por E4. No es una solución suficiente
demostrada para el gate: también queda espera eligible→claim por resolver.**

La recomendación elimina un amplificador medido de latencia sin congelar un
contexto obsoleto antes del claim. No autoriza su implementación, una nueva
política de polling ni un rerun. Si se exige conservar literalmente la espera
de silencio vigente incluso después de vencer, esta propuesta no procede;
la alternativa sigue siendo coordinación E4 con esa semántica intacta y un
mecanismo aún por demostrar. La evidencia disponible no identifica un único
cambio ya probado que vuelva robusto el PASS integral.

Se conservan B9A–D COMPLETED, B9E FAIL, PROFILE-BETA-1 FAIL, E4 PARTIAL,
ROOT_CAUSE_CONFIRMED y B9 IN_PROGRESS. No se modifica código productivo,
contratos vigentes, perfil, threshold de 10 s, N=1, presupuesto, número de
llamadas LLM ni despliegue. Este documento no es una aceptación ni una
enmienda contractual ejecutada.

## Evidencia y método

Se revisaron el plan canónico completo y sus definiciones C4/B3/B9/E4/E5,
contratos B3/B9B/B9C, TurnContext B1, binding B6, acta B9E y acta/evidencia E4.
El recorrido de código se descubrió con el grafo del repositorio reindexado;
se contrastó con fuente actual cuando faltaban helpers o había offsets
desactualizados. Las referencias de línea siguientes corresponden al corte
de runtime auditado, no a los offsets antiguos del grafo.

La derivación [JSON](../evals/architecture-capacity-e4-analysis.json) y su
[script offline](../evals/architecture-capacity-e4-analysis.py) leen evidencia
ya cerrada. No levantan PostgreSQL, no ejecutan workers ni repiten carga.
Registran 229 hashes SHA-256 de entradas, autoridad, runtime e históricos.
Los percentiles usan `higher`, índice `ceil((n−1)q)`, igual que el gate.
Las cifras se redondean aquí a seis decimales; el JSON conserva precisión.
El [recibo de verificación](../evals/architecture-capacity-e4-verification.json)
comprueba las 30 secciones, enlaces, reproducción byte a byte del JSON y
contenido de las entradas contra el HEAD documental; distingue conversiones
CRLF de checkout de cambios de contenido.

`T0=Message.created_at` es la persistencia definida por la metodología,
no una medición exacta del commit de ingreso. `T1=available_at` es el valor
final, tras posibles extensiones. `claimed_at` se escribe dentro del claim
antes del commit. Los marcadores de retorno tras commit son diagnósticos.
No se suman percentiles de componentes para fabricar un percentil total.

## 1. Fase canónica aplicable

[E4 del plan](../plan-implementacion-auditoria-agente-whatsapp-2026-09md),
líneas 806–823, autoriza coordinación operativa acotada cuando la medición
demuestra la necesidad: selección justa, lotes pequeños y coordinación de
claims, con una mejora por PR. No autoriza por sí sola redefinir qué mensajes
constituyen el turno ni retirar barreras de consentimiento.

La elegibilidad irreversible con incorporación de input nuevo antes del
claim cambia la política W1 de formación del turno. Su propietario canónico
es **B3/C4**, composición con TurnContext B1 y la regla W1-4 existente.
Requiere enmendar esas fronteras antes de implementarla; B9/E4 medirían su
composición. B6/B7/B8 conservan binding, consentimiento y autoridad.
**E5** (825–839) trata exclusivamente altas compuestas pet/appointment;
no autoriza debounce, scheduling ni otra cola. No existen fases E4.1/E4.2
canónicas aplicables.

## 2. Semántica actual de debounce

La fuente explícita es W1-4 en [módulo agent](../modules/agent.md):1204:
ventana silenciosa de **8 s**, tope **25 s**, «La ráfaga humana se responde
en UN turno». `_extend_quiet_window`, `services.py`:409–428, expresa que
«mientras el cliente siga escribiendo, el turno espera». `QuietWindowTests`,
`test_w1_experience.py`:224–273, exige que cada mensaje empuje todos los
pendientes, conserve un deadline común y agrupe los tres miembros.

Por tanto, A —esperar silencio— y B —agrupar la ráfaga— están documentados.
C —reducir calls— puede ser consecuencia de agrupar; no consta como
garantía cuantificada ni como razón suficiente para elegir exactamente 8 s.
D —evitar carreras— se resuelve con locks/fences B3 y no explica ese valor.
E —evitar espera indefinida por escritura continua— explica el tope 25 s.
No hay evidencia de que 8 s sea un óptimo de producto investigado.

Hay documentación histórica de 3–5 s y delay fijo de 3 s, y un comentario
antiguo de `Message.available_at` dice delay fijo. No describen el runtime
actual. La excepción histórica W1 de descartar solo texto puro tampoco
sustituye la política conservadora posterior B3/B7/B8 para publicación y
efectos. El docstring promete respuesta por el hard cap, pero el código
solo acota elegibilidad: **25 s no acota claim ni respuesta**.

## 3. Semántica actual de available_at y transacciones

La fuente persistida de verdad es **Message.available_at**, campo nullable
en `channels/models.py`:255–257. Conversation tiene actividad/ownership,
no un deadline durable de READY. TurnWork tiene retries/lease propios;
no son el debounce del inbound nuevo. No existe un estado durable READY.

El recorrido actual es:

1. `ingest_inbound_message`, `services.py`:327–406, captura receipt server-side
   de consentimiento, deduplica, resuelve contacto y episodio abierto.
2. Captura `now` de aplicación **antes** de esperar el lock e insertar Message;
   prepara `available_at=now+8 s` y status PENDING, o DISCARDED si bloqueado.
3. Bajo `transaction.atomic` y lock de Conversation, inserta el Message,
   actualiza `last_inbound_at/last_activity_at` y llama `_extend_quiet_window`.
   Si el episodio se cerró antes, resuelve otro después de liberar ese lock.
4. El helper toma inbound PENDING **sin turn_work**, de esa org/conversación,
   excluyendo safety_signal. Calcula `oldest=min(created_at)` y
   `target=max(now, min(now+8 s, oldest+25 s))`; escribe ese mismo valor en
   **todos** los miembros, sin comprobar si alguno ya era elegible.
5. El selector `worker.py`:36–64 busca pendientes con `available_at IS NULL`
   o `available_at <= reloj`, junto con retries/reclaims. Excluye org ocupada,
   toma una conversación por org y ordena por último claim durable de la org.
6. `durable.claim_turn`:125–227 revalida capacidad y elegibilidad bajo locks
   Organization→Conversation→TurnWork→Message; crea o recupera TurnWork.
7. Solo entonces fija membership, anchor/cursor y contexto, obtiene UUID/lease
   y confirma PROCESSING. La selección previa no concede autoridad.

El estado PENDING inicial de un TurnWork nuevo ocurre dentro de la misma
transacción que su primer claim; no representa una cola READY persistida.
El inbound asignado, aunque siga PENDING durante procesamiento/retry, queda
excluido del helper. La extensión afecta solo trabajo aún no constituido.

`now` anterior al save explica delays medidos próximos a 7.94 s respecto de
`created_at`. Esa diferencia no es margen contractual de scheduling ni un
cambio deliberado a 7.94 s. Lease/capacidad se validan con reloj DB fresco.

## 4. Timeline exacto de una extensión observada

Baseline instrumentado, org sana 2 (rank 1), Messages **67=A**, **83=B**,
TurnWork **32**. Origen relativo: `A.created_at=0`.

| Evento | t relativo, s | Evidencia/entidad |
| --- | ---: | --- |
| Persistencia A | 0.000000 | Message 67 pendiente, sin membership |
| Primera observación de A elegible | 8.887522 | Observer readonly; no claim todavía |
| Persistencia B | 10.030300 | Message 83, misma Conversation |
| Deadline final común A/B | 17.958842 | `available_at` de ambos tras ingestión B |
| Poll observa deadline final vencido | 18.537944 | T2 |
| Entrada al claim tras selección | 21.382391 | T3 |
| Inicio SQL Organization | 21.386180 | T4 |
| `claimed_at` durable | 21.402439 | Dentro de la transacción, antes del commit |
| Fin del último SQL de locks | 21.470249 | T5, no wait puro |
| Retorno tras commit | 21.477358 | T6 |

A tarda 21.402439 s hasta claimed_at y B 11.372139 s. El valor inicial
exacto de `available_at` no quedó auditado antes de sobrescribirse; la
observación a 8.887522 prueba elegibilidad previa. No se inventa el instante
del UPDATE dentro de la ingestión B. El valor común final y el recorrido
transaccional explican el cambio. El tope 25 s no se activa en este caso.

No se cambia un TurnWork ya listo: **aún no existe**. Cambian el Message B
nuevo, deadlines A/B y actividad de Conversation. En el claim se crean
TurnWork 32, membership A/B, anchor B y cursor exclusivo de A.

Si B llegara exactamente a `8+ε`, la fórmula sin cap daría aproximadamente
`16+ε`, no 18 s. La traza próxima a 18–22 s corresponde a B próximo a 10 s,
tal como ocurre en este perfil. El polling/servicio añade la espera restante.

## 5. Razón contractual de la extensión

Es la implementación literal de esperar **silencio posterior al último
inbound** mientras la ráfaga no haya sido claimed. No contiene un latch
«ya venció, no extender». Pasar un reloj por un deadline no cambia status ni
crea membership: solo vuelve verdadero temporalmente el predicado de claim.
El helper puede volverlo falso bajo el mismo mutex Conversation.

El test de empuje de ráfaga demuestra la intención de reiniciar la ventana;
no contiene un caso específico B después del vencimiento de A. La ausencia
de guard y la traza medida demuestran ese caso adicional. No se atribuye el
comportamiento a un bug de lease, a una carrera sin serializar ni al cursor.

## 6. Relación con TurnContext

`turn_context.py`:17–24 y 64–102 fija un objeto inmutable con tupla de eventos,
IDs, evidencia, anchor y reloj contextual. Se construye al claim a partir
de miembros persistidos, ordenados `(created_at,id)`, no al vencer 8 s.
`context_for_work`, `durable.py`:230–243, recupera exactamente esos miembros
y verifica cursor/anchor contra el trabajo.

Con la política actual A/B esperan juntos y el contexto contiene ambos.
Una alternativa monotónica puede conservar esa coherencia **si agrega B
antes de crear/fijar el trabajo**. No permite mutar el contexto de W1 ni
anexar B después del claim. La inmutabilidad del contexto no exige congelar
el input en el momento anterior de elegibilidad.

## 7. Cursor, membership y nuevo input

[B3](../contrato-trabajo-durable-b3.md) fija `Message.turn_work`; anchor es el
último miembro y cursor exclusivo es la coordenada del **primer miembro**.
El historial anterior usa `< cursor`, no «el ID del mensaje anterior».
Los triggers de `channels/0012_b3_scope_and_membership.py`:23–52 impiden
cambiar identidad causal, reasignar miembros o anexarlos cuando attempts>0.

Si claim gana el lock antes de B, A forma W1 y B queda para W2. Si ingestión
B gana, hoy retira la elegibilidad A/B; con la propuesta ambos entrarían en
W1 al claim sin volver a esperar. Esa frontera es serializable y observable.

Después del claim, `has_new_input`, `durable.py`:246–251, detecta inbound
no descartado posterior al anchor **aunque no sea aún elegible**. B3 difiere
la publicación ordinaria, completa W1 y deja el nuevo miembro a W2; no
reinicia W1 ni mueve su cursor. La continuación conserva historia permitida
y cambios locales válidos, sin anexar miembros ni fabricar otro witness.

## 8. Persisted→eligible, por organización

Ordinarios del cohort de mensajes de la ventana medida. Ranks 0/1 son sanas
1/2; rank 2 es noisy, no los PK productivos. Segundos:

| Escenario/org | n claimed | media T1−T0 | p95 T1−T0 |
| --- | ---: | ---: | ---: |
| Baseline / sana 1 | 20 | 8.915595 | 17.950669 |
| Baseline / sana 2 | 20 | 12.944684 | 18.129125 |
| Baseline / noisy | 105 | 7.929097 | 7.948824 |
| E4 base / sana 1 | 20 | 7.944270 | 7.973606 |
| E4 base / sana 2 | 20 | 7.943077 | 7.973035 |
| E4 base / noisy | 97 | 7.940606 | 7.968002 |
| E4 blocked / sana 1 | 20 | 7.926884 | 7.972231 |
| E4 blocked / sana 2 | 20 | 8.442735 | 17.941190 |
| E4 blocked / noisy | 93 | 7.924601 | 7.962441 |

Los n noisy son **subconjuntos reclamados**, no los 300 arribos. Sus delays
no describen los pendientes sin claim. En blocked un A vuelve a esperar
~10 s; que el p95 conjunto de 40 ordinarios siga próximo a 8 s no elimina
ese máximo. En n=20 el método higher da p95=máximo.

## 9. Eligible→claim

Mismos cohorts y reloj contractual `claimed_at`, desde **T1 final**:

| Escenario/org | media, s | p95, s |
| --- | ---: | ---: |
| Baseline / sana 1 | 0.863555 | 1.742090 |
| Baseline / sana 2 | 3.452245 | 4.349370 |
| Baseline / noisy, subset | 130.126334 | 200.799945 |
| E4 base / sana 1 | 0.597089 | 1.025390 |
| E4 base / sana 2 | 1.348715 | 2.456132 |
| E4 base / noisy, subset | 136.337953 | 209.167632 |
| E4 blocked / sana 1 | 0.724440 | 1.843472 |
| E4 blocked / sana 2 | 1.336302 | 2.647364 |
| E4 blocked / noisy, subset | 143.968095 | 214.419890 |

La primera elegibilidad retirada es una espera adicional anterior a T1
final; no desaparece porque se mida este tramo final pequeño. El gate
persisted→claim conserva toda esa espera. Las dos sanas tienen carga baja,
pero fases/orden/ocupación causan colas altas diferentes.

## 10. Claim→complete

Duración durable de READ desde `claimed_at` a `completed_at`, **todo el run**
(warmup/medición/drain), de las colecciones cerradas:

| Escenario | n works | p50, s | p95, s | máximo, s |
| --- | ---: | ---: | ---: | ---: |
| Baseline instrumentado | 166 | 1.813074 | 2.032245 | 3.512549 |
| E4 base | 170 | 1.686061 | 2.146376 | 3.168214 |
| E4 blocked | 165 | 1.748513 | 2.436325 | 11.043208 |

Todos conservan **dos calls por READ**. El journal baseline permite además
separar servicio por org (sección 12). El suplemento baseline desde retorno
tras commit hasta completed_at da p50 1.742013, p95 1.943854, máximo
3.396954 s, n=166. No se confunden esos marcadores con el instante DB.

Los recibos post-fix no retienen journals internos de servicio por org;
no se puede calcular una media exacta por org allí ni deducirla del p95
agregado. Tampoco se atribuye la media baseline al candidato o a blocked.
El servicio posterior de un trabajo no suma a **su** gate de claim; consume
el planner/slot que necesitan trabajos siguientes.

## 11. Arrival rate λ por organización

Ventana fija de 300 s, según runner/cohort observados:

| Org | Inbound total | λ mensajes/s | Ordinarios | λ ordinary/s | Safety |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sana 1 | 30 | 0.100000 | 20 | 0.066667 | 10 / 0.033333 s⁻¹ |
| Sana 2 | 30 | 0.100000 | 20 | 0.066667 | 10 / 0.033333 s⁻¹ |
| Noisy | 300 | 1.000000 | 300 | 1.000000 | 0 |

Safety usa recepción B5 inmediata, no dos LLM ni el servicio ordinario del
planner. Noisy usa conversación/contacto distinto por mensaje: no se
coalesce ese tráfico. Las sanas ordinarias comparten conversación y pueden
coalescer. En baseline los 20 miembros de sana 1 se asignaron a 18 works y
los de sana 2 a 10: tasa observada del cohort 0.060000/0.033333 works/s.
Es una estimación de arribos efectivos tras agrupación, con límites de
ventana, no una tasa de producto independiente del scheduling. Los 105
works noisy claimed no reducen su λ a 105/300; los demás siguen pendientes.

## 12. Service rate μ por organización

Baseline instrumentado: works con marcador de retorno del claim dentro de
los 300 s; se usa su finalización aun si cae en drain. Mapping org/work de
logs por IDs, tiempos exclusivamente de journals. Se verifican dos dispatch
por work. `S=finalize_end−claim_commit` es servicio observado entre retornos,
**proxy**, no ocupación exacta del slot DB. `μ_service=1/media(S)`:

| Org | n | media S, s | p95 S, s | μ_service, works/s | Completados en ventana / throughput |
| --- | ---: | ---: | ---: | ---: | --- |
| Sana 1 | 18 | 1.740423 | 1.981715 | 0.574573 | 18 / 0.060000 s⁻¹ |
| Sana 2 | 10 | 1.809328 | 2.001792 | 0.552692 | 10 / 0.033333 s⁻¹ |
| Noisy | 120 | 1.752298 | 1.920091 | 0.570679 | 119 / 0.396667 s⁻¹ |

El throughput real incluye scheduling, disponibilidad del planner y pausa;
no es μ de servicio intrínseco. Las sanas no están saturadas, por lo que
su bajo throughput no estima su máximo de capacidad. No se usan timestamps
textuales de logs como relojes, ni se mezclan el cohort de arribos y el de
claims para hacer una supuesta media de ocupación.

Además, los fakes originales fijan `.5+.5+.1=1.1 s` mínimo de servicio READ.
Con N=1, aun sin coste local/polling, `μ_noisy <= 1/1.1 = 0.909091/s`.
Este bound es del perfil controlado, no un pronóstico de otro proveedor.

## 13. Utilization ρ y límites del modelo

Para comparar unidades compatibles se calcula intensidad de carga ofrecida
`ρ=λ_ordinary×media(S)`, equivalente a λ/μ_service:

| Org | ρ ordinary sin coalescer | ρ de cohort sano coalescido |
| --- | ---: | ---: |
| Sana 1 | 0.116028 | 0.104425 |
| Sana 2 | 0.120622 | 0.060311 |
| Noisy | 1.752298 | No aplica |

Usar λ total como si cada safety requiriese READ daría cotas conservadoras
0.174042/0.180933 para las sanas, no su utilización real. Un ρ ofrecido >1
indica sobrecarga; no significa que un recurso esté físicamente ocupado
175% del tiempo. No se midió aquí fracción temporal exacta de ocupación.
λ_noisy/throughput_noisy=2.521008 es presión llegada/salida, **no** utilización.
No se ajusta M/M/1 ni se presupone llegada Poisson/servicio exponencial.

## 14. Estabilidad de cola

**Noisy es inestable bajo carga sostenida de este perfil:** λ=1/s supera
tanto el bound ideal .909091/s como μ_proxy observada .570679/s. El
throughput efectivo .396667/s refuerza la conclusión. El snapshot baseline
alcanza 204 pendientes noisy; las sanas alcanzan 2 y todas obtienen claim.

ρ bajo en las sanas y ausencia de pérdida en la ventana no prueban un SLO
robusto ni estabilidad universal del sistema compartido. La fairness puede
aislar su latencia aunque noisy acumule backlog durable. El perfil no exige
drenar toda noisy ni convierte antigüedad de cola en permiso de descarte.
La inestabilidad noisy **no demuestra imposibilidad del gate sano**, ni
autoriza N>1, cancelar calls o sustituir PROFILE-BETA-1.

## 15. Presupuesto real del SLO

Gate original: **persisted→claim p95 ≤10 s**, 60 sanos incluidos 20 safety.
Sin extensión, 8 s de silencio deja nominalmente **2 s** para toda espera
y claim. En base, T1−T0 ordinary p95=7.973035 deja 2.026965 s como resta
descriptiva de ese percentil, no p95 garantizado del presupuesto restante.
El JSON calcula el margen `10−(T1−T0)` **por mensaje** para no mezclar colas.
Si el deadline ya cae a ~18 s, ese mensaje tiene margen negativo antes de
scheduling. El hard cap 25 s no protege el threshold de 10 s.

| Componente | Medición disponible | Interpretación |
| --- | --- | --- |
| Debounce | ~7.94–7.97 s sin extensión; hasta ~18 s con B | Consume casi todo el margen; reloj pre-save no concede buffer fiable |
| Polling | Pausa configurada 1 s **después del servicio**; start→start baseline p95 3.050742, máx. 4.621660 s | No equivale a un despertar cada segundo; puede superar los 2 s restantes |
| Elegible→poll / poll→candidato | Baseline ordinary p95 2.824882 / 3.454857 s | Observación/selección comparten fase de ejecución; no sumables |
| Selector | SQL online anterior p95 .009375 s; EXPLAIN anterior .001109, E4 base .001456, blocked .003065 s | Coste medido pequeño; EXPLAIN no es percentil de espera bajo carga |
| Claim/locks | Candidato→retorno commit baseline p95 .146599 s | Incluye DB/IO/mutaciones, no solo locks ni reloj de gate |
| Locks separados | Control v2 máximos SQL Org .013629, Conv .047224, Work .016644, Message .028332 s | Cotas superiores de waits por statement; no tiempos exactos de espera |
| Jitter | Presente en tails y costes locales; sin marcador exhaustivo propio | No asignar un número residual inventado ni sumar máximos incompatibles |

Base p95 contractual **9.844989** deja **.155011 s** (1.55011% del threshold).
Blocked **10.497891** excede **.497891 s**. Ordinary separado da 10.104683
y 10.572319 s respectivamente; no sustituye el denominador congelado.
Hubo 2/60 sanos >10 s en base y 4/60 en blocked. De estos cuatro, **tres
no tuvieron T1−T0>10 s**: eliminar solo la extensión observada no demuestra
resolver el FAIL. Tampoco se trasladan claimed_at observados al cambiar
la política: el nuevo scheduling requeriría medición causal propia.

**Conclusión de robustez:** con 8 s y topología actual no hay evidencia de
margen robusto; base pasa estrechamente y blocked falla. No se ha demostrado
incompatibilidad matemática del SLO sano con todo diseño permitido. Su
cumplimiento exige controlar la espera tras elegibilidad y la amplificación
por reabrir la ventana; no cambiar el gate por dificultad.

## 16. Evaluación de elegibilidad monotónica

READY propuesto significa «ráfaga pendiente ya vencida», sin autoridad de
procesamiento y **sin nuevo estado TurnWork**. Requiere decisión de producto
porque sustituye silencio reiniciable hasta claim por silencio reiniciable
solo **hasta la primera elegibilidad**.

| Tratamiento de B antes del claim | Compatibilidad y resultado |
| --- | --- |
| A. Incorporar al mismo trabajo | Recomendado: B se integra al conjunto pendiente elegible bajo Conversation; el claim posterior fija A/B de una vez. B3 inmutabilidad posterior permanece. Cambia política W1/eligibilidad preclaim y requiere enmienda |
| B. Dejar B para el siguiente | Estructuralmente B3 lo admite, pero W1 de A ya ve input posterior al anchor y difiere su publicación/efectos. Puede pagar dos LLM por contexto obsoleto y esperar otra ventana para la corrección. No recomendado como atajo del gate |
| C. Invalidar/reemplazar trabajo | Antes del claim no hay TurnWork que reemplazar. Después, fabricar otro para replanning contraría membresía/no-reinicio y arriesga reiniciar presupuesto. No usar cancel/replace ni un input epoch nuevo |
| D. Continuación B3 después del claim | Política existente: B permanece fuera, W1 deferred_to_new_input y completado, W2 lo toma con estado/historial permitido. Mantenerla |

**Conservar solo el deadline de A y dejar B disponible a +8 s no implementa
la opción A.** El claim actual toma solo miembros elegibles; se quedaría
fuera la corrección. La enmienda debe mantener ready el conjunto e incorporar
B antes de congelarlo. No se debe anexar luego a un PROCESSING ni congelar
anchor/cursor en el primer vencimiento.

Ownership, lease/token, epoch y locks continúan en B3/B9C; READY no concede
witness. Reclaim conserva miembros y presupuesto. Binding/correcciones se
validan B6; receipt y consentimiento B7 no nacen de estar ready. Input nuevo
después del anchor sigue bloqueando publicación/admisión sensible según
B3/B7/B8. Takeover humano invalida epoch y no espera al cupo.

## 17. Riesgos conversacionales y cierre del turno

Caso «quiero cita mañana», A ready a ~8 s, «mejor el viernes» B antes del
claim: **el agente debe ver A y B en ese orden**, no preparar una cita de
mañana con el pretexto de que A ya estaba listo. La opción A propuesta
lo permite. La semántica vigente también ve ambos, después de esperar
otro silencio. Si B llega después del claim, no entra retroactivamente:
B3 impide publicar resultado ordinario obsoleto y B6/B7/B8 invalidan args,
propuesta/autorización derivada cuando corresponda.

«quiero cita» / «para Firulais» / «mañana» / «no, mejor viernes»: todos los
mensajes persistidos antes del claim que pertenezcan a esa ráfaga deben
formar un contexto ordenado. La frontera de membership es **el claim
atómico bajo Conversation**, no el tick de 8 s ni el comienzo del poll.
Una corrección posterior va a continuación y revisa binding/date; no puede
reutilizar consentimiento de otro digest. Un texto ambiguo no acredita por
sí mismo intención resuelta: se conserva aclaración/consentimiento.

Cerrar antes sin volver a esperar silencio aumenta la posibilidad de que
otro fragmento C llegue durante LLM y provoque defer. Es un riesgo explícito
de coherencia/coste: la propuesta no garantiza una respuesta con una única
ráfaga a alguien que escribe indefinidamente. Nunca debe omitir C, introducir
un segundo matter ni ejecutar la propuesta anterior tras cambio de fecha.
Human takeover y safety tienen precedencia sobre esta optimización.

## 18. Comparación de alternativas A–I

Las mejoras no medidas se expresan como mecanismos/expectativas, no segundos
inventados ni PASS previsto. Ninguna alternativa se implementa aquí.

| Alternativa | Causa y mejora sustentada | Complejidad / riesgos | Migración, plan y fase |
| --- | --- | --- | --- |
| A. Solo selector E4 | Reduce preferencia de backlog noisy frente a org sana; base 9.844989 PASS, blocked 10.497891 FAIL. Mejora demostrada, insuficiente | Moderada: WindowAgg, subquery recencia, tres candidatos. No evita reextensión ni acota fase de poll | Sin schema; KEEP en E4. No autoriza aceptación |
| B. Elegibilidad monotónica + coalescer hasta claim | Elimina la retirada medida de READY y su segunda espera (~10 s en la traza). Beneficio estructural; no resuelve por sí solo tres tails blocked sin extensión | Moderada, frontera semántica delicada; perder correcciones si solo se congela A, más defer si C llega después | Proponer sin nueva tabla/estado; mutex y deadlines Message. Enmienda B3/C4 + B1/W1 previa, composición E4. No E5 |
| C. Wake-up/event-driven | Reduce espera idle/poll tras vencimiento o liberación; no preempta planner ocupado ni drena noisy. Sin medida exacta de ganancia | Moderada/alta: hints perdidos, timer del futuro available_at, crash/reconnect, fallback durable, no loops calientes | PG como autoridad, hints tras commit y wake de deadline/liberación. E4 si acotado. **Runner frozen no ejercita cambio solo al loop continuo**; no cambiarlo para aparentar PASS |
| D. Polling menor | Control .1 s da 10.121223 FAIL, una extensión; demuestra contribución de pausa, no solución completa | Fácil en código, más DB/ciclos; no recupera coherencia retirando deadlines | Config/runner; tuning expresamente excluido. E4 podría evaluarlo en otro encargo, aquí no; PROFILE-BETA-1 sigue poll 1 |
| E. Más scheduling/fairness | Ataca colas eligible→claim >2 s y misses; fair frente a efficient demostró valor del orden por org. No se midió otro mecanismo superior | Moderada/alta: prioridad por deadline ingenua favorece noisy siempre atrasada; reservas rígidas pueden desperdiciar planners | E4, una mejora definida por reporte; sin scheduler/cola nueva por defecto. Medir mecanismo antes de elegirlo; no prometer que otra ordenación baste |
| F. Cambiar debounce | Menor espera dejaría más presupuesto y menos cliff; beneficio aritmético, sin prueba de conducta de usuario | Fragmenta ráfagas, más turnos/calls/deferrals; cambiar 8 a otro valor sería tuning sin justificación de producto | W1/formación de turno B1/B3 requiere decisión contractual; no permiso implícito E4/E5. No recomendado aquí |
| G. N>1/org | Podría aumentar capacidad noisy, según paralelismo real y coordinación; no corrige por sí solo debounce sano | Alta: dominios/consentimiento y varios works misma org; no paralelizar misma conversación | Cambia contrato B9C y perfil N=1: excluido. E4 fila de coordinación no autoriza elevar N de este encargo |
| H. Desacoplar procesamiento del slot | Podría liberar recurso mientras se espera LLM; no baja latencia del proveedor ni garantiza orden | Alta: segundo planificador/lifecycle y resultados tardíos. Si sigue PROCESSING, no libera N; si se libera, cambia definición de autoridad/cupo | Requiere rediseño/enmiendas B3/B9B/B9C, no extensión menor E4. Meta ya está desacoplado en B4. No E5 |
| I. Otra arquitectura de cola | Puede aportar dispatch/wakes a otra escala; no crea capacidad con λ>μ ni elimina ventanas de silencio | Muy alta: doble fuente de verdad, replay, fencing, operativa y migración | Nuevo diseño canónico/ADR y corte de writers; broker/Celery/Kafka no autorizados por plan actual. Evidencia no justifica sustituir PostgreSQL |

| Alternativa | Invariantes / impacto B3 | Impacto B9B | Impacto B9C |
| --- | --- | --- | --- |
| A | Conserva ownership/token/membership/CAS; selección advisory | Ninguno; todos los calls admitidos igual | N=1, lock order y busy exclusion intactos |
| B | Cambia solo formación preclaim; exige nuevos tests de frontera, conserva contexto postclaim, cursor, epoch, reclaim y defer | Mismos topes/no-refund por work; agrupación podría cambiar número de works/calls, no medido | READY no cuenta como PROCESSING ni reserva N; mismo claim y exclusión |
| C | Hints no son autoridad; rescaneo durable y claim actual | Ninguna devolución/admisión por evento | Despertar no concede cupo; competencia real bajo Organization |
| D | Predicados/recovery iguales, mayor frecuencia | No llamadas por poll/miss | Más contención, mismo N; probar procesos |
| E | Orden advisory no altera evidencia ni witness | Preservar accounting durante misses/retry | Cupo y lock order permanecen; evitar monopolizar candidatos |
| F | Cambia lote preclaim y frecuencia de defer | No reducir calls fingiendo equivalencia; nuevos turns siguen cobrando | Mismo N pero más competencia entre turns |
| G | Mantener un work por conversación, evaluar autoridad cruzada de dominio | Reservas por work sobreviven, carga aumenta | Cambia N: incompatible con encargo/profile |
| H | Slot separado podría divergir de lease/PROCESSING, permite autoridad superpuesta si se diseña mal | Admisiones tardías sin witness o reset son prohibidos | Redefine recurso que limita N; no bypass mediante background futures |
| I | Nueva cola no sustituye membership/epoch/fences | Accounting durable no se migra a mensajes efímeros | Coordinación global común sigue necesaria; no cupos por réplica |

Sobre C: `b9e_profile.py`:114–118 llama comando `once=True, batch=1, poll=1`
y duerme 1 s fuera. `run_agent_worker.py`:85–90 termina antes del sleep en
modo once. Una optimización del loop continuo no cambia esa pausa del
runner. Un ensayo específico de wake puede servir como diagnóstico, pero
no sustituye el perfil original. Cambiar cobertura metodológica requeriría
decisión expresa; este análisis no cambia runner ni propone otro perfil.

## 19. KEEP / REVERT / SUPERSEDE del candidato E4

**KEEP**, como componente útil de la rama, no fix aceptado ni despliegue.

La separación experimental efficient=21.773134 frente a fair=9.289224 s
(diagnósticos 120 s), control baseline comparable=21.371626 y runs completos
post-fix sustentan el valor de prioridad por org, no solo el hecho de estar
implementada. El baseline instrumentado completo da 21.843496; E4 base
9.844989 y blocked 10.497891. Las ventanas/control runs son distintos;
no se presenta una diferencia de p95 como efecto universal aditivo.

El coste añadido es acotado: una candidata por org, recencia tomada de
TurnWork, fallback máximo tres sin progreso, claim atómico existente. No
schema/cursor de scheduler. EXPLAIN real 1.456/3.065 ms bajo los backlogs
ensayados; 460 regresiones PASS, cero skips. No se demostró cuello de
botella del query ni regresión crítica que justifique REVERT.

WindowAgg y subquery de historia pueden crecer con tenants/TurnWork;
el plan pequeño no prueba escalabilidad futura. El límite tres no garantiza
fairness fuerte. Se debe volver a medir a mayor dataset/topología, sin
añadir índices anticipados. SUPERSEDE requeriría un mecanismo que demuestre
mejor composición/coste; no hay esa evidencia. El FAIL residual limita
promoción, pero no elimina la mejora independiente.

## 20. Solución recomendada

Recomendar para el **siguiente encargo**, después de enmienda contractual:
**B, elegibilidad monotónica del conjunto pendiente y coalescing hasta el
claim atómico**, conservando KEEP de E4. Cuando vence por primera vez la
ventana/cap, la llegada de B no desplaza los deadlines ya elegibles; B se
incorpora al conjunto listo si la ingestión gana el mutex antes del claim.
El contexto permanece abierto hasta ese claim y luego totalmente inmutable.

Esta es una corrección estructural de la política de espera propuesta, no
una afirmación de que el comportamiento actual viole su contrato. No bajar
8 s, no nuevo READY de TurnWork, no reemplazo de work, no preemptar llamadas,
no eliminar la segunda LLM. Si no se aprueba esa semántica de producto, no
implementarla: seguir E4 sobre scheduling preservando rolling silence.

No hacer inmediatamente otro PROFILE-BETA-1 tras B esperando verde: el
tramo eligible→claim todavía debe demostrar que cabe en el presupuesto.
La propuesta se elige como **siguiente cambio**, no como paquete B+C+E ni
garantía de solución integral. Una mejora por PR sigue siendo la regla.

## 21. Por qué esta recomendación

Hay una cadena causal y un efecto específico medidos: Message ya elegible,
nuevo input antes de claim, deadline común reescrito, latencia ~22 s. B
elimina exactamente ese mecanismo por construcción, aun si un planner
pierde la primera ventana. Aumentar fairness no hace irreversible READY;
optimizar SQL de milisegundos no elimina una reapertura de ~10 s.

Incluir la corrección antes del claim evita resolver el gate declarando
claimed un contexto viejo que inmediatamente será deferred. Usa las
entidades/locks existentes; no necesita una plataforma nueva ni cambiar
N/budget. Esta justificación no extrapola cuántos segundos bajaría el p95
global: nueva política puede cambiar agrupación, llamadas y scheduling.

La evidencia también **refuta su suficiencia aislada**: blocked tiene tres
tails >10 s sin elegibilidad final >10 s. El valor es retirar el amplificador
y fijar una frontera coherente antes de seleccionar otra coordinación,
no presentar monotonicidad como PASS obtenido. No se recomienda por falta
de alternativas fáciles ni porque el gate sea inconveniente.

## 22. Fase que autoriza implementarla

**B3/C4 enmendado**, referenciado desde B1/W1; seguimiento de capacidad en
**E4**. El texto vigente B3 toma «inbound elegibles sin asignar» y W1 exige
silencio reiniciable; una excepción preclaim necesita definición vinculante
de cómo B se vuelve miembro elegible antes de ese claim. Se debe aprobar
y versionar esa enmienda y los casos de producto antes del código, y ajustar
la especificación W1 para evitar dos contratos contradictorios.

El plan actual no otorga autorización automática para ese cambio solo por
E4 FAIL. Este documento **propone** la enmienda; no marca B3 abierto/cerrado
de nuevo ni modifica el plan/contrato. No se invoca E5 ni otra fase inventada.
El presente encargo autoriza únicamente análisis y concluye aquí.

## 23. Cambios esperados, sin implementación

Definir bajo mutex Conversation un predicado de ready de pendientes
ordinarios no asignados, usando reloj DB fresco al decidir si el deadline
ya venció. Antes de READY seguir la ventana 8 s/cap 25 s. Después preservar
ready de los anteriores y hacer elegible al inbound B de esa ráfaga antes
del claim; no dejarlo con una ventana futura separada por accidente.

Mantener una fuente de verdad Message, sin copiar transcript ni persistir
un segundo cursor. El claim sigue revalidando, fija todos los miembros una
vez y conserva history-before/anchor. Retries/reclaims no se mezclan con
inbound sin asignar. Safety, descartados, cierre/reset y takeover conservan
sus rutas/precedencias. No migración prevista si basta el deadline existente;
si hace falta persistencia adicional, ADR acotado previo y revaluación del
alcance, no tabla READY por defecto.

Documentar composición con workers antiguos antes de rollout: un escritor
antiguo puede volver a extender deadlines. El corte de versiones compatible
es obligatorio en un futuro despliegue. Rollback restaura rolling silence
sin desasignar work, restituir budget ni borrar evidencia; un deadline ya
promovido no puede reconstruirse como silencio histórico exacto.

## 24. Tests necesarios en un próximo encargo

No se ejecutan ahora pruebas productivas ni temporales. La nueva política
necesitaría tests que separen frontera causal de timing real:

- Antes del vencimiento, B mueve toda la ráfaga; cap 25 s se mantiene.
- Después del vencimiento, B no retira READY y pertenece al contexto si
  ingesta gana el lock; probar t=8−ε, t=8, t=8+ε con reloj DB, incluyendo
  `now` de aplicación viejo por esperar el mutex y `available_at NULL` legacy.
- Dos procesos PostgreSQL con barreras: ingesta/claim en ambos órdenes,
  tres inbounds simultáneos, dedup y cierre/reset; todos los IDs se asignan
  exactamente una vez, orden/cursor/anchor correctos, sin miembros extra.
- Corrección viernes antes del claim se ve junto a mañana; después se
  difiere W1 y se invalida propuesta/digest/consentimiento según B6/B7/B8.
  Fragmentos mascota/fecha, cambio de matter, cortesía y ambigüedad.
- Crash/restart/reclaim conservan work/membership/clock, token nuevo,
  fencing stale, límite de intentos y presupuesto acumulado/no-refund.
- Takeover/safety/blocked/cross-tenant no obtienen autoridad por READY;
  guidance no espera silencio ni cupo ordinario.
- B9C último slot, dos conversaciones de una org, dos orgs y busy exclusion:
  misma N=1 y sender independiente. OWN/DUR/SEND/SAFE/SEC/COST pertinentes.
- Instrumentación diagnóstica separada para medir primera/final elegibilidad,
  claim y completion por org; estados READY observados sin prometer autoridad.
  Comprobar tails sin reextensión además de calls/deferrals por corrección.

Los tests W1 existentes deben distinguir «empuje antes del vencimiento» de
«latch después», manteniendo sus IDs/aserciones relevantes con una enmienda
explícita; no borrar cobertura para conseguir verdes. Luego checks/schema,
regresión por impacto y carga en metodología original. No llamar a un
test unitario ni a un diagnóstico temporal aceptación PROFILE-BETA-1.

## 25. Impacto en B3

Cambia formación de conjunto preclaim, no la autoridad concedida. Se
preservan un trabajo no terminal por conversación, identidad anchor/cursor,
membership inmutable desde claim, reloj contextual, 15 min lease/12 min
deadline, UUID/token/epoch, CAS/publicación atómica y no-reinicio ante input.
La enmienda debe hacer explícito que el input recibido antes del lock de
claim puede integrarse sin otro silencio si el conjunto ya alcanzó ready.
Los triggers actuales siguen protegiendo la frontera posterior.

## 26. Impacto en B9B

Se mantienen 30 llamadas/work, 18.000 tokens máximos reservados/work,
600 máximo por call (clasificadores 160/120), tamaño de contexto, timeout,
admisión durable previa a HTTP bajo witness y no-refund. Un evento READY
no consume ni otorga admisión. Recuperación cuenta llamadas anteriores.

Agrupación/deferrals pueden variar la cantidad de works/calls por diálogo;
se deben medir, no suponer ahorro. No reemplazar un PROCESSING para empezar
presupuesto de cero, ni quitar LLM para compensar scheduling. El límite de
contexto sigue fallando de forma controlada si una ráfaga grande lo excede.

## 27. Impacto en B9C

N=1 por org se conserva. READY pendiente no ocupa slot ni autoriza LLM.
Cada planner sigue secuencial; claim committed PROCESSING con lease/epoch
vigentes es la unidad de capacidad. Organization→Conversation→TurnWork→
Message y chequeo bajo autoridad DB permanecen. No force-release, semáforo
en memoria ni cupo por réplica. Nuevos inbounds no cambian attempts ni
reserva, y saturación deja el trabajo durable para el siguiente intento.

## 28. Riesgos y límites pendientes

Riesgo principal: menos silencio después de READY produce más input
postclaim, deferrals y consumo; se necesita evaluar diálogo, no solo latency.
Riesgo de implementación: dejar B afuera o crear otra autoridad READY.
Riesgo operativo: versiones antiguas reextienden deadlines y hacen ambigua
la transición. La alternativa no arregla la inestabilidad noisy ni todo
el scheduling; no hay throughput prometido para tráfico ilimitado.

Los runs post-fix completos fueron uno base y uno blocked; las otras tres
variantes del candidato están NOT_EVALUATED. μ por org procede de baseline
diagnóstico con observer, cuyo p95 de coste .026936 s/máx. .325583 s está
declarado; no es una nueva muestra del candidato. Waits exactos y jitter
aislado no están disponibles. No reconstruirlos de los percentiles.
La proyección de escala del query y semántica de usuario fuera del corpus
siguen abiertas. Estos límites impiden afirmar robustez o cambiar el perfil.

## 29. Criterio para volver a PROFILE-BETA-1

Primero autorizar un encargo concreto y su frontera contractual; cerrar
regresión/casos de producto y demostrar en diagnóstico que no se retira
elegibilidad y que el **tramo residual eligible→claim** cabe en el presupuesto
del mismo mensaje, incluso con planner bloqueado. Si no cabe, seleccionar
un mecanismo E4 adicional con evidencia, en otro cambio acotado, antes de
consumir un nuevo intento de aceptación. No asumir B suficiente ni escoger
repeticiones favorables del candidato actual.

Luego evaluar el candidato en PROFILE-BETA-1 **original**: topología dos
planners/un sender, N=1, batch/poll 1, 30/300 s, mismos fixtures/tasas/fakes,
dos calls reales READ, presupuesto y denominadores, threshold 10 s y gates
safety/outbox originales. Publicar todos los recibos/variantes necesarias,
invariantes, hashes y errores/missing. Un control de wake o poll diferente
es diagnóstico y no reemplaza esa evaluación.

No se propone PROFILE-BETA-2: no se demostró que el SLO sano sea incompatible
con el producto deliberado. La sobrecarga noisy y el FAIL de un mecanismo
no bastan para cambiar el requisito.

## 30. Criterio para volver a B9E y STOP

Reapertura formal B9E requiere **un nuevo encargo explícito**, candidato
versionado, cambio autorizado/cerrado, regresión requerida sin skips,
evidencia temporal original completa y gates B9D/activación revisados según
su acta. Preservar el FAIL y los históricos; no marcar B9 COMPLETED por
este documento, por base PASS ni por una mejora diagnóstica. Repetir B9E
no significa reimplementar componentes técnicos B9A–D.

**STOP del análisis.** No implementación de B/C/E, no tuning, no cambio de
threshold/profile/N/budget/calls, no rerun ni reapertura B9E y sin deploy.
La entrega es este documento y la derivación reproducible sobre evidencia
cerrada. Los cambios preexistentes del árbol quedan fuera del encargo.
