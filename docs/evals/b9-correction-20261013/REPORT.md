# B9: corrección mínima y aceptación — PENDING

**Decisión técnica: PENDING.** El monitor detuvo full el 2026-10-14 a las 07:10:53 UTC porque Windows disponía de 1,42 GiB de RAM, por debajo de la reserva autorizada de 2 GiB. Hay 353 PASS parciales, cero FAIL/ERROR registrados y 2.978 IDs sin recibo; no existe recibo completo de full. Los nueve bloques anteriores aprobaron. Frontend, seguridad, auditorías advisory y las cinco variantes PROFILE permanecen NOT_EXECUTED. La incidencia invalida la aceptación integral sin demostrar un fallo del producto.

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

Verificación enfocada final: **155 PASS, cero fallos/errores y un skip histórico
identificado**, de 156 IDs. Los 11 resultados problemáticos anteriores pasaron.
Se conservan la primera iteración con un fallo de literal y la preparación
rechazada por hashes antes de ejecutar tests; son desarrollo previo al sello,
no reintentos de esta campaña. [Verificación](focused-verification.json).

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
| full | PENDING_ENVIRONMENT_INTERRUPTION | 353/3331 parciales | -15 |
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

Las cinco variantes PROFILE permanecen **NOT_EXECUTED**, como registra el
[índice de cobertura temporal](profile-results-index.json). No existen métricas
temporales de esta campaña: denominadores, faltantes, latencias, máximos, colas,
errores y gates se mantienen sin evaluar. No se transfieren métricas históricas.

## Conservación y cierre

Fuentes del árbol, dependencias y evaluador: **PASS en todas las comparaciones registradas**.
Los [monitores por bloque](monitor-summary.json) conservan mínimos
de recursos y desviación de reloj. No se rebajaron las reservas autorizadas de
2 GiB de RAM, 1 GiB de disco ni el guard de reloj de 1 s.

Cleanup, restauración de sincronización WSL, cierre del observador y liberación
de la solicitud propia de actividad: **PASS**. W32Time y políticas globales de
energía/pantalla intactos. Se verificaron **2073 archivos históricos** y
los tres cambios ajenos sin diferencias. [Preservación](preservation-of-prior-work.json).

[Matriz R01–R15/I01–I14](candidate-decision.json), con activación
**PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado, E/P/UX y requisitos
operativos/privacidad separados. Sin commits, push, despliegue ni activación.

[Recuperación y selección de evidencia](README.md). La aprobación técnica, si
corresponde, se limita al árbol y contrato fijo evaluados; no acredita capacidad
comercial, carga máxima, estabilidad de cola o fairness fuerte.
