# Acta de implementación B1 — Evidencia única del turno y evento de canal

Fecha: 2026-09-14. Base funcional: B0 cerrado en `ecd7912`. Fuente de verdad: [fase B1 del plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md). Alcance exclusivo B1; esta acta no vuelve a auditar H01–H20.

Estado técnico: **implementada y validada localmente**, sin despliegue.

## Entrega

`TurnContext` fija una única raíz causal por intento. El worker lo construye con los inbounds reclamados; el wrapper del planner normaliza los callers directos antes de distribuir. Policy, planner, prompts, guard de historial y wrapper del arbiter reciben el mismo valor. El arbiter conserva `TurnFacts`/`CommitmentView` puros. El adaptador de ORM para `triggered_by` y el assessment existente carga únicamente los IDs de C1, conserva su orden y rechaza cambios en la evidencia; no modifica su semántica de autorización.

Es un `dataclass(frozen=True, slots=True)` en memoria, con eventos igualmente inmutables y colecciones tuple. Contiene IDs de organización, conversación, cuenta/canal y contacto; eventos e inbound IDs; anchor del último mensaje; límite histórico exclusivo anterior al primero; reloj y zona de la clínica. No contiene ORM, transcript completo, goals, datos clínicos, tools, permisos ni estado futuro de B3. No se añade ninguna tabla, migración ni backfill.

El cursor es `(Message.created_at, Message.id)` local. `history_before` contiene la coordenada del primer inbound y se consulta con `<`: representa la posición inmediatamente anterior, no una fila sintética de mensaje previo. `anchor` es la coordenada del último inbound. El estado técnico controla elegibilidad, nunca la relación temporal. Los miembros actuales se agregan al prompt una sola vez desde C1; los mensajes posteriores al límite no entran en historia ni modifican el texto congelado. No se usa el timestamp de Meta para ordenar.

La historia exige organización+contacto+cuenta. Los cuerpos de otros episodios requieren verificación vigente; se conserva p58 D19 para hechos de existencia/fecha de contacto previo sin revelar su contenido. Salientes pendientes del humano siguen visibles en Inbox, pero no acreditan emisión para el prompt. Recibos requieren emisión y estar antes del cursor, conservando su alcance al episodio actual.

## Contrato de eventos de canal

Módulo `backend/apps/channels/events.py`; productor `views._extract_body`; lector `event_from_message`. Se conserva `Message.body` como única copia persistida del texto/caption/título. `raw_metadata.type` y `raw_metadata.timestamp` mantienen su significado diagnóstico.

La clave reservada **`Message.raw_metadata._channel_event`**, versión entera **1**, contiene exactamente:

| Campo | Contrato |
| --- | --- |
| `version` | `1`; ausente/desconocida/malformada se interpreta como desconocida |
| `event_type` | Tipo real recibido, incluido `interactive`, `button`, imagen/documento/audio |
| `body_source` | `text`, `caption`, `title` o `none`; indica el origen de `Message.body` |
| `interaction_type` | `button_reply` o `list_reply` cuando corresponde; conserva otros tipos declarados sin inferir acciones |
| `reply_to_id` | `context.id` real, o null |
| `action_id` | ID real de botón/lista o payload explícito de botón de plantilla, o null |
| `media_reference_id` | Referencia de media del proveedor, o null; nunca se descarga |
| `media_mime_type` | MIME declarado, o null; no demuestra comprensión |

El lector valida versión, campos, tipos y coherencia entre origen/tipo de evento y `Message.payload_type`; no interpreta JSON externo arbitrario. Caption y título se exponen como propiedades estructuradas derivadas del cuerpo y su origen validado. El texto original conserva espacios y caracteres. No existe una segunda normalización almacenada en el contrato actual: `normalized_text=None`. La ausencia de ID nunca se cubre con el título.

Los eventos antiguos conservan su body y `payload_type`; sin proyección válida quedan desconocidos tipo real, origen/caption/título, reply/action y referencia de media. No se leen esos datos desde claves crudas antiguas ni se rellenan por coincidencia de texto. No se sintetizan IDs ni causalidad. El `payload_type` histórico `button_reply` se conserva también para listas por compatibilidad del modelo; el subtipo real vive en la proyección validada.

Imagen/documento con caption aporta ese texto a los matchers existentes y al LLM. Todo adjunto sigue marcado sin comprensión binaria, incluso si lleva caption. Media sin texto interpretable produce una limitación explícita y ofrece texto/persona antes de interpretar un pending viejo. No hay OCR, transcripción, descarga, storage nuevo ni hechos clínicos/de negocio deducidos del binario.

`channels.selectors.referenced_message` permite únicamente la consulta exacta de un ID explícito anterior al cursor en la misma organización, cuenta, contacto y episodio. Rechaza referencias ajenas, ambiguas, posteriores o salientes no emitidos. Es lectura acotada para inspección; no se integra como resolución semántica de negocio, no retoma operaciones ni concede consentimiento. E1/B7B siguen pendientes.

## Compatibilidad y desviaciones acotadas

- **B1-D01 — Grafo desactualizado.** Las búsquedas localizaron los símbolos, pero algunos snippets cortaban funciones por posiciones antiguas. Se leyeron solo sus fuentes y dependencias directas; no se reindexó ni exploró todo el agente.
- **B1-D02 — Lista sin opción propia en el modelo.** `Message.PAYLOAD_CHOICES` solo ofrece `button_reply`. Añadir `list_reply` exigiría una migración de opciones. La corrección mínima conserva ese valor de compatibilidad y registra `event_type=interactive`, `interaction_type=list_reply` e ID real en la proyección v1. Sin pérdida del subtipo runtime ni migración.
- **B1-D03 — Callers legacy.** Prioridad: C1 explícito → `burst_messages` reales → `triggered_by` real → entradas de texto de tests/callers antiguos. Sin argumentos, la entrada directa usa únicamente el último inbound local, sin inventar agrupaciones. Las entradas de texto sin mensajes no tienen IDs/anchor/cursor histórico (`None`) ni acceso a una historia cuya relación causal no se conoce. Una lectura standalone sin ningún inbound usa solamente un corte por la hora de lectura, con `message_id=None`, sin inventar un ID ni un turno recibido. Se adaptan fixtures del prompt para incluir `contact`, como hace la ingestión productiva.
- **B1-D04 — Media y expectativa anterior de F5.** El test anterior exigía enviar media vacía al LLM para improvisar su limitación desde historia. B1 exige una limitación segura y explícita sin fingir comprensión. Se sustituye esa expectativa y se conserva el camino de texto/caption, sin mover los guards de humano, bloqueo o kill switch. El circuito safety independiente sigue correspondiendo a B5.
- **B1-D05 — Permiso de hechos de recurrencia.** La referencia a p58 diferencia transcript privado de existencia/fecha de contacto previo. El nuevo cursor se aplica a ambos; se conserva ese permiso anterior de hechos mínimos para no convertir B1 en un cambio de identidad/privacidad. Las pruebas verifican contenido excluido con identidad ausente/caducada y fecha real disponible.

## Validación

La selección final CTX-01/CHANNEL-01 y continuidad ejecutó **105 tests, 0 fallos, 0 errores, 0 skips** en PostgreSQL 18.3 local aislado, Python 3.13.2 / Django 6.0.3. Incluye 29 tests nuevos de B1 y regresión de los cuatro módulos más `test_f2_continuity`; los subtests amplían la matriz de tipos/estados. Incorpora la aclaración D05 y prueba que un reply/action con título afirmativo no crea autorización. La pasada anterior de los cuatro módulos había aprobado 86 tests.

```powershell
rtk proxy python manage.py test apps.agent.tests.test_worker apps.agent.tests.test_turn_decision apps.agent.tests.test_prompts apps.channels.tests.test_webhook apps.agent.tests.test_f2_continuity --noinput
```

CTX-01 cubre worker real, orden estable con empate temporal, identidad de C1 entre consumidores, bytes de la ráfaga en el wrapper del arbiter, primer contacto con inbounds ya PROCESSED, pasado PENDING/PROCESSED/FAILED, historia permitida recurrente, exclusión del burst y de un inbound que llega durante el ensamblado, reloj fijo, inmutabilidad y compatibilidad sin IDs fabricados. CHANNEL-01 cubre texto, media vacía, captions, botón/lista y botón de plantilla, título distinto del ID, context/reply, referencia local y aislamiento, legacy, validación y caption crítico en safety existente. Las pruebas de media vacía exigen cero llamadas al planner/commit y respuesta de limitación.

Las primeras pasadas no se presentan como verdes: 57 tests iniciales tuvieron 5 fallos y 1 error por fixtures sin `contact`/versión esperada del prompt; la primera matriz de 86 tuvo 2 fallos por un reloj futuro de fixture que permitía recoger el inbound tardío y una caducidad de 90 días menor al TTL real de 182 días. Se corrigieron los fixtures sin modificar claim/leases/TTL.

No se llama a proveedores reales ni se ejecuta contra producción. Los tests se descubren dentro de los módulos existentes en CI; no se atribuye ejecución remota a esta validación local.

La selección de compatibilidad aprobó **179 tests, sin fallos/errores/skips**, en `test_planner`, `test_policy`, `test_arbiter`, `test_w0_hardening`, `test_w1_experience`, `test_f5_fase5` y `test_b0_containment`. Las repeticiones no se suman como nuevos casos. Esta es una selección por impacto de B1, no la suite total del repositorio ni una repetición de la auditoría.

B0 se repitió además con **`CriticalB0Runner`: 17 tests aprobados, sin omisiones ni skips**. Se conserva su contención y no se modifica su corpus ni su runner.

Tras explicitar `message_id=None` en el corte temporal de lectura standalone, se repitieron **12 tests, todos PASS sin skips**: fechas, autoría, recibos, guard de historial y adaptación legacy sin IDs. Esta repetición cubre el último ajuste de código; no introduce casos adicionales en los conteos anteriores.

```powershell
rtk proxy python manage.py test apps.agent.tests.test_planner apps.agent.tests.test_policy apps.agent.tests.test_arbiter apps.agent.tests.test_w0_hardening apps.agent.tests.test_w1_experience apps.agent.tests.test_f5_fase5 apps.agent.tests.test_b0_containment --noinput
rtk proxy python manage.py test apps.agent.tests.test_b0_containment --testrunner apps.agent.tests.harness.CriticalB0Runner --noinput
rtk proxy python manage.py makemigrations --check --dry-run
rtk git diff --check
```

`makemigrations --check --dry-run`: **No changes detected**. Se aplicaron únicamente las migraciones existentes a la base aislada de tests. Sintaxis de los archivos modificados y `git diff --check`: PASS. No se crearon migraciones.

## Límites y activación

Los criterios B1 de H10/H11/H15 se implementan en las fronteras descritas. **H01/H02/H03/H13 no se declaran resueltos**: reciben mejor evidencia de entrada. No se avanza B2–B9, E1–E5 ni P-A/P-B; no se cambia goals, consentimiento, sender durable, leases, operaciones persistentes, capacidades o writes.

El cursor congela pertenencia y orden del intento, no es un snapshot transaccional de todos los estados de entrega o permisos. Los lectores revalidan elegibilidad/permisos al consultar. B3 y B7B deberán integrar durabilidad y evidencia exacta de emisión/consentimiento; esta entrega no los simula.

Estado operativo conservado: **PENDING_ACTIVATION_REQUIREMENTS**. Clínicas, responsables y canal alternativo siguen pendientes. No hay despliegue ni activación con tráfico real. Rollback: conservar parser de captions, lector compatible y contención B0; no volver a historia definida por `PROCESSED` ni reinterpretar metadata ausente como autoridad.
