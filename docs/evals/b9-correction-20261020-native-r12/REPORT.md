# B9 Windows nativo r12 — FAIL

**Decisión técnica: FAIL.** El gate bloqueante Gitleaks del historial devolvió exit 1 con 3156 detecciones generic-api-key; no se declaran 3156 credenciales reales confirmadas. Se conservan los PASS y los cinco perfiles quedan NOT_EXECUTED por la parada exigida.

El candidato es `f5f18d71847a46d66644775cd90d30268f072e3b`, sobre la base `194772677ca4e9fe1a1dec7f4dafa48396a6c583`.
La aceptación, si corresponde, mantiene la condición de evidencia enmendada aceptada
por el usuario: falta el monitor histórico de disco/reloj monotónico de r6. No se
inventan esas muestras ni los exits desconocidos de r6/r7. Esta aceptación compuesta
no declara una campaña continua. [Matriz R/I](candidate-decision.json).

Se conservan los **3331 IDs backend: 3319 PASS y 12 SKIP**, el build frontend PASS de
r9 y **355 PASS frontend**: 354 originales r9 y el caso corregido aprobado en r11.
En r12 se ejecutan cero casos frontend o backend y se conserva también smoke PASS
y lint ADVISORY_NONZERO. Ningún PASS anterior se repite. Las pruebas de los cinco perfiles
son las cargas originales pendientes, con sus umbrales y concurrencia intactos.
[Referencias completas](completed-reference-manifest.json) ·
[Procedencia](composite-evidence-provenance.json) · [Ejecuciones](execution-summary.json).

El intento r10 permanece **PENDING por selector**: ejecutó cero casos,
con 0 PASS, 0 fallos y 26 metadatos filtrados de duración 0 ms. Su comando
terminó con exit 0; el ensamblador rechazó correctamente la ausencia del caso
con exit 1 y el controlador terminó con exit 2. Esos recibos se conservan;
no acreditan un PASS frontend ni un fallo de las aserciones del producto.
La decisión r11 permite reparar únicamente el patrón del selector, con el mismo
árbol f5, fixture, ocho aserciones y timeout de 5000 ms. Exige comprobar una
coincidencia exacta antes del primer intento real pendiente y no repite PASS.
[Intento de cero casos](selector-attempt-history.json) ·
[Manifest de historia](selector-history-manifest.json) ·
[Decisión de reparación](selector-repair-decision.json).

El frontend original r9 conserva **354 PASS, un timeout y exit 1**, clasificado
PENDING_TIMEOUT; no se convierte en un PASS original. El comando referenciado de la tabla
para frontend-test es el ensamblador r11: su exit es del agregado, no de una corrida
completa de Vitest. El agregado conservado aprobó con 354 casos r9 y un
caso r11, 355 identidades distintas y cero omisiones; los 355 se referencian en r12. Los metadatos de
casos excluidos por el filtro no son skips de aceptación.
[Timeout conservado](frontend-original-timeout.json) ·
[Manifiesto frontend](referenced-prefix-evidence/r11/frontend-resumption-manifest.json) ·
[Caso aprobado r11](referenced-prefix-evidence/r11/blocks/frontend-test-remainder.command.json) ·
[Ensamblador r11](referenced-prefix-evidence/r11/blocks/frontend-test-assemble.command.json) ·
[Resultado lógico conservado](referenced-prefix-evidence/r11/blocks/frontend-tests.json).

El intento de seguridad r11 permanece **PENDING antes del scanner**. El guard
observó cambios solo en referencias internas de capturas Codex; HEAD y el árbol f5
no cambiaron. Su comando y controlador terminaron con exit 2, `scans=[]` y cero
invocaciones del scanner: no se le atribuyen hallazgos del producto ni un scan PASS.
La decisión r12 refresca exclusivamente la instantánea de historia y vuelve a
exigir los guards completos de HEAD/refs y los scans originales, auditorías y cinco
perfiles pendientes. Los recibos r11 permanecen intactos.
[Precheck conservado](security-precheck-history.json) ·
[Decisión](security-history-resumption-decision.json) ·
[Prefijo completo](completed-prefix-manifest.json).

La corrección adicional cambia solamente dos armados de texto del caso de
A→B→A en index.test.jsx: fireEvent.change invoca el onChange real para establecer
el mismo borrador completo. Conserva las ocho aserciones, navegación, clicks,
promesa tardía, IDs, imports y timeout de 5000 ms. Evita 62 pulsaciones ajenas al
objetivo de aislamiento causal del borrador. No cambia runtime productivo ni locks.
Los otros **3331 blobs** coinciden con el candidato r9.
[Autorización](frontend-resumption-authorization.json) ·
[Equivalencia](frontend-equivalence.json) · [Diff completo](correction.diff).

Los trece bloques históricos iniciales conservan su identidad anidada; los casos
backend r6/r7/r8 y el único caso corregido de r9 siguen en sus journals originales.
Los **tres FAIL backend históricos** permanecen visibles y sus correcciones tienen
PASS verificado dentro del backend completo r9. El exit original r8 sigue siendo 1;
r6/r7 siguen UNKNOWN. Los 12 SKIP identificados conservan sus motivos y no cubren
requisitos críticos. [Historial de fallos](historical-failed-attempts.json).
La nueva excepción frontend no vuelve a ejecutar las correcciones de reloj,
snapshots o baseline tenant ya aprobadas.

| Bloque | Estado | IDs | Exit | Alcance | Evidencia |
|---|---|---:|---:|---|---|
| directed | PASS | 87 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r4/blocks/directed.command.json) |
| django-check | PASS | — | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r4/blocks/django-check.command.json) |
| migration-drift | PASS | — | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r4/blocks/migration-drift.command.json) |
| migrate | PASS | — | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r4/blocks/migrate.command.json) |
| billing-schema | PASS | — | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r4/blocks/billing-schema.command.json) |
| b0 | PASS | 17 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r3/blocks/b0.command.json) |
| b3 | PASS | 42 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r3/blocks/b3.command.json) |
| b4 | PASS | 68 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r3/blocks/b4.command.json) |
| b5 | PASS | 37 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r3/blocks/b5.command.json) |
| full-b8b | PASS | 21 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r3/blocks/full-b8b.command.json) |
| full-b8c | PASS | 41 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261016-native-r3/blocks/full-b8c.command.json) |
| full-b8d | PASS | 27 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261017-native-r5/blocks/full-b8d.command.json) |
| full-b8e | PASS | 29 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/referenced-evidence/b9-correction-20261017-native-r5/blocks/full-b8e.command.json) |
| full-general | PASS | 3213 | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/blocks/full-general-assemble.command.json) |
| full | PASS | 3331 | — | evidencia referenciada | [recibo](referenced-completed-evidence/r9/blocks/full.results.json) |
| frontend-build | PASS | — | 0 | evidencia referenciada | [recibo](referenced-completed-evidence/r9/blocks/frontend-build.command.json) |
| frontend-test | PASS | 355 | 0 | evidencia referenciada | [recibo](referenced-prefix-evidence/r11/blocks/frontend-test-assemble.command.json) |
| frontend-lint | ADVISORY_NONZERO | — | 1 | evidencia referenciada | [recibo](referenced-prefix-evidence/r11/blocks/frontend-lint.command.json) |
| frontend-smoke-urls | PASS | — | 0 | evidencia referenciada | [recibo](referenced-prefix-evidence/r11/blocks/frontend-smoke-urls.command.json) |
| security | FAIL | — | 1 | ejecución actual | [recibo](blocks/security.command.json) |
| pip-audit | NOT_EXECUTED | — | — | sin ejecución | — |
| pnpm-audit | NOT_EXECUTED | — | — | sin ejecución | — |
| profile-base | NOT_EXECUTED | — | — | sin ejecución | — |
| profile-blocked_llm | NOT_EXECUTED | — | — | sin ejecución | — |
| profile-meta_slow | NOT_EXECUTED | — | — | sin ejecución | — |
| profile-duplicate | NOT_EXECUTED | — | — | sin ejecución | — |
| profile-saturation | NOT_EXECUTED | — | — | sin ejecución | — |

Los resultados del agregado no cuentan como ejecuciones adicionales. Los recibos
backend conservan sus candidatos originales y la cadena de equivalencias autorizadas;
su aceptación actual no los presenta como ejecuciones nuevas. Los monitores de los
ensambladores acreditan solo esos comandos. Los nuevos comandos conservan los guards
de 2 GiB RAM, 1 GiB disco y desviación máxima de reloj de 1 s.
[Monitores](monitor-summary.json) · [Integridad](integrity-summary.json).

Los cinco perfiles deben aprobar completos; no se transfieren métricas históricas.
El índice conserva denominadores, faltantes, percentiles, máximos, estados durables y
gates por variante. No se promedian percentiles entre organizaciones. Un campo ausente
no significa cero faltantes. [Recibos PROFILE](profile-results-index.json).

| Variante | Frontera | Muestras | Faltantes | p95 s | Máximo s |
|---|---|---:|---:|---:|---:|
| base | healthy_claim | — | — | — | — |
| base | safety_dispatch | — | — | — | — |
| base | outbox_dispatch | — | — | — | — |
| blocked_llm | healthy_claim | — | — | — | — |
| blocked_llm | safety_dispatch | — | — | — | — |
| blocked_llm | outbox_dispatch | — | — | — | — |
| meta_slow | healthy_claim | — | — | — | — |
| meta_slow | safety_dispatch | — | — | — | — |
| meta_slow | outbox_dispatch | — | — | — | — |
| duplicate | healthy_claim | — | — | — | — |
| duplicate | safety_dispatch | — | — | — | — |
| duplicate | outbox_dispatch | — | — | — | — |
| saturation | healthy_claim | — | — | — | — |
| saturation | safety_dispatch | — | — | — | — |
| saturation | outbox_dispatch | — | — | — | — |

Cleanup del runtime privado y cierre de los auxiliares actuales: PASS. La restauración
API corresponde a los auxiliares actuales; no se atribuye a procesos históricos
terminados por reinicio. No se cambió la configuración del reloj del host ni políticas
globales de energía. Se verificaron 9710 archivos históricos y los cambios ajenos.
[Cierre nativo](native-closure.json) · [Preservación](preservation-of-prior-work.json).

Activación **PENDING_ACTIVATION_REQUIREMENTS**, R1-04 PENDING aceptado, E/P/UX y
operación/privacidad separados. Sin commits, push, despliegue ni activación. El PASS
técnico bajo esta condición no acredita capacidad comercial ni fairness fuerte.
[Recuperación](README.md).

## Triaje del gate de seguridad

Gitleaks reportó 3156 ocurrencias de generic-api-key en 221 rutas y 16 commits con hallazgos. El triaje verificó 2606 coincidencias como contextos de SHA256 de archivos fuente; las 550 restantes siguen sin clasificar como credenciales reales o falsos positivos. No son 3156 credenciales únicas ni se afirma una fuga confirmada. La configuración del candidato no se cambió y el gate conserva FAIL. El scan de la corrección, las auditorías y los cinco perfiles permanecen NOT_EXECUTED por la regla de parada.

[Triaje detallado](diagnostics/security-finding-triage.md) · [Conteos y comprobación histórica](diagnostics/security-finding-triage.json) · [Clasificación del gate](security-classification.json).
