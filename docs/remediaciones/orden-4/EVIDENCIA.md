# Evidencia de avance

Revisión inicial `8886604`; checkout con cambios previos extensos. Grafo MCP no expuesto en esta sesión; se consultaron fuentes actuales. No se leyeron registros reales ni credenciales. `rtk --version`: 0.48.0; `rtk gain` disponible.

Desde `frontend`:

* `rtk proxy pnpm test src/utils/inventory.test.js`: 35 pruebas pasan, incluyendo sombra divergente, direcciones, cero, ausencia y empates.
* `rtk proxy pnpm exec eslint src/utils/inventory.js src/utils/inventory.test.js`: pasa.
* `rtk proxy pnpm exec eslint src/utils/inventory.js src/utils/inventory.test.js src/pages/inventory.jsx`: falla con cinco errores existentes de la pantalla (dos variables sin usar, declaración posterior y dos efectos con setState).
* `rtk proxy pnpm build`: pasa, con advertencia de tamaño de chunk.

No se realizó comprobación visual. `postgres` y `pg_ctl` no aparecen en PATH; no se estableció un destino PostgreSQL aislado de orden 4. Existe un runner de orden 2 restringido a su propio cluster, que no se usó como destino alternativo. No hay evidencia de migraciones fresh/upgrade, locks reales ni suites backend para esta entrega.

## Continuación 31-10

Grafo MCP no expuesto; consulta directa del código actual. PostgreSQL 18.3 localizado por ruta absoluta. Se creó cluster propio `Temp/opencode/orden4_pg18_20261031`, distinto del de orden 2, loopback `127.0.0.1:49935`, usuario y base exclusivos. `backend/scripts/orden4_isolated.py` limpia el entorno, desactiva integraciones y verifica nombre de base administrativa, puerto, listen y directorio efectivo antes de comandos. Una primera verificación inline falló por `ParserError` de quoting PowerShell; el runner verificó el destino y creó la base sintética. No se utilizó la base habitual.

Desde `backend`, prefijo `rtk proxy python scripts/orden4_isolated.py`:

* `check`: PASS.
* `migrate --noinput`: la primera ejecución llegó a 0028 y excedió 240 s; la segunda completó 0029 y las restantes. Fresh sobre base aislada, no prueba upgrade con datos históricos.
* `makemigrations --check --dry-run`: PASS, sin drift.
* `test apps.imports.tests.test_import_commit_concurrency apps.imports.tests.test_parser_streaming_caps --keepdb --noinput`: 20 PASS en PostgreSQL.
* Tests dirigidos demo, no ADMIN, cross-tenant y `apps.users.tests.test_demo_restrictions`: 9 PASS. La ejecución previa de toda la suite inventory import excedió 240 s y no acredita resultado global.
* Gate `InventoryImportApiTests.test_stock_parity_manual_vs_import`: PASS. Dos tests adicionales de factores 1/3/12/0.125/1.2345, cero, lotes y fallo inyectado: PASS; el error sintético esperado se registra como 500 y rollback pasa.
* `apps.inventory.tests.test_order4_alias`: 5 PASS, incluyendo backfill repetido e invariantes básicas de producto/presentación/ledger. No incluye snapshots documentales ni upgrade con datos preexistentes.
* `apps.inventory.tests.test_order4_diagnostics`: 2 PASS; no prueba todos los casos requeridos.
* Frontend `rtk proxy pnpm test src/utils/inventory.test.js`: 35 PASS. Sin comprobación visual o integración de página.

Al finalizar se comprobó mediante `pg_ctl status` que el proceso propio usaba ese directorio y puerto, y se detuvo con `pg_ctl -D <directorio orden4> -m fast -w stop`; no se borró el directorio. Para repetir, arrancar explícitamente ese cluster en loopback y usar el runner de orden 4; verificar antes que el puerto esté libre y siga siendo el destino propio.

## Continuación r2

El grafo MCP sigue sin exponerse; fuentes actuales consultadas directamente. `pg_ctl status` confirmó que el cluster exclusivo estaba detenido y un bind loopback confirmó libre 49935 antes de arrancar el mismo directorio; el runner verificó el destino efectivo. No se conectó a otros clusters.

* `test apps.inventory.tests.test_order4_diagnostics --keepdb --noinput`: 3 PASS en PostgreSQL, incluido borrado sintético real de lote con FK SET_NULL y snapshot preservado, sin cambios de dominio por el diagnóstico.
* `test apps.imports.tests.test_order4_conflicts apps.imports.tests.test_import_commit_concurrency --keepdb --noinput`: 7 PASS en PostgreSQL, con 0/100/101/2000, cursor, publicación fallida, legacy incompleto, aislamiento tenant y catálogo alterado. La primera ejecución de los tres tests nuevos falló en setup por crear dos veces un rol; corregido con `get_or_create` antes de repetir.
* `test apps.imports.tests.test_owner_pet_import apps.imports.tests.test_inventory_import apps.inventory.tests.test_order4_alias apps.inventory.tests.test_stock_reception --keepdb --noinput`: 89 PASS; incluye prueba del admin y gate manual/import. No acredita upgrade histórico con snapshots ni reintentos remotos del wizard.
* `makemigrations --check --dry-run`: PASS tras añadir imports 0003.
* Frontend: `pnpm test src/pages/imports/PreviewStep.test.jsx src/pages/imports/ResultStep.test.jsx` 43 PASS; `pnpm test src/pages/imports/ConflictPages.test.jsx` 1 PASS; lint dirigido a nuevo componente/API PASS; `pnpm build` PASS con advertencia de chunk. Sin comprobación visual.
* `test apps.inventory.tests.test_order4_upgrade --keepdb --noinput`: 1 PASS en PostgreSQL con `MigrationExecutor` desde inventory 0027 y snapshots clínico/financiero sintéticos; conserva factor, saldo, mínimo y sombra, y repite backfill. Cuatro intentos iniciales fallaron al construir fixtures por guards de orden 2 (`missing_subject_snapshot`, `invoice_requires_checkout_and_customer`, `missing_subject_snapshot`, `invoice_posted_at_required`); corregidos aportando snapshots/checkout/fecha, sin desactivar constraints. Aún falta probar factores inválidos y todas las invariantes.
* Frontend `pnpm test src/pages/inventory.order.test.jsx`: 1 PASS; interacción con cabeceras de stock y valor en ambos sentidos con valores mostrados 120 y 300.
* Lint de todos los archivos frontend tocados: falla en `PreviewStep.jsx` por tres errores y dos advertencias en secciones existentes (líneas 106, 116, 244, 281 y 285); lint separado de `ConflictPages.jsx` y API pasa. No se atribuye PASS global.
* Prueba aislada `ConflictReportTests.test_unauthenticated_cannot_read_report`: PASS; check Django y lint de los archivos frontend nuevos/API pasan tras los cambios.
* `pg_ctl status` confirmó PID propio, directorio orden4 y puerto 49935; `pg_ctl -D <directorio orden4> -m fast -w stop` detuvo ese proceso. Directorio conservado.

## Continuación posterior

Se comprobó status detenido y bind libre de 49935 antes de reiniciar el mismo cluster; runner verificó el directorio efectivo.

* `test apps.imports.tests.test_order4_report_rollback --keepdb --noinput`: 2 PASS en PostgreSQL. Un rollback real de migraciones restituyó 201 detalles; otra prueba conservó el indicador legacy incompleto y detuvo inconsistencias.
* `test apps.imports.tests.test_order4_conflicts.ConflictReportTests.test_commit_checks_blocking_after_reloading_locked_job apps.imports.tests.test_import_commit_concurrency --keepdb --noinput`: 3 PASS.
* `test apps.imports.tests.test_order4_report_concurrency --keepdb --noinput`: 1 PASS, lectura con versión anterior durante reemplazo devuelve 409.
* `test apps.inventory.tests.test_order4_diagnostics --keepdb --noinput`: 6 PASS, incluyendo referencia incompleta, unidades legacy, desbalance de lotes y cambio de watermark.
* `test apps.imports.tests.test_order4_conflicts.ConflictReportTests.test_disabled_organization_jwt_cannot_read_report --keepdb --noinput`: PASS con JWT y organización sintética desactivada.
* `test apps.imports.tests.test_inventory_import.InventoryImportApiTests.test_new_presentation_stock_uses_ledger_and_patch_cannot_assign_stock apps.inventory.tests.test_stock_reception apps.inventory.tests.test_order4_alias --keepdb --noinput`: 16 PASS en PostgreSQL.
* Tests `test_new_presentation_stock_uses_ledger_and_patch_cannot_assign_stock` y `test_new_lot_tracked_presentation_rejects_unidentified_stock`: 2 PASS tras incluir caso de lotes.
* Tests `test_unauthenticated_cannot_read_report` y `test_disabled_organization_jwt_cannot_read_report`: 2 PASS; cada uno comprueba tanto lectura como POST directo de importación.
* `test_cursor_from_another_job_is_rejected`: PASS con versión sintética igual y cursor de otro job.
* Frontend: 36 PASS para helper/tabla de inventario y 44 PASS para preview/resultado/páginas de conflictos. Build PASS con advertencia de chunk; `makemigrations --check --dry-run` PASS.
* El wizard ahora comunica un resultado de recepción no confirmado y pide revisar movimientos/lotes antes de otra entrada; esto no acredita idempotencia del endpoint de recepción ante una respuesta perdida.
* `apps.inventory.tests.test_order4_alias`: 7 PASS, incluyendo preflight simulado con factores inválidos que detiene antes de actualizar; el caso inválido es mock, no un upgrade PostgreSQL con constraint eludida.
* `pg_ctl status` identificó PID 35504 y directorio/puerto propios; `pg_ctl -D <directorio orden4> -m fast -w stop` detuvo el servidor, sin borrar directorios.

## Continuación 01-11

Grafo MCP no disponible; fuentes locales contrastadas. Cluster exclusivo detenido, puerto 49935 libre antes de reiniciarlo; runner verificó directorio/puerto efectivos y entorno sintético.

* `test apps.imports.tests.test_order4_report_rollback --keepdb --noinput`: 2 PASS en PostgreSQL. `MigrationExecutor` publicó 201 detalles, bajó a 0002, subió a hojas actuales y recorrió API con versión nueva y cinco páginas; también preservó `complete=false` en legacy incompleto.
* `test apps.inventory.tests.test_stock_reception.ReceptionIdempotencyTests --keepdb --noinput`: 3 PASS para replay, payload incompatible, identidad distinta con misma compra, actor/tenant y fallo previo al commit. `test_order4_reception_concurrency`: 1 PASS en dos conexiones PostgreSQL, un movimiento y un saldo.
* `test apps.inventory.tests.test_order4_diagnostics --keepdb --noinput`: 7 PASS, incluida comparación simulada de evidencia de propuesta; no implica aprobación ni aplicación.
* Frontend `pnpm test src/pages/inventory.order.test.jsx`: 3 PASS, incluyendo pendiente tras recarga simulada y fallo de red seguido de retry con identidad idéntica; la prueba usa mocks de transporte y se complementa con las pruebas PostgreSQL del servidor.
* `check` y `makemigrations --check --dry-run`: PASS. `pnpm build`: PASS con advertencia de chunk. Lint dirigido a API y test nuevos: PASS; pantalla `inventory.jsx` mantiene cinco errores previamente registrados.
* No se ejecutó comprobación visual de preview/resultado I03. La pérdida total de almacenamiento local en otro navegador o al borrarlo no tiene aún reconciliación autoritativa antes de una nueva entrada; el caso bloquea cerrar I01.
* `pg_ctl status` identificó PID 43096 y directorio/puerto propios; `pg_ctl -D <directorio orden4> -m fast -w stop` detuvo únicamente ese servidor. Directorio conservado.
* Tras endurecer `compare_proposal` para rechazar campos de evidencia ausentes, se verificó de nuevo puerto libre y se reinició el mismo cluster. `apps.inventory.tests.test_order4_diagnostics`: 7 PASS. `pg_ctl status` identificó PID 34992 y el directorio/puerto propios; se detuvo ese proceso y se conservó el directorio.
