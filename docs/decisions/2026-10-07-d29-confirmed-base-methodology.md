# D29: procedencia de CONFIRMED_BASE y orden de acreditación

Fecha: 2026-10-07. Baseline: `825db75df68bf076929fa787e77beefe96803350`.
Estado conservado: **CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY**.

## Decisión técnica anterior a la implementación

`CONFIRMED_BASE` no puede obtenerse como un artefacto de acreditación de
fronteras independiente de caracterización bajo el método vigente. El hecho
de que un ensayo tenga duración finita no cambia su finalidad metodológica.
No se implementa en esta fase ningún productor ni sustituto de esa base.

El protocolo D29-v1, §5, distingue una referencia de calibración de un nivel
compatible confirmado. La calibración usa pacing condicionado al claim; no
prueba sostenibilidad ni confirma una tasa. El nivel exige población completa,
fronteras temporales decidibles, oferta realmente emitida, invariantes y
backlog por organización/global. La confirmación requiere las repeticiones
físicas previstas, sin promediar fallos ni reutilizar repeticiones descartadas.

`Controller.search()` materializa esa secuencia: CALIBRATE, SCREEN, REFINE
cuando corresponde, y CONFIRM. Solo tras las confirmaciones asigna
`self.confirmed[case]`. `Controller.run()` toma específicamente
`self.confirmed['R1-02']` para R1-03/R1-04/R1-05/R1-06. Una referencia de R1-01,
el control equilibrado finito de R1-03, un probe R1-02 de dos inputs o un replay
no son esa base. Las variantes de burst y el tamaño del backlog dependen de
ella; no de valores elegidos para una fixture.

Una futura base será un prerrequisito reutilizable con procedencia hacia sus
corridas de caracterización, planes sellados, fuentes, coste, topología,
cohortes, ventanas y confirmaciones. El artefacto de base y las corridas que lo
producen son conceptos distintos: consumir el primero no autoriza ni evita
las segundas. No se obtiene E, capacidad máxima o aprobación comercial por
producir una base experimental confirmada.

## Orden permitido y orden recomendado

El protocolo §8 permite primero acreditar el instrumento con casos mínimos,
después caracterizar la primera ronda y confirmar candidatos, y finalmente
ejecutar los casos dependientes sobre la carga base observada.
El controlador permite seleccionar R1-02 como primera serie; R1-01 es una
búsqueda independiente y no produce la base equilibrada de los dependientes.
No hay en el método una ruta alternativa que transforme acreditación finita
en CONFIRMED_BASE.

Orden recomendado, sujeto a autorización humana de las fases posteriores:

1. **Esta fase:** cerrar las fronteras finitas R1-01/R1-03/R1-04, preparar
   burst/backlog y verificar la infraestructura. No caracterización.
2. **Revisión y decisión metodológica:** aceptar que las fronteras finitas
   preparan el instrumento mientras las condiciones completas dependientes
   permanecen pendientes. Mantener FULL_LIVE_MATRIX_NOT_READY.
3. **Futura fase expresamente autorizada:** caracterización inicial de R1-02
   conforme al protocolo; conservar sus confirmaciones físicas. No sustituir
   este paso por una fixture ni por una calibración aislada.
4. Consumir esa base con trazabilidad en R1-03/R1-04/R1-05/R1-06 y acreditar las
   condiciones completas de oferta, backlog y seguimiento. No declarar
   FULL_CONTROLLER_ACCREDITED antes de revisar la acreditación real de los 17.

Si se exige simultáneamente 17/17 bajo las condiciones completas y ninguna
caracterización previa, el prerrequisito es inalcanzable en ese orden.
Resolver esa puerta necesita una decisión metodológica del usuario, no un
cambio de significado de CONFIRMED_BASE ni una primitiva de producción.
No se cambia esa puerta automáticamente en código.

## Separación obligatoria en recibos de esta fase

- Frontera física observada: hechos respaldados por captura PostgreSQL,
  procesos, selección y commits reales.
- Condición completa de carga: NOT_ACCREDITED en estos probes finitos.
- Prerrequisito de base: PENDING cuando aplica al recorrido de carga.
- Replay: ningún resultado sintético se acepta como evidencia física.
- R1-05/R1-06: preparación documentada, estado PENDING; sin base, sin ejecución
  del escenario completo y sin rótulo de acreditación.

Se conserva el objetivo de producto y los valores existentes del protocolo.
No se proponen tasas, E, nuevos SLA, tuning, scheduling, cambios B8/B9/E4 ni
configuración persistente. Las nuevas herramientas solo pertenecen a tests.

Referencias: [protocolo D29-v1](2026-10-05-scheduling-characterization-protocol.md),
[controlador](../../backend/apps/agent/tests/scheduling_characterization/controller.py),
[acreditación física anterior](../evals/d29-physical-2026-10-06/report.md).
