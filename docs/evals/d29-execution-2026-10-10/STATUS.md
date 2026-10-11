# Seguimiento acumulativo D29 — 10 de octubre de 2026

Plan vigente: [PLAN-RECTOR.md](PLAN-RECTOR.md). Solicitud original sellada en
`authorization.json`. Se conserva toda la preparación del 9 de octubre.

Baseline: `825db75df68bf076929fa787e77beefe96803350`.
Base confirmada: SHA-256 `71c3e58c34decfac1698f9517f39b4d7cbc936c0463e35a4bbfe00ee04920a56`.
Rama inicial: `codex/e4-capacity-scheduling`; cambios previos preservados.

| Punto | Estado | Evidencia / siguiente paso autorizado |
|---|---|---|
| Harness R1-06 | ACCREDITED | Validación de infraestructura: 4 pruebas PostgreSQL en `adapter-02`; no acredita carga física. |
| Harness R2-09 | ACCREDITED | Cohorte natural 2×3, sender previo, procesos libres y gates de uncertain_meta físicamente conciliados. |
| R1-06 físico | ACCREDITED | `r106-prospective-01/scenario-result.json`; 360/240 completos, todos los gates. |
| Siete regresiones | ACCREDITED | 192/192 sin skips/fallos/errores; `sequential-regressions.json`. Una DB nueva por suite, todas retiradas. |
| R2-09 uncertain_meta | ACCREDITED | `r209-uncertain-01/scenario-result.json`; un intento físico, conciliación v3 de evidencia preservada. |
| R2-09 slow_meta | ACCREDITED | `r209-slow-01/scenario-result.json`; intento independiente, 360/240 completos y todos los gates. |
| R1-04 | PENDING | `r104-passive-01/physical-verification-v2.json`: intento único 360/240, 1.082 preconsultas, cero forecast-yields; no se acreditó secuencia. |
| R2-04 | ACCREDITED | `r204-intact-01/scenario-result.json`; reclaim natural durante oferta, verificador original PASS, W32Time intacto. |

Cambios de esta fase sólo en este directorio. Runtime, contratos, baseline,
verificadores originales y provider conservados. Sin commits, matriz, tuning,
caracterización ni estimaciones de capacidad.

## Registro

- Inicio: confirmados HEAD/rama, estado previo y entrega offline.
- Implementación: captura guard por proyección de su SELECT nativo, CAS por
  retorno del update nativo y contexto por render real comprobado antes del LLM.
  No hay consulta retrospectiva para producir los tres testigos.
- Ejecutado unittest discovery anterior: 94 ejecuciones exitosas, 69 controles
  distintos (25 se descubren también por importación). No es acreditación física.
- Laboratorio nuevo: migraciones del archive original completadas; durabilidad
  `fsync=on`, `synchronous_commit=on` exigida por el inicializador preservado.
- `offline-validation-01.json`: 72 controles distintos exitosos (69 anteriores
  y 3 de orden de arranque). Logs completos conservados.
- `adapter-01`: 3 pruebas PostgreSQL exitosas y una con error de firma del mock
  HTTP del propio test. Corregido ese cableado; no se cambió runtime/provider.
- `adapter-02`: 4 pruebas PostgreSQL exitosas, incluido guard real, terminal CAS,
  rollback exterior y consumo de contexto del sucesor antes del primer LLM.
  Ambas DB de tests retiradas con ausencia de clientes comprobada.
- `r106-prospective-01`: ejecución física iniciada. W32Time observado Running /
  Automatic, sin intervención. Se observa un guard de diferimiento verdadero;
  la cadena sigue pendiente de conciliación final, sin declarar PASS provisional.
- R1-06 completado: 32 inputs, 31 episodios/works, 62 llamadas LLM y 30 Meta
  aceptadas; 1 diferimiento y 1 sucesor causal demostrados. Clock/host válidos,
  360/240 completos, workers con exit 0 y DB retirada sin clientes remanentes.
- La conexión v1 del verificador lanzó TypeError por orden invertido en
  `_savepoint_rolled_back`. Además comparaba texto UTC del journal con texto
  -06:00 del censo para el mismo instante. `native_verifier_bridge.py` adapta
  argumentos y representación UTC sin editar verificador, gates o artefactos.
  Cinco controles pasan, incluidos rollback rechazado y timestamps distintos.
  Se preservan fallo v1, reparación v2 y 20 fuentes selladas del ejecutor.
- R1-06 final: `ACCREDITED`, sin errores de conciliación ni gates pendientes.
  Iniciada sólo la primera suite pendiente, `test_b4_sender`, en otra DB privada.
- Suites sender 42/42, W1 12/12, safety 30/30 y operation_execution 53/53:
  `ACCREDITED` como regresiones, sin skips, fallos o errores. Cada base nueva
  retirada tras comprobar ausencia de clientes; fuentes originales íntegras.
- `offline-validation-04.json`: 81 controles distintos exitosos, incluidos
  cuatro controles negativos del predicado de forecast. No son prueba física.
- R2-04 conectado reutilizando ejecutor, fixture y verificador byte a byte de
  revision2; el worker acepta el escenario con provider conservado. El guard
  original permanece estricto, sin control de W32Time.
- R1-04: preparado un único experimento finito de 6 inputs ordinarios y una
  corrección condicional después de yield nativo; dos planners libres, sin
  barreras de polling ni cambios al selector/deadlines. Su calendario sólo
  programa emisiones: nunca se usa como evidencia de la secuencia. No es
  acreditación de la demanda completa de la base.
- Budget: 28/28 en 833,191 s, sin skips/fallos/errores; `ACCREDITED` como
  regresión. Cierre sin clientes y DB retirada. Comenzó concurrencia.
- `offline-validation-05.json`: 82 controles distintos exitosos, incluido
  rechazo de señales de yield con poll fallido, candidatos o evento incorrecto.
- Revisión previa a ejecutar R1-04: el fixture concentrado descrito arriba se
  descartó SIN ejecutarlo porque añadía correcciones fuera del pacing confirmado.
  `r104_entry.py` usa ahora sólo las 24 ofertas ordinarias del calendario base,
  360/240 completos y rotación global %3; no hay inputs extra ni corrección
  disparada por señal. Observación antes de toda selección, con planners libres.
  La conciliación exige que la corrección sea una oferta ordinaria real del
  calendario y rechaza carreras de writes durante la preconsulta/selección.
- `offline-validation-06.json`: 83 controles distintos exitosos. La búsqueda
  dinámica del waiter/forecast respeta estado real, horizonte y recencia nativa.
- Regresiones completadas: concurrencia 18/18 y procesos 9/9 (428,066 s),
  sin skips, fallos o errores. Las siete suman 192/192; todas con integridad
  y cierre sin clientes, DB retirada. `sequential-regressions.json` conserva
  los receipts individuales. No se observó OOM; su causa histórica sigue abierta.
- Inicia `r209-uncertain-01`: ejecución independiente posterior a las siete
  suites, cohorte inicial 2×3 naturalmente READY y parámetros 360/240 sellados.
- `r209-uncertain-01` terminó 360/240, clock/host válidos, workers exit 0 y DB
  retirada sin clientes. Verificación provisional PENDING sólo por asumir
  erróneamente un vínculo padre directo RTK→intérprete: Windows venv introduce
  un proceso python intermedio. 254 snapshots Toolhelp contemporáneos contienen
  las tres cadenas completas. `native_ancestry.py` verifica sus enlaces reales,
  repetición temporal, orden de creación y rechazo de ciclos/ausencias/cambios.
  `r209_verification_v3.py` conserva todos los demás gates de v2. No se cambió
  verificador original protegido ni bound de aceptación; v2 se conserva intacta.
- Primera reconcilación offline v3 encontró que el observador antiguo consultaba
  la DB ya retirada. `sealed_census.py` ofrece exactamente el outbox independiente
  capturado, incluyendo timestamps y estado uncertain; rechaza IDs ausentes,
  duplicados o timestamps sin zona. No se reconstruye estado faltante.
- `offline-validation-08.json`: 93 controles distintos exitosos (7 de ascendencia
  y 3 de censo sellado adicionales). Reconciliación final v3 sin errores:
  `ACCREDITED`, 30 inputs, 28 works/episodios, 56 LLM, 28 Meta, 14 resultados
  ACCEPTED y 14 UNCERTAIN correlacionados; solapamiento natural y progreso del
  par demostrados. No se repitió la ejecución física.
- `r209-slow-01`: `ACCREDITED`, 360/240, 30 inputs, 29 works/episodios,
  58 LLM, 28 Meta ACCEPTED, cero UNCERTAIN. Un diferimiento y su sucesor
  causal resuelto; dos overlaps naturales y 12 progresos ordinarios del par.
  Todos los gates y clock/host válidos; workers exit 0, DB retirada sin clientes.
- Inicia `r104-passive-01`: único intento físico de la secuencia forecast,
  calendario base 360/240 y 24 inputs ordinarios, cero inputs extra, dos
  planners libres; testigos previos a cada selección nativa. No se programan
  correcciones fuera del calendario ni se retienen participantes.
- R1-04 cerrado como `PENDING`: 24 inputs/episodios/works, 48 LLM, 24 Meta
  ACCEPTED, 360/240 completos; clock/host, demanda, invariantes, ventanas y
  preparación pasan. 1.082 preconsultas reales y cero forecast-yields válidos.
  Falta la secuencia temporal requerida; esto no prueba imposibilidad general.
  No se repite el intento sin decisión específica sobre el fixture compatible.
- El primer verificador R1-04 esperaba un receipt de cleanup de otro launcher.
  `native_cleanup.py` verifica salidas nativas, ausencia de los tres procesos
  en el snapshot AFTER real y ausencia de clientes/DB retirada; la conciliación
  v2 de la misma captura resuelve ese cableado. El ejecutor queda corregido
  para capturar también ausencia de procesos/backends al terminar workers.
  `offline-validation-10.json`: 97 controles distintos exitosos. Resultado
  provisional y final v2 preservados; ninguna prueba física repetida.
- Las fuentes exactas de cada verificación reparada se archivan y contrastan
  con los hashes ya publicados en `verification-archives.json`.
- R2-04 preflight intacto: W32Time observado Running/Automatic, cuatro guards
  previos válidos, ejecutor/fixture/verificador originales byte idénticos.
  Se autoriza por el plan vigente un único intento con expiración natural,
  sin asumir que el reloj se mantendrá válido durante la espera larga.
- R1-04, diagnóstico final de las 7 coexistencias físicas: 6 tenían futuro
  atendido más recientemente que el waiter; 1 waiter sin claim previo.
  Las selecciones nativas devolvieron candidatos, no forecast-yield.
  `observed-predicate-blockers.json` conserva secuencias/IDs/historial real.
  La separación mínima observada entre aceptaciones de la misma conversación
  fue 91,543014 s. Esto describe el intento; no prueba imposibilidad universal.
- R2-04 `r204-intact-01`: `ACCREDITED` por verificador original byte intacto,
  cero errores. 25 inputs/episodios/works (1 prelude +24 ordinarios), 26 claims,
  un reclaim causal del mismo work tras expiración natural de 900 s dentro
  de la oferta 360 s. Ambas organizaciones aceptan antes/después del reclaim.
  Historial, presupuesto y membresía preservados, fencing sin efecto,
  demanda/servicio/invariantes/ventanas pasan; followup 240,6099271 s.
  Clock/host válidos, workers exit 0 y DB retirada sin clientes.
- W32Time observado nuevamente Running/Automatic tras R2-04; nunca se
  detuvo ni configuró. No se precisó intervención ni recuperación del host.
- Todos los intentos físicos autorizados concluidos. Único pendiente R1-04:
  requiere decisión sobre la limitación del calendario/fixture temporal.
  Sin nuevo intento, matriz, tuning, caracterización, capacidad E o commits.
- Cierre del laboratorio: 14 expedientes sellados antes de retirar el temporal;
  `precleanup-integrity.json` confirma 3.409 fuentes protegidas y evidencia previa
  intactas. `lab-cleanup.json` confirma temporal/credenciales/bases retirados y
  puerto cerrado; `final-integrity.json` confirma integridad posterior.
- Entrega consolidada: [ENTREGA.md](ENTREGA.md), resultados autoritativos en
  `execution-summary.json` y recursos en `resources-summary.json`. El plan
  permanece abierto sólo por R1-04; la limitación no se presume aceptada.

Actualizar este registro con resultados y receipts; no borrar intentos anteriores.
