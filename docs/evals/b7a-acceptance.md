# Reproducción de aceptación B7A

Baseline exacto: `fc95ab89a4b3a8020641fd2850c345ee42aae64b`.
La evidencia final está en [b7a-acceptance-results.json](b7a-acceptance-results.json)
y el [acta](../implementacion-b7a-agente-whatsapp-2026-09-18md).

Se requiere PostgreSQL real, una base **exclusiva de tests**, permisos para crear
la base de test/clones y el entorno backend del proyecto. No usar SQLite ni una
base de producción. Ejecutar desde `backend` con las variables normales de Django,
DATABASE_URL de esa base aislada y proveedores externos deshabilitados. Los tests
usan stubs/transportes locales controlados; no envían mensajes reales.

```text
python manage.py test apps.agent.tests.test_b7a_schema apps.agent.tests.test_b7a_operations apps.agent.tests.test_b7a_processes apps.agent.tests.test_b7a_migration --testrunner apps.agent.tests.harness.CriticalB7ARunner --keepdb --noinput --verbosity 2
python manage.py makemigrations --check --dry-run
python manage.py showmigrations agent
python manage.py check
```

En Codex se prefija el shell con `rtk proxy` conforme a AGENTS.md. La conjunta usa
la unión de los módulos del inventario versionado `b6-acceptance-results.json`
(47 módulos; 936 tests únicos), añade los cuatro módulos B7A, `test_family_link`
y `test_stale_phone_identity`, y ejecuta el mismo runner con `--parallel 1`.
El coordinador secuencial reduce contención local; los casos de concurrencia
conservan sus intérpretes y conexiones PostgreSQL independientes.
La lista exacta de módulos/test IDs, duración y hash de cada log está en el JSON
de aceptación B7A. No se suman reintentos como pruebas distintas.

CriticalB7ARunner exige escenarios críticos de definición/permission/containment,
crashes y PostgreSQL multiproceso; rechaza una suite vacía, parcial, skips, xfail
o unexpected successes. El inventario final se compara además con los 936 IDs B6
para acreditar regresión completa, incluidas las 17 pruebas B0 críticas.

Los siete casos multiproceso B7A arrancan intérpretes independientes y conexiones
PostgreSQL con barreras stdio. B7A-FI-03 inyecta error PostgreSQL real dentro de la
transacción de replacement. Se mata al worker antes y después de persistir; se
prueban duplicación, corrección, cambio de identidad y takeover concurrentes.
En Windows, el arnés usa el ejecutable base de Python y no el launcher del `venv`,
porque solo el primero permite que `kill` cierre el intérprete real y demuestre el
rollback de una transacción sin commit.
No son pruebas de corte de energía: el cluster local heredado B5 conserva
fsync/synchronous_commit desactivados. Producción conserva su configuración propia.

Las fixtures de pending legacy están bajo tests/legacy_pending.py. El decorador
legacy_write_component de las suites históricas sustituye explícitamente el writer
retirado; las pruebas B0/B7A usan containment y contrato de producción. La evidencia
no interpreta los tests de componentes inactivos como apertura de WRITE.

No se ejecuta frontend porque B7A no modifica frontend. Ninguna fila migrada se
convierte sintéticamente en operación/consentimiento. AUTHORIZED, envío y ejecución
permanecen cerrados en el runtime B7A.
