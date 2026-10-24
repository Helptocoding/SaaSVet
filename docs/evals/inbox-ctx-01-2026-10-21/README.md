# WA-CTX-01 — contexto mínimo del cliente, 2026-10-21

Implementado y verificado localmente. Desde el chat abierto, desplegar contexto
y elegir «Abrir expediente» lleva a la ficha existente de la mascota en dos clics.
Se muestran cliente vinculado, teléfono, mascotas y última cita anterior con su
estado real. Sin datos clínicos, emparejamiento por teléfono ni modelos duplicados.

## Contrato y alcance

- GET `/api/inbox/threads/{contact_uuid}/{account_uuid}/context/`, permiso
  `agentinbox.view`; VET sí, AGENT 403. UUID/par inexistente o cliente vinculado
  de otra clínica/inactivo/genérico: 404. Contacto sin cliente devuelve
  `{owner:null,pets:[],last_appointment:null}`.
- Serializers públicos de patients restringidos a UUID/nombre/teléfono o especie.
  Cada relación se limita a la clínica del caller; no publica PK internos,
  notas, motivo de cita, historia clínica, precios ni catálogo.
- «Última cita» es la más reciente cuya hora programada ya llegó, conservando
  su estado. UTC para filas modernas, fecha/hora local para legacy; futuras
  excluidas. Usa mascotas activas, no genéricas, del cliente vinculado.
- Panel plegable con carga/error/reintento propios y consulta solo al abrir.
  Abort/continuaciones tardías cubiertos al cerrar, cambiar de hilo y desmontar.
  Reabrir refresca; el poll normal no añade consultas de contexto. Disponible
  en archivados/view sin send; el botón de ficha exige `patient.retrieve`.
- GET sin efectos de escritura. No cambia sender, ingesta, delivery, retry,
  historia o marcadores de lectura. Sin migración nueva ni aplicación de M3.

## Evidencia

| Comprobación | Resultado | Recibo |
|---|---|---|
| PostgreSQL API | 20 PASS: 17 nuevos + 3 afectados | [backend.json](backend.json), [log](backend.log) |
| Frontend dirigido, evidencia compuesta | 112 casos únicos PASS: 17 nuevos + 95 afectados | [vitest.json](vitest.json), [historial aislado](vitest-history-isolated.json), [retry, 25 casos](vitest-retry.json) |
| Consultas de dominio | 6 con una mascota y 6 con 36 | `test_queries_do_not_grow_with_number_of_pets`, [log](backend.log) |
| Build Vite | PASS, sin upload | [build-run.json](build-run.json), [log](build.log) |
| Lint de archivos afectados | PASS, cero errores/advertencias | [lint.json](lint.json), [selector final](lint-history.json) |
| Chromium 1366×768 / táctil 390×844 | PASS; ficha correcta en dos clics, errores propios y vacío | [browser.json](browser.json) |
| Limpieza | DB temporal destruida, puerto temporal cerrado | [backend.json](backend.json), [browser-run.json](browser-run.json) |
| Hashes / diff / recibos | PASS; autoridad B4 y helpers WIN sin cambios | [final-checks.json](final-checks.json), [hashes](source-sha256.json) |

Las pruebas API cubren DTO exacto, exclusión de campos privados, cliente no
vinculado aunque coincida el teléfono, filas legacy y límite horario en Tijuana,
citas futuras, archivado, permisos/autenticación y relaciones corruptas de otra
clínica. El GET deja intactos contacto, conversación, mensajes y lectura.

Las pruebas UI cubren lazy loading, error/reintento, vacío, homónimos por UUID,
texto HTML escapado, permisos de ficha, archivado, borrador/historia y cancelación
de respuestas tardías. Se repiten los flujos afectados de ventana, lectura,
historial, identidad, envío y retry; no una suite general ni B9.

## Fallos conservados y correcciones

1. [Primer frontend](initial-vitest.json): 80 fallos derivados de pasar `undefined`
   a `phoneHref` antes de cargar el panel. Se corrigió el componente con teléfono
   vacío durante carga/sin cliente. La siguiente ejecución dio 86 PASS y un fallo.
2. [Segundo frontend](vitest.json): un test de historial buscaba la única región
   de toda la página; el panel añade una región accesible. Se nombró explícitamente
   «Mensajes de la conversación», conservando las 110 filas, cursor y assertions.
   [Repetición](vitest-history.json): timeout de cinco segundos con build/navegador
   concurrentes. [Aislado](vitest-history-isolated.json): PASS, sin nuevo cambio de
   código, assertions ni límite. No se cuentan los skips o repeticiones como casos nuevos.
3. [Primer navegador](initial-browser.json): selector exacto del cuerpo de mensaje
   no contemplaba los metadatos dentro de la burbuja. El harness ahora selecciona
   la fila por ID y verifica cuerpo + 20 filas; el producto no cambió. PASS en ambas
   vistas tras corregirlo; recibos iniciales conservados.
4. Vite terminó con código 0 y [recibo PASS](build-run.json); imprimir el log en
   una consola cp1252 lanzó `UnicodeEncodeError` por el símbolo de check. El runner
   ahora imprime un resumen JSON ASCII. No se repite un build ya válido.

## Capturas y reproducción

- [Contexto escritorio](context-desktop.png) / [móvil](context-mobile.png).
- [Ficha escritorio](expediente-desktop.png) / [móvil](expediente-mobile.png).
- [Error escritorio](error-desktop.png) / [móvil](error-mobile.png).
- [Sin cliente escritorio](unlinked-desktop.png) / [móvil](unlinked-mobile.png).

Runners y comandos exactos están junto a sus recibos. `run_backend_tests.py`
crea/migra solo una DB desechable; `run_browser.py` posee y cierra su propio árbol
Vite oculto en Windows, con Chromium headless y API sintética. `verify_results.py`
consolida únicamente IDs ejecutados y valida limpieza/hashes. Para este corte
no hay tráfico Meta, cambios de recepción real, commit, push, despliegue ni activación.

La aceptación operativa de §13 sigue pendiente. M3 no se aplicó a la base de
trabajo. Los gates Meta/media y el FAIL de seguridad B9 r12 siguen vigentes.
Siguiente tarea prioritaria: WA-PERF-03; sus dependencias locales ya están acreditadas.
