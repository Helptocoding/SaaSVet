# Guía vigente para cerrar Inbox y agente WhatsApp

Fecha: **2026-10-23**. Estado: **seguimiento de cierre funcional**.

## Actualización vigente del 23 de octubre: política recibida

El usuario definió [la política de retención y purga](decisions/2026-10-22-inbox-media-retention-policy.md):
180 días naturales desde persistencia, bloqueo al vencer, purga operativa verificada
en hasta siete días, reintentos diarios, alerta al primer fallo y escalamiento
tras 24 horas. Superar siete días abre incidente de cumplimiento; no se borra su
evidencia al recuperarse. Esta definición cierra la decisión de parámetros,
sin acreditar operación real ni firma/contrato.

Responsable y canal de alertas son [pendiente operativo no bloqueante](decisions/2026-10-23-inbox-media-alert-ops-deferred.md)
por instrucción posterior del usuario. B9 BASE conserva su excepción no bloqueante.
B2 real y Meta/recepción continúan aplazados; aviso, contrato, aceptación legal y
activación no se dan por realizados. El código y pruebas locales de esta entrega
se registran en [el expediente nuevo](evals/inbox-media-policy-2026-10-23/README.md).
La migración aditiva **channels.0018** ya está aplicada en desarrollo local,
con dump privado verificado y conteos conservados; preview/producción sin tocar.
Django check y ausencia de drift: PASS. El build del aviso actualizado también
es **PASS en 18 páginas** en la copia de revisión.
El nuevo [aviso preparado](compliance/inbox-privacy-review-2026-10-23/README.md)
sustituye al borrador anterior para revisión; ninguno se ha publicado.

## 0. Actualización autorizada del 22 de octubre

El usuario pidió ejecutar los puntos 1, 2, 3, 5 y 6, dejando el 4
(Meta/recepción) a su cargo. Después confirmó que B2 real también se aplaza y
pidió preparar privacidad. Despliegue/activación no se ejecuta. Para esos puntos,
esta actualización prevalece sobre los cortes históricos conservados más abajo.

| Punto | Estado vigente |
|---|---|
| M2/M3/M4 | **Aplicadas a la base habitual local**, con backup previo y doce prerrequisitos. PostgreSQL 18.3, conteo de mensajes conservado, Django check PASS. Preview/producción pendientes de su release autorizado. |
| B2 operativo | **Aplazado por el usuario**: aún no hay credenciales dedicadas. Configuración y recibo de validación futura preparados; lifecycle nativo no acredita borrado físico exacto al día 180. |
| Privacidad/DPA/ARCO | **Preparados para revisión**: aviso Astro completo y parche, ficha DPA, publicación/reconsentimiento y cancelación anticipada/restore. Sintaxis Astro PASS. Sin publicar, aceptar contrato ni promover versión legal. |
| Meta/recepción | **Excluidos de esta ejecución**, pendientes del usuario. |
| Seguridad | **Nueva verificación PASS**, 457 commits y seis archivos de corrección. 3156 hallazgos históricos clasificados y fingerprints exactos; reglas intactas, control negativo detectado. El FAIL r12 se conserva. |
| Aceptación B9 | **Deuda de latencia aceptada y NO BLOQUEANTE por el usuario**: p95 claim BASE 11,57 s frente al objetivo 10 s. Se conservan FAIL y cuatro perfiles NOT_EXECUTED, sin reintento ni otra campaña automática. No se exige reducir ese valor para continuar el cierre/activación. No se inventa aceptación integral PASS. Auditorías advisory con avisos conservadas; cleanup PASS. |
| Despliegue/activación | **No ejecutados**; decisión separada con sus gates reales. MED-06 saliente sigue opcional. |

[Expediente nuevo y resultados](evals/inbox-readiness-2026-10-22/README.md),
[privacidad preparada](compliance/inbox-privacy-review-2026-10-22/README.md) y
[operación de media](runbooks/inbox-media.md). Las auditorías no dieron un entorno
libre de vulnerabilidades: se registra su deuda sin cambiar el carácter advisory
acordado para B9 ni actualizar locks dentro del candidato congelado.

**Decisión posterior del usuario (22-10):** la latencia BASE se acepta como deuda
no bloqueante. [Decisión registrada](decisions/2026-10-22-b9-base-latency-accepted-debt.md).
No reiniciar B9 ni tuning por ella. La nueva
[lista B2/WhatsApp de seis puntos](compliance/cierre-b2-whatsapp-2026-10-22.md)
recoge región/contrato, retención, validación real, publicación, versión legal y
activación. La landing ya declara Backblaze en EE.UU.; eso no prueba la región
real de un bucket operativo aún sin provisionar. En ese corte los seis cierres seguían pendientes
de su evidencia final; implementación, documentación y build son avances parciales.

Este documento recoge la instrucción del usuario de cerrar el trabajo pendiente sin
repetir pruebas aprobadas ni ampliar el alcance con sobreingeniería. Es la guía de
seguimiento desde ahora. Ordena el trabajo; no sustituye los contratos originales,
dispensa requisitos de seguridad ni convierte resultados FAIL/PENDING en PASS.

## 1. Separar los tres cierres

| Alcance | Autoridad y criterio | Estado que se conserva |
|---|---|---|
| Inbox para recepción | [Plan de agosto](plan-implementacion-whatsapp-inbox-2026-08-22.md), tareas WA y Definition of Done §13 | No se declara completo por tener tests del agente aprobados. Deben acreditarse las funciones y la operación diaria exigidas. |
| Correcciones del agente | [Plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md), fases B0–B9 | B0–B8E y B9A–D tienen cierres técnicos documentados. E4 y D29 conservan sus cierres y límites aceptados. |
| Aceptación integral de candidato | [PLAN B9](evals/b9-integral-acceptance-1947726/PLAN.md) y decisiones posteriores autorizadas | La última ejecución terminó **FAIL en seguridad**. Su informe, acta, cleanup y conservación están completados. Aceptación integral no aprobada; activación separada. |

**Terminar una ejecución con decisión respaldada no equivale a obtener PASS ni a
tener todo el Inbox implementado.** No mantener abierta indefinidamente la
implementación por confundir estos estados.

El plan Inbox busca una bandeja profesional para recepción; excluye rediseñar
planner, tools, goals o FSM. Los cinco perfiles pertenecen a B9 y no son tareas
funcionales del Inbox. Gitleaks sí aparece en el CI requerido por ambos planes.

## 2. Punto de partida acreditado

La [última entrega r12](evals/b9-correction-20261020-native-r12/REPORT.md) conserva:

- Backend: **3331 IDs, 3319 PASS y 12 SKIP identificados**; build frontend PASS.
- Frontend: **355 PASS**, formados por 354 conservados y un caso corregido aprobado;
  smoke de URLs PASS. Lint advisory: 64 errores y 18 advertencias registrados.
- Seguridad: Gitleaks devolvió exit 1 con 3156 detecciones. El
  [triaje](evals/b9-correction-20261020-native-r12/diagnostics/security-finding-triage.md)
  verificó 2606 contextos de hashes de archivos; 550 permanecen sin clasificar.
  No son 3156 credenciales confirmadas ni 550 defectos funcionales del Inbox.
- Auditorías de dependencias y cinco perfiles: **NOT_EXECUTED**, por la parada
  exigida ante el gate bloqueante. No se presentan como aprobados.
- Cleanup PASS; dos recuperaciones de 1398 archivos sin diferencias; selección Git
  explícita verificada. Sin commit, push, despliegue ni activación.

Se conservan los fallos originales y la limitación histórica de monitor de disco y
reloj r6 aceptada por el usuario. La evidencia compuesta no es una campaña continua.

## 3. Lista finita de trabajo funcional

La [revisión del 11 de octubre](evals/inbox-whatsapp-closure-review-2026-10-11/REVIEW.md)
documentó fase 0 cerrada, fase 1 parcial y fases 2/3 incompletas. Ese es un corte
histórico, **no una nueva inspección del código actual**. No reimplementar una tarea
porque su seguimiento esté desactualizado.

Usar esta tabla como único listado de cierre, con los criterios del plan original:

| Familia / IDs originales | Evidencia o trabajo que debe quedar acreditado | Estado de seguimiento |
|---|---|---|
| FIX-01/02/03 | Aislamiento de borrador, envío humano preservado e idempotencia | **Cierre histórico conservado.** Evidencia: §4 del [plan original](plan-implementacion-whatsapp-inbox-2026-08-22.md), cortes del 23-08. CMP-01 afecta el campo del borrador; se verifican sus resets y el envío únicamente en frontend. No se modifican servicios ni idempotencia. |
| Fase 1: UX/SEP/TCK/OPT/GRP/CMP/CPY/TAB/VIS/VER/LDE/AGT/GTF | Completar las tareas obligatorias de presentación y envío del plan; distinguir implementación de acuses reales Meta | **Implementación local acreditada hasta el 21-10; aceptación real pendiente.** UX/SEP, TCK y OPT implementados: [datetime](../frontend/src/utils/datetime.js), [DeliveryTicks](../frontend/src/pages/inbox/DeliveryTicks.jsx), [Inbox](../frontend/src/pages/inbox/index.jsx), [MessageSerializer](../backend/apps/agent/serializers.py); evidencia histórica §4. **CMP-01 implementada y verificada localmente**: [evidencia](evals/inbox-cmp-01-2026-10-20/README.md), 30/30 tests dirigidos, build y Chromium escritorio/móvil PASS; lint advisory con dos errores previos. **GRP-01 implementada y verificada localmente**: [evidencia](evals/inbox-grp-01-2026-10-20/README.md), 19 tests frontend y cuatro backend PASS, build y Chromium escritorio/móvil PASS. **CPY-01 implementada y verificada localmente**: [evidencia](evals/inbox-cpy-01-2026-10-20/README.md), 18 casos frontend PASS (evidencia compuesta), build y Chromium escritorio/táctil PASS. **TAB-01 implementada y verificada localmente**: [evidencia](evals/inbox-tab-01-2026-10-20/README.md), siete pruebas nuevas y build PASS. **VIS-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-vis-01-2026-10-21/README.md), 17 pruebas, build, lint y red Chromium PASS con visibilidad controlada. **VER-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-ver-01-2026-10-21/README.md), 15 pruebas, build, lint y Chromium escritorio/móvil PASS. **LDE-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-lde-01-2026-10-21/README.md), 18 pruebas, build, lint y Chromium escritorio/móvil PASS; caída simulada y recuperación automática. **AGT-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-agt-01-2026-10-21/README.md), seis pruebas API PostgreSQL y nueve frontend PASS, build, lint y Chromium escritorio/móvil PASS. **GTF-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-gtf-01-2026-10-21/README.md), 25 pruebas, build, lint y Chromium escritorio/móvil PASS. Funciones obligatorias de fase 1 implementadas localmente; aceptación operativa y gates reales pendientes. TCK conserva **gate Meta real pendiente** según [contrato frontend](modules/frontend.md), sin acta real posterior localizada. |
| PERF-01/02, FIL-01, SRCH-01 | Lista sin N+1, paginación, filtros y búsqueda básica | **PERF-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-perf-01-2026-10-21/README.md), 14 pruebas PostgreSQL PASS y payload idéntico al baseline capturado; 7/37 hilos pasan de 15/75 consultas a 1/1 con autenticación de fixture. SQL selecciona una sesión por hilo y aplica el cap antes de materializar. **PERF-02 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-perf-02-2026-10-21/README.md), 21 pruebas PostgreSQL y 29 casos frontend únicos PASS, build, lint y Chromium escritorio/móvil PASS. Páginas de 100 con aviso y carga adicional, 250 hilos alcanzables; refresca juntas las páginas cargadas. **FIL-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-fil-01-2026-10-21/README.md), 52 pruebas PostgreSQL y 119 casos frontend únicos PASS, build, lint y Chromium escritorio/móvil PASS. Segmentos AND en servidor, scope de cursor y cancelación al cambiar, con borrador conservado. **SRCH-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-srch-01-2026-10-21/README.md), 41 pruebas PostgreSQL y 134 frontend únicas PASS, build, lint y Chromium escritorio/móvil PASS. Búsqueda de contacto/teléfono/cliente con segmentos, debounce y atajos; EXPLAIN de 1.004 hilos, sin índice nuevo. |
| HIST-01/02/03 | Historial conservado completo, scroll estable, mensajes nuevos sin secuestrar la lectura | **HIST-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-hist-01-2026-10-21/README.md), 77 casos frontend únicos PASS, build, lint y Chromium escritorio/móvil PASS. Recorre el historial conservado, acumula páginas y ancla inserciones; 200 mensajes sin duplicados con variación visual <1 px. **HIST-02 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-hist-02-2026-10-21/README.md), 96 pruebas únicas PASS, build, lint y Chromium escritorio/móvil PASS. Conserva lectura ante llegadas, contador sin duplicados y retorno suave; ancla sin variación al leer julio y recibir mensajes de octubre. **HIST-03 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-hist-03-2026-10-21/README.md), 33 pruebas PostgreSQL únicas PASS (22 nuevas y 11 afectadas). Consulta centrada 25+destino+24, flags de continuidad, destino oculto marcado y aislamiento por hilo/org. Conserva página reciente, cursor anterior y metadatos vigentes. |
| UNR-01/02 | Conteos por usuario, lectura y divisor con la semántica acordada | **UNR-01 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-unr-01-2026-10-21/README.md), 35 pruebas PostgreSQL únicas PASS (24 nuevas, 11 afectadas), incluidas dos carreras reales. Estado por empleado/hilo, conteo solo del episodio vigente y POST read monótono con permiso view. Migración aditiva M3 generada y probada en bases temporales, sin aplicarla a la base de trabajo. **UNR-02 implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-unr-02-2026-10-21/README.md), 125 pruebas frontend y 41 API PASS; build, lint y Chromium escritorio/móvil PASS. Contador por hilo/total de todas las páginas, divisor y lectura con foco/visibilidad tras 1,5 s; reintento silencioso y ancla 0 px al retirar divisor. M3 sigue pendiente de aplicar a la base de trabajo. |
| RETRY-01 | Reintento explícito de fallo conocido conforme a B4 | **Implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-retry-01-2026-10-21/README.md), 29 pruebas API y 106 casos frontend únicos PASS en evidencia compuesta; build, lint y Chromium escritorio/móvil PASS. Misma fila/cuerpo/autor/key, una transición en carrera real, ventana cerrada sugiere llamar. Nunca resetea UNCERTAIN, evidencia externa ni autoridad invalidada. Sin migración nueva. |
| WIN-01 | Ventana de 24 h visible en composer | **Implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-win-01-2026-10-21/README.md), 19 pruebas API y 84 casos frontend únicos PASS en evidencia compuesta; build, lint y Chromium escritorio/móvil PASS. Proyección de vencimiento, aviso bajo 12 h, cierre entre ticks y guard de Enter; conserva borrador y vuelve a habilitarse con ventana renovada. Sin migración nueva. |
| CTX-01 | Contexto mínimo del cliente y enlace al expediente | **Implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-ctx-01-2026-10-21/README.md), 20 pruebas API y 112 casos frontend únicos PASS en evidencia compuesta; build, lint y Chromium escritorio/móvil PASS. Contexto de solo lectura del cliente vinculado, mascotas y última cita anterior; expediente correcto en dos clics. Scope estricto por clínica, sin historia clínica ni migración nueva. |
| ASN-01 | Asignación explícita a colega | **Implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-asn-01-2026-10-21/README.md), 20 pruebas API PostgreSQL y 25 frontend únicas PASS en evidencia compuesta; build, lint y navegador escritorio/móvil PASS. Directorio mínimo y UUID estricto, permiso send DB del objetivo, lock compartido con claim, fence y auditoría tras commit sin PII. Conserva borrador y no inventa acuse/push. M3 sigue pendiente de aplicar a la base de trabajo; recepción/Meta pospuestos. |
| RPL-01..07, MED-01..05 | Replies y media entrante completos, permisos, expiración y estados de error | **Fase 3 obligatoria implementada y verificada localmente (22-10).** RPL-01..06 conservadas; RPL-07 conecta `context.message_id` tras admisión B4 y verifica su matriz. MED-01..05: M4, captura atómica, storage privado local/B2, worker acotado/reintentos, purga/reconciliación, proxy por clínica y previews/controles. 170 pruebas PostgreSQL y 257 frontend únicas PASS; build, lint, drift y Chromium escritorio/móvil PASS con servicios simulados. [Evidencia fase 3](evals/inbox-phase3-2026-10-22/README.md). M2/M3/M4 sin aplicar a bases habitual/preview; procesamiento apagado por defecto. Gates B2/privacidad/lifecycle y recepción/Meta reales pendientes; MED-06 opcional. |
| PERF-03 | Polling incremental correcto, deduplicación y pausa en pestaña oculta | **Implementada y verificada localmente (21-10)**: [evidencia](evals/inbox-perf-03-2026-10-21/README.md), 123 pruebas API y 259 frontend únicas PASS en evidencia compuesta; build, lint, drift y Chromium escritorio/móvil PASS. Cursores por usuario/consulta, upserts/retiradas, floor firmado y recuperación del rango leído. Con 6.001 mensajes y 50 cargados: 52.002 → 303 bytes JSON estable; índice existente, sin nueva migración. M3 sigue sin aplicar y SSE mantiene NO-GO. |
| DoD operativo §13 | Prueba de diez minutos con recepción y validaciones reales exigidas por el plan | **Pendiente real.** No se localizó acta de recepción ni validación Meta posterior; [readiness existente](evals/profile-beta-1-operational-readiness.md) conserva responsables/simulacro/fallback PENDING_REAL. Faltan prueba con recepción de los ocho puntos de §13, acuses Meta y media real con sus gates. El FAIL de seguridad de r12 continúa vigente. Ninguna prueba local de CMP-01 acredita estos requisitos. |

**Acción completada (20-10): WA-CMP-01.** El cierre del plan original recomienda
expresamente este siguiente paso; no tiene dependencias pendientes y su carencia
se confirmó en el textarea de altura fija. Se implementó auto-resize de 40–120 px,
contador visible al superar 3600/4000 y advertencia desde 3800, conservando envío,
idempotencia y limpieza al cambiar de hilo.

**Acción completada (20-10): WA-GRP-01.** Agrupación visual de consecutivos del
mismo autor a menos de cinco minutos y dentro del mismo día de la clínica.
Cada mensaje conserva cuerpo, hora, estado y reintento. Un UUID público de autor
humano distingue homónimos; datos legacy/optimistas sin identidad permanecen
separados. No cambia la deduplicación del envío. [Evidencia dirigida](evals/inbox-grp-01-2026-10-20/README.md):
19 tests frontend y cuatro backend PASS, build y Chromium escritorio/móvil PASS.

**Acción completada (20-10): WA-CPY-01.** Copia del cuerpo original y teléfono,
link telefónico y autolink HTTP/HTTPS como nodos React, sin ejecutar HTML.
Disponible con teclado y pantalla táctil, incluido teléfono de hilos archivados.
[Evidencia dirigida](evals/inbox-cpy-01-2026-10-20/README.md): 18 casos únicos PASS
(ocho conservados y diez corregidos), build y Chromium escritorio/móvil PASS.

**Acción completada (20-10): WA-TAB-01.** El título muestra `(N) SaaslyVet`
en segundo plano usando `has_unanswered` del último poll, y se restaura al foco
o al salir del Inbox. [Evidencia dirigida](evals/inbox-tab-01-2026-10-20/README.md):
siete pruebas nuevas y build PASS; lint conserva sólo los dos errores previos.

**Acción completada (21-10): WA-VIS-01.** Polling de lista/hilo detenido mientras
la pestaña está oculta, refresh inmediato al volver y selección vigente conservada.
[Evidencia dirigida](evals/inbox-vis-01-2026-10-21/README.md): 17 pruebas, build y
lint PASS; Chromium con visibilidad controlada registró cero polls durante 21 s
oculto y ambos GET en menos de 47 ms al volver.

**Acción completada (21-10): WA-VER-01.** Badge de verificación en lista y cabecera,
incluidos hilos archivados; distingue coincidencia de teléfono de verificación.
[Evidencia dirigida](evals/inbox-ver-01-2026-10-21/README.md): 15 pruebas, build,
lint y Chromium escritorio/móvil PASS. No modifica permisos de identidad.

**Acción completada localmente (21-10): WA-LDE-01.** Carga inicial, error y
reconexión persistentes en ambos paneles, con datos y borrador conservados.
[Evidencia dirigida](evals/inbox-lde-01-2026-10-21/README.md): 18 pruebas, build,
lint y Chromium escritorio/móvil PASS. La caída se simuló abortando peticiones;
el ensayo de backend/recepción real sigue pendiente.

**Acción completada localmente (21-10): WA-AGT-01.** Indicador del turno activo
y bloqueo visual de Tomar/Liberar, sin cambiar la autoridad de TurnWork.
[Evidencia dirigida](evals/inbox-agt-01-2026-10-21/README.md): seis pruebas API
PostgreSQL y nueve frontend, build, lint y Chromium escritorio/móvil PASS.

**Acción completada localmente (21-10): WA-GTF-01.** Botón al alejarse más de
200 px del fondo, retorno con foco conservado y control móvil libre de superposición.
[Evidencia dirigida](evals/inbox-gtf-01-2026-10-21/README.md): 25 pruebas, build,
lint y Chromium escritorio/móvil PASS. Anclaje e historial acumulativo pendientes.

**Acción completada localmente (21-10): WA-PERF-01.** Lista agrupada y anotada
en SQL, sin consultas por hilo ni materialización del historial de episodios.
[Evidencia dirigida](evals/inbox-perf-01-2026-10-21/README.md): 14 pruebas API
PostgreSQL PASS, payload idéntico al baseline y consultas 15/75 → 1/1 para 7/37 hilos.

**Acción completada localmente (21-10): WA-PERF-02.** Paginación explícita de
100 hilos, botón «Cargar más» y refresco que conserva todas las páginas cargadas.
[Evidencia dirigida](evals/inbox-perf-02-2026-10-21/README.md): 21 pruebas API
PostgreSQL y 29 casos frontend únicos PASS; build, lint y Chromium escritorio/móvil
PASS. Se conservan dos fallos iniciales del harness y su corrección dirigida.

**Acción completada localmente (21-10): WA-HIST-01.** Scrollback mediante
`next_before`, historial acumulado y anclaje al insertar anteriores, con carga
manual desde 500 mensajes. [Evidencia dirigida](evals/inbox-hist-01-2026-10-21/README.md):
77 casos únicos PASS, build, lint y Chromium escritorio/móvil PASS. Se conservan
los fallos iniciales del harness y sus correcciones dirigidas.

**Acción completada localmente (21-10): WA-HIST-02.** Lectura conservada ante
llegadas del poll y contador local con retorno suave al fondo, sin contar páginas
anteriores ni duplicar confirmaciones. [Evidencia dirigida](evals/inbox-hist-02-2026-10-21/README.md):
96 pruebas únicas PASS, build, lint y Chromium escritorio/móvil PASS. Se conserva
el anclaje de HIST-01 y el envío optimista/idempotente.

**Acción completada localmente (21-10): WA-HIST-03.** Endpoint `around` con
ventana cronológica acotada, continuidad y destino oculto identificado.
[Evidencia dirigida](evals/inbox-hist-03-2026-10-21/README.md): 33 pruebas API
PostgreSQL únicas PASS; cinco cortes, estados, cursores, permisos y tenant scoping.
Se conservan tres fallos iniciales del harness/fixture y su repetición dirigida.
Sin migraciones; salto desde citas/búsqueda pendiente de RPL-06/SRCH.

**Acción completada localmente (21-10): WA-UNR-01.** Estado de lectura por
empleado/hilo y contador de entrantes visibles solo del episodio vigente.
[Evidencia dirigida](evals/inbox-unr-01-2026-10-21/README.md): 35 pruebas
PostgreSQL únicas PASS, incluidas carreras de creación/avance, view-only, scope,
paginación y presupuesto de consultas conservados. Se preservan los fallos
iniciales de formato de errores y clasificación SQL, con tres repeticiones
dirigidas PASS. M3 generada/probada; base de trabajo aún sin migrar.

**Acción completada localmente (21-10): WA-UNR-02.** Contadores por empleado,
divisor y marcado automático tras 1,5 s de foco/visibilidad, con cancelación,
reintento silencioso y protección frente a GETs/acuse tardíos.
[Evidencia dirigida](evals/inbox-unr-02-2026-10-21/README.md): 125 pruebas
frontend y 41 API PASS; build, lint y Chromium escritorio/móvil PASS. Dos
empleados independientes y retirada del divisor con ancla sin variación.
Se conservan los fallos de arranque del harness, corregidos sin tocar producto.
La integración requiere M3; no se ha migrado la base de trabajo.

**Acción completada localmente (21-10): WA-RETRY-01.** Endpoint y acción para
reintentar un fallo conocido sin editar su contenido, autor o clave. Revalida
scope, epoch, cuenta y ventana, conserva acuses e incertidumbre y bloquea doble
clic/carrera. [Evidencia dirigida](evals/inbox-retry-01-2026-10-21/README.md):
29 pruebas API y 106 casos frontend únicos PASS en evidencia compuesta, build,
lint y Chromium escritorio/móvil PASS; ancla 0 px, teclado/táctil y borrador
conservados. Se preservan el timeout inicial de un test y el error de selector
del harness de navegador con sus correcciones/repeticiones dirigidas.
No se aplica M3 ni se acredita operación Meta real.

**Acción completada localmente (21-10): WA-WIN-01.** El transcript proyecta
apertura y vencimiento de la sesión vigente. El composer avisa bajo 12 h, actualiza
el tiempo y se bloquea al vencer; conserva borrador, ofrece llamar y se habilita
al recibir una ventana renovada. [Evidencia dirigida](evals/inbox-win-01-2026-10-21/README.md):
19 pruebas API y 84 casos frontend únicos PASS en evidencia compuesta, build,
lint y Chromium escritorio/móvil PASS. La ingesta real local renueva la ventana;
se conservan los timeouts iniciales de una regresión y la corrección acotada del
harness sin cambiar sus assertions ni cinco segundos. Sin nueva migración,
aplicar M3, despliegue ni aceptación Meta real.

**Acción completada localmente (21-10): WA-CTX-01.** Panel plegable del cliente
vinculado, mascotas y última cita anterior con su estado real. API de solo lectura
con permiso view y scope estricto por clínica; no busca por teléfono ni expone
notas clínicas. Desde el chat abierto llega al expediente correcto en dos clics.
[Evidencia dirigida](evals/inbox-ctx-01-2026-10-21/README.md): 20 pruebas API y 112
casos frontend únicos PASS en evidencia compuesta, build, lint y Chromium
escritorio/móvil PASS. Carga y error propios, abort al cambiar/cerrar, historial y
borrador conservados. Recibos iniciales de fallo y timeout preservados, sin rebajar
assertions ni umbrales. Sin migración nueva, aplicar M3 ni aceptación Meta real.

**Acción completada localmente (21-10): WA-PERF-03.** Cursores firmados por
organización/usuario/consulta, delta de lista y transcript, retiradas explícitas y
recuperación completa del rango leído. Mantiene una petición activa por recurso,
pausa por visibilidad y conserva borrador/ancla al cambiar datos o recuperar cursor.
[Evidencia dirigida](evals/inbox-perf-03-2026-10-21/README.md): 123 pruebas API y 259
frontend únicas PASS en evidencia compuesta; build, lint, drift y Chromium
escritorio/móvil PASS. Payload JSON estable 52.002 → 303 bytes con 6.001 mensajes,
50 cargados; EXPLAIN usa el índice existente. Ancla 0,15625 px y recuperación 0 px.
Tracking optativo de updated_at en cinco modelos, sin alterar autoridad B4. Recibos
iniciales conservados, sin rebajar assertions ni umbrales. Sin migración nueva,
aplicar M3, despliegue ni aceptación operativa/Meta real.

**Acción completada localmente (21-10): WA-FIL-01.** Segmentos «Sin atender»,
«Esperando cliente», «Urgentes» y «Míos», combinados en SQL antes de paginar y
ligados al scope del cursor. Cancelación de GETs y reinicio de páginas al cambiar,
con chat, borrador y total personal de no leídos conservados.
[Evidencia dirigida](evals/inbox-fil-01-2026-10-21/README.md): 52 pruebas API y
119 frontend únicas PASS; build, lint y Chromium escritorio/móvil PASS.
Un selector erróneo del harness se corrigió y repitió de forma acotada, conservando
los nueve PASS iniciales. Sin nueva migración, aplicar M3, despliegue ni activación.

**Acción completada localmente (21-10): WA-SRCH-01.** Búsqueda de contacto,
teléfono parcial/formateado y cliente vinculado, combinada con segmentos y archivo
antes de paginar. Debounce 250 ms, mínimo dos caracteres, Ctrl/Cmd+K y Escape,
scope de cursor y respuestas tardías protegidos, chat/borrador conservados.
[Evidencia dirigida](evals/inbox-srch-01-2026-10-21/README.md): 41 pruebas API y
134 frontend únicas PASS; build, lint y Chromium escritorio/móvil PASS.
EXPLAIN: 17,869 ms con 1.004 hilos sintéticos; navegador con API sintética bajo
un segundo. Fallo inicial de fixture preservado y corregido sin rebajar criterios.
Sin nueva migración, aplicar M3, despliegue ni activación. El usuario pospone
recepción/Meta para después; se conserva como pendiente real.

**Acción completada localmente (21-10): WA-ASN-01.** Asignación a compañeros
activos de la clínica con permiso DB para responder, directorio mínimo y selector
de cabecera. Lock compartido con claim, fence de autoridad y auditoría tras commit
sin PII. Repetición idempotente, asignaciones múltiples, borrador conservado y
respuestas tardías descartadas; no inventa acuse de handoff ni push.
[Evidencia dirigida](evals/inbox-asn-01-2026-10-21/README.md): 20 pruebas API y 25
frontend únicas PASS en evidencia compuesta, dos carreras PostgreSQL reales, build,
lint y navegador escritorio/móvil PASS. Se preservan los fallos de fixture/aserción,
lint y el defecto real de ruta legado corregido con UUID estricto, con repeticiones
acotadas. Sin migración nueva, aplicar M3, despliegue ni activación.

**Acción completada localmente (21-10): WA-RPL-01.** Modelo nullable
`Message.reply_to`, destino protegido de borrado e índice único de consulta.
Validación compartida por clínica/persona/cuenta, incluida en el save normal;
permite citas entre episodios y conserva destinos ocultos o descartados.
[Evidencia dirigida](evals/inbox-rpl-01-2026-10-21/README.md): 19 pruebas PostgreSQL
únicas PASS (14 nuevas y cinco afectadas), drift y Django check PASS. M2 conserva
todas las columnas históricas y admite writers anteriores/nuevos. Ensayo repetido
solo para compatibilidad con el nombre normal de una base test_; sin fallos de
producto. Sin aplicar M2/M3 a la base habitual, despliegue ni activación.

**Acción completada localmente (21-10): WA-RPL-02.** Webhook firmado resuelve
`context.id` dentro de la cuenta receptora e ingesta revalida clínica/persona/cuenta
bajo lock antes de guardar la FK. Referencias inexistentes, ambiguas o ajenas quedan
nulas sin perder el entrante; warning sin contenido personal solo para mensajes nuevos.
[Evidencia dirigida](evals/inbox-rpl-02-2026-10-21/README.md): 40 pruebas PostgreSQL
únicas PASS (21 nuevas y 19 afectadas), en evidencia compuesta; carrera real de
duplicados, firma y límites B1 conservados. Drift/Django check PASS. Se preserva el
fallo inicial de fixture por borrado masivo bloqueado y su repetición acotada.
Sin migración nueva, aplicar M2/M3, despliegue ni activación.

**Acción completada localmente (21-10): WA-RPL-03.** API acepta `reply_to_id`
scoped bajo lock antes de takeover/outbox. Proyecta cita de un nivel y excerpt
de 80 caracteres, estado y autor. Idempotencia y retry conservan la cita original;
transcripts reciente/histórico/around/delta cargan sus relaciones sin N+1.
[Evidencia dirigida](evals/inbox-rpl-03-2026-10-21/README.md): 42 pruebas PostgreSQL
únicas PASS (25 nuevas, 17 afectadas), incluida carrera real con dos citas distintas
y la misma key. Drift/Django check PASS. EXPLAIN: 1,49 ms, índice existente;
6.001 mensajes/50 cargados: full 52.804 bytes, delta estable 303 bytes.
Sin migración nueva, aplicar M2/M3, despliegue ni activación.

**Prerrequisito resuelto localmente (22-10, RPL-07):** sender y adaptador
Meta incorporan `context.message_id` scoped con wamid utilizable, después de la
admisión B4. Sin evidencia externa se conserva la cita interna; resultados
ambiguos siguen uncertain sin resend. La validación Meta real continúa pospuesta.

**Acción completada localmente (21-10): WA-RPL-05.** Acción Responder junto a
Copiar, accesible por hover/foco/táctil, y chip único sobre el composer con autor y
extracto Unicode acotado. Escape/× conservan texto; enviar captura la cita por
intento y limpia el chip; retry preserva referencia y key. Cambio de hilo/cuenta o
episodio cancela sin afectar citas nuevas por acuses tardíos. Tmp y ventana cerrada
deshabilitados. [Evidencia dirigida](evals/inbox-rpl-05-2026-10-21/README.md): 61
pruebas frontend únicas PASS (27 nuevas, 34 afectadas), build, lint y Chromium
escritorio/móvil PASS con API sintética. Fallo inicial del reloj de fixture y
repetición de un solo caso conservados. Sin cambiar backend, migrar M2/M3,
desplegar ni activar. No acredita aún el payload nativo Meta.

**Acción completada localmente (22-10): WA-RPL-06 + WA-RPL-04.** Conjunto mínimo
inseparable: el salto requiere la cita pulsable dentro de las burbujas. Bloque de
un nivel con autor/extracto/media/no enviado, visible en ambos sentidos y legible
sin send o en archivo. PK independiente de client_message_id, around si falta,
merge sin duplicados y foco/resaltado de dos segundos, con movimiento reducido.
Conserva borrador, cadena before, floor ampliado y avisos reales; cancela búsquedas
anteriores y evita que un GET previo sustituya la página recién abierta. Errores
sin inventar contenido ni borrar historial. [Evidencia dirigida](evals/inbox-rpl-06-04-2026-10-22/README.md):
128 pruebas frontend únicas PASS (45 nuevas, 83 afectadas), build, lint y Chromium
escritorio/móvil PASS con API sintética. Los 127 PASS iniciales se conservan y se
añade un caso específico para el destino oculto durante el resaltado, sin repetir
la suite. Sin cambiar backend, aplicar M2/M3, desplegar ni activar.

**Fase 3 obligatoria completada localmente (22-10): RPL-07 y MED-01..05.**
170 pruebas PostgreSQL y 257 frontend únicas PASS, build, lint, drift y Chromium escritorio/móvil
PASS. [Expediente compuesto](evals/inbox-phase3-2026-10-22/README.md) y
[operación media](runbooks/inbox-media.md). Sin aplicar M2/M3/M4 a bases
habitual/preview, despliegue ni activación. Recepción/Meta reales y gates de
privacidad/B2/lifecycle pendientes; MED-06 opcional. Fase 4 ya cubierta por
PERF-03 con SSE NO-GO; fase 5 requiere evidencia y priorización, no se inicia aquí.

La inspección anterior usa fuentes del checkout actual y evidencia histórica
identificada, sin suites generales ni una nueva campaña B9. Los resultados nuevos
de estas tareas se registran en [CMP-01](evals/inbox-cmp-01-2026-10-20/README.md)
y [GRP-01](evals/inbox-grp-01-2026-10-20/README.md),
[CPY-01](evals/inbox-cpy-01-2026-10-20/README.md) y
[TAB-01](evals/inbox-tab-01-2026-10-20/README.md).

## 4. Reglas de ejecución desde ahora

1. Trabajar una tarea WA o un conjunto mínimo inseparable. Cambiar solo lo necesario
   para su criterio de aceptación; actualizar esta tabla al terminar.
2. Conservar los PASS válidos. Ejecutar únicamente pruebas nuevas o afectadas y los
   checks exigidos por el cambio. Justificar por dependencia cualquier repetición;
   no trasladar resultados a código modificado sin comprobar su aplicabilidad.
3. Un fallo de entorno/harness no se atribuye automáticamente al producto. Conservar
   el recibo y resolver la causa mínima, sin rebajar aserciones, guards o umbrales.
4. No iniciar automáticamente otra campaña B9 para buscar verde. Sus cinco perfiles
   sí son requisitos acordados para obtener aquella aceptación integral; retomar
   esa aceptación requiere una decisión explícita y acotada, conservando lo válido.
5. Seguridad sigue siendo un gate aplicable. La clasificación de hallazgos y cualquier
   remediación deben basarse en evidencia. No añadir allowlists generales ni cambiar
   configuración congelada para forzar PASS; documentar el cambio concreto si procede.
6. Lint y auditorías conservan su carácter advisory. No convertir deuda no bloqueante
   en condición nueva para implementar funciones o terminar una ejecución.
7. No reabrir E4, D29/R1-04, tuning, barridos, capacidad comercial, scheduler nuevo,
   SSE, extensiones E o features opcionales para cerrar este hito.
8. No modificar recibos o copias selladas históricos. La evidencia nueva debe ser
   suficiente y recuperable; no recrear expedientes completos sin una necesidad concreta.

## 5. Criterio de terminación

**Inbox completo según el alcance original:** tareas obligatorias de fases 0–3 y
PERF-03 acreditadas, DoD operativo y técnico de §13 satisfecho, seguridad y gates
aplicables aprobados. Los 355 PASS por sí solos no acreditan este resultado.

**Cierre administrativo con pendientes:** requiere una decisión explícita del usuario
sobre el alcance que se entrega y el backlog que se transfiere. Registrar qué falta;
no marcarlo como implementado, aprobado ni listo para uso real.

**Campaña B9 r12:** ejecución terminada y documentada con FAIL en seguridad. No falta
otra campaña para cerrar esa ejecución. Obtener aceptación integral PASS es un
objetivo distinto y sus requisitos no se eliminan mediante este documento.

**Activación o producción:** decisión separada, con los requisitos humanos, de
privacidad y de capacidad aplicables. Esta guía no autoriza activar, desplegar,
crear commits ni publicar cambios.
