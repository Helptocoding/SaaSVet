# B9: aceptación compuesta del árbol corregido, Windows nativo r5 — PENDING

**Decisión técnica compuesta: PENDING.** Se conservan 13 gates completos PASS: 11 referenciados y full-b8d/full-b8e nuevos (27/27 y 29/29). Full-general queda incompleto: 2639/3213 IDs, 2636 PASS, 2 SKIP y 1 ERROR por fixture dependiente de la hora en test_upcoming_window, anterior a la interrupción. La parada formal corresponde a heartbeat de vigilia inválido tras una brecha de unas 3 horas; los eventos System documentan suspensión/reanudación. No se establece fallo del producto ni escasez de RAM/disco como causa. La corrección propuesta del fixture no se aplicó al candidato sellado; los bloques pendientes necesitan ejecución válida. [Diagnóstico conjunto](diagnostics/fixture-and-awake-observation.json).

Este cierre reúne evidencia de varias ejecuciones del mismo candidato; **no es
una corrida continua**. La reanudación por bloques fue autorizada por el usuario.
Se conservan 11 bloques completos en PASS mediante referencias
verificadas a sus recibos originales, sin volver a ejecutarlos. Los bloques
pendientes se ejecutan completos con sus pruebas, aserciones, cargas y umbrales.
[Manifiesto de reutilización](reuse-manifest.json) ·
[Procedencia verificada](composite-evidence-provenance.json).

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

Los resultados aceptados de los casos corregidos son los registrados por ID
en los recibos originales identificados y en los nuevos. Los recibos aceptados de full, referenciados y nuevos, contienen 2 skips observados; sus IDs y motivos figuran en [block-status.json](block-status.json). Si full está incompleto, este conteo es parcial. Un skip no cubre un requisito pendiente.

## Bloques y procedencia

| Bloque | Estado | IDs | Exit | Evidencia | Origen |
|---|---|---:|---:|---|---|
| directed | PASS | 87 | 0 | PASS referenciado | [b9-correction-20261016-native-r4](referenced-evidence/b9-correction-20261016-native-r4/blocks/directed.command.json) |
| django-check | PASS | — | 0 | PASS referenciado | [b9-correction-20261016-native-r4](referenced-evidence/b9-correction-20261016-native-r4/blocks/django-check.command.json) |
| migration-drift | PASS | — | 0 | PASS referenciado | [b9-correction-20261016-native-r4](referenced-evidence/b9-correction-20261016-native-r4/blocks/migration-drift.command.json) |
| migrate | PASS | — | 0 | PASS referenciado | [b9-correction-20261016-native-r4](referenced-evidence/b9-correction-20261016-native-r4/blocks/migrate.command.json) |
| billing-schema | PASS | — | 0 | PASS referenciado | [b9-correction-20261016-native-r4](referenced-evidence/b9-correction-20261016-native-r4/blocks/billing-schema.command.json) |
| b0 | PASS | 17 | 0 | PASS referenciado | [b9-correction-20261016-native-r3](referenced-evidence/b9-correction-20261016-native-r3/blocks/b0.command.json) |
| b3 | PASS | 42 | 0 | PASS referenciado | [b9-correction-20261016-native-r3](referenced-evidence/b9-correction-20261016-native-r3/blocks/b3.command.json) |
| b4 | PASS | 68 | 0 | PASS referenciado | [b9-correction-20261016-native-r3](referenced-evidence/b9-correction-20261016-native-r3/blocks/b4.command.json) |
| b5 | PASS | 37 | 0 | PASS referenciado | [b9-correction-20261016-native-r3](referenced-evidence/b9-correction-20261016-native-r3/blocks/b5.command.json) |
| full-b8b | PASS | 21 | 0 | PASS referenciado | [b9-correction-20261016-native-r3](referenced-evidence/b9-correction-20261016-native-r3/blocks/full-b8b.command.json) |
| full-b8c | PASS | 41 | 0 | PASS referenciado | [b9-correction-20261016-native-r3](referenced-evidence/b9-correction-20261016-native-r3/blocks/full-b8c.command.json) |
| full-b8d | PASS | 27 | 0 | Nueva ejecución | [b9-correction-20261017-native-r5](blocks/full-b8d.command.json) |
| full-b8e | PASS | 29 | 0 | Nueva ejecución | [b9-correction-20261017-native-r5](blocks/full-b8e.command.json) |
| full-general | PENDING_ENVIRONMENT_INTERRUPTION | 2639/3213 parciales | 1 | Nueva ejecución | [b9-correction-20261017-native-r5](blocks/full-general.command.json) |
| full | INCOMPLETE | 2757/3331 parciales | — | Agregado compuesto | b9-correction-20261017-native-r5 |
| frontend-build | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| frontend-test | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| frontend-lint | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| frontend-smoke-urls | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| security | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| pip-audit | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| pnpm-audit | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| profile-base | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| profile-blocked_llm | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| profile-meta_slow | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| profile-duplicate | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |
| profile-saturation | NOT_EXECUTED | — | — | Sin ejecución nueva | b9-correction-20261017-native-r5 |

Los recibos referenciados se conservan byte por byte bajo `referenced-evidence/`,
con ruta original y SHA-256 en el manifiesto; son copias de preservación
identificadas, sin presentarlas como ejecuciones de esta reanudación.
La equivalencia de reutilización cubre el backend, Python y PostgreSQL.
Los gates del frontend requieren ejecuciones nuevas, según los estados de la
tabla; no se afirma identidad total de sus metadatos pnpm entre instalaciones.

Cada bloque pendiente/variante formal se ejecutó como máximo una vez en esta
reanudación. Se distinguen 56 observaciones backend
nuevas completas y 313 referenciadas. Los solapes
entre corpus, runners y full están deduplicados en
[execution-summary.json](execution-summary.json), que separa IDs nuevos y evidencia
compuesta aceptada. El agregado full es metadato; no añade ejecuciones ni IDs.
Los skips/advisories conservan su aplicabilidad; no cubren requisitos críticos.
La orquestación local usa suites secuenciales, preservando los procesos internos
de los tests. No se afirma ejecución de CI remoto.

Los journals incompletos y sus IDs faltantes figuran en el resumen. Sus
observaciones no sustituyen un recibo completo ni acreditan un gate aprobado.

No hay recibos PROFILE completos en esta campaña.
Estados actuales: base: NOT_EXECUTED, blocked_llm: NOT_EXECUTED, meta_slow: NOT_EXECUTED, duplicate: NOT_EXECUTED, saturation: NOT_EXECUTED. El [índice de cobertura temporal](profile-results-index.json)
conserva las variantes sin recibo; no se transfieren métricas históricas.

## Orquestación de la suite completa

La partición conserva cinco grupos nativos del mismo inventario: full-b8b: 21 IDs en `test_b8b_b9i_full`, full-b8c: 41 IDs en `test_b8c_b9i_full`, full-b8d: 27 IDs en `test_b8d_b9i_full`, full-b8e: 29 IDs en `test_b8e_b9i_full`, full-general: 3213 IDs en `test_b9i_full_general`. Se referencian los grupos completos aprobados y se ejecutan completos los pendientes. La selección y los prefijos de los workers se comprueban antes de ejecutar; las comprobaciones y la concurrencia interna de las pruebas se conservan. El bloque lógico full queda **INCOMPLETE** y solo aprueba con los cinco grupos y su agregado completos, 3331 IDs sin duplicados ni omisiones. [Partición](full-partition.json).

Los journals presentes de grupos conservan las ejecuciones originales. El agregado full reúne sus recibos; no ejecuta pruebas adicionales ni se cuenta de nuevo en los totales backend. Un grupo nuevo incompleto deja los bloques pendientes
posteriores NOT_EXECUTED conforme a la parada de esta reanudación; conserva
la evidencia original completa de los bloques referenciados.

## Conservación y cierre

Fuentes del árbol, dependencias y evaluador de esta reanudación:
**PASS en todas las comparaciones registradas**. La evidencia reutilizada se valida contra su
manifiesto, fuentes originales y equivalencia de backend antes del reporte.
Los monitores disponibles contienen muestras de 14 comandos originales y nuevos; su procedencia se identifica por bloque. El mínimo Windows registrado en ellos fue 4.007 GiB; las incidencias se conservan por comando.
Los [monitores por bloque](monitor-summary.json) conservan mínimos
de recursos y desviación de reloj. No se rebajaron las reservas autorizadas de
2 GiB de RAM, 1 GiB de disco ni el guard de reloj de 1 s.

Cleanup nativo, cierre del observador y liberación de la solicitud propia de
actividad: **PASS**. [Cierre nativo](native-closure.json) acredita que no se
cambió la configuración del reloj del host. W32Time y políticas globales de
energía/pantalla intactos. Se verificaron **4359 archivos históricos** y
los tres cambios ajenos sin diferencias. [Preservación](preservation-of-prior-work.json).

[Matriz R01–R15/I01–I14](candidate-decision.json), con activación
**PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado, E/P/UX y requisitos
operativos/privacidad separados. Sin commits, push, despliegue ni activación.

[Recuperación y selección de evidencia](README.md). La aprobación técnica, si
corresponde, se limita al árbol y contrato fijo evaluados; no acredita capacidad
comercial, carga máxima, estabilidad de cola o fairness fuerte.
