# Reproducción de aceptación B7B

Usar PostgreSQL real aislado, Python/venv del backend y variables locales de
prueba: DATABASE_URL apuntando a esa instancia, SECRET_KEY de prueba,
DISABLE_SENTRY=True, OPENAI_API_KEY y webhooks externos vacíos. No ejecutar
contra producción. No requiere cuenta Meta ni llamadas LLM.

Desde backend, con RTK según AGENTS.md:

```powershell
rtk proxy ..\venv\Scripts\python.exe manage.py check
rtk proxy ..\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
rtk proxy ..\venv\Scripts\python.exe manage.py test apps.agent.tests.test_operation_consent apps.agent.tests.test_b7b_corpus apps.agent.tests.test_b7b_processes apps.agent.tests.test_b7b_migration --testrunner apps.agent.tests.b7b_runner.CriticalB7BRunner --keepdb --noinput --verbosity 2
```

Para resultado JSON, establecer B7B_RESULTS_PATH antes de ejecutar el runner.
El inventario completo B0–B7A es `runs.b7a_combined_final.modules` de
[b7a-acceptance-results.json](b7a-acceptance-results.json). Pasar exactamente
esas claves como labels a `manage.py test` y usar
`apps.agent.tests.harness.CriticalB7ARunner`, parallel=1. El runner exige los
1022 IDs previos; no equivale a limitarse a los módulos nuevos. No compartir
la misma test DB entre coordinadores concurrentes.

Los casos multiproceso lanzan intérpretes independientes, no simulan sus
transacciones con mocks. El padre espera barreras observables; un kill provoca
rollback o recovery según si hubo commit. El proveedor Meta sí es simulado.
La suite de migración baja a B7A y vuelve al esquema final exclusivamente en
su test DB. Restaurar latest forma parte del cleanup.

| Requisitos | Casos/invariantes que los comprueban |
| --- | --- |
| EMIT-01..10 | test_emit_01..09, pendiente sin admisión, sender tras corrección, proveedor duplicado y webhook firmado |
| CAUSAL-01..10 | test_causal_01..10, respuesta concurrente HTTP, receipt inmutable, scope ajeno y proceso de respuestas incompatibles |
| CONSENT-01..10 | Corpus completo, rechazo sin negocio, correction/conditional antes de aceptar, parser exacto y worker sin LLM |
| MODE-01..05 | test_mode_01_to_05_contextual_declaration_never_authorizes, matriz B7A y writer privado; no propuesta ni AUTHORIZED contextual |
| REV-01..08 | test_rev_01..08, referencias antiguas y baseline B7A de replacement/permission; evidencia no transferida |
| INT-01..08 | tests int_01/02/05/08, ownership, corrección resuelta/no resuelta al flush, writer privado, UNCERTAIN y legacy |
| FI-01..10 | test_b7b_processes, 13 escenarios de procesos con las dos carreras inversas y respuestas diferentes |
| Corpus | test_b7b_corpus, 44 casos parametrizados desde JSON versionado |
| Inspectabilidad | test_inspector_distinguishes_consent_from_execution y observabilidad sin labels de alta cardinalidad |
| Esquema | test_no_synthetic_legacy_consent_or_emission, trigger de receipt, constraints y makemigrations --check |

Algunos requisitos comparten caso y otros tienen subtests. El JSON publica los
IDs reales para no contar un subtest como test backend adicional. Las 44
conversaciones del corpus tampoco se suman dos veces al total B7B.

La última modificación del fixture de ráfaga se comprueba además con rerun
de sus dos casos: ambos asserts exigen dos miembros reales de TurnContext.
Los resultados finales distinguen esa verificación de la ejecución completa
posterior, que vuelve a comprobar todo B7B con el fixture corregido.

Después se añadió el bloqueo de snapshot antiguo de cita. Su caso RED quedó
verde y se repitieron los 55 tests de contrato/integración. La evidencia final
es la unión de 1022 baseline y 113 B7B únicos; no se presenta como una única
invocación. El JSON conserva los inventarios de cada ejecución y sus hashes.

Resultados efectivos: [aceptación JSON](b7b-acceptance-results.json).
Interpretación y limitaciones: [acta](../implementacion-b7b-agente-whatsapp-2026-09-20md).
