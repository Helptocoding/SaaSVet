# Evidencia saneada y reproducibilidad

**Destino:** clúster PostgreSQL local dedicado 18.3, loopback `127.0.0.1:55483`; nombres `orden2_iso_20261028`, `orden2_iso_20261028_fresh` y `orden2_iso_20261028_final` (UTF8), `orden2_iso_20261028_test` (WIN1252, creado por Django desde plantilla local). La ruta real del clúster se mantiene fuera del workspace y se verifica por el wrapper; ninguna conexión heredada de `.env` se usa. No se adjuntan logs, dumps, IDs de fixtures, claves, PII del operador ni conexiones de proveedores. Runtime seleccionado: Python global **3.13.2**, Django **6.0.5**, psycopg **3.3.4** (versiones verificadas, coincidentes con pins consultados). No se instaló ni actualizó global/venv habitual; frontend Node 22.14.0 y pnpm 11.1.1 existentes. El wrapper limpia variables heredadas, reemplaza el repositorio de decouple por uno vacío, usa email locmem y deja Sentry/Meta/LLM/deadman apagados.

## Gates y resultados

Todos los comandos Django pasan primero por `scripts/orden2_isolated.py`: conexión al nombre/host/puerto/usuario explícitos; comparación de `data_directory` con clúster de prueba y encoding; allowlist de comandos, DB y `test` distintos. En otro equipo se debe adaptar **solo** el wrapper a un clúster descartable nuevo antes de ejecutar: no utilizarlo con la base habitual.

| Comando (desde `backend/`, precedido por `rtk proxy`) | Resultado |
|---|---|
| `python scripts/orden2_isolated.py check` | PASS, 0 issues |
| `python scripts/orden2_isolated.py makemigrations --check --dry-run` | PASS, no changes detected |
| `python scripts/orden2_isolated.py --isolated-fresh-db migrate --noinput` | PASS, desde cero; una invocación alcanzó timeout al final y la siguiente completó las migraciones restantes sin `--fake` |
| `python scripts/orden2_isolated.py --isolated-final-db migrate --noinput` | PASS, desde cero en UTF8 tras agregar la dependencia `users.0007` al backfill vet y `billing.0042` (UUID de auditoría NOT NULL) |
| `python scripts/orden2_isolated.py test apps.platform.tests.test_order2_migrations --keepdb --noinput --verbosity 0` | PASS, 1 test PostgreSQL: upgrade con Owner/Pet, MR, Rx, Checkout, Invoice, auditoría y Payment sintéticos; anchors/identidades preservados y backfill repetido no sobrescribe |
| `python scripts/orden2_isolated.py --isolated-test-db migrate billing 0040 --noinput` seguido de `--isolated-test-db migrate --noinput` | PASS, reversión/reaplicación segura de `billing.0041` antes de separaciones físicas |
| `python scripts/orden2_isolated.py test apps.billing.tests --keepdb --noinput --verbosity 0` | PASS, 71 tests, esquema Billing incluido |
| `python scripts/orden2_isolated.py test apps.medical_records.tests apps.patients.tests apps.prescriptions.tests --keepdb --noinput --verbosity 0` | PASS, 231 tests PostgreSQL en 456.510 s, tras adaptar criterios DELETE cotidianos al archivo y conservar guard físico de evidencia |
| `python scripts/orden2_isolated.py test apps.appointments.tests apps.inventory.tests apps.organizations.tests --keepdb --noinput --verbosity 0` | PASS, 224 tests PostgreSQL en 799.887 s; auditoría de solapes emite resultados sintéticos esperados dentro de los tests, resultado final OK |
| `python scripts/orden2_isolated.py test apps.platform.tests.test_physical_deletion --keepdb --noinput --verbosity 0` | PASS final, 12 tests: historia positiva, saldo/ledger/PDF, confirmación, replay, carreras, autorización, stale preview, genérico/procedencia de importación, rollback de auditoría |
| `python scripts/orden2_isolated.py test apps.medical_records.tests.test_order2_close_atomicity --keepdb --noinput --verbosity 0` | PASS, 2 tests con PostgreSQL: cierre concurrente y fallo intermedio íntegramente revertido |
| tests dirigidos de `medical_records.tests.test_close`, `patients.tests.test_order2_archive`, `agent.tests.test_b4_sender`, `agent.tests.test_b3_durable` | PASS después de correcciones; carrera archivo/cita y sender sin proveedor verificados |
| `python scripts/orden2_isolated.py test apps.imports.tests.test_owner_pet_import.ImportApiTests.test_commit_creates_owner_and_pet_with_legacy apps.imports.tests.test_owner_phone_ambiguity --keepdb --noinput --verbosity 0` | PASS, 8 pruebas de commit con locks de Organization/Owner; la corrida completa del importador agotó el timeout sin resumen y no se marca PASS |
| `python scripts/orden2_isolated.py test apps.imports.tests.test_owner_pet_import.ImportApiTests.test_commit_does_not_create_subjects_after_organization_deactivation --keepdb --noinput --verbosity 0` | PASS, 1 test adicional: commit con clínica desactivada devuelve 400 sin crear Owner/Pet |
| `python scripts/orden2_isolated.py test apps.patients.tests.test_order2_archive.ArchiveContractTests.test_disabled_org_denies_existing_access_and_refresh_then_reactivation_keeps_staff_state --keepdb --noinput --verbosity 0` | PASS: acceso JWT previo, refresh, sesión Django, reactivación sin reactivar staff |
| `audit_billing_schema --json`, `audit_anchor_integrity --json`, `audit_payment_ledger_integrity --json`, `audit_stock_integrity --json` con mismo wrapper | PASS: 0 violaciones en base de migraciones; esa base no contenía fixtures financieros, por lo que no es prueba de ledger poblado. Fixtures positivas se verifican en tests independientes |
| `pnpm exec vitest run src/pages/pets.test.jsx` | PASS, 9 tests |
| `pnpm exec eslint src/pages/pets.jsx src/pages/pets.test.jsx src/api/pets.js` | PASS |
| `pnpm build` | PASS (warning de tamaño de chunk ya existente) |
| `rtk git diff --check`, `python -m compileall -q ...` | PASS |

Intentos de regresión ampliada de múltiples apps e importador terminaron por **timeout del comando (600/420/240 s)** sin resumen final; no se registran como PASS ni como fallos atribuidos. El clúster desechable dejó de responder posteriormente y se reinició exclusivamente ese proceso para las pruebas aisladas siguientes. No hay skips, expectedFailure, SQLite, mocks de transacciones o datos de base habitual en las pruebas de invariantes; los mocks de fallo de auditoría/Checkout provocan rollback en PostgreSQL real.

**Cambio concurrente de árbol durante la sesión:** al último `git status` aparecieron cambios ajenos a este orden en configuración (`.env.prod.example`, `backend/config/settings.py`, `infra/Caddyfile`), throttling, `backend/apps/imports/views.py` y pruebas nuevas de otros dominios. No se editaron, eliminaron ni se atribuyen a esta entrega; la ejecución final de `check`/drift observó el árbol tal como estaba en ese instante. El estado inicial solo tenía documentación del usuario sin seguimiento, conservada.
