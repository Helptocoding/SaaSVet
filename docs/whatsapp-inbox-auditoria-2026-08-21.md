# Auditoría integral del módulo WhatsApp — Paridad funcional y UX

**Fecha**: 2026-08-21
**Alcance**: subsistema de mensajería completo — `backend/apps/channels`, `backend/apps/agent`, frontend Inbox (`frontend/src/pages/inbox/`, `frontend/src/api/inbox.js`), worker/sender, webhooks, tests y documentación del módulo.
**Metodología**: auditoría basada exclusivamente en el código real del repositorio. Cada afirmación relevante lleva evidencia (`archivo:línea`). Donde la documentación dice algo que el código no confirma, se señala explícitamente.
**Pregunta central**: *si una recepcionista usa nuestro Inbox durante todo el día, acostumbrada a WhatsApp Web, ¿qué echará de menos?*

---

## Contenido

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Estado actual real](#2-estado-actual-real)
3. [Matriz completa de paridad](#3-matriz-completa-de-paridad)
4. [Las 30 cosas que probablemente no estabas considerando](#4-las-30-cosas-que-probablemente-no-estabas-considerando)
5. [UX de conversación](#5-ux-de-conversación)
6. [UX de Inbox](#6-ux-de-inbox)
7. [Historial](#7-historial)
8. [Replies / mensajes referenciados](#8-replies--mensajes-referenciados)
9. [Media y archivos](#9-media-y-archivos)
10. [Búsqueda](#10-búsqueda)
11. [Multiusuario](#11-multiusuario)
12. [IA ↔ humano](#12-ia--humano)
13. [Performance](#13-performance)
14. [Accessibility + responsive](#14-accessibility--responsive)
15. [Edge cases](#15-edge-cases)
16. [Quick Wins](#16-quick-wins)
17. [Cambios medianos](#17-cambios-medianos)
18. [Cambios grandes](#18-cambios-grandes)
19. [Lo que NO deberíamos construir todavía](#19-lo-que-no-deberíamos-construir-todavía)
20. [Roadmap recomendado](#20-roadmap-recomendado)
21. [Criterio final](#21-criterio-final)

---

## 1. Resumen ejecutivo

1. **Madurez**: el backend del subsistema es notablemente sólido para su tamaño (dedup por wamid, selector único de visibilidad, claim serializado con lock, release con testigo CAS, acuses forward-only, dead-letter de turnos). El **frontend Inbox es un prototipo funcional de una sola pantalla** (`pages/inbox/index.jsx`, 781 líneas) que explota quizá el 40% de lo que el backend ya expone.
2. La distancia con una experiencia tipo WhatsApp **no está principalmente en features ausentes del backend, sino en que la UI no consume lo que ya existe** (cursor de historial, sesiones, estados delivered/read, verificación de contacto) más un conjunto de comportamientos de mensajería que nadie implementó en ninguna capa.
3. Las 10 carencias más importantes:
   1. Historial truncado a 50 mensajes en la UI aunque el backend pagina con cursor (`views.py:882-889` vs `inbox.js:25-28` — `next_before` nunca se usa).
   2. Tu propio mensaje tarda ~2–12 s en aparecer (sin optimistic UI; además el selector oculta los salientes `pending`: `selectors.py:38-43`) — la rama "enviando…" de la UI es código muerto (`index.jsx:745`).
   3. Cero soporte de media: imágenes/audio/documentos entrantes se pierden para siempre (ni siquiera se persiste el `media id`; solo `type`+`timestamp`: `views.py:151-154`) y se pintan como `[image]`.
   4. Sin separadores de fecha ni agrupación de mensajes consecutivos.
   5. Sin replies/referencias en ninguna capa (el `context.id` de WhatsApp ni siquiera se parsea: `views.py:94-111`).
   6. Sin búsqueda (conversaciones ni mensajes) — no existe endpoint ni input.
   7. Sin contador de no leídos ni "marcar leído"; solo un punto binario `has_unanswered`.
   8. **Draft leak**: el texto sin enviar sobrevive al cambio de conversación y puede enviarse al cliente equivocado (`setSelectedThread` no limpia `body`; `index.jsx:570-579`).
   9. Estados delivered/read existen en BD pero son invisibles en la UI (solo `failed`/`pending` se renderizan: `index.jsx:740-745`).
   10. Lista de hilos con tope silencioso de 100 filas y N+1 queries por cada poll de 20 s (`views.py:771-815`).
4. **Más fáciles de corregir**: ticks delivered/read, separadores de fecha, contador de no leídos, limpieza de draft al cambiar de hilo, consumir `next_before` (todo backend-ready o casi).
5. **Requieren cambios arquitectónicos**: realtime (hoy polling 20 s/10 s, sin WS/SSE en todo el repo), media pipeline (descarga/persistencia/servido), búsqueda full-text, multi-agente con presencia.

Dos correcciones urgentes por daño potencial activo: el **draft leak** (§16.3) y el **discard silencioso de respuestas humanas** durante turnos del agente (§11.4).

---

## 2. Estado actual real (código, no documentación)

### Backend — implementado y verificado

| Componente | Evidencia |
|---|---|
| Webhook Meta firmado HMAC, fail-closed, ACK siempre 200 | `channels/views.py:39-91` |
| Dedup inbound por `(channel_account, wamid)` unique parcial | `channels/models.py:240-245`, `services.py:324-329` |
| Tabla única Message in/out; estados in: `pending→processed/discarded`; out: `pending→sent→delivered→read / failed` | `channels/models.py:151-168` |
| Acuses del proveedor forward-only (sent→delivered→read), `failed` con razón | `services.py:388-432` |
| Sender con backoff exponencial (30s·2ⁿ, cap 1h, 5 intentos), ventana 24h validada al enviar | `worker.py:35-42, 319-401` |
| Debounce de ráfagas (quiet window 8 s, tope 25 s) | `services.py:40-41, 366-385` |
| Descarte de respuesta desfasada si el cliente siguió escribiendo | `worker.py:185-226` |
| Turno con lease (`processing_until`), dead-letter a 3 intentos + escalado | `worker.py:44-47, 261-306` |
| Bandeja agrupada por `(contacto, cuenta)` con `session_count`, urgente primero | `views.py:758-815` |
| Transcript por hilo con cursor `before` (página 50) y `next_before` | `views.py:860-918` |
| Sesiones paginadas (20/página) | `views.py:833-857` |
| Claim/close/release serializados con `select_for_update`; release con testigo CAS y veredicto restore/discard | `views.py:502-595`, `services.py:499-789` |
| Handoff formal (`HumanHandoff`) con reason_code/detail/prioridad/resolución | `agent/models.py:419-493` |
| Identidad: niveles, vínculos revocables, verificación humana append-only (FLUJO-C) | `views.py:598-680`, `models.py:615-717` |
| Kill switch global, FAQ facts, token rotado cifrado write-only | `views.py:141-185, 683-703` |
| Métricas de negocio read-only | `views.py:188-222` |
| Permisos granulares `agentinbox.view/send/claim/config/identity_verify` | `views.py` (todas las vistas) |
| Deprecación RFC 8594 de endpoints viejos | `views.py:52-56, 120-138` |
| Cierre automático por inactividad (24 h) + nudge único | `policy.py:514+`, `run_agent_worker.py:69-73` |

### Backend — NO existe (verificado por inspección, no por docs)

- **Media**: ningún modelo de archivo, ninguna descarga al Graph API, ningún campo de caption/media_id. El webhook guarda `{type, timestamp}` en `raw_metadata` y descarta el resto (`views.py:143-155`). Un audio recibido hoy es irrecuperable.
- **Replies**: `msg.context` (quoted wamid) no se lee. No hay `reply_to` en `Message`.
- **Búsqueda**: cero endpoints con parámetro de búsqueda en `channels`/`agent` (grep confirmado).
- **Read-state del staff**: no hay "marcar leído", ni tabla de lectura por usuario. `has_unanswered` es un heurístico de dirección del último mensaje visible (`views.py:799-800`).
- **Realtime**: no hay WebSocket/SSE/Channels en el repo (grep confirmado). Polling del cliente: lista 20 s, transcript 10 s (`index.jsx:34-35`).
- **Plantillas HSM / envío interactivo / media saliente**: el adaptador solo implementa `send_text` (`providers.py:58-99`). Documentado como F3 en la spec — coherente código↔docs, pero sigue siendo carencia operativa (fuera de ventana 24 h todo sale `failed`, `worker.py:354-364`).
- **Marcar-como-leído hacia el cliente** (blue ticks del negocio): la Cloud API lo permite; nosotros no lo hacemos.
- **Auditoría DB de acciones de staff**: claim/close/release solo dejan logs estructurados JSON; no hay tabla append-only de acciones de bandeja (la auditoría formal existe para identidad y tools, no para gestión de bandeja).

### Frontend — implementado (una sola página)

Lista con filtros Activas/Archivadas, punto de sin-responder, badges de estado/handoff con motivo fino, banner de caso de identidad con verificar/autorizar, acciones Tomar/Liberar/Cerrar/Resetear/Revocar vínculo, composer Enter/Shift+Enter con tope 4000, burbujas in/out con autoría (Staff/Asistente/Automático), barra de métricas, token bar ADMIN + kill switch, kill-switch con gate accionable (`index.jsx` completo; `apiError` + `useConfirm` consistentes con el resto del SaaS).

### Frontend — deficiente o muerto

| Hallazgo | Evidencia |
|---|---|
| Cursor `next_before` jamás usado → **el historial visible es solo los últimos 50** | `views.py:914-916` vs `getThreadMessages(target.contact, target.account)` sin params (`index.jsx:273`) |
| `getThreadSessions` exportada y jamás llamada (navegación por episodios inexistente) | `api/inbox.js:31-34` |
| Rama "enviando…" muerta: el selector nunca devuelve salientes `pending` | `selectors.py:24-29` vs `index.jsx:745` |
| Scroll forzado al fondo ante cualquier cambio de longitud, incluso leyendo historial | `index.jsx:334-336` |
| Draft compartido entre conversaciones (riesgo de envío cruzado) | `body` no se limpia al seleccionar (`index.jsx:570-579`) |
| `contact_verification` viaja en el payload y no se muestra como badge | `views.py:907` vs `index.jsx` (solo condiciona Reset) |
| Comentario interno desactualizado ("En F0 todas las conversaciones las atiende un humano") | `index.jsx:32` — el planner completo existe (`worker.py:158-179`) |

### Discrepancias doc ↔ código relevantes

- La spec funcional (F3: plantillas, transcripción de audio UX-14, recordatorios) está documentada como plan, no como hecho — correcto, pero conviene que el backlog oficial las marque "NO IMPLEMENTADO".
- Ningún doc afirma que haya búsqueda, replies o media: no hay contradicción, simplemente nada de eso existe.

---

## 3. Matriz completa de paridad

Estados: **IMPLEMENTADO · PARCIAL · DEFICIENTE · NO IMPLEMENTADO · BLOQUEADO POR PROVEEDOR · NO APLICA**

| # | Área | WhatsApp / patrón esperado | Nuestro sistema | Estado | Impacto | Prioridad | Complejidad |
|---|------|---------------------------|-----------------|--------|---------|-----------|-------------|
| 1 | Timeline: separadores Hoy/Ayer/fecha | Sí | Ausente; timestamp por burbuja (`index.jsx:57-64`) | NO IMPLEMENTADO | Alto | **P1** | Baja |
| 2 | Agrupación de mensajes consecutivos | Sí | Ausente (gap fijo 8px) | NO IMPLEMENTADO | Medio | P2 | Baja |
| 3 | Diferenciación enviado/recibido | Sí | Sí (burbuja in/out) | IMPLEMENTADO | — | — | — |
| 4 | Estado enviando (optimistic) | Instantáneo | No; aparece tras sender (~2–12 s) | **DEFICIENTE** | Alto | **P0** | Media |
| 5 | Ticks entregado/leído | Sí | BD sí, UI no | PARCIAL | Medio | P1 | Baja |
| 6 | Mensaje fallido + reintento | Sí | Muestra "no entregado" sin acción | DEFICIENTE | Medio | P1 | Media |
| 7 | Replies/referencias | Sí | Nada en las 3 capas | NO IMPLEMENTADO | Alto | **P1** | Alta |
| 8 | Historial completo con scroll-back | Sí | Backend listo, UI truncada a 50 | **DEFICIENTE** | Alto | **P0** | Media |
| 9 | Saltar a mensaje / "ir al mensaje" | Sí | No | NO IMPLEMENTADO | Medio | P3 | Alta |
| 10 | Nuevos mensajes mientras lees (divider + botón) | Sí | No; salto forzado al fondo | DEFICIENTE | Alto | P1 | Media |
| 11 | Contador de no leídos | Sí | Solo punto binario | DEFICIENTE | Alto | **P0** | Media |
| 12 | Marcar leído (staff) | Estándar en inboxs pro | No existe | NO IMPLEMENTADO | Medio | P1 | Media |
| 13 | Blue ticks al cliente (marcar leído vía API) | Sí | No llamado (proveedor lo permite) | NO IMPLEMENTADO | Bajo | P3 | Baja |
| 14 | Búsqueda de conversaciones | Sí | Nada | NO IMPLEMENTADO | Alto | P1 | Media |
| 15 | Búsqueda dentro de conversación | Sí | Nada | NO IMPLEMENTADO | Medio | P2 | Media |
| 16 | Imágenes entrantes | Sí | Placeholder `[image]`, dato perdido | **DEFICIENTE (pérdida de datos)** | Alto | **P0** | Alta |
| 17 | Audio/notas de voz entrantes | Sí | Igual que arriba | DEFICIENTE | Alto | P1 | Alta |
| 18 | Documentos/PDF entrantes | Sí | Igual | DEFICIENTE | Medio | P1 | Alta |
| 19 | Stickers/ubicación entrantes | Sí | Tipo preservado, contenido no | DEFICIENTE | Bajo | P3 | Media |
| 20 | Envío de media (imágenes/doc) | Sí | Adaptador texto-only | NO IMPLEMENTADO (proveedor SÍ lo permite) | Alto | P1 | Alta |
| 21 | Plantillas fuera de ventana 24h | Sí (HSM) | Todo sale failed | NO IMPLEMENTADO (decisión F3 consciente) | Alto | P1 | Alta |
| 22 | Botones/listas interactivos (salida) | Sí | No | NO IMPLEMENTADO | Medio | P2 | Alta |
| 23 | Botones interactivos (entrada: title extraído) | Sí | Parcial — contexto perdido | PARCIAL | Bajo | P3 | Baja |
| 24 | Typing indicator al cliente | Sí | No (Cloud API lo soporta desde 2024) | NO IMPLEMENTADO | Bajo | P3 | Media |
| 25 | Presencia staff ("quién está viendo") | Inboxs pro | Solo `claimed_by_name` estático | NO IMPLEMENTADO | Medio | P2 | Alta |
| 26 | Advertencia de edición simultánea | Intercom/Zendesk sí | Claim 409 al tomar; nada al escribir | PARCIAL | Medio | P2 | Media |
| 27 | Asignar a otro agente | Zendesk sí | Solo auto-claim | NO IMPLEMENTADO | Medio | P2 | Baja |
| 28 | Etiquetas/notas | Inboxs pro | No | NO IMPLEMENTADO | Bajo | P3 | Media |
| 29 | Archivar vs cerrar diferenciados | Sí | Conflados (`close`=archivado) | PARCIAL | Bajo | P3 | Baja |
| 30 | Reabrir cerrada | WhatsApp no aplica / inboxs sí | No (diseño: nueva sesión) | NO APLICA/PARCIAL | Bajo | P3 | Media |
| 31 | Panel de contexto del cliente | Intercom/HubSpot | owner_name + teléfono; sin link a expediente/mascotas | PARCIAL | Alto | **P1** | Media |
| 32 | Badge de verificación de contacto | Propio SaaS | Dato viaja, UI no lo pinta | DEFICIENTE | Medio | P1 | Baja |
| 33 | Timezone de organización | — | UI usa TZ del navegador (`fmtTime`) | DEFICIENTE | Medio (multi-TZ) | P1 | Baja |
| 34 | Orden cronológico confiable (ts proveedor) | — | Ordena por llegada (`created_at`); ts de Meta ignorado | PARCIAL | Medio | P1 | Media |
| 35 | Duplicados absorbidos | — | Unique wamid | IMPLEMENTADO | — | — | — |
| 36 | Realtime push | Estándar actual | Polling 20/10 s | DEFICIENTE | Alto | **P1** | Alta |
| 37 | Paginación lista de hilos | Sí | Cap 100 silencioso | DEFICIENTE | Medio | P1 | Media |
| 38 | Virtualización de transcript | Apps grandes | Innecesario hoy (50 msgs) | NO APLICA aún | Bajo | P3 | Media |
| 39 | Enter envía / Shift+Enter salto | Sí | Correcto | IMPLEMENTADO | — | — | — |
| 40 | Auto-resize composer | Sí | CSS min/max fijos, sin JS | DEFICIENTE | Bajo | P2 | Baja |
| 41 | Contador de caracteres | Apps SMS-style | Tope 4000 silencioso | NO IMPLEMENTADO | Bajo | P3 | Baja |
| 42 | Idempotencia de envío (server) | Sistemas serios | Guard client-side solamente | PARCIAL | Medio | P2 | Baja |
| 43 | Accesibilidad teclado completa | — | Tab nativo; sin shortcuts, sin aria-live | DEFICIENTE | Medio | P2 | Media |
| 44 | Responsive tablet/mobile | — | 1 breakpoint apilando paneles | DEFICIENTE | Medio | P2 | Media |
| 45 | Auditoría de acciones de bandeja | Zendesk | Logs JSON, sin tabla | PARCIAL | Bajo | P3 | Media |

---

## 4. Las 30 cosas que probablemente no estabas considerando

Ordenadas por impacto real sobre quien usa el Inbox todo el día:

1. **Tu mensaje propio no aparece al instante** (y la UI tiene una rama muerta que finge que sí): percepción diaria de "esto está roto".
2. **El borrador viaja entre conversaciones**: escribes para Ana, clic en Beto, envías → el texto de Ana sale a Beto. Único bug de la lista con riesgo reputacional directo.
3. **Las fotos que mandan los clientes se pierden**: hoy un cliente que manda la foto de la herida de su perro deja un `[image]` vacío. Es pérdida de dato clínico-adjacente, no solo UX.
4. **El caption de la imagen también se descarta** (`_extract_body` ignora `image.caption`) — cuando llegue media, ni el texto que acompañaba a la foto existirá.
5. **Leer historial antiguo es imposible desde la UI** aunque el backend ya trae el cursor — feature gratuita atrapada en el backend.
6. **Salto forzado al fondo**: estás leyendo un mensaje de hace 3 meses, llega un mensaje, la vista te arrastra abajo (`scrollIntoView` incondicional).
7. **No sabes cuántos clientes esperan**: un punto sin número no prioriza un turno de 30 hilos.
8. **Los ticks azules/grises existen en tu base de datos y no los muestras**: costo cero, señal enorme de "producto terminado".
9. **No hay forma de saber si el agente está "pensando" ahora mismo** (`processing_until` no se publica) → recepción libera y recibe 409 `turn_in_progress` sin entender por qué.
10. **El mensaje fallido no se puede reintentar ni copiar**: con ventana de 24 h cerrada, la única salida del staff es llamar por teléfono — y el sistema no se lo sugiere.
11. **La sesión de 24 h es invisible**: no hay countdown ni aviso "ventana por cerrar" — el staff descubre el límite cuando su mensaje rebota.
12. **Doble render de identidad**: `contact_verification` llega al frontend y no se pinta; el recepcionista no distingue un número desconocido de un cliente verificado sin leer banners.
13. **Sin "responder a qué"**: cuando el staff contesta, no queda marcado qué mensaje del cliente respondió — en clínicas con varias mascotas por familia esto genera errores de interpretación.
14. **Polling ciego**: sigue golpeando el servidor con la pestaña en segundo plano toda la noche (no hay `visibilitychange`).
15. **Dos pestañas abiertas = dos pollers independientes**, sin sync: una libera y la otra no se entera hasta 10–20 s.
16. **El conteo de hilos se trunca en 100 sin avisar**: clínica con 150 contactos cree que "ya no hay más".
17. **N+1 estructural**: cada poll de lista hace 1 query por hilo (último mensaje) + 1 por conversación (handoff) y carga TODAS las conversaciones a memoria antes de agrupar (`views.py:771-815`). Con 500 clientes son ~1000 queries cada 20 s por usuario mirando la pantalla.
18. **No hay atajos de teclado**: una recepcionista con auriculares y 30 hilos necesita `j/k`, `Ctrl+K`, `Esc`. Hoy: solo mouse.
19. **No hay "copiar teléfono" / "copiar mensaje"** — acciones de 5 líneas que se usan 10 veces al día (pegarlo en el software de llamadas, compartir con el vet).
20. **Sin indicador de "nuevos mensajes abajo ↓"** flotante cuando estás scrolleando arriba.
21. **El título de la pestaña no cambia** con mensajes nuevos (`(3) WhatsApp`) — quien trabaja con varias pestañas pierde llegadas.
22. **Sonido/notificación desktop**: ninguna. La recepcionista debe vigilar la pantalla pasivamente.
23. **El preview de lista muestra `[image]`** — ni siquiera un emoji 📷 que ayude a triagear.
24. **Mensajes largos sin colapso**: un cliente que pega 2000 caracteres rompe visualmente la burbuja (72% max-width ayuda, pero no hay clamp + "ver más").
25. **URLs sin autolink** en burbujas (texto plano `pre-wrap`).
26. **Formato WhatsApp (*negritas*, _cursivas_) sin renderizar** — el cliente manda `*Luna*` y recepción ve asteriscos.
27. **Sin manejo de reconexión**: si la red cae 2 minutos, no hay banner "reconectando…", solo polls fallando en consola (lista) o toast (transcript).
28. **El botón "Enviar" no refleja la ventana 24h**: habilitado siempre, el fallo llega después.
29. **Sin timezone-awareness en "mismo día"**: `toDateString()` compara en TZ del navegador; una clínica en BC (`America/Tijuana`) con recepcionista en CDM ve "Hoy" mal cerca de medianoche.
30. **Sin métricas de operación de bandeja** (tiempo de primera respuesta, quién atendió qué): las métricas actuales son de negocio del agente, no del equipo humano.

---

## 5. UX de conversación (pantalla de transcript)

Estado actual conceptual:

```
┌──────────────────────────────────────────────────────────┐
│ Nombre · teléfono · [badge estado] · Atiende: X          │  ← header
│ [Tomar][Liberar][Cerrar]…                                │
├──────────────────────────────────────────────────────────┤
│ (banner identidad / banner motivo handoff)               │
├──────────────────────────────────────────────────────────┤
│ [burbuja in]                                    ← máx 50 │
│ [burbuja out + autor + hora + ¿falló?]                   │
│ … sin separadores de fecha, sin agrupación,              │
│   sin divider de no leídos, sin media real               │
├──────────────────────────────────────────────────────────┤
│ [textarea fija]                                 [Enviar] │
└──────────────────────────────────────────────────────────┘
```

Lo que falta para sentirse mensajería (target):

```
│ ⬇ Cargar mensajes anteriores (botón/spinner infinito)    │
│ ────── Hoy ──────                                        │
│ [msg]                                                    │
│ [msg ← grouping: sin repetir autor/hora <5min]           │
│ ───── Ayer ─────                                         │
│ …                                                        │
│ ──── Mensajes nuevos ────                                │
│ [msg nuevo]                                              │
│                              [↓ 2 nuevos mensajes] (flot)│
│ [chip de reply citado sobre el composer al responder]    │
│ [composer auto-expansible · 1234/4000 · 📎]              │
```

Detalles de comportamiento requeridos: scroll anclado (auto-scroll solo si ya estabas abajo), divider de no leídos calculado contra última lectura, hover con fecha completa, doble función del header (tap → panel de contexto), estado de la ventana 24 h visible junto al composer.

---

## 6. UX de Inbox (lista)

Actual: dos filtros, orden urgente→reciente, punto sin-responder, badge de estado, hint de handoff, contador de sesiones. Correcto como semilla, insuficiente como centro de trabajo. Falta:

- **Buscador arriba de la lista** (nombre, teléfono, dueño, contenido).
- **Contador numérico de pendientes** por fila + total junto al filtro "Activas".
- **Asignación visible en la fila**: "Atiende: María", no solo dentro del hilo.
- Segmentos: *Sin atender* (último = cliente) / *Esperando cliente* (último = nosotros) / *Urgentes*. Hoy `has_unanswered` existe en el payload y no hay filtro que lo use.
- Indicador relativo de tiempo ("hace 5 min") con fecha completa en hover.
- Avatar/inicial + color estable por contacto (reconocimiento pre-attentivo).
- Vacío de "Archivadas" diferenciado; hoy reutiliza el mismo empty state.

---

## 7. Historial (diseño conceptual)

El backend ya define el contrato correcto; lo que falta es diseño de consumo:

1. **Carga inicial**: página más reciente (50) + `conversation` vigente + banners (como hoy).
2. **Scroll-back**: al llegar a `scrollTop < umbral`, pedir `?before=next_before`, insertar arriba y **preservar offset** (delta de `scrollHeight`). Spinner arriba, no overlay completo.
3. **Nuevos mensajes durante lectura histórica**: el poll de 10 s debe fusionarse por `id` (union ordenada) sin tocar scroll salvo que el usuario esté "pegado al fondo" (`scrollTop+clientHeight >= scrollHeight - margen`). Si no está abajo: pill flotante "↓ N nuevos".
4. **Referencias futuras (reply)**: al hacer click en una cita cuyo `id` no está cargado, fetch dirigido `?around=<id>` (endpoint a agregar: página centrada) y resaltar 2 s.
5. **Búsqueda**: server-side (trigram/SearchVector sobre `body`), resultados agrupados por hilo con snippet, click → abrir hilo con `around=<id>`.
6. **Performance**: estado normalizado (map por id) para que el merge del polling no remonte el árbol; virtualización (react-window) solo si el límite montado supera ~300 nodos.
7. **Límite propuesto**: página 50, buffer máximo en memoria ~500 mensajes; después "Cargar más" manual (evita memoria ilimitada en hilos de años).

---

## 8. Replies / mensajes referenciados

Hoy: nada existe en ninguna capa. Diseño end-to-end:

1. **Seleccionar**: hover sobre burbuja → menú contextual (Responder / Copiar / Copiar teléfono). También tecla `r` con mensaje enfocado por teclado.
2. **Iniciar reply**: chip de preview sobre el composer (autor + extracto de 1 línea + ✕ para cancelar). Escape cancela.
3. **Enviar**: el payload incluye `reply_to_id` (id interno del mensaje). El backend valida que pertenezca al mismo hilo/org y lo persiste en un nuevo campo `Message.reply_to` (FK nullable; para entrantes, resolución lógica por `external_message_id`).
4. **Mostrar**: burbuja con bloque citado (borde izquierdo, autor + extracto de 80 caracteres, 📷 si era media).
5. **Click en la cita**:
   - si el mensaje está cargado → scroll suave + highlight de 2 s;
   - si no → fetch `?around=<id>`, inserción y highlight;
   - si fue descartado/failed → mostrar "mensaje no disponible (no llegó a enviarse)" en lugar de mentir.
6. **Entrantes con reply de WhatsApp**: parsear `msg.context.id` en el webhook (`channels/views.py:_extract_body` hoy lo ignora), resolverlo contra `external_message_id` y persistir la referencia aunque el original sea de una sesión anterior (el hilo agrupado por contacto lo resuelve naturalmente).
7. **Casos borde definidos desde el día 1**: original descartado (`discarded`) → cita con estado explícito "mensaje no enviado"; original fuera de página → fetch dirigido; media referenciada sin pipeline aún → cita con tipo + "contenido no disponible"; nunca inferir el contenido del original si no está en BD.

Requisito previo honesto: esto es **cambio de modelo** (`reply_to` en `Message` + parseo del webhook + migración). Sin eso, cualquier UI de replies sería decorativa.

---

## 9. Media y archivos

| Capa | Estado |
|---|---|
| **A. Proveedor (Meta Cloud API)** | Soporta entrada y salida de imagen/video/audio/documento/sticker/ubicación/contactos, captions en image/document/video, descarga vía `GET /{media-id}` con token (URLs **expiratorias** — exige persistencia propia), botones/listas, plantillas, typing indicator, mark-as-read |
| **B. Nuestro backend** | Solo guarda `{type, timestamp}` crudo (`views.py:151-154`). Ni media-id, ni caption, ni filename, ni mime. **El contenido entrante es irrecuperable desde el momento del webhook** |
| **C. Frontend** | Placeholder textual `[image]` (`index.jsx:730`) |
| **D. Falta** | Modelo `MessageMedia`, descarga al recibir (worker), storage con acceso autenticado org-scoped, thumbnails, player de audio (Meta entrega `audio/ogg; codecs=opus` — reproducible en Chrome/Edge, no en Safari viejo), política de retención (la regla PII R15 aplica doble aquí) |

Restricciones reales del proveedor a planificar:

- Las URLs de media caducan: "guardar el link" no es estrategia; hay que bajar el binario.
- El caption va dentro del objeto `image`/`document`: el parser actual también lo pierde para texto plano.
- Notas de voz: ogg/opus; documentos traen filename; stickers webp estáticos.
- Para ENVIAR media hay que subir el binario o dar un link público; las plantillas requieren header media aprobado.

Prioridad: **P0 recepción de imágenes** (los clientes veterinarios mandan fotos constantemente), P1 documentos y audio, P3 stickers/ubicación. Envío de imágenes: P1 (upload + validación + coste de storage).

---

## 10. Búsqueda

Hoy: cero en todo el stack. Diseño recomendado:

- **Fase 1 (server-side, barata)**: `GET /inbox/threads/?q=` sobre `contact_display_name`, `phone_normalized`, `owner__name`, `owner__pet__name`. Resuelve el 80% del uso real ("¿ya escribió la dueña de Luna?").
- **Fase 2**: búsqueda en contenido (`pg_trgm` o `SearchVector` sobre `body`) con endpoint propio devolviendo `{message_id, snippet, conversation}`. El frontend abre el hilo con `around=<id>` (ver §7).
- **Frontend**: input en la cabecera de la lista + `Ctrl/Cmd+K`. Debounce 250 ms, mínimo 2 caracteres.
- **Filtros con materia prima ya disponible y no expuestos**: sin responder (`has_unanswered`), urgente (`handoff_priority`), asignación (`claimed_by`), archivadas (`archived`). Fechas y "solo agente/solo humano" → P3.
- Decisión front/back: todo filtro y toda búsqueda de texto van **server-side**; filtrado cliente solo para estados transitorios de UI.

---

## 11. Multiusuario

Lo bueno (verificado): claim exclusivo serializado con lock (`views.py:514-529`), close/release bajo la misma fila, release con testigo compare-and-set y `TurnInProgress`/`ReleaseConflict` diferenciados (`services.py:499-525`).

Lo que falta cuando 2–5 personas trabajan juntas:

1. **Dos staff pueden responder a la vez sin advertencia**: `send_message` respeta el claim existente pero no bloquea ni avisa (`views.py:488-497`). Falta señal de "X está escribiendo" o al menos "reclamada por X" junto al composer (el dato existe en el header; el composer no lo usa).
2. **Sin asignación delegada**: no existe "asignar a María"; solo auto-toma. En clínicas con recepción + veterinaria esto obliga a coordinarse a gritos.
3. **Sin notificación de takeover**: si otro toma la conversación que estoy viendo, mi pantalla no cambia hasta el poll y no hay toast específico (solo el 409 al intentar acciones).
4. **Race humano↔agente real (bug latente)**: `_discard_if_superseded` descarta TODO saliente `pending` creado tras el inicio del turno, **sin filtrar `author_type`** (`worker.py:210-217`). Secuencia: cliente escribe → worker procesa → recepcionista responde (queda `pending`) → cliente manda otro mensaje antes del drain → la respuesta *humana* se descarta silenciosamente. Probabilidad baja, daño alto, corrección de una línea (excluir `author_type='human_staff'`).
5. **Sin auditoría consultable**: quién tomó/cerró/liberó queda en logs JSON, no en tabla. Para "¿quién atendió esto el martes?" hay que ir a logs de servidor.

---

## 12. IA ↔ humano

Primitivas correctas y poco comunes en proyectos de este tamaño: FSM de 4 estados, release con veredicto restore/discard sobre lo suspendido, resolución del handoff observado (no "el último"), verificación de identidad append-only con evidencia externa al teléfono, gate del kill switch.

Brechas de experiencia:

| Necesidad | Estado |
|---|---|
| Staff sabe cuándo el agente está procesando | No — `processing_until` no se publica; el 409 `turn_in_progress` llega como sorpresa |
| Ver qué respondió el agente | Sí, con autoría etiquetada (Asistente/Automático) — IMPLEMENTADO |
| Tomar control | Sí (Tomar / responder-asume) — IMPLEMENTADO |
| Devolver control | Sí (Liberar, con veredicto) — IMPLEMENTADO |
| Silenciar agente SOLO en esta conversación manteniendo atención humana | No existe: Liberar devuelve a ACTIVE (el agente vuelve) y Cerrar archiva. Falta un tercer camino "seguir yo" |
| Reactivación accidental del agente | Posible: liberada la conversación, el siguiente mensaje del cliente dispara al bot otra vez — comportamiento correcto pero invisible para el staff |
| Handoff conserva contexto | Sí, excelente: banner con goal.promise/captured/missing (`views.py:265-292`) |

Quick win específico: publicar `processing_until > now` como booleano en el thread payload y mostrar "el asistente está respondiendo…" en el header. Elimina la mitad de los 409 confusos.

---

## 13. Performance

Riesgos actuales (ordenados):

1. **`list_threads` es O(N) filas + O(N) queries**: carga todas las conversaciones de la org a memoria (`views.py:771-776`), agrupa en Python, y hace 1 query de último mensaje + 1 de handoff **por hilo** (`views.py:794-798`, `_thread_row:727`). Irónicamente la vista deprecada sí usaba `Prefetch` correctamente (`views.py:77-92`). Con 300 clientes × poll cada 20 s × 2 usuarios = ~90 queries/min extra por espectador. Corrección: `Subquery` para último mensaje y handoff abierto, o `Prefetch(...to_attr)` como la vista vieja.
2. **Tope silencioso de 100 hilos** (`THREADS_CAP`, `views.py:815`) — correctness antes que performance.
3. **Polling reemplaza arrays completos** cada 10/20 s: la reconciliación de React con keys estables aguanta miles de nodos, pero el fetch completo desperdicia ancho de banda; un `since_id` cortaría el 95% de los payloads.
4. Transcript bien acotado (50 filas + `select_related`); virtualización innecesaria mientras no se suba la página.
5. Polls nocturnos sin pausa (`visibilitychange`) — costo gratuito evitable.

Arquitectura que el código pide: agregar `?since=<id>` a ambos endpoints ahora (barato) y dejar la puerta abierta a SSE (un canal por usuario con eventos `thread.new_message`) como fase C.

---

## 14. Accessibility + responsive

**Accesibilidad**

- Positivo: elementos nativos `<button>` en la lista, `useConfirm` (nada de `window.confirm`), focus visible por defecto del navegador.
- Faltantes: textarea sin label accesible (solo placeholder, `index.jsx:754-766`); mensajes nuevos sin `aria-live` (lectores de pantalla mudos); tooltips solo `title` (inaccesibles en touch/teclado); sin shortcuts (`j/k` lista, `Esc` cancela/deselecciona, `Ctrl+K` buscar; `Enter` enviar ya existe); burbujas sin roles semánticos (`role="list"/"listitem"` + autor en aria-label); contraste del punto "sin responder" (8px teal) justo.
- Respuesta a la pregunta clave: **hoy no se puede operar el Inbox sin mouse** más allá del Tab secuencial.

**Responsive**

- Un único breakpoint (`max-width: 900px`) apila lista (40vh) + chat (50vh) simultáneos: usable en tablet vertical, incómodo en móvil (dos scrollers a la vez, header+metrics+token bar consumen el resto).
- Comportamiento objetivo: <900px navegación maestro-detalle (lista ↔ chat a pantalla completa con botón volver), metrics/token bar colapsados detrás de un menú, composer pegado al bottom con safe-area iOS.
- La barra de métricas arriba empuja el pliegue: en laptop 13" deja ~500px de chat.

---

## 15. Edge cases (lista exhaustiva)

| Caso | Comportamiento hoy | Veredicto |
|---|---|---|
| Hilo de 1000 mensajes | UI muestra 50; el resto inalcanzable | Defecto |
| Hilo de años | Igual que arriba | Defecto |
| 1 mensaje / 10 mensajes | Funciona | OK |
| Ráfaga de 10 mensajes del cliente | Debounce 8 s/25 s agrupa en un turno (`services.py:40-41`) | OK, bien hecho |
| Mensajes simultáneos de dos contactos | Worker paraleliza por conversación (SKIP LOCKED) | OK |
| Webhook duplicado | Unique wamid + pre-check + catch de carrera | OK |
| Webhook fuera de orden (llegada tardía) | Ordena por `created_at` de llegada → posible desorden histórico; ts de Meta ignorado (`raw_metadata.timestamp`) | Riesgo latente |
| Mensaje duplicado en UI tras poll | Reemplazo total del array → no duplica | OK |
| Proveedor caído | Backoff sender, luego `failed`; UI "no entregado" tras refresh; sin acción | Parcial |
| Backend caído / red intermitente | Polls fallan: consola (lista) o toast (transcript); sin banner reconectando; sin cola de salida | Deficiente |
| Dos agentes a la vez | Claim 409; envíos paralelos permitidos sin aviso | Parcial |
| Agente IA responde mientras humano escribe | Turn lease + release guard; hueco de discard de mensajes humanos (§11.4) | Bug latente |
| Dos pestañas | Pollers independientes, sin sync | Aceptable |
| Cambio de conversación al llegar mensaje | El interval del hilo anterior muere limpio | OK |
| Scroll arriba + mensaje nuevo | Salto forzado al fondo (`index.jsx:334-336`) | Defecto |
| Referencia a mensaje no cargado | N/A (no hay replies) | Pendiente |
| Archivada recibe mensaje nuevo | Se crea sesión nueva; fila reaparece activa con `session_count+1`; vista archivada muestra `current=null` sin acciones | Correcto |
| Asignada a otro usuario | Sin notificación | Deficiente |
| Cliente manda 10 seguidos | Ver ráfaga | OK |
| Audio largo / archivo enorme | Contenido descartado por diseño actual | Bloqueado internamente |
| Caracteres especiales/emojis | Sanitizado + UTF-8 | OK |
| Mensaje muy largo | Se envía; sin clamp visual de lectura | Menor |
| URLs | Texto plano sin autolink | Menor |
| Formatos WhatsApp (*bold*) | Asteriscos literales | Menor |
| Interactivo (botón) entrante | Title como body, resto perdido | Parcial |
| Mensajes cerca de medianoche / DST | TZ navegador vs `Organization.timezone` (`fmtTime`, `index.jsx:57-64` vs `organizations/models.py:26`) | Defecto multi-TZ |
| Mensajes históricos importados | No existen | N/A |

---

## 16. Quick Wins (días, impacto visual enorme)

1. **Ticks de entrega/lectura** — `status` ya viaja; renderizar ✓/✓✓/leído. Backend: 0 líneas.
2. **Separadores de fecha Hoy/Ayer/fecha absoluta** — puro frontend sobre `created_at`.
3. **Limpiar draft al cambiar de hilo** — una línea; elimina el riesgo de envío cruzado.
4. **Infinite scroll con `next_before`** — el backend ya responde exactamente lo necesario.
5. **Contador de no leídos** — v1 con heurística local (localStorage de última lectura por hilo); el punto pasa a "3".
6. **Agrupación de consecutivos** (<5 min, mismo autor).
7. **Copiar teléfono / copiar mensaje / click-para-llamar** en header.
8. **Auto-resize del composer + contador 4000.**
9. **Título de pestaña con `(N)`** al llegar mensajes fuera de foco.
10. **Badge de verificación** del contacto (dato ya en payload).
11. **Pausar polls con pestaña oculta.**
12. **Autolink de URLs + fecha completa al hover.**
13. **Estados de carga/error con reintento** en ambos paneles (hoy "Cargando…" texto plano y toast).

---

## 17. Cambios medianos (backend + frontend)

1. **Optimistic send + idempotency key** (header `Idempotency-Key`, unique en Message) + mostrar el pending propio en transcript (ajustar el selector para incluir out-pending propio).
2. **Búsqueda fase 1** (contactos/dueño/teléfono/mascota) + segmentos de filtros (sin atender/esperando cliente/urgentes).
3. **Modelo de lectura por usuario** (`ConversationReadState`) → divider "mensajes nuevos", marcar leído automático al abrir.
4. **Optimización de `list_threads`** (Subquery/Prefetch) + paginación real de la lista.
5. **Panel de contexto del cliente**: owner, mascotas, última visita, link directo al expediente (las rutas ya existen en el SaaS).
6. **Retry de mensaje fallido** (endpoint re-enqueue validando ventana 24h) + sugerencia "llámala: el número es…" cuando falló por ventana.
7. **Banner de ventana 24 h** (countdown desde `last_inbound_at`, dato ya en modelo).
8. **Indicador "el asistente está respondiendo"** (`processing_until` publicado).
9. **Fix del discard de mensajes humanos** en `_discard_if_superseded`.
10. **Asignación a colega + tabla append-only de acciones de bandeja.**
11. **Formato temporal org-aware** compartido (usar `Organization.timezone`; la regla "hoy = día local de la organización" ya está establecida en CLAUDE.md para backend).
12. **`?since=<id>` en ambos endpoints** + `around=<id>` en transcript.

---

## 18. Cambios grandes (arquitectónicos)

1. **Pipeline de media entrante** (descarga en worker → storage privado → servido auth-scoped → thumbs → retención) y luego **media saliente** (upload, validación, límites).
2. **Realtime**: SSE (más simple que WS para este stack Django) con fanout por org/usuario; degrada a polling.
3. **Replies end-to-end** (modelo + webhook context + UI + jump-to-message).
4. **Plantillas HSM (F3)**: gestión de aprobaciones Meta, render de variables, envío fuera de ventana — desbloquea recordatorios de citas, el caso de negocio #1 fuera de la ventana.
5. **Presencia multiagente** (typing/viendo) — requiere realtime primero.
6. **Virtualización + store normalizado** solo cuando el historial completo esté expuesto y los hilos reales superen ~300 mensajes montados.

---

## 19. Lo que NO deberíamos construir todavía

- Reacciones, encuestas, catálogo/comercio, notas de voz salientes con waveform custom — paridad cosmética sin demanda operativa demostrada.
- Presencia tipo Figma (cursores), co-edición de borradores.
- Automatizaciones/reglas visuales sobre etiquetas (no existen etiquetas).
- App móvil nativa; el responsive maestro-detalle cubre el caso "recepcionista en el celular".
- Multi-canal (Instagram/Messenger) antes de que WhatsApp sea impecable.
- CRM completo dentro del inbox (custom fields, pipelines) — el expediente ya vive en su módulo; enlazar, no duplicar.
- Virtualización prematura, WebRTC, llamadas.
- Cualquier feature nueva del inbox **antes** de corregir el draft leak y el discard humano: son las únicas dos cosas de esta auditoría que pueden causar daño activo.

---

## 20. Roadmap recomendado

### Fase A — "Deja de sentirse incompleto" (1–2 semanas, casi todo frontend)

Ticks · separadores de fecha · draft fix · grouping · contador no leídos (local) · copy actions · auto-resize + contador · título de pestaña · pausa de polls · badge verificación · estados de carga/error.

- Dependencias: ninguna.
- Backend: mínimo (ninguno o 1 campo de serializer).
- Tests: unitarios de formateo/fechas; smoke del flujo de cambio de hilo.
- Riesgo: muy bajo. Impacto: **alto** — es la capa de percepción.

### Fase B — "Inbox profesional" (2–4 semanas)

Optimistic send + idempotencia · historial completo (`next_before`) · búsqueda fase 1 + filtros segmentados · read-state + divider + mark-read al cliente · optimización de `list_threads` + paginación · panel de contexto del cliente · retry de fallidos · banner ventana 24h · fix discard humano · timezone org-aware.

- Backend: medio (5 endpoints/ajustes, 1 modelo nuevo, 2 fixes de concurrencia).
- Tests: concurrencia (claim/envío/discard), paginación, permisos de lectura.
- Riesgo: medio-bajo. Impacto: alto.

### Fase C — "Mensajería avanzada" (4–8 semanas)

Media entrante (pipeline completo) · replies end-to-end · búsqueda en contenido (`pg_trgm` + around/jump) · SSE realtime · media saliente básica (imágenes/documentos).

- Dependencias: B (read-state, historial).
- Tests: integración con Graph API mockeada, expiración de URLs, permisos de servido de archivos, e2e de reply→jump.
- Riesgo: medio-alto (storage, PII, coste). Impacto: alto — aquí desaparece la pérdida de datos.

### Fase D — "Operación a escala" (continua)

Plantillas HSM F3 · presencia/asignación multiagente + auditoría DB · métricas de operación humana · virtualización si el volumen lo pide · observabilidad de polls/SSE.

- Riesgo: medio (aprobaciones Meta, calidad de cuenta). Impacto: alto para clínicas grandes.

### Fase E — "Polish" (perenne)

Atajos de teclado completos + paleta `Ctrl+K` · aria-live y semántica de burbujas · render de formato WhatsApp · lightbox de imágenes · microinteracciones (pill de nuevos mensajes, highlight de referencias, skeletons) · mobile maestro-detalle.

---

## 21. Criterio final — la prueba de los 10 minutos

Una recepcionista acostumbrada a WhatsApp Web deja de sentir que usa "una herramienta interna" cuando, en la primera sesión: **su propio mensaje aparece al instante con ticks**, ve **"Hoy" separando lo de ayer**, nota que **el número junto al nombre dice cuántos clientes esperan**, puede **subir a leer lo del martes sin que la vista la secuestre**, y al abrir un hilo ve **quién es, su mascota y un botón hacia el expediente**.

Nada de eso requiere IA, WebSocket nuevo o plantillas: cuatro de esas cinco cosas ya tienen el backend listo y solo esperan frontend. Las dos únicas correcciones urgentes por daño potencial son el **draft leak** entre conversaciones y el **discard silencioso de respuestas humanas** durante turnos del agente. Todo lo demás es, en este orden: percepción (Fase A), operación diaria (Fase B), y sustancia (media/replies/realtime, Fase C).
