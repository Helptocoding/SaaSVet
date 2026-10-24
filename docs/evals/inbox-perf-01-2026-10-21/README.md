# WA-PERF-01 — lista agrupada sin consultas por hilo

Estado: **implementada y verificada localmente** (2026-10-21). PostgreSQL elige
una sesión por contacto/cuenta y anota conteo de episodios, último mensaje
operacional y handoff. Mantiene urgentes primero, actividad del mensaje y
actividad del bucket en empates. El cap de 100 se aplica antes de materializar.
No cambia `ThreadSerializer[]`, permisos, visibilidad ni migraciones.

| Muestra | Antes | Después |
|---|---:|---:|
| 7 hilos | 15 consultas | 1 consulta |
| 37 hilos | 75 consultas | 1 consulta |

Medido mediante la misma API con usuario autenticado de fixture y warmup de
permisos; no incluye autenticación JWT de producción ni demuestra latencia
constante. Las subconsultas siguen teniendo coste dependiente de los datos.

| Check | Resultado |
|---|---|
| Caracterización previa | Capturada **antes de editar la consulta**; `baseline-views.py`, `baseline-source-sha256.json`, `baseline-backend.json/log`. Fixture congelada: `backend/apps/agent/tests/fixtures/inbox_threads_perf01.json`. |
| Verificación PostgreSQL | **14 PASS**: cuatro pruebas nuevas y diez regresiones afectadas. Payload exacto de activas/inclusión de archivadas, cuentas separadas, estados operacionales, Unicode, empates, urgencia, sesión vigente, conteo y cap. `backend.json`, `backend.log`. |
| Carga de historial | Con 100 episodios cerrados adicionales, se materializa un objeto Conversation por fila de salida; conteo del hilo correcto (103). |
| Cleanup | Ambas bases temporales de las ejecuciones válidas eliminadas, comprobado en catálogo; también se eliminó la del intento fallido de fixture. |
| Integridad | `source-sha256.json` identifica código/fixture; diff-check PASS. Frontend y serializer no cambiaron en PERF-01, por lo que no se repitieron sus suites/build. |

El primer intento de captura falló antes de ejecutar pruebas porque la fixture
`uncertain` omitía `uncertain_at`. Se añadió esa evidencia sin cambiar el guard;
fallo y cleanup conservados en `baseline-backend-attempt1.json/log`. Ninguna
referencia previa fue sobrescrita. El runner `capture` se niega a sobrescribir
la fixture; la verificación regular solo la lee.

La paginación y el fin del cap silencioso pertenecen a PERF-02. Esta prueba
local no acredita operación real ni revoca el FAIL B9 r12. Sin suites generales,
commit, push, despliegue ni activación.
