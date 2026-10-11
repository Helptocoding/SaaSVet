# D29 — Cierre de fase con R1-04 PENDING

**Decisión registrada el 10 de octubre de 2026:** la fase se cierra con la
limitación de R1-04 explícita y aceptada. R1-04 permanece **PENDING**; esta
decisión no lo convierte en ACCREDITED ni FAILED. No se autoriza otra ejecución
ahora. La limitación documentada se considera una decisión técnica legítima.

## R2-04 — conciliación de duración

No hay discrepancia en la duración numérica del resumen. Se cotejaron el recibo
físico, el resultado del verificador original y las marcas monotónicas de la
captura; los cinco archivos coinciden con su índice SHA-256 sellado.

`observed-window.json` registra inicio `11.313.036.952.700 ns` y final
`11.553.646.879.800 ns`. La diferencia es `240.609.927.100 ns`, que equivale
a `240.6099271 s` (`240 s + 0.6099271 s`, aproximadamente 4 min 0.61 s).
El verificador original reporta exactamente `240.6099271` y PASS, sin errores.
Esto satisface el límite original de seguimiento de al menos 240 s. En el
resumen entregado, `240,6099271 s` usa coma decimal española; la cifra no era
una duración de cientos de millones de segundos. Este párrafo deja la
representación inequívoca sin reescribir el recibo físico ni repetir la prueba.

Fuentes: [resultado autoritativo](../d29-execution-2026-10-10/r204-intact-01/physical-verification.json),
[verificación original PASS](../d29-execution-2026-10-10/r204-intact-01/capture/authorized-verification-v2.json),
[intervalo observado](../d29-execution-2026-10-10/r204-intact-01/capture/observed-window.json),
[ancla monotónica](../d29-execution-2026-10-10/r204-intact-01/capture/fixed-anchor.json) e
[índice sellado del intento](../d29-execution-2026-10-10/r204-intact-01/attempt-artifact-index.json).
Los SHA-256 y la aritmética de conciliación quedan en
[r204-duration-audit.json](r204-duration-audit.json).

## R1-04 — estado y evidencia faltante

El único intento físico usó el calendario base, 24 ofertas ordinarias y los
planners libres durante oferta de 360 s y seguimiento de 240 s. La observación
capturó 1.082 preconsultas y cero forecast-yields que cumplieran los predicados.
Hubo siete casos con waiter READY y futuro dentro del horizonte, pero seis no
tenían la relación de recencia requerida y el séptimo tenía waiter sin claim
previo, caso exento de yield nativo. Las selecciones nativas devolvieron
candidatos. Por ello faltó evidencia física de la cadena requerida:

`waiter READY → forecast válido → selección nativa vacía/yield →
corrección ordinaria comprometida después del yield → forecast anterior obsoleto
→ nueva elegibilidad y claims causales`.

El resultado y sus observaciones originales están preservados en el
[resultado físico R1-04](../d29-execution-2026-10-10/r104-passive-01/physical-verification-v2.json),
el [análisis de predicados](../d29-execution-2026-10-10/r104-passive-01/observed-predicate-blockers.json)
y la [limitación del intento](../d29-execution-2026-10-10/r104-passive-01/observed-window-limitation.json).
La ausencia de esa cadena en el único intento no prueba imposibilidad general.

Si el escenario se retoma en el futuro, antes de ejecutarlo debe aparecer un
candidato cuya compatibilidad con el contrato original se pueda demostrar:

- recencia sustentada por historial de claims real y los mismos predicados
  nativos de disponibilidad, organización libre y horizonte;
- población, pacing, calendario, rotación, costes y límites 360/240 originales,
  sin entradas adicionales ni ajuste de tiempos para fabricar la ventana;
- selección realmente vacía y retorno nativo sin claim, luego corrección
  comprometida dentro del deadline anterior, sin escrituras concurrentes que
  hagan ambigua la causa;
- evidencia posterior del miss del forecast anterior, nueva elegibilidad y
  claims en el orden y límites temporales originales;
- guard estricto de reloj, gates existentes, captura contemporánea, integridad
  y cleanup válidos.

La demostración previa de compatibilidad sólo permitiría decidir si conviene
solicitar retomar el caso; no reemplazaría la evidencia física ni autoriza una
ejecución. La decisión actual es **cero intentos adicionales**. No se construyó
ni diseñó un fixture, no se modificó el planner ni se ejecutaron pruebas nuevas.

## Estado de la fase

| Trabajo | Estado |
|---|---|
| R1-06 | ACCREDITED |
| Siete regresiones | ACCREDITED, 192/192, sin skips |
| R2-09 uncertain_meta | ACCREDITED |
| R2-09 slow_meta | ACCREDITED |
| R2-04 | ACCREDITED; seguimiento conciliado arriba |
| R1-04 | PENDING; limitación aceptada, sin ejecución autorizada |

La [entrega de ejecución](../d29-execution-2026-10-10/ENTREGA.md) y su recibo
final reflejan la situación antes de esta decisión. Este documento actualiza el
estado de decisión; los recibos previos conservan su contenido y sirven como
historial sellado. No quedan acciones autorizadas pendientes en esta fase y no
se inicia la matriz. R1-04 permanece PENDING. Un candidato futuro requerirá
demostrar compatibilidad antes de ejecutarlo y una nueva decisión explícita.
