# B9: aceptación del árbol corregido, campaña r3 — PENDING

**Decisión técnica: PENDING.** La suite completa no pudo evaluar validamente los workers B8B: el ensamblaje asigno test_b9i_full, pero sus guards exigen test_b8b_. Siete procesos salieron antes de READY; un octavo fallo se registro durante la parada propia. Se conservan 2.707 PASS, dos skips historicos y ocho FAIL brutos; 614 IDs quedaron sin recibo en full. Los nueve bloques previos aprobaron y los 11 casos corregidos pasaron dentro de full. No se demuestra un fallo del producto. Frontend, seguridad, auditorias advisory y las cinco variantes PROFILE permanecen NOT_EXECUTED. B8C/B8D/B8E tambien requieren prefijos distintos, por lo que la remediacion minima de ensamblaje es una particion secuencial, exhaustiva y sin duplicados del mismo inventario de 3.331 IDs, sellada antes de una nueva ejecucion.

Base `194772677ca4e9fe1a1dec7f4dafa48396a6c583`; árbol evaluado **`196aceb4f5f234c086b96d8e8af93787613f3c25`**.
Es un árbol Git reproducible con el [diff de dos archivos de tests](correction.diff),
sin commit nuevo. Runtime productivo, locks, cargas, tiempos y gates originales
se conservaron. El resultado corresponde a ese árbol, no se atribuye al commit
base sin las correcciones ni sustituye los resultados históricos de r9.

## Correcciones y verificación

F2 era un componente legacy explícito: sus argumentos del stub no aportaban
provenance B6. Su helper de turnos ahora evita crear accidentalmente un binding
en fixtures sin versión; los bindings existentes conservan el resolver real.
Se mantienen las aserciones de autorización/confirmación, vencimiento, carrera,
efecto único y ausencia de mutaciones indebidas. La oferta tras cancelar se
comprueba por su contenido y ausencia de una reserva nueva.

La prueba de precio exige servicio, precio y moneda del catálogo validado y
rechaza el precio/moneda contradictorios del modelo. No se acepta prosa sensible
no respaldada. No se cambió código productivo.

Verificación enfocada de la campaña anterior, sin repetición actual: **155 PASS, cero fallos/errores y un skip histórico
identificado**, de 156 IDs. Los 11 resultados problemáticos anteriores pasaron.
La primera iteración con un fallo de literal y la preparación rechazada por
hashes pertenecen al expediente anterior. Esta campaña no repite esa verificación
ni transfiere su resultado a los gates integrales actuales.
[Referencia conservada](prior-focused-verification.json).

Los 11 IDs problemáticos anteriores también registraron PASS en esta ejecución
de `full`. [Recibo actual por ID](diagnostics/full-original-11-progress.json).
Los dos skips actuales ya existían en el candidato original y no pertenecen
al inventario crítico. [Aplicabilidad](diagnostics/full-skip-applicability.json).

## Campaña de alcance fijo

| Bloque | Estado | IDs | Exit |
|---|---|---:|---:|
| directed | PASS | 87 | 0 |
| django-check | PASS | — | 0 |
| migration-drift | PASS | — | 0 |
| migrate | PASS | — | 0 |
| billing-schema | PASS | — | 0 |
| b0 | PASS | 17 | 0 |
| b3 | PASS | 42 | 0 |
| b4 | PASS | 68 | 0 |
| b5 | PASS | 37 | 0 |
| full | PENDING_HARNESS_INCOMPATIBILITY | 2717/3331 parciales | -9 |
| frontend-build | NOT_EXECUTED | — | — |
| frontend-test | NOT_EXECUTED | — | — |
| frontend-lint | NOT_EXECUTED | — | — |
| frontend-smoke-urls | NOT_EXECUTED | — | — |
| security | NOT_EXECUTED | — | — |
| pip-audit | NOT_EXECUTED | — | — |
| pnpm-audit | NOT_EXECUTED | — | — |
| profile-base | NOT_EXECUTED | — | — |
| profile-blocked_llm | NOT_EXECUTED | — | — |
| profile-meta_slow | NOT_EXECUTED | — | — |
| profile-duplicate | NOT_EXECUTED | — | — |
| profile-saturation | NOT_EXECUTED | — | — |

Cada bloque/variante formal se ejecutó como máximo una vez. Los solapes entre
corpus, runners y full están deduplicados en [execution-summary.json](execution-summary.json).
Los skips/advisories conservan su aplicabilidad; no cubren requisitos críticos.
La orquestación local usa suites secuenciales, preservando los procesos internos
de los tests. No se afirma ejecución de CI remoto.

Los journals incompletos y sus IDs faltantes figuran en el resumen. Sus
observaciones no sustituyen un recibo completo ni acreditan un gate aprobado.

Las cinco variantes PROFILE permanecen **NOT_EXECUTED** según el
[índice de cobertura temporal](profile-results-index.json). No existen métricas
temporales actuales ni se transfieren métricas históricas.

## Incompatibilidad y remediación acotada

`full` usó `test_b9i_full`. Siete workers B8B rechazaron ese nombre antes de
READY; el octavo FAIL bruto apareció durante la parada propia y se conserva
separado. [Clasificación](failure-classification.json). La terminación propia
SIGTERM/SIGKILL no acredita OOM ni un defecto del producto. El STOP automático
registra la ausencia del recibo completo; la causa previa queda en las trazas
y en [la solicitud de parada](manual-stop-request.json).

B8B/B8C/B8D/B8E exigen cuatro prefijos incompatibles entre sí. La
[especificación del siguiente ensamblaje](next-assembly-remediation.json)
particiona los mismos 3.331 IDs en cinco grupos: 3.213 generales y 21/41/27/29
de procesos B8B/B8C/B8D/B8E. La unión es exacta, sin omisiones ni duplicados.
Es una especificación estática: no se ejecutó otra campaña ni se cambiaron
producto, tests, guards, locks, cargas, tiempos o umbrales.

## Conservación y cierre

Fuentes del árbol, dependencias y evaluador: **PASS en todas las comparaciones registradas**.
La [validación de muestras de recursos](resource-observation-validation.json)
revisó los intervalos de los diez comandos formales: no observó una reserva
de RAM agotada durante ellos (mínimo Windows: 2,151 GiB). Las bajas transitorias
de preparación y posteriores a la ejecución se conservan separadas y no se
presentan como valores de ejecución. Los [monitores por bloque](monitor-summary.json) conservan mínimos
de recursos y desviación de reloj. No se rebajaron las reservas autorizadas de
2 GiB de RAM, 1 GiB de disco ni el guard de reloj de 1 s.

Cleanup, restauración de sincronización WSL, cierre del observador y liberación
de la solicitud propia de actividad: **PASS**. W32Time y políticas globales de
energía/pantalla intactos. Se verificaron **2741 archivos históricos** y
los tres cambios ajenos sin diferencias. [Preservación](preservation-of-prior-work.json).

[Matriz R01–R15/I01–I14](candidate-decision.json), con activación
**PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado, E/P/UX y requisitos
operativos/privacidad separados. Sin commits, push, despliegue ni activación.

[Recuperación y selección de evidencia](README.md). La aprobación técnica, si
corresponde, se limita al árbol y contrato fijo evaluados; no acredita capacidad
comercial, carga máxima, estabilidad de cola o fairness fuerte.
