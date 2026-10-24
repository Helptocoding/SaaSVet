# WA-SRCH-01 — búsqueda de contactos

Corte local del 2026-10-21. Implementación y verificación dirigidas completadas.
El usuario pospuso la validación con recepción/Meta; continúa pendiente y no se
presenta como aceptada. Siguiente tarea funcional: **WA-ASN-01**.

## Comportamiento

`GET /api/inbox/threads/?q=<texto>` recorta espacios, ignora consultas de menos
de dos caracteres y busca sin distinguir mayúsculas por nombre del contacto,
identificador externo/teléfono y nombre del cliente vinculado. Reutiliza
`phone_digits` y `normalize_wa_id`: admite fragmentos y teléfonos mexicanos
formateados con prefijo 52/521 sin cambiar el dominio de diez dígitos.

El OR de búsqueda se combina mediante AND con segmentos y archivo, antes de
paginar la proyección agrupada. No busca cuerpos, mascotas ni el teléfono de
un cliente ajeno al contacto. Todos los valores pasan por el ORM; SQL/LIKE son
literales y se conserva organización/permiso `agentinbox.view`.
`q` efectivo pertenece al scope del cursor, junto con usuario/org/filtros/offset.
Un cambio de nombre puede retirar el hilo del delta. El total unread no se filtra.

El input espera 250 ms desde la última tecla; Ctrl/Cmd+K enfoca y selecciona,
Escape o «Limpiar búsqueda» limpian inmediatamente. Cada cambio efectivo aborta
GETs anteriores y reinicia páginas/cursores; polls, páginas y reintentos conservan
consulta y segmentos. Las respuestas tardías no repueblan otra búsqueda. El
chat/historial/borrador se conservan, con vacío que sugiere otra consulta.
El panel móvil deja espacio para búsqueda, filtros y resultados.

Runtime modificado: `backend/apps/agent/views.py`,
`frontend/src/pages/inbox/index.jsx` e `inbox.module.css`. Sin nueva migración,
dependencia, cambio de permiso ni escritura de negocio.

## Resultados

| Check dirigido | Resultado | Evidencia |
|---|---|---|
| API PostgreSQL | **41 PASS**: 16 nuevos + 25 regresiones afectadas | `backend-fixture-fixed.json` y `.log` |
| Frontend nuevo | **15 PASS** | `vitest-new.json` |
| Frontend afectado | **119 PASS** | `vitest-affected.json` |
| Build | PASS, sin subida a Sentry | `build-final.json` y `.log` |
| Lint dirigido | PASS, cero errores/advertencias | `lint-final.json`, `lint-report-final.json` |
| Chromium escritorio/móvil | PASS, API sintética | `browser.json`, `browser-run.json`, `search-desktop/mobile.png` |
| Conteos, hashes y limpieza | PASS | `final-checks.json`, `executed-tests.json`, `source-sha256.json` |

Total frontend: **134 casos únicos PASS**. Las regresiones se justifican porque
la búsqueda modifica la misma lista, reinicio de páginas y scope de cursor de
FIL-01/PERF-02/PERF-03; no se ejecutó suite general ni campaña B9. API conserva
caracterización de payload, paginación de 250 hilos y número de consultas acotado.

Los nuevos casos cubren nombre parcial/mayúsculas/acentos, teléfono formateado,
identificador sin teléfono normalizado, cliente vinculado, mínimo, vacío,
filtros/archivo/páginas, tenant isolation, permisos, inyección/LIKE literal,
scope/equivalencias de cursor y retirada por cambio de nombre. La interfaz cubre
el límite exacto de 250 ms, ráfagas, atajos, limpieza, páginas/polls, aborts,
respuestas tardías, fallos/reintento, visibilidad y desmontaje.

## EXPLAIN y navegador

Con **1.004 hilos locales sintéticos**, la búsqueda por apellido devuelve una
fila mediante **un SELECT de lista** con `LIMIT 101` y OR parametrizado.
Se capturan ocho consultas totales del GET, incluidas permisos/lectura/metadatos;
no se confunden con un SELECT de proyección. `query-plan-fixture-fixed.json`
guarda `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`: planificación 7,296 ms,
ejecución **17,869 ms** y una fila devuelta. Usa el índice de organización de
Conversation, PKs de joins e índice existente de mensajes por hilo. El filtro
de texto sigue siendo `icontains`; esta muestra no demuestra coste constante ni
un índice especializado de substring. No justifica añadir índices/migraciones.

Chromium real a 1366×768 y 390×844 con API sintética verifica nombre del cliente,
teléfono parcial, segmentos AND, Ctrl/Cmd+K, Escape/tap para limpiar y sugerencia
de vacío. Desde completar el input hasta mostrar el resultado midió **509,29 ms
en escritorio y 389,15 ms en móvil**, ambos bajo un segundo incluyendo debounce.
Estos tiempos no acreditan latencia de Meta ni de la API en producción.
Sin overflow horizontal ni errores JS, borrador conservado. Capturas inspeccionadas
visualmente; el servidor Vite oculto pertenece al harness y deja 4178 libre.

## Fallo inicial y corrección

`backend-directed.json/.log` preservan un error de preparación de fixture:
`phone_normalized` tenía doce dígitos y el modelo permite diez. Se ejecutaron
**cero tests**, no hay PASS que conservar de esa pasada. Duración 189,46 s y
base temporal eliminada. Se corrigió la fixture al formato canónico del modelo
y se reutilizaron los normalizadores existentes para prefijos completos.

La ejecución corregida empieza por los casos nuevos, con `failfast` antes de
ampliar a regresiones: 41 PASS en 21,129 s de tests, **141,61 s** incluyendo
preparación/migraciones y limpieza de la base desechable. Ambas bases indican
`test_database_remains=false`. No se aplicó M3 ni otra migración a la base de
trabajo. No se rebajaron guards, assertions o tiempos y no hubo más repeticiones API.

## Reproducción

Desde la raíz, con etiquetas nuevas para no sobrescribir recibos:

```powershell
rtk proxy python -X utf8 docs/evals/inbox-srch-01-2026-10-21/run_tests.py frontend reproduction src/pages/inbox/index.search.test.jsx
rtk proxy python -X utf8 docs/evals/inbox-srch-01-2026-10-21/run_tests.py backend reproduction apps.agent.tests.test_inbox_search apps.agent.tests.test_inbox_filters apps.agent.tests.test_inbox_thread_pagination apps.agent.tests.test_inbox_thread_performance
```

`run_browser.py`/`check_browser.py` reproducen el ensayo en otro directorio de
evidencia para preservar estos recibos. `verify_results.py` valida este corte
y crea un manifiesto exclusivo. No hay despliegue, activación ni aceptación real;
seguridad/B9 r12, M3, media y DoD operativo conservan sus pendientes.
