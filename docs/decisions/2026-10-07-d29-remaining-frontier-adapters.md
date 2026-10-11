# D29: extensiones de infraestructura para fronteras restantes

Fecha: 2026-10-07. Baseline `825db75df68bf076929fa787e77beefe96803350`.
Estado conservado: `CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY`.
Alcance autorizado: infraestructura de evaluación y evidencia física finita.

## Implementación aislada

Se añaden tres módulos bajo `backend/apps/agent/tests/scheduling_characterization`:

- `frontier_infrastructure.py`: procesos reales con gates de arranque/poll,
  preparación READY, calendarios finitos de oferta y seguimiento de población,
  edad por input, cola READY y obligaciones de trabajo separadas.
- `frontiers.py`: ejecuta únicamente R1-01/R1-03/R1-04, prepara R1-05/R1-06
  sin abrir PostgreSQL ni ejecutar esos escenarios, y genera receipts.
- `frontier_verify.py`: recompone desde journals, ledger de ingress y cortes
  PostgreSQL. Un rótulo PASS, un hash reseñado o una declaración del ejecutor
  no sustituye las comprobaciones semánticas de cada frontera.

Las fuentes runtime, la configuración persistente, E4, B8/B9 y los módulos
D29 anteriormente acreditados permanecen intactos. La orquestación usa una
copia del archivo Git del baseline y PostgreSQL privado temporal, durable,
en loopback. Cada probe usa una base recién creada desde un schema vacío;
los workers y las bases se retiran al terminar. Los tres participantes
ejecutan el selector y el servicio del baseline. LLM/READ/Meta usan el
provider local contenido ya existente; no proveedores ni efectos externos.

## Fronteras y controles

| Caso | Preparación y ejecución | Testigo exigido por el verificador |
|---|---|---|
| R1-01 | Tres conversaciones distintas de una organización. Los participantes se inicializan pero permanecen retenidos. Ingress ordinario y espera hasta READY natural; luego se liberan los planners. | Corte independiente con todos los episodios READY, sin work asignado; ledger durable; claims exteriores posteriores al corte; servicio y población completos. |
| R1-03 | Dos fases finitas con dos orgs activas por fase. Control 3:3 y sujeto 4:2; calendario normalizado común de seis slots, tomado del intervalo de poll existente. Pares nuevos de organizaciones para evitar historia de servicio heredada. | Emisiones realmente iniciadas en cada slot, aceptación durable conciliada, conversaciones distintas, población íntegra, journals de planners concurrentes y corte de drain del control antes del sujeto. |
| R1-04 | Servicio previo real de la org del waiter; waiter READY natural. Un peer ordinario futuro activa el yield nativo. Un segundo ingreso committed antes del deadline original pospone solamente ese peer aún no READY. Se observa el deadline no materializado, el segundo yield, READY natural del peer y los claims siguientes. | Estado **anterior** a cada consulta, poll real correlacionado con journal y reloj DB, selección vacía sin claim intentado, cambio durable de deadline, miss de forecast distinto de miss de claim, origen del waiter conservado en todos los cortes y commits siguientes. |
| R1-05 | Infraestructura para sellar calendarios suministrados de pre-burst/burst/retorno, emitir fases y observar drain con conciliación. Simultáneo describe las orgs afectadas conjuntamente; no afirma commits atómicos simultáneos. | Preparación `PENDING`. No se genera calendario de carga basado en una base artificial, no se ejecuta el caso completo ni se acredita su carga. |
| R1-06 | Preparación de backlog con ingress ordinario y READY natural sin polls. Helper para corte con workers no iniciados, arranque posterior retenido, liberación y seguimiento. | Preparación `PENDING`. El helper de arranque de backlog no se ejecuta como R1-06 en esta fase y rechaza participantes iniciados previamente. |

La cadencia finita de R1-03 no produce ni propone una tasa. El desplazamiento
de 0,9 segundos usado para liberar polls de R1-04 sitúa el probe dentro del
horizonte **existente** de un segundo de E4; no cambia ese horizonte ni el
reloj. Si el bracket real no cabe dentro de él, la corrida falla. No existe
fallback mediante reloj adelantado, selector mock, query posterior ni replay.
La consulta independiente de estado se ejecuta dentro del participante antes
del poll real; ambos hechos conservan sus tiempos DB. Su publicación en disco
ocurre después del poll. La corrección ordinaria del peer se ejecuta tras el
primer yield y antes de publicar su receipt, evitando que el transporte de
archivos ocupe la ventana causal. Si la corrección no commitea antes del
deadline original, la corrida permanece fallida.

`prepare_burst` acepta calendarios explícitos y los conserva como preparación
sin procedencia de carga acreditada. No dimensiona burst/backlog, no produce
CONFIRMED_BASE y no transforma un calendario suministrado en aprobación de
ejecución. El comando `run` rechaza R1-05/R1-06 antes de bootstrap. El futuro
consumo y comprobación de procedencia de base aún debe encargarse después de
resolver el orden metodológico.

La conciliación registra edad READY **por input**, conservando el origen
observado; la edad contractual por episodio se deriva por `reconstruct`.
No confunde coalescing con nuevas conversaciones ni cola READY cero con
trabajos terminados. Conserva miembros omitidos, futuras elegibilidades y
trabajos incompletos. La secuencia R1-04 representa cuatro inputs en tres
episodios porque la corrección del peer coalesce antes de READY.

## Separación y límites de evidencia

Todos los receipts separan frontera física, condición de carga, prerrequisito,
evidencia física y evidencia sintética. `FINITE_BOUNDARY_ONLY` no acredita un
nivel, sostenibilidad, E ni las condiciones completas de caracterización.
R1-03/R1-04 conservan explícitamente `CONFIRMED_BASE: PENDING` para ese recorrido;
R1-05/R1-06 conservan `PENDING` como escenario completo.

Los tests negativos alteran **copias temporales de capturas reales** y
comprueban el rechazo de evidencia inválida: corte posterior, cambio de
cadencia, población incompleta, claim miss mal atribuido, PASS inventado,
procedencia sintética y eliminación del prerrequisito. Son tests del
verificador, no ejecuciones físicas ni acreditación por replay. Las capturas
originales y los fallos de ejecución permanecen conservados.

El análisis anterior a cualquier mecanismo de base está en
[CONFIRMED_BASE y orden metodológico](2026-10-07-d29-confirmed-base-methodology.md).
Los resultados, hashes, regresión y cleanup se concentran en
[evidencia de esta fase](../evals/d29-frontiers-2026-10-07/report.md).
No hay commits ni ejecución de caracterización en este encargo.
