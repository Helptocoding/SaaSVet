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

## Continuación 06-11 (I01)

**Estado: verificado localmente el 07-11; suite global local y migración de la base habitual el 08-11.** Los siete escenarios en navegador tienen PASS sobre la build final. El alcance exacto y sus límites están en [Cierre 07-11](#cierre-07-11) y [Cierre 08-11](#cierre-08-11). La corrida del 06-11 se interrumpió por falta de memoria del equipo; lo que sigue conserva ese registro.

Entorno: no se consultó el grafo, se leyeron fuentes actuales. `pg_ctl status` confirmó el cluster exclusivo detenido y un bind loopback confirmó libre 49935 antes de arrancarlo; el runner verificó directorio y puerto efectivos. Las migraciones 0031–0033 se aplicaron solo a `test_orden4_iso_20261031`. Base habitual, otros clusters y VPS no se tocaron. Sin commit, push ni despliegue.

### Prueba directa contra PostgreSQL

Desde `backend`, prefijo `rtk proxy python scripts/orden4_isolated.py`:

| Comando | Resultado | Qué cubre |
|---|---|---|
| `check` · `makemigrations --check --dry-run` | PASS; sin drift | Sin cambios de modelo posteriores |
| `test apps.inventory.tests.test_order4_reception_recovery apps.inventory.tests.test_stock_reception apps.core.tests.test_tenant_scoping_audit --keepdb --noinput` | 43 PASS, 1 FAIL | Login real sin identidad previa, evidencia histórica frente a saldo actual, identidad idéntica, aislamiento, supervisión, límites. El FAIL era de la prueba: el conteo de consultas medía la caché de permisos del primer request |
| `test …recovery.DiscoveryBoundsTests …recovery_races …reception_concurrency …reception_upgrade --keepdb --noinput` | 13 PASS | El caso corregido; 8 carreras con conexiones independientes; concurrencia previa; upgrade desde 0030 y rollback con intención abierta |

Las carreras retienen una transacción abierta mientras otra conexión actúa: ejecución en vuelo visible como `pending`, intención aún sin commit que hace esperar y rechaza a otra, discard contra ejecución en vuelo, fallo antes del commit, y dos preparaciones, completados o completado contra descarte a la vez. Después de estas corridas se añadió a `test_presentation_factor_is_kept_with_the_operation` la comprobación de cambiar el factor más tarde, que pasó el 07-11.

### Prueba directa en navegador

`test_order4_reception_browser`: Chromium headless, API real con `LiveServerTestCase` y PostgreSQL de orden 4. Cada recuperación abre un contexto nuevo sin almacenamiento ni cookies e inicia sesión con credenciales; las pruebas no leen ningún `operation_id`. La pérdida de respuesta se provoca con la petición ya servida, reenviada por `route.fetch` y abortada hacia la página.

| Corrida | Resultado |
|---|---|
| Primera, 7 escenarios | 3 PASS, 1 FAIL, 3 ERROR. Una causa fue un selector de la prueba; la otra, un **bug real**: `loadAll` activaba `loading`, la página se reemplazaba por su pantalla de carga y el panel se desmontaba con la evidencia. Corregido con refresco sin `loading` y regresión en `inventory.receptions.test.jsx`. La salida estaba truncada: qué escenarios fueron los 3 PASS es una inferencia, no un dato |
| Segunda, tras la corrección | **Interrumpida por el sistema por falta de memoria** durante el quinto escenario. 4 PASS: `test_committed_reception_with_lost_response_is_recovered_in_a_clean_browser`, `test_execution_in_flight_cannot_become_a_second_entry_from_a_clean_browser`, `test_execution_that_never_arrived_is_completed_once_and_a_new_entry_stays_legitimate`, `test_identical_candidates_need_an_explicit_choice` |
| Tercera, 07-11, solo los 3 sin resultado y sobre la build final | 3 PASS en 126,7 s: `test_intent_that_never_arrived_leaves_nothing_and_a_new_entry_is_free`, `test_lost_intent_response_is_closed_without_touching_stock`, `test_new_product_from_the_wizard_is_not_created_again` |
| Cuarta, 07-11, los 4 restantes sobre la misma build final | 4 PASS en 190,1 s: los mismos cuatro de la segunda corrida |

La build de la segunda corrida no incluía los últimos ajustes del panel: textos, «Cargar más» en Entradas sin identidad y guarda de página tardía. La cuarta corrida regeneró las capturas y se revisaron visualmente sobre la build final: confirmada, sin confirmar y candidatas sin selección. Muestran horas en UTC porque la clínica sintética se crea con `timezone='UTC'`, no por un error del panel, que usa la zona de la organización.

### Frontend

Simulación con transporte mockeado, complementaria a la prueba en navegador:

- `pnpm exec vitest run src/components/ReceptionsModal.test.jsx src/pages/inventory.receptions.test.jsx`: 19 PASS; tras la corrección del panel, `inventory.receptions.test.jsx`: 8 PASS.
- `src/api/inventory.reception.test.js` y `src/pages/inventory.order.test.jsx`: PASS. Se conservan las pruebas de recarga con estado local; solo se añadió `getReceptions` al mock. **Corrección 08-11:** el PASS de `inventory.reception.test.js` no se sostiene sobre su versión final; esa prueba fallaba siempre por un error de la propia prueba, corregido en [Cierre 08-11](#cierre-08-11).
- ESLint dirigido: sin hallazgos en archivos nuevos. `inventory.jsx` mantiene los cinco errores ya registrados y `StockEntryModal.jsx` un error y una advertencia de un efecto previo. No se atribuye PASS global.
- `vite build` hacia un directorio temporal: PASS.

Los últimos ajustes del panel se verificaron el 07-11.

### Cierre 07-11

Por indicación expresa, solo se ejecutó lo que no tenía resultado, salvo lo necesario para probarlo. El código de backend no cambia desde el 06-11 a las 22:30 y sus corridas en verde son de 22:36 a 22:48, así que esas suites no se repitieron.

Desde `backend`, prefijo `rtk proxy python scripts/orden4_isolated.py`, con `--keepdb --noinput`:

| Comando | Resultado | Motivo |
|---|---|---|
| `test apps.inventory.tests.test_order4_reception_concurrency` | 1 PASS | Ya verificada. Se repitió porque limpia las filas sintéticas que dejó la corrida interrumpida |
| `test …ConfirmedOperationRecoveryTests.test_presentation_factor_is_kept_with_the_operation apps.core.tests.test_admin_registration_audit` | 3 PASS | Comprobación añadida y auditoría de admin, sin resultado previo |
| `test` de los 11 módulos de `apps.inventory.tests` no verificados | 80 PASS | Regresión. Excluye `test_order4_reception_*` y `test_stock_reception`, ya en verde |
| `test apps.imports` | 115 PASS | Regresión |
| `ORDEN4_BROWSER_DIST=<dir> test` de los 3 escenarios pendientes | 3 PASS | Chromium sobre la build final |
| `ORDEN4_BROWSER_DIST=<dir> test` de los 4 escenarios restantes | 4 PASS | Repetidos a petición, para tener los 7 sobre la misma build |

Frontend, con el código final:

- `pnpm exec vitest run src/components/ReceptionsModal.test.jsx src/pages/inventory.receptions.test.jsx src/pages/inventory.order.test.jsx`: 23 PASS.
- Ninguna prueba ejercitaba «Cargar más» en Entradas sin identidad ni la guarda de página tardía, así que se añadieron dos a `ReceptionsModal.test.jsx`, que queda en 14 PASS. Al retirar la guarda temporalmente, la prueba falla con la página tardía visible; después se restauró el archivo y se comprobó con `cmp`.
- ESLint: `ReceptionsModal.jsx` y su prueba sin hallazgos. `inventory.jsx` conserva cinco errores y una advertencia, y `StockEntryModal.jsx` un error y una advertencia, ya registrados. No se atribuye PASS global.
- `VITE_API_URL=http://127.0.0.1:49936/api/ pnpm exec vite build --outDir <dir>`: PASS.

Alcance y límites:

- **Los 7 escenarios usan la misma build, en dos corridas.** Entre la de 3 y la de 4 ningún archivo fuente de `frontend/src` cambió respecto a esa build.
- **Sin suite global ni CI.** `billing`, `medical_records` y `dashboard` también consumen inventario y sus suites no se ejecutaron. Resuelto en local el 08-11, salvo la CI real.
- **Sin aplicar fuera del destino sintético.** Las migraciones 0031–0033 no se han aplicado a la base habitual ni a producción. La base habitual local se migró el 08-11; producción sigue sin tocar.

Entorno: un bind loopback confirmó libres 49935, 49936 y 49937, y el runner verificó destino y puerto en cada comando. El primer arranque con `pg_ctl … start | tail` quedó colgado porque el postmaster heredó la tubería, y detener esa tarea tumbó el cluster. Se rearrancó con la salida a un archivo, antes de ejecutar cualquier prueba; al repetir, no canalizar esa salida. En cada una de las dos sesiones, `pg_ctl status` identificó el proceso propio (PID 38372 y 41396) con su directorio y puerto, y `pg_ctl -m fast stop` lo detuvo. Directorio conservado y puertos libres. Base habitual, otros clusters y VPS no se tocaron. Sin commit, push ni despliegue. No se pudo inspeccionar la lista de procesos (acceso denegado), así que no consta si quedó algún Chromium huérfano de la corrida interrumpida.

### Cierre 08-11

Por petición expresa: suite global, pasos de CI en local, migraciones en la base habitual local y commit, sin push ni despliegue.

**Suite global del backend.** Corrida en el cluster exclusivo de orden 4 (PostgreSQL 18.3, loopback 49935), que ningún otro proceso usa. Antes de empezar:

- `makemigrations --check --dry-run`: sin cambios.
- La base de pruebas se migró desde cero y se guardó como plantilla.
- `audit_billing_schema --json` sobre esa plantilla: 0 violaciones.

`DiscoverRunner` descubre 3.860 pruebas y todas se ejecutaron:

| Dato | Resultado |
|---|---|
| Lotes | 146 |
| Ejecuciones | 3.899. Las 39 de más son clases importadas por otro módulo, que se ejecutan dos veces |
| Skipped | 19. 7 son el navegador de I01, que necesita `ORDEN4_BROWSER_DIST` y Playwright; 9 están en `test_d29_frontiers` y 3 en otros módulos |
| Fallos | 21, en 5 lotes, ninguno atribuible a I01 |

Los módulos que consumen inventario pasan: `inventory` 140, `billing` 73, `medical_records` 122, `dashboard` 69, `prescriptions` 15, `cash` 30, `imports` 115 y `core` 216.

| Fallos | Causa | Situación |
|---|---|---|
| 17 | `MediaWorkerTests` y `test_inbox_media` necesitan `INBOX_MEDIA_ALLOW_LOCAL`, que por defecto vale `DEBUG`, y CI corre con `DEBUG=False` | Previo a I01; corregido en `develop` (`3d7157f`) |
| 1 | `test_identity_evidence` borra una mascota sin `authorize_physical_deletion` | Previo a I01; corregido en `develop` (`9129f5f`) |
| 1 | `test_inbox_thread_around`, aserción sobre lecturas de metadatos (`0 != 2`) | Previo a I01; `develop` cambia esa aserción (`3d7157f`) |
| 1 | `test_inbox_search` con `'ramÍREZ'` | Del entorno: el cluster sintético usa collation `C`, donde `upper('ramírez')` devuelve `'RAMíREZ'` y el `ILIKE` no pliega el acento. CI usa `en_US.utf8` |
| 1 | `test_media_restore_drill` | Puerta de entorno: el drill exige una base `test_inbox_policy_*` |

I01 no modifica `channels`, `agent`, `patients`, `platform` ni `config`. Esta rama va 25 commits por detrás de `origin/develop`, donde la última CI de `develop` (3.944 pruebas) pasó.

Diferencias con la CI real, que no se ejecutó porque requiere push:

- **Entorno:** Windows 11, Python 3.13 y PostgreSQL 18.3 local, frente a Ubuntu con PostgreSQL 16 en CI.
- **Lotes:** procesos separados en lugar de un único `test --parallel`. Cada lote reutiliza su base; si falla, se repite sobre una copia limpia de la plantilla (8 repeticiones) y solo cuenta el resultado limpio.
- **Contraseñas de fixtures:** `MD5PasswordHasher`, como hace `apps/agent/tests/run_b8b_acceptance.py`, salvo en los cuatro primeros lotes. PBKDF2 tarda unos 3 s por hash en este equipo.
- **Multiproceso B8B–B8E:** sus workers exigen una base con prefijo `test_b8X_`, así que corrieron sobre bases con ese nombre. `develop` ya retiró esa exigencia.
- **Cluster:** desechable, con `fsync=off` durante la mayor parte de la corrida.
- **Interrupciones:** hubo dos reinicios inesperados del equipo (Kernel-Power 41; el de las 13:09 con el cluster ocioso) y dos suspensiones. Tras cada reinicio, la plantilla se rehízo desde cero y un `pg_dump` completo leyó la base sintética sin error. Los lotes cortados se repitieron.
- **Pasos críticos de CI:** B0, B3, B4 y B5 no se lanzaron por separado con sus `Critical*Runner`. Sus módulos pasaron dentro de la suite sin skips.

**Frontend con los pasos de CI.** Node 22 y pnpm 11, frente a Node 20 y pnpm 9 en CI, con `VITE_API_URL=http://127.0.0.1:8000/api`:

- `vite build` hacia un directorio temporal: PASS.
- `pnpm run test`: en la primera corrida, 5 fallos de 798.
  - `inventory.reception.test.js` fallaba siempre por un error de la prueba. `beforeEach(() => vi.mocked(api.post).mockReset())` devolvía el mock, Vitest ejecuta como limpieza lo que devuelve `beforeEach`, y en la prueba que simula la pérdida de conexión ese mock rechazaba. Corregido con un cuerpo de bloque: 3/3 en tres corridas.
  - Los otros 4 eran timeouts de 5 s en `inbox/index.test.jsx` con el equipo cargado. Ese archivo solo da 93/93.
  - Segunda corrida completa: **69 archivos y 798 pruebas en verde**.
- `smoke:urls`: 5/5.
- `pnpm run lint`, que en CI es solo advertencia: 217 problemas en todo el frontend. Comparado archivo por archivo con `HEAD`, I01 no añade errores, pero sí una advertencia `react-hooks/exhaustive-deps` en `inventory.jsx`. `loadAll` llama ahora a `loadUnresolvedReceptions`, que lee `canReceive`, y el efecto sigue dependiendo solo de `token`. No tiene efecto práctico, porque `PrivateRoute` no monta la página hasta cargar los permisos de `/me/`. Corregirlo exigiría reestructurar `loadAll` en un archivo con 5 errores previos de `react-hooks`.
- No se ejecutaron `pnpm audit` ni `pip-audit`, que en CI son solo advertencia.

**Base habitual local.** `veterinaria_saas` en `localhost:5432`, 08-11, por petición expresa:

- Para aplicar 0031–0033, Django exige antes `organizations` 0013–0015 e `inventory` 0027–0030, entre ellas 0028/0029 de I02. Se aplicaron las 10 con aprobación explícita.
- Comprobación previa: 0 conexiones abiertas, 0 factores inválidos y 0 alias que 0029 fuera a reescribir.
- `pg_dump -Fc` completo antes de migrar, fuera del repositorio.
- `migrate inventory 0033`: 10 migraciones en 21 s.
- Después siguen iguales los conteos de productos (116), movimientos (237), presentaciones (117) y stock total (25.631). Hay 0 alias distintos del factor y 6 organizaciones, todas activas.
- Existen `stock_reception_state_consistent`, el índice único parcial `stock_reception_one_pending` y los índices `idx_reception_org_actor`, `idx_reception_org_created` e `idx_stockmov_reception_op`. `check`: sin problemas.
- Las otras 23 migraciones pendientes de esa base (`billing`, `patients`, `medical_records` y otras) no se tocaron.

Para volver atrás se restaura ese respaldo; consultar antes [aplicación y rollback](APLICACION-Y-ROLLBACK.md).

Sin push, despliegue ni cambios en producción o en el VPS.

### I02: writers del alias (08-11)

Una búsqueda de todas las escrituras de `Presentation` fuera de pruebas deja 6 writers vivos: alta de producto, PATCH anidado del producto, alta y PATCH de presentación, admin, importador y seed de demo. Las migraciones 0005 y 0018 son históricas. La tabla está en [decisiones](DECISIONES.md#writers-de-producción-contrastados).

`apps/inventory/tests/test_order4_alias_writers.py` recorre cada writer por su entrada real y relee el par desde PostgreSQL:

| Writer | Casos |
|---|---|
| Alta de producto | Alias solo, par igual (12 y 12.0000), ninguno → 1, límite 999999.9999. Rechazo sin escribir nada de contradicción, 0, -1, NaN, Infinity, 5 decimales, 1000000 y texto |
| PATCH del producto con `presentation_input` | Factor 0.125, alias 6, contradicción rechazada sin cambios, edición sin presentación que conserva el par |
| PATCH de presentación | Solo precio conserva el par; factor 1.2345 y alias 12 normalizan; contradicción y factor 0 rechazados |
| Nueva presentación | Contradicción rechazada sin crearla; factor 0.125 guardado en ambos |
| Importación | Factores 0.125 y 0.004 con su stock base (1 y 4) |
| Seed de demo | Pasos de organización y catálogo dos veces: alias igual al factor y sin cambios ni movimientos nuevos al repetir |

La prueba de importación encontró un **defecto real**: el importador guardaba alias 0.1300 con factor 0.1250 y bloqueaba la fila con factor 0.004. Ver [decisiones](DECISIONES.md#writers-de-producción-contrastados). Con el importador de `HEAD` la prueba falla (`import_has_blocking_errors`); con la corrección pasa, y el archivo corregido se restauró y se comprobó con `cmp`.

Corridas en el cluster de orden 4:

- Módulo nuevo, `test_order4_alias` y `apps.imports` juntos: 129 pruebas, 128 PASS. El error era el seed completo, que en esta rama falla en la parte de cobros («requiere una atestación externa vigente»), ajena a las presentaciones. `develop` cambia ese comando; la prueba quedó limitada a los pasos que escriben presentaciones.
- Módulo final: 7 PASS.

Pendiente de decisión, sin cambio: el importador redondea a 4 decimales un factor con más, mientras el alta manual lo rechaza.

### I03: comprobación visual (08-11)

`apps/imports/tests/test_order4_conflicts_browser.py` usa el mismo arnés que el navegador de I01 (Chromium headless, `LiveServerTestCase`, build estática) y se omite sin `ORDEN4_BROWSER_DIST` y Playwright. El escenario:

- La clínica tiene 130 productos.
- El CSV choca con todos: 110 coincidencias altas, con el mismo código y nombre, y 20 por revisar, con el mismo código y otro nombre. Además trae 5 productos nuevos.
- La prueba recorre subida, columnas, vista previa, confirmación y resultado.
- En la vista previa y en el resultado recorre el detalle: 50, 50 y 30 filas, sin huecos ni duplicados. «Siguiente» se desactiva en la última página y «Anterior» vuelve.
- Comprueba en la base el job confirmado, 135 productos y los existentes intactos.

Revisando las capturas aparecieron tres defectos, ahora fijados por la prueba de navegador y por `ConflictPages.test.jsx` y `entityConfig.test.jsx` (ver [decisiones](DECISIONES.md#i03-presentación-del-reporte-08-11)):

1. El detalle mostraba `name:` e `internal_code:` sin indicar qué era del archivo y qué estaba registrado. En las filas por revisar salían dos `name:` seguidos.
2. La muestra titulaba «Posibles duplicados por nombre (20)» y pedía añadir el código interno, cuando esas filas ya lo traían y chocaban por código.
3. El resultado decía «0 Duplicados omitidos» con 130 filas omitidas.

Corridas: navegador 1 PASS en cada una de las tres builds, la última con el código final; capturas revisadas a resolución real. `vitest run src/pages/imports`: 72 PASS. ESLint sin hallazgos nuevos; `PreviewStep.jsx` conserva los 3 errores y 2 advertencias que ya tenía en `HEAD`.

Observaciones sin cambio, fuera de I03:

- El botón flotante de ayuda «?» tapa en parte «Confirmar importación» cuando se llega al final de la página. Es un componente global.
- Con reportes grandes, la muestra de 100 tarjetas alarga la vista previa a unos 20.000 px antes del detalle.
- Si las primeras 100 son altas, la sección «por revisar» de la muestra queda en «Mostrando 0 de 20»; el detalle completo sí las muestra.
- En clientes y mascotas, el texto fijo «…ya pertenece a otro paciente» también se usa para un número de cliente repetido.

### Integración en develop y CI (08-11)

Por petición expresa, I01, I02 e I03 se rebasaron sobre `origin/develop` y se subieron a `codex/e4-capacity-scheduling`. El push fue fast-forward desde `8886604`, sin forzar.

- **Rebase:** la rama iba 25 commits por detrás. Hubo un único conflicto, de imports en `inventory/serializers.py`, y se conservaron ambos lados. `develop` no trae migraciones nuevas.
- **Antes del push, sobre el código integrado, en el cluster de orden 4:**
  - `makemigrations --check --dry-run` sin cambios.
  - `apps.core`: 315 PASS, 7 skipped. Incluye las compuertas nuevas de `develop` de permisos explícitos, rutas y validación de tenant.
  - `apps.inventory` y `apps.imports`: 263 PASS, 8 skipped, que son los navegadores.
  - Vitest: 813 de 814. El que falta es el timeout de 5 s del Inbox con el equipo cargado; ese archivo solo da 93/93 dos veces.
  - Build y smoke de URLs: PASS.
  - Navegador sobre la build integrada: los 7 escenarios de I01 y el de I03, 8 PASS.
- **CI real**, disparada con `workflow_dispatch` porque el push a esta rama no la lanza ([corrida 42516001803](https://github.com/Helptocoding/SaaSVet/actions/runs/42516001803), `711162e`), con los 4 jobs en verde:
  - Backend: 3.999 pruebas OK, 20 skipped, además de migraciones, `audit_billing_schema` y los runners críticos B0, B3, B4 y B5. La última CI de `develop` tenía 3.944.
  - Frontend: 71 archivos.
  - Security: gitleaks bloqueante.
  - Images.

El escaneo local de gitleaks sobre todo el historial (Windows) marcaba hallazgos en manifiestos ruta → sha256 de `docs/evals` del commit `8886604`. En CI el mismo historial pasa. No se investigó la diferencia.

Sin despliegue ni cambios en producción o en el VPS. La base habitual local quedó migrada como se registra en [Cierre 08-11](#cierre-08-11).


## Decisiones 09-11

Premisa: el usuario confirmó que no existen clínicas ni datos reales; todas las clínicas de la base local son de prueba.

**I02, factores con más de 4 decimales.** Una prueba nueva (`test_import_blocks_a_factor_it_would_have_to_round`) falló con el código anterior: `0.33333` no bloqueaba la fila. Con la corrección, `0.33333` bloquea la vista previa y el commit responde 400 sin crear el producto, mientras que `1.50000` entra como 1.5. Importador, alias de todos los writers y diagnóstico: 57 pruebas PASS en el cluster sintético de orden 4.

**I04, medición en el tope.** Una sola importación de 2.000 filas nuevas, en el cluster sintético, con `fsync` apagado y en este equipo; los tiempos no valen para otro servidor. Solo cubre la importación de inventario.

| Medida | Resultado |
|---|---|
| Importación sola | 54,0 s |
| Importación con carga simultánea | 58,2 s; 2.000 productos y 2.000 movimientos iniciales |
| Ventas sobre un producto existente durante la importación | 1.663, mediana 13,6 ms, máximo 71,1 ms |
| Alta manual con el código de una fila ya insertada y sin confirmar | Esperó 56,7 s y terminó en `IntegrityError` |

La importación solo bloquea productos creados en su propia transacción, que nadie más ve hasta el commit. El alta con código repetido es el único bloqueo observado, y ese error no tiene manejo específico en inventario. El `--timeout=60` de gunicorn no limita la duración de una petición con el valor por defecto de `docker-compose.prod.yml` (2 hilos por worker); el valor real del servidor no se comprobó.

**I07, clasificación de la base local.** Lectura con `default_transaction_read_only=on` y `audit_stock_integrity` sin escrituras: 116 productos, 84 reconciliados sin diferencias y 32 `no_baseline`.

| Situación de los 32 | Productos |
|---|---|
| Sin movimientos y con saldo | 18 |
| Una salida y ninguna entrada | 4 |
| Entradas menos salidas igual al saldo | 9 |
| Sin movimientos y saldo 0 | 1 |

Sin regularización. Base habitual sin escrituras, VPS sin tocar, cluster detenido con su directorio conservado y puerto 49935 libre.
