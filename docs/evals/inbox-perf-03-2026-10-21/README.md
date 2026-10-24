# WA-PERF-03 — polling incremental, 2026-10-21

Implementado y verificado localmente. Tras cargar, lista y transcript usan `since`
y reciben cambios, retiradas y metadatos. El full se conserva para inicialización,
caducidad/pérdida de caché o paquetes inconsistentes. No hay SSE ni infraestructura
nueva. [Decisión y tradeoffs](../../decisions/2026-10-21-p60-perf03-cursors.md).

## Resultado

| Comprobación | Resultado | Evidencia |
|---|---|---|
| API PostgreSQL, compuesta | 123 casos únicos PASS: 26 nuevos + 97 afectados | [consolidado](final-checks.json), [IDs ejecutados](executed-tests.json) |
| Frontend, compuesta | 259 casos únicos PASS: 37 nuevos + 222 afectados | [inicial](vitest-initial.json), [regresiones](vitest-regressions.json), [corregidos](vitest-fixed.json), [cadencia](vitest-cadence.json) |
| SQL y payload | 6.001 mensajes, 50 cargados; 52.002 → 303 bytes JSON, 99,42 % menos antes de compresión HTTP | [query-plan.json](query-plan.json) |
| EXPLAIN ANALYZE | 50 filas, índice existente, 2,116 ms en esta fixture | [plan completo](query-plan.json) |
| Escrituras | Cinco modelos opt-in; managers/default/scoping preservados | [inventario](write-audit.json) |
| Build / lint | PASS, cero errores/advertencias de lint | [build](build-run.json), [lint](lint.json), [lint final](lint-final.json) |
| Drift de migraciones | PASS, no changes detected; no migra la DB de trabajo | [migration-run.json](migration-run.json), [log](migration.log) |
| Chromium escritorio/móvil | PASS; 100 filas únicas, tick READ, nuevo/retirado y recuperación | [browser.json](browser.json) |
| Ancla de lectura | Delta 0,15625 px; recuperación 0 px en ambas vistas | [browser.json](browser.json) |
| Limpieza | Cuatro DB temporales destruidas y puerto Vite cerrado | Recibos backend y [browser-run.json](browser-run.json) |
| Fuentes protegidas / whitespace | PASS; sender, delivery, retry, serializers y helpers WIN sin cambios | [hashes](source-sha256.json), [final-checks.json](final-checks.json) |

La medición SQL captura 13 consultas de todo el GET, incluidas RBAC y metadatos;
el campo histórico `domain_queries` del recibo contiene ese total, no un subconjunto
de consultas de dominio. El plan usa `channels_me_organiz_c00b67_idx` sobre
organización/contacto/cuenta/created_at. No requiere un índice nuevo. El tiempo
observado no es un umbral ni una certificación de capacidad comercial.

## Contrato implementado

- Cursor firmado, emitido por servidor y ligado a organización, usuario,
  recurso/filtros/offset. Watermarks `(updated_at,id)` más fingerprints/pertenencia;
  no reloj del cliente ni created_at como único cursor. TTL de diez minutos.
- Caché default existente con hashes, IDs y límites, sin cuerpos/nombres/teléfonos.
  Snapshots inmutables: un replay no consume cambios. Pérdida/caducidad/scope inválido
  → `400 invalid_sync_cursor`. Sin caché, full sigue disponible con cursor null.
- Lista: upserts/retiradas por hilo, orden completo solo cuando cambia, paginación
  y unread_total. La UI combina cada offset y publica juntas las páginas cargadas.
- Transcript: nuevos y modificados por ID, retiradas explícitas y metadata sparse.
  El límite firmado `sync_floor` sobrevive a una fila eliminada y amplía el rango
  al cargar anteriores. `range_ids` reconcilia filas desaparecidas durante esa carga.
  `before`/`around` permanecen separados de `since`.
- Recuperación completa del rango cargado con `reset_range`; no deja huecos ante
  ráfagas de más de 50. Mantiene historial, borrador, contador, lectura y ancla.
- Una petición activa por recurso, abort e invalidación al cambiar hilo/filtro o
  desmontar. Cargar más interrumpe un poll pendiente. Oculto pausa; volver intenta
  delta. Errores HTTP ordinarios retienen datos/cursor y usan el reintento existente.
- Tracking central optativo de updated_at para Message, Conversation,
  ContactIdentity, HumanHandoff e InboxReadState, con save parcial/update/bulk_update.
  No altera filtros, locks, validación, default manager, transiciones o autoridad B4.

La API nueva cubre scopes, permisos, replay, timestamps iguales (incluidos dos
estados del mismo ID), commits tardíos dentro del rango, expiración de lease sin
write, unread por usuario, responsable, archivo/renovación, filas retiradas,
ráfagas, scrollback, pérdida de caché y floor firmado. Las regresiones dirigidas
cubren paginación/N+1/around/lectura/retry y el sender B4 porque los cinco modelos
optan por mantenimiento de timestamp. No se ejecutó una suite general ni B9.

## Recibos iniciales conservados

| Ejecución backend | Ejecutados | Resultado original | Corrección / repetición |
|---|---:|---|---|
| [backend](backend.json) / [log](backend.log) | 116 | 6 FAIL + 18 ERROR; 92 PASS válidos | Se conserva la cobertura no afectada por las correcciones siguientes. |
| [api-fixed](backend-api-fixed.json) / [log](backend-api-fixed.log) | 52 | 4 FAIL; 48 PASS | Error canónico, preview SQL y dos assertions de paginación. |
| [api-final](backend-api-final.json) / [log](backend-api-final.log) | 29 | Un ERROR de medición; 28 PASS | Solo se repitió la medición. |
| [plan](backend-plan.json) / [log](backend-plan.log) | 1 | PASS | Consolidado: 123 IDs únicos PASS. |

1. Caché: `LocMemCache.set()` no devuelve booleano de éxito. El código interpretaba
   None como fallo y no emitía cursor. Ahora verifica que el snapshot pueda leerse.
   Se mantiene la recuperación si Redis/cache realmente falla.
2. El handler global convierte un dict de detalle en validation_error. La excepción
   nueva usa detalle simple y default_code para emitir el `invalid_sync_cursor`
   exigido, sin cambiar el handler global ni otros errores.
3. El serializer de conversación leía dos cuerpos completos para preview/unanswered.
   La proyección ahora hidrata una sola lectura Substr(120) usando su prefetch
   existente. No cambia sus campos ni las etiquetas de caption/media.
4. Assertions previas de keys/comparación completa no contemplaban campos aditivos
   ni nonces distintos. Se conservan sus comprobaciones de filas/orden/scope y se
   comprueban modo/cursor; solo se excluye la igualdad del token efímero.
5. La medición usaba json.dumps sobre Response.data con UUID nativo. Se corrigió
   el harness con el renderer real de DRF; el producto no cambió.

Frontend inicial: 82 PASS. [Regresiones](frontend-regressions-run.json): 170 PASS
y seis FAIL. Cinco assertions se actualizaron para exigir los parámetros y
AbortSignal nuevos; una carrera reveló que Cargar más se ignoraba con un poll
pendiente y se corrigió la prioridad del código. [Repetición dirigida](frontend-fixed-run.json):
36 PASS y un FAIL de cadencia: el reloj falso disparaba dos intervalos sin resolver
la promesa entre ellos, que ahora debe ser excluyente. Se deja resolver cada tick,
conservando las tres llamadas esperadas y añadiendo la comprobación intermedia.
[Caso aislado](frontend-cadence-run.json): PASS. No cambian umbrales ni guards.

Los PASS de sender/delivery/retry se conservan porque sus fuentes no cambiaron;
el tracking de timestamps ya estaba activo en esa ejecución. Las correcciones
posteriores afectan a cursor/preview/contratos de lectura y tienen repetición
dirigida. Skips y repeticiones no se cuentan como casos nuevos.

## Navegador y reproducción

[Delta escritorio](delta-desktop.png) / [móvil](delta-mobile.png),
[recuperación escritorio](recovered-desktop.png) / [móvil](recovered-mobile.png).
Chromium real headless, API sintética: full inicial, delta vacío, carga anterior,
fila histórica retirada, READ y nuevo mensaje durante lectura de otro tramo,
cursor rechazado, full del rango y vuelta a delta. Borrador conservado, sin IDs
duplicados, errores de página ni overflow horizontal. Payload sintético estable:
13.006 → 86 bytes; el backend real se mide aparte en query-plan.json.

La captura del plan ahora es opt-in con `INBOX_SYNC_PLAN_OUTPUT` y creación
exclusiva de archivo. Los tests normales no reescriben este recibo; un runner
`plan...` elige un destino nuevo y exige caché LocMem privado para la evaluación.

Runners y comandos exactos están en los recibos. Cada ejecución PostgreSQL usa
una DB desechable; run_browser.py posee/cierra su Vite oculto y árbol de procesos.
verify_results.py consolida IDs ejecutados, limpieza, hashes y checks. El inventario
AST contiene 108 llamadas (incluye actualizaciones de diccionarios) y no encontró
literales SQL de escritura en los módulos runtime inspeccionados; la cobertura
de managers se verifica por introspección y pruebas sobre los cinco modelos.

No hay migración nueva, aplicación de M3 a la DB de trabajo, commit/push,
despliegue, activación ni tráfico Meta. M3, recepción real, gates Meta/media y
FAIL de seguridad B9 r12 siguen pendientes. Siguiente tarea: WA-FIL-01.
