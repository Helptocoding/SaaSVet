# Changelog

## 2026-10-22

- Inbox, cierre local de fase 3: RPL-07 conecta citas nativas tras admisión B4;
  MED-01..05 incorporan captura atómica, almacenamiento privado local/B2,
  descarga durable, expiración/reconciliación, proxy por clínica y controles de
  archivos/captions/previews. 170 pruebas PostgreSQL y 257 frontend únicas PASS, build, lint,
  drift y Chromium escritorio/móvil PASS. M2/M3/M4 sin aplicar a bases habitual/
  preview; banderas apagadas y gates reales pendientes. Evidencia:
  `docs/evals/inbox-phase3-2026-10-22/README.md`. MED-06 saliente opcional.

- Inbox, WA-RPL-06/04: citas pulsables en burbujas entrantes/salientes, con
  autor, extracto, media y estado no enviado. Salto al original local o mediante
  around, foco/resaltado de dos segundos y continuidad de before/floor, con
  borrador conservado y respuestas tardías descartadas. 128 pruebas frontend
  únicas, build, lint y Chromium escritorio/móvil PASS con API sintética.
  El contexto nativo y la matriz RPL-07 se cerraron en el corte anterior de esta fecha; Meta real sigue pendiente.

## 2026-10-21

- Inbox, WA-RPL-05: acción Responder y cita única sobre el composer con autor,
  extracto y cancelación por Escape/×. Envío y reintento conservan la referencia
  original sin trasladarla entre hilos; tmps y ventana cerrada deshabilitados.
  61 pruebas frontend únicas, build, lint y Chromium escritorio/móvil PASS.
  Citas en burbujas, salto y payload nativo Meta siguen pendientes.
- Inbox, WA-RPL-03: envío API con `reply_to_id` validado por clínica/hilo y cita
  acotada en POST/transcripts. Conserva idempotencia/retry, evita N+1 y actualiza
  excerpt/estado/autor por delta incluso con el destino fuera de página.
  Evidencia dirigida en `docs/evals/inbox-rpl-03-2026-10-21/README.md`.

- Inbox, WA-RPL-02: el webhook enlaza `context.id` con el mensaje citado de la
  cuenta receptora. Revalida el hilo bajo lock, conserva entrantes sin destino
  válido y registra aviso sin PII; redelivery no cambia la cita ni duplica efectos.
  Evidencia dirigida en `docs/evals/inbox-rpl-02-2026-10-21/README.md`.

- Inbox, WA-RPL-01: modelo `Message.reply_to` opcional con destino protegido,
  índice único y validación de clínica/hilo. M2 aditiva ensayada con mensajes
  históricos y writers previos/nuevos; sin aplicar a la base habitual.
  Evidencia dirigida en `docs/evals/inbox-rpl-01-2026-10-21/README.md`.

- Inbox, WA-ASN-01: asignación a compañeros activos con permiso para responder,
  aislada por clínica y serializada con Tomar. Selector en cabecera con carga y
  reintento, borrador conservado y auditoría tras commit sin datos personales.
  Evidencia dirigida en `docs/evals/inbox-asn-01-2026-10-21/README.md`.

- Inbox, WA-SRCH-01: búsqueda de contactos por nombre, teléfono parcial/formateado
  y cliente vinculado, combinada con segmentos y paginación. Debounce de 250 ms,
  Ctrl/Cmd+K y Escape, con protección de cursores y borrador conservado.
  Evidencia dirigida en `docs/evals/inbox-srch-01-2026-10-21/README.md`.

- Inbox, WA-FIL-01: segmentos combinables «Sin atender», «Esperando cliente»,
  «Urgentes» y «Míos», filtrados en servidor antes de paginar. Cursores ligados
  al segmento y cancelación al cambiarlo, con chat y borrador conservados.
  Contrato y evidencia en `docs/evals/inbox-fil-01-2026-10-21/README.md`.

### Agregado

- Inbox, WA-PERF-03: polling con cursores por usuario/consulta, cambios por hilo/ID
  y retiradas explícitas. Recupera cursores inválidos, preserva historial/borrador
  y pausa por visibilidad. Tracking optativo de updated_at, sin migración nueva.
- Inbox, WA-CTX-01: panel plegable del cliente vinculado, mascotas y última cita
  anterior, con carga/error propios y acceso al expediente en dos clics.
  Consulta de solo lectura aislada por clínica, sin historia clínica en el Inbox.
- Inbox, WA-WIN-01: aviso preventivo de la ventana de 24 horas, cuenta regresiva
  cuando quedan menos de 12 h y bloqueo del composer al vencer. Conserva borrador,
  ofrece llamada y habilita de nuevo al recibir una ventana renovada por el poll.
- Inbox, WA-RETRY-01: reintento explícito del mismo mensaje con fallo conocido,
  permisos y ventana comprobados, autor y clave conservados. Bloquea concurrencia,
  respeta la evidencia B4 y ofrece llamada cuando la ventana está cerrada.
- Inbox, WA-UNR-02: contadores por hilo y total de lectura, divisor de mensajes
  nuevos y marcado automático tras 1,5 s con foco y visibilidad. Cancela al cambiar
  de hilo/atención, reintenta sin toast y conserva el ancla al retirar el divisor.
- Inbox, WA-UNR-01: lectura persistente por empleado/hilo y contador solo del
  episodio vigente, con POST idempotente, avance monótono y aislamiento tenant.
  Incluye migración aditiva M3 y conteos agregados sin consultas por fila.
- Inbox, WA-HIST-03: consulta `around` centrada en un mensaje, con continuidad
  hacia ambos lados y destino oculto identificado; mantiene aislamiento por
  clínica/hilo y el contrato del transcript normal.
- Inbox, WA-HIST-02: conserva la lectura al recibir mensajes nuevos y muestra
  «N mensajes nuevos» con retorno suave al fondo. Sigue las llegadas cuando ya
  estaba al fondo y evita contar históricos o confirmaciones optimistas dos veces.
- Inbox, WA-HIST-01: carga mensajes anteriores con cursor, conserva el historial
  durante el polling y ancla la lectura al insertar páginas. Incluye cancelación
  al cambiar de hilo, reintento persistente y carga manual desde 500 mensajes.
- Inbox, WA-PERF-02: páginas de 100 hilos con aviso y botón «Cargar más»;
  conserva todas las páginas cargadas durante el refresco, deduplica por
  contacto/cuenta y permite reintentar errores sin perder lista ni borrador.
- Inbox, WA-PERF-01: listado agrupado en SQL con último mensaje, handoff y
  conteo de episodios; elimina consultas por fila y la carga de todo el historial,
  conservando el payload y aplicando el límite existente antes de materializar.
- Inbox, WA-GTF-01: botón «Ir al final» al alejarse del fondo, accesible con
  teclado y puntero; conserva foco y posición de página, también en archivados.
- Inbox, WA-AGT-01: indicador de respuesta del asistente mediante booleano de
  solo lectura; Tomar/Liberar se deshabilitan mientras la proyección indica
  turno activo. No expone el timestamp ni cambia la autoridad de TurnWork.
- Inbox, WA-LDE-01: carga y error persistentes por panel, banner tras dos fallos
  consecutivos y recuperación automática o manual, conservando historial y borrador.
- Inbox, WA-VER-01: distintivos de verificación en lista y cabecera, con
  explicación del nivel; distingue coincidencia de teléfono de identidad
  verificada y refleja cambios posteriores sin modificar permisos.
- Inbox, WA-VIS-01: pausa del polling de lista/hilo al ocultar la pestaña y
  actualización inmediata al volver; conserva selección vigente y limpieza
  de intervalos al cambiar filtro, conversación o salir del Inbox.

## 2026-10-20

### Agregado

- Inbox, WA-TAB-01: título de pestaña con número de hilos sin responder al
  ocultar o desenfocar; restaura el título al recuperar foco o salir del Inbox.
- Inbox, WA-CPY-01: copiar mensaje/teléfono, enlace telefónico y URLs HTTP/HTTPS
  clicables con render seguro de texto plano. Acciones accesibles por teclado y
  en táctil; errores del portapapeles visibles y teléfono de hilos archivados.
- Inbox, WA-GRP-01: ráfagas visuales del mismo autor a menos de cinco minutos,
  sin cruzar el día local ni ocultar mensajes, horas o estados. El serializer
  publica un UUID de autor humano de sólo lectura para distinguir homónimos.
- Inbox, WA-CMP-01: campo de respuesta con altura automática de 40–120 px,
  contador visible después de 3600/4000 caracteres y advertencia desde 3800.
  Borrar, enviar y cambiar de cliente reajusta la altura y el contador.
  Seguimiento funcional actualizado en `docs/CIERRE-INBOX-WHATSAPP.md`.

## 2026-04-27

### Agregado

- Componente global `SearchSelect` (`frontend/src/components/SearchSelect.jsx`): typeahead con debounce 300ms, proteccion contra respuestas stale, estado de carga, reset externo via `value?.id`. Reemplaza todos los `<select>` de lookup de datos en el sistema.
- Backend: `GET /api/pets/` ahora acepta `?search=<nombre>` (icontains) y `?owner=<id>` (combinables, limite 20 resultados).
- Backend: `GET /api/owners/` ahora acepta `?search=<nombre>` (limite 20).
- Backend: `GET /api/billing/services/` ahora acepta `?search=<nombre>` (combinable con `?active=true` existente).
- Guardia de integridad owner↔pet en `AppointmentSerializer.validate()`: si el frontend envia `owner_id`, el backend valida que `pet.owner_id` coincida.
- Sistema de notificaciones global via Sonner (`<Toaster>` en `App.jsx`): todo feedback transaccional y de validacion ahora es toast.

### Cambiado

- **Citas**: seleccion de mascota en `SidebarForm` y `WalkInModal` migrada a `SearchSelect`. Ya no se carga la lista completa de mascotas al montar la pagina — se busca contra el backend al escribir.
- **Historial clinico**: seleccion de mascota en modal Nueva Consulta migrada a `SearchSelect` con filtrado client-side sobre el array ya cargado (pets sidebar). Se agrego estado `isLoadingPets` que deshabilita el campo mientras carga.
- **Cobros**: seleccion de propietario y mascota en modal Nuevo Cobro migradas a `SearchSelect` con dependencia propietario→mascota. La mascota se deshabilita hasta seleccionar propietario. `owners` y `pets` ya no se cargan globalmente al montar el modulo.
- **PrescriptionForm**: seleccion de mascota migrada a `SearchSelect` con `getPets` importado directamente en el componente. Cuando `lockedPet=true` muestra texto estatico en lugar del campo. No requiere cambios en los sitios de llamada.
- **API `pets.js`**: firmas actualizadas — `getPets(params={})` y `getOwners(params={})` aceptan objeto de parametros opcionales.
- Todas las alertas de tipo `<div className="alert">` y `<div className="form-alert">` eliminadas del sistema. Reemplazadas por:
  - `toast.error()` para validaciones y errores de servidor
  - `toast.success()` para confirmaciones
  - `toast.promise()` para operaciones asincronas con loading/success/error

### Corregido

- La advertencia "No puedes crear una cita pasada" dejaba de mostrarse como banner siempre visible. Ahora es condicional: solo aparece cuando el slot seleccionado en el calendario es una fecha anterior a hoy.
- `handleAddPrescriptionSuggestion` en cobros no ejecutaba la llamada a la API por referencia a variable eliminada (`setError` huerfano). Corregido.
- Import de `SearchSelect` faltante en `billing.jsx` causaba crash de render (ErrorBoundary). Corregido.

## 2026-04-25

### Agregado
- Estado clinico en `MedicalRecord` con `status`, `closed_at` y `closed_by`.
- Endpoint idempotente `POST /api/medical-records/<id>/close/` para finalizar consulta.
- Policy de dominio en `backend/apps/medical_records/policies.py` para ownership y bloqueo por consulta cerrada.
- Permiso `medicalrecord.close` en el catalogo RBAC.
- Modelo `MedicalRecordService` con sus endpoints para agregar y quitar servicios desde la consulta.
- Flags `can_modify_charges` y `can_close` expuestos al frontend desde serializers.
- Componente compartido `PrescriptionForm` para reutilizar el formulario de recetas sin duplicar logica.
- Documentacion inicial en `docs/decisions/` y `docs/modules/`.

### Corregido
- El flujo de productos usados en consulta dejo de depender de `inventory.create` y ahora se alinea al recurso clinico `medicalrecord`.
- La eliminacion de productos usados en consulta ahora ajusta o elimina el `InvoiceItem` asociado para no dejar facturacion inconsistente.
- La consulta cerrada ahora bloquea `update/delete` tambien en el endpoint principal del medical record.
- El frontend ahora muestra estado `Cerrada`, permite finalizar consulta, oculta `Editar/Eliminar` y bloquea mutaciones de productos cuando la consulta ya no es editable.
- La creacion de recetas desde historial clinico ahora ocurre en un modal contextual sin navegar fuera de la consulta.
- Si crear receta falla, el modal conserva los datos y muestra el error sin cerrarse.
- El historial clinico ahora muestra el detalle de la receta asociada y separa visualmente receta medica vs productos consumidos en consulta.
- Agregar el mismo producto a una consulta ahora acumula cantidad en lugar de fallar por unicidad.
- El calculo de `can_close` y `can_modify_charges` ahora considera permiso RBAC real ademas de ownership/policy.

### Decisiones tecnicas
- El cierre de consulta se resuelve de forma explicita y no por eventos de facturacion.
- Una consulta `closed` se considera inmutable para todos los roles.
- El endpoint de cierre responde `200` de forma idempotente incluso si la consulta ya estaba cerrada.

### Pendiente
- Agregar prueba de concurrencia real con requests paralelos para el cierre de consulta.
- Extender la UI para gestionar servicios usados desde historial clinico con el mismo nivel de soporte visual que productos.
