# D29: cierre de fronteras físicas restantes

Baseline `825db75df68bf076929fa787e77beefe96803350` conservado. Estado **CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY**. Cero commits.
Alcance: infraestructura de evaluación, tres fronteras físicas finitas y dos
preparaciones pendientes. No caracterización, benchmark, sweep, tuning,
PROFILE, E, scheduling de producción ni cambios B8/B9/E4.

| Escenario | Resultado de esta fase | Evidencia |
|---|---|---|
| R1-01 | Acreditado físicamente: tres episodios en conversaciones distintas de una misma org coexistiendo READY natural, seguidos por claims committed y servicio. | [Receipt](individual-02-R101/receipt.json), [verificador](individual-02-R101/verification.json), [coexistencia](individual-02-R101/coexistence.json). |
| R1-03 | Geometría física finita acreditada: control 3:3 y sujeto 4:2, seis emisiones/aceptaciones reales en cada fase, calendario global común y planners concurrentes. La condición completa de carga sigue pendiente de CONFIRMED_BASE. | [Receipt](individual-02-R103/receipt.json), [verificador](individual-02-R103/verification.json), [emisiones](individual-02-R103/emissions.jsonl). |
| R1-04 | Secuencia causal física acreditada: READY waiter, dos polls que realmente producen selección vacía/yield, corrección ordinary committed antes del primer deadline, forecast original no materializado, nueva elegibilidad natural y claims del peer y del waiter. Origen del waiter conservado. Ningún yield se atribuye a miss de claim. Condición completa de carga pendiente. | [Receipt](individual-06-R104/receipt.json), [verificador](individual-06-R104/verification.json), [secuencia](individual-06-R104/forecast-sequence.json). |
| R1-05 | Infraestructura preparada: calendarios de pre-burst/burst/retorno, emisión por fases, cortes y conciliación de aceptaciones, edades READY, cola y obligaciones; **PENDING**, no ejecutado/acreditado como caso completo. | [Preparación](preparation-R105/preparation.json). |
| R1-06 | Infraestructura preparada: ingreso ordinario sin polls, READY natural, corte antes de arrancar workers, arranque retenido y drain posterior; **PENDING**, no ejecutado/acreditado como caso completo. | [Preparación](preparation-R106/preparation.json). |

## Alcance y procedencia

Las corridas usan PostgreSQL privado durable, copia congelada del baseline,
bases nuevas e ingress/selector/claims/servicio reales. El provider local
contenido conserva el fixture READ existente; no se usan proveedores externos
ni se producen efectos externos. Las dos parejas de orgs de R1-03 son nuevas
por fase; solo dos orgs tienen demanda activa en cada fase. El control drena
antes de la oferta desigual. Se conservan calendario, emisiones realmente
ejecutadas, ledger durable, journals y cortes independientes.

R1-04 conserva consultas independientes **anteriores** al poll del selector.
La publicación de sus archivos ocurre después; sus tiempos y estado proceden
de la consulta previa real. Los polls conservan brackets DB y trazas nativas.
La corrección usa el mismo ingress ordinario dentro del participante después
del yield, antes de publicar archivos. No hay selector/clock mock ni replay
para cerrar las fronteras. Los cuatro inputs quedan representados en tres
episodios, incluido el coalescing del peer antes de READY.

Los receipts mantienen separados frontera observada, carga no acreditada,
prerrequisito pendiente, evidencia física y evidencia sintética vacía. El
seguimiento distingue edad por input de edad reconstruida por episodio; una
cola READY vacía no borra trabajos pendientes ni inputs faltantes. Ninguna
captura finita de esta fase se convierte en evidencia de capacidad.

## Fallos conservados y reproducción final

R1-04 conserva cuatro intentos fallidos: lectura de arranque parcialmente
publicado; acceso Windows transitorio a una barrera; poll que cruzó el
deadline durante publicación del corte; y corrección cuyo ACK durable quedó
después del deadline original. Todos permanecen NOT_ACCREDITED y sus bases
privadas se eliminaron. Se corrigió únicamente el transporte y la colocación
del testigo dentro del harness; no se modificó runtime ni se amplió el
horizonte nativo. El quinto intento acreditó la secuencia.

Después de esas correcciones, se repitieron los tres probes con las fuentes
finales. R1-01/R1-03 pasaron su segunda ejecución y R1-04 pasó su sexta
ejecución. Todos los intentos y sus versiones congeladas están conservados;
la selección final está en [selection.json](selection.json). Estas
repeticiones verifican el instrumento tras cambios, sin adaptar demanda ni
buscar capacidad. No se descartó un fallo para confirmar un nivel.

## Regresión e integridad

- **78 tests D29 y verificadores: PASS, sin skips.** Incluyen
  rechazo semántico de copias alteradas de capturas físicas, incluso con hash
  reseñado o PASS inventado, y checks de los límites de preparación.
- **231 tests existentes de aplicación: PASS, sin skips.** B3,
  sender, W1, safety, operaciones, budgets y concurrencia B9C. Los tests son
  regresión, no acreditación física ni caracterización.
- Todos los participantes terminados, todas las bases privadas eliminadas,
  PostgreSQL privado detenido, puerto cerrado y directorio/credenciales
  temporales eliminados. Binarios PostgreSQL compartidos preservados.
- **3405 fuentes/archivos previos y
  1930 artefactos anteriores intactos**, HEAD
  exactamente en el baseline. No se modificaron los cambios ajenos ya
  presentes en el workspace ni los módulos D29 anteriormente acreditados.

Logs y receipts: [regresión D29](unit-regression.log),
[regresión de aplicación](application-regression.json),
[cleanup](lab-cleanup.json), [integridad](final-integrity.json).
[result.json](result.json) reúne resultados, intentos, hashes y procedencia.
[artifact-index.json](artifact-index.json) conserva hashes de esta evidencia.

## CONFIRMED_BASE y decisión pendiente

El análisis se documentó antes de construir las extensiones:
[análisis formal](../../decisions/2026-10-07-d29-confirmed-base-methodology.md).
Según D29 §5 y el controlador vigente, la calibración R1-02 es solo referencia;
CONFIRMED_BASE aparece después de evaluar niveles y completar sus
confirmaciones físicas. La duración finita de su artefacto no la vuelve
independiente de caracterización. Un probe R1-02 de dos inputs, el control
finito de R1-03, R1-01, una fixture satisfecha o replay no pueden producirla.
No se implementó ningún productor/sustituto ni consumidor que la presuponga.

Orden recomendado: revisar estas fronteras finitas → aprobar explícitamente
el orden metodológico permitido por D29 §8 → encargar por separado la
caracterización inicial R1-02 conforme §5 → conservar base confirmada con
procedencia completa → consumirla para las condiciones completas
R1-03/R1-04/R1-05/R1-06 → revisar acreditación real de los 17 antes de cambiar
el estado global. Esa fase de caracterización **no está autorizada ni
iniciada**. El controlador existente permite seleccionar primero R1-02;
no se crea una excepción automática a la autorización humana.

La decisión pendiente es aceptar ese orden y autorizar posteriormente su
fase inicial. Exigir a la vez la matriz completa bajo CONFIRMED_BASE y cero
caracterización previa deja un prerrequisito circular; necesita una decisión
metodológica expresa. No requiere nueva primitiva de producción ni redefinir
CONFIRMED_BASE. **FULL_CONTROLLER_ACCREDITED no se declara.**

## Archivos añadidos

Tres módulos `frontier_infrastructure.py`, `frontiers.py`, `frontier_verify.py`,
`test_d29_frontiers.py`, dos documentos D29 del 2026-10-07 y este directorio de
evidencia/orquestación. El diseño de adapters está en
[extensiones de evaluación](../../decisions/2026-10-07-d29-remaining-frontier-adapters.md).
Los hashes exactos están en `result.json`; cada corrida conserva sus propias
fuentes congeladas. Commits: **0**.
