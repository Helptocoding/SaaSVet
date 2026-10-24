# B9: aceptación del árbol corregido, campaña Windows nativa r2 — PENDING

**Decisión técnica: PENDING.** La reserva de disco C: cayo por debajo de 1 GiB durante B5. El controlador detuvo su arbol propio; B5 conserva 34/37 PASS parciales sin FAIL/ERROR registrados, ocho gates previos PASS y el resto NOT_EXECUTED. La aceptacion integral sigue pendiente por interrupcion ambiental; no se acredita un fallo de producto ni OOM.

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

Verificación enfocada de la campaña anterior, sin repetición actual:
**155 PASS, 0 fallos, 0 errores y 1 skips identificados, de 156 IDs**. Esta referencia no sustituye los recibos actuales
ni se transfiere a sus gates integrales.
[Referencia conservada](prior-focused-verification.json).

Los resultados actuales de los casos corregidos son los registrados por ID
en esta campaña. No hay recibos por ID de full en esta campaña; no se infiere que hubo cero skips.

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
| b5 | PENDING_ENVIRONMENT_INTERRUPTION | 34/37 parciales | 1 |
| full-b8b | NOT_EXECUTED | — | — |
| full-b8c | NOT_EXECUTED | — | — |
| full-b8d | NOT_EXECUTED | — | — |
| full-b8e | NOT_EXECUTED | — | — |
| full-general | NOT_EXECUTED | — | — |
| full | NOT_EXECUTED | — | — |
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

No hay recibos PROFILE completos en esta campaña.
Estados actuales: base: NOT_EXECUTED, blocked_llm: NOT_EXECUTED, meta_slow: NOT_EXECUTED, duplicate: NOT_EXECUTED, saturation: NOT_EXECUTED. El [índice de cobertura temporal](profile-results-index.json)
conserva las variantes sin recibo; no se transfieren métricas históricas.

## Orquestación de la suite completa

La campaña prepara cinco grupos nativos consecutivos del mismo inventario: full-b8b: 21 IDs en `test_b8b_b9i_full`, full-b8c: 41 IDs en `test_b8c_b9i_full`, full-b8d: 27 IDs en `test_b8d_b9i_full`, full-b8e: 29 IDs en `test_b8e_b9i_full`, full-general: 3213 IDs en `test_b9i_full_general`. La selección y los prefijos de los workers se comprueban antes de ejecutar; las comprobaciones y la concurrencia interna de las pruebas se conservan. El bloque lógico full queda **NOT_EXECUTED** y solo aprueba con los cinco grupos y su agregado completos. [Partición](full-partition.json).

No se generaron journals de ejecución de full en este intento. Un grupo incompleto deja los bloques posteriores
NOT_EXECUTED conforme a la parada de campaña.

## Conservación y cierre

Fuentes del árbol, dependencias y evaluador: **PASS en todas las comparaciones registradas**.
Los monitores disponibles contienen muestras de 9 comandos. El mínimo Windows registrado en ellos fue 3.900 GiB; las incidencias se conservan por comando.
Los [monitores por bloque](monitor-summary.json) conservan mínimos
de recursos y desviación de reloj. No se rebajaron las reservas autorizadas de
2 GiB de RAM, 1 GiB de disco ni el guard de reloj de 1 s.

Cleanup nativo, cierre del observador y liberación de la solicitud propia de
actividad: **PASS**. [Cierre nativo](native-closure.json) acredita que no se
cambió la configuración del reloj del host. W32Time y políticas globales de
energía/pantalla intactos. Se verificaron **3469 archivos históricos** y
los tres cambios ajenos sin diferencias. [Preservación](preservation-of-prior-work.json).

[Matriz R01–R15/I01–I14](candidate-decision.json), con activación
**PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado, E/P/UX y requisitos
operativos/privacidad separados. Sin commits, push, despliegue ni activación.

[Recuperación y selección de evidencia](README.md). La aprobación técnica, si
corresponde, se limita al árbol y contrato fijo evaluados; no acredita capacidad
comercial, carga máxima, estabilidad de cola o fairness fuerte.
