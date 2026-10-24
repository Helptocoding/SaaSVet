# B9E — cierre de campaña integral de `1947726`

Fecha: **2026-10-11**. Candidato: **`194772677ca4e9fe1a1dec7f4dafa48396a6c583`**. Rama de entrega: `codex/e4-capacity-scheduling`.

**Decisión: PENDING / PREFLIGHT_BLOCKED.** La instalación congelada del frontend terminó con exit code **1** y `ERR_PNPM_EPERM`: el sistema rechazó la creación del enlace simbólico de `preact@10.12.1` en las dependencias de `@fullcalendar/core@6.1.20`. [Recibo del comando](frontend-install.exit.json), [log original local](frontend-install.log), [incidente](environment-incident.json) y [parada](STOP.json).

El bloqueo impide completar el preflight requerido por el §0 del plan. Se aplica la regla de incompatibilidades y la parada del §4: **no se inició el bloque 1**. No acredita un defecto del producto ni un fallo funcional del frontend. No hubo un segundo intento de instalación, una corrida formal, ajustes de cargas/umbrales, cambios de producto ni sustitución del modo de enlaces de pnpm para obtener verde.

## Preparación acreditada

- Se exportó una copia temporal del árbol Git exacto, independiente de los cambios locales. Los **3.332 archivos** se comprobaron contra sus IDs de blob Git y se sellaron con SHA-256. La rama y HEAD compartidos permanecieron en el candidato. [Fuentes](candidate-sources.json), [integridad después de la instalación fallida](integrity-after-failed-install.json) e [integridad final](integrity-final-before-cleanup.json).
- Discovery, sin ejecutar casos ni migrar la aplicación, resolvió los **87/87 IDs dirigidos** y congeló **3.331 IDs** para la regresión general. Los runners críticos seleccionan B0=17, B3=42, B4=68 y B5=37. Los 87 dirigidos y los 164 de esos runners están dentro de la suite general; no son ejecuciones adicionales acreditadas. No hubo errores de importación, IDs ausentes ni duplicados. [Selección](discovery.json), [dirigidos](directed-selected.json), [suite general](full-selected.json).
- Python **3.13.2**: las **34 dependencias** del lock coinciden con el entorno existente; `pip check` satisfactorio. Node **20.20.2** y pnpm **9.15.9** se prepararon de forma privada y se verificaron con los checksums de sus distribuciones. Gitleaks **8.18.4** quedó preparado; no se ejecutó el escaneo. [Python](python-environment.json), [toolchain](toolchain.json), [Gitleaks](gitleaks-toolchain.json).
- PostgreSQL **16.15** privado, usuario de evaluación `b9e`, puerto **35459**, escucha sólo en `127.0.0.1`, `fsync`, `synchronous_commit` y `full_page_writes` habilitados. Se creó únicamente `test_b9i_control`, sin tablas de aplicación ni clínicas. No se usaron bases, credenciales o proveedores productivos. [Preflight SQL](postgresql-preflight.json), [configuración conservada](private-postgresql/postgresql.conf).
- Se registró el presupuesto para una suite: **3 GiB** de memoria más **2 GiB** de reserva, campaña con presupuesto de **2 GiB** de disco más **1 GiB** de reserva. El inicio de preparación tenía margen suficiente; esto no acredita el consumo de una suite que nunca corrió. [Recursos](resource-preflight.json).
- El runner temporal, el harness de proveedores y la fuente del fixture existente tienen blobs idénticos a `0831046`. Se conserva el escenario fijo SATURATION, sus tres gates originales, las ventanas 30/300/20 s y las **dos llamadas LLM reales** por READ. La comprobación de compatibilidad no es una ejecución temporal. [Compatibilidad](profile-compatibility.json).

La selección general incluye una anotación de skip en una política futura de Analytics; no fue ejecutada ni se usó para cubrir requisitos. Las pruebas de regresión de D29 inspeccionadas validan recibos/harness con fixtures y replay; **no se ejecutó ninguna prueba ni escenario físico D29**.

## Incidentes de preparación

Antes de cualquier prueba, se corrigió el ensamblaje porque `git archive` había aplicado `core.autocrlf` del host. La copia se volvió a exportar con `core.autocrlf=false` y `core.eol=lf`, y sólo después se acreditó igualdad de todos los blobs. El intento rechazado quedó registrado; no fue una deriva posterior de fuentes selladas. También se sustituyó la lectura interactiva de `cat-file` por cálculo del hash de blob Git debido a la retención de handles del wrapper RTK. [Registro](assembly-incident.json), [incidente original](preparation-incident.json).

`pg_ctl` informó servidor listo, pero su wrapper RTK conservó handles de los descendientes. Se terminó exclusivamente ese wrapper propio, se verificaron por SQL la propiedad y durabilidad del clúster y se continuó la preparación con la misma instancia, sin reiniciar PostgreSQL ni ejecutar tests. [Registro](pg-start-wrapper-incident.json), [salida original](pg-start.log). Esos incidentes de ensamblaje precedieron a la instalación fallida que determina la parada final.

## Resultado por bloque

| Bloque | Estado de esta campaña |
|---|---|
| Preflight íntegro | **PENDING**, instalación congelada bloqueada por EPERM |
| Corpus dirigido, 87 IDs, incluidas I04/I07 | NOT_EXECUTED |
| Checks/migraciones/schema Billing y B0/B3/B4/B5 | NOT_EXECUTED |
| Suite backend completa, 3.331 IDs descubiertos | NOT_EXECUTED |
| Frontend build/tests/smoke | NOT_EXECUTED |
| Gitleaks de historial completo | NOT_EXECUTED |
| Lint y auditorías advisory | NOT_EXECUTED |
| PROFILE BASE | NOT_EXECUTED |
| PROFILE BLOCKED_LLM | NOT_EXECUTED |
| PROFILE META_SLOW | NOT_EXECUTED |
| PROFILE DUPLICATE | NOT_EXECUTED |
| PROFILE SATURATION | NOT_EXECUTED |

**Totales de ejecución: 0 pruebas, 0 corridas formales y 0 variantes PROFILE.** No existen p95, máximos, colas ni denominadores temporales nuevos. Los 3.331 IDs son selección descubierta, no resultados. [Estados legibles por máquina](block-status.json), [matriz R01–R15/I01–I14 del candidato](candidate-decision.json).

## Conservación y cierre

Se comprobaron conexiones, locks, prepared transactions y ausencia de tablas de aplicación en el clúster privado. Se eliminó la única base propia, se detuvo PostgreSQL y se retiró exclusivamente el directorio temporal identificado de la campaña. Se conservaron las configuraciones, recibos y logs. Las instalaciones Python/PostgreSQL reutilizadas y los procesos ajenos no se retiran. [Cleanup](cleanup.json), [checkout final](checkout-final.json).

La eliminación encontró `WinError 145` en una ruta profunda de pnpm y se completó usando la ruta extendida de Windows del mismo destino verificado. Las consultas y la eliminación SQL precedieron a ese error, pero sus filas quedaron en memoria y no se persistieron antes de la excepción; se declara esa limitación sin inventar snapshots. La parada del servidor, el puerto cerrado y la eliminación final del directorio tienen comprobaciones conservadas. [Incidente de cleanup](cleanup-incident.json). Los adaptadores de recibos preparados para etapas posteriores no se ejecutaron ni acreditan validación de esas etapas.

El expediente usa un inventario propio y ZIP/deflate en partes de hasta 20 MiB. La recuperación aislada compara tamaño y SHA-256 de cada archivo, verifica las partes y el ZIP concatenado, y comprueba confinamiento de rutas. [Manifiesto](preservation-manifest.json), [recuperación](preservation-verification.json), [índice](artifact-index.json). Los originales locales se conservan; los logs y journals se entregan dentro de los paquetes sin convertir sus finales de línea.

La selección Git es explícita, en la misma rama, y excluye los tres cambios ajenos en `DEPLOY_VPS_PLAN.md`, `DEPLOY_VPS_STATUS.md` y `skills-lock.json`. **No se hace commit ni push.** Los recibos históricos permanecen intactos. El [acta vigente](../b9-consolidation-2026-10-11/ACTA.md) incorpora esta decisión sin transferir métricas de `0831046` al candidato actual.

La campaña termina con **PENDING_INTEGRAL_ACCEPTANCE**. Activación: **PENDING_ACTIVATION_REQUIREMENTS**; R1-04 conserva **PENDING con limitación aceptada**, y E/P/UX siguen separados. Una nueva campaña requiere una decisión nueva y un entorno que permita completar la instalación congelada; este cierre no la inicia.
