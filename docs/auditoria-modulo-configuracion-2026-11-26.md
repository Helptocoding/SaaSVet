# Auditoría de producto — Módulo Configuración

**Fecha:** 2026-11-26
**Tipo:** auditoría de producto, madurez, seguridad funcional y benchmark (no es plan de
implementación ni ADR).
**Alcance:** `frontend/src/pages/config/` (y su envoltorio `pages/config.jsx`), app
`backend/apps/organizations`, `Service` de `backend/apps/billing`, cuenta propia (cambio de
contraseña y MFA de `backend/apps/users`), RBAC (`apps/core/permissions*.py`) y los consumidores
de la configuración: agente de WhatsApp, onboarding, Citas, Cobros, POS/Caja, PDFs e Historial
clínico.
**Plantilla:** estructura, severidades y forma de justificar tomadas de
[`auditoria-modulo-equipo-2026-11-23.md`](auditoria-modulo-equipo-2026-11-23.md).
**Contexto comercial:** clínicas veterinarias pequeñas en México (1–15 personas). Según
`CLAUDE.md`, hoy no hay clínicas ni usuarios reales: las recomendaciones no se limitan por
proteger datos existentes, pero sí por seguridad, aislamiento entre clínicas e invariantes.

Leyenda de evidencia: **[E]** verificado en código · **[D]** documentado, no verificado en código
· **[I]** inferencia razonada a partir de evidencia · **[NV]** no verificable con las fuentes
disponibles.

Severidades: **P0** riesgo crítico de seguridad, aislamiento, integridad o indisponibilidad ·
**P1** problema grave en una operación importante o exposición de información · **P2**
limitación funcional, de UX o de integración que reduce mucho la calidad · **P3** mejora menor o
inconsistencia.

---

## Resumen ejecutivo

- Configuración es hoy un **formulario de datos de clínica bien aislado en backend**, conectado de
  forma sólida al agente de WhatsApp, pero **no un centro de administración**: varias opciones que
  muestra o documenta no tienen efecto, otras que la clínica necesita no se pueden ver ni editar, y
  no queda registro de quién cambió qué.
- **Madurez general: 2.4/5 (Básica alta).** Aislamiento multi-tenant, validación del horario y
  reglas de caja/crédito aplicadas en servidor ≈ Madura; auditoría de cambios ≈ Inicial; permisos
  en frontend, catálogo, identidad e integración ≈ Básica.
- **Ningún P0.** Tres **P1**: cambiar la zona horaria desalinea las citas existentes sin aviso
  (C1); desde Configuración se puede borrar el teléfono con el agente encendido, el estado que
  `agent.md` declara inalcanzable (C2); el precio que ven la clínica y el agente no incluye el IVA
  que se cobra, y la clínica no ve ni puede cambiar esa tasa (C3). C2 y C3 son latentes mientras
  el agente siga sin activarse en producción.
- **Frente a los módulos de configuración de Shepherd, Digitail, Provet, Vetspire y ezyVet**
  (§7), el de SaaSLyVet es el más pequeño y el único plano: 5 apartados sin agrupar frente a
  áreas por dominio (identidad, finanzas, práctica clínica, agenda, seguridad). Es el único caso
  verificado que mete la cuenta personal dentro de la configuración de la clínica, no tiene área
  fiscal ni de impuestos y usa un solo permiso para todo. A su favor, el primer uso lleva al
  apartado correcto según el estado real de la clínica; en los competidores no se encontró algo
  equivalente (NV).
- La brecha con el mercado no es «más pantallas». Son tres conceptos que los competidores
  resuelven y SaaSLyVet no: **cierres excepcionales del horario**, **impuestos visibles y
  configurables por la clínica** y **datos de la clínica impresos en sus documentos**.

---

## 1. Metodología y fuentes

### 1.1 Orden de autoridad aplicado

1. Código ejecutable (fuente de verdad): se siguió cada flujo frontend → `api/` → vista →
   serializer → modelo, y cada valor configurado hasta sus consumidores con búsquedas cruzadas en
   todo `backend/apps` y `frontend/src`.
2. Pruebas: `apps/organizations/tests/` (45 métodos en `test_configuration.py`, `test_views.py`,
   `test_org_phone_validation.py`, `test_legacy_view_org_id_writable.py`),
   `apps/core/tests/test_admin_explicit_grants.py`, `apps/users/tests/test_member_permissions.py`,
   `test_mfa.py` (19), `test_change_password.py` (22), `MfaSettings.test.jsx` (4 casos) y
   `FirstRunAssistant.test.jsx` (17 casos).
3. Documentación técnica: [ADR p53](decisions/2026-07-21-p53-clinic-configuration-aggregates.md),
   [diseño técnico de configuración](diseno-tecnico-configuracion-clinica-2026-07-21.md),
   [`modules/organizations.md`](modules/organizations.md), [`modules/frontend.md`](modules/frontend.md),
   [`modules/agent.md`](modules/agent.md), [`frontend/design-system.md`](../frontend/design-system.md),
   ADR p66–p69.
4. Documentación de producto y `CLAUDE.md`.
5. Investigación externa (§7), consultada el 2026-11-26.

### 1.2 Qué no se hizo

- No se ejecutó la aplicación ni pruebas en navegador: los efectos visuales (por ejemplo, el
  recorte en móvil) se infieren del CSS y se marcan **[I]**.
- No se corrieron las suites; las pruebas se citan por lo que afirman, no por un resultado nuevo.
- Las afirmaciones «sin consumidor» se basan en búsquedas del nombre del campo en todo el código
  ejecutable (excluidas migraciones y pruebas).

---

## 2. Estado actual reconstruido

### 2.1 Frontend [E]

| Pieza | Estado |
|---|---|
| Ruta | `/config` → `wrap(Config)` (`App.jsx` ≈L158). `pages/config.jsx` solo espera `initializing` y monta `SettingsLayout`. **Sin guarda por permiso**: cualquier usuario autenticado con organización abre la página por URL. Equipo, en cambio, redirige sin capacidad (`pages/staff.jsx` ≈L163). |
| Menú | `Sidebar.jsx` muestra «Configuración» solo con `can("organization.update")`. |
| Navegación interna | Menú lateral de 5 apartados (`index.jsx` ≈L17-23): Clínica, Horarios, Reglas operativas, Servicios, Cuenta. Cada apartado es `lazy` y **solo el activo está montado** (≈L141-174). En ≤880 px el menú pasa a una fila con scroll horizontal. |
| Carga | Una llamada a `GET /api/settings/configuration/` (organización, settings, horario) y otra a `GET /api/billing/services/` (≈L78-97). Errores solo a `console.error`. |
| Estado | `org`, `settings`, `schedule` y `services` viven en el layout: lo tecleado sobrevive al cambiar de apartado, pero no hay indicador de cambios sin guardar ni aviso al salir de `/config`. |
| Guardado | Explícito y **por apartado** (un botón por sección). No hay autosave ni guardado global. |
| Decisiones por rol | `canManage = user?.role !== "ASSISTANT"` (≈L69) y `isPlatformOperator = user?.role === "ADMIN_SAAS"` (≈L66): contradicen la regla «nunca por rol, siempre `can()`» de `frontend/CLAUDE.md`. Servicios sí usa `can("service.create")`. |
| Piezas compartidas | `SettingsPanel` (cabecera + panel + pie con acción), `SettingRow`, `ToggleRow` (`role="switch"`, `aria-checked`), `IdentityHeader`. Esqueleto con la forma del apartado. |
| Pruebas | Solo `MfaSettings.test.jsx` (4). `FirstRunAssistant.test.jsx` cubre el enlace profundo a `section: "clinic"`/`"services"`. Ningún apartado de clínica, horario, reglas o servicios tiene prueba propia. |

### 2.2 Backend [E]

| Pieza | Estado |
|---|---|
| `Organization` (`organizations/models.py` ≈L15-93) | Identidad y contacto: `name`, `display_name`, `timezone`, `tax_rate`, `phone`, `whatsapp`, `email`, `website`, dirección en 7 campos, `google_maps_url`, `latitude/longitude`, `arrival_instructions`, `is_demo`, estado de activación. `save()` llama `full_clean()` (zona horaria IANA, coordenadas juntas). Sin `updated_at` ni `updated_by`. Sin logo, RFC ni datos fiscales. |
| `OrganizationSettings` (≈L96-113) | 7 reglas (`auto_create_medical_record`, `require_confirmation_before_start`, `allow_anonymous_walkin`, `show_status_change_history`, `require_open_cash_session`, `allow_post_unpaid`, `credit_default_days`) + 6 «de Fase 1» (`locale`, `currency_code`, `default_appointment_duration_minutes`, `appointment_buffer_minutes`, `allow_emergency_walkin`, `week_starts_on`). Sin marcas de auditoría. |
| `OrganizationSchedule` (≈L119-167) | Una fila por día, único `(organization, weekday)`, una franja + un descanso. `clean()` valida apertura < cierre y descanso dentro. |
| `OrganizationTimezoneAudit` (≈L170-188) | Única auditoría de configuración: registra cambios de zona horaria (sin UI que la muestre). |
| Endpoints | `GET/PATCH /api/organizations/me/` · `GET/PATCH /api/organizations/settings/` · `GET/PUT /api/organizations/schedule/` · `GET /api/settings/configuration/` (`config/urls.py` ≈L293-296). `DELETE`/`POST` → 405 (probado). La organización sale siempre de `request.user.organization`; `id`/`public_id` en el cuerpo se ignoran (probado en `test_legacy_view_org_id_writable.py`). |
| Serializers (`organizations/serializers.py`) | `tax_rate` **solo lectura** (≈L22-25). `name` es escribible pero no lo expone la UI. Teléfono con la regla compartida `validate_mx_phone(..., allow_blank=True)` (≈L32-42); `whatsapp` solo quita no-dígitos (≈L44-48). Rangos de duración, buffer, semana y crédito (≈L101-119). Horario: exactamente 7 días, sin duplicados, reglas por día, errores por `day_N` (≈L171-203). |
| Escritura del horario | `PUT` en `transaction.atomic()` con `select_for_update()` sobre las 7 filas (`views.py` ≈L91-118): todo o nada. |
| Siembra | Señal `initialize_organization` crea settings, 7 días por defecto (L-V 9-18, sáb 9-14, dom cerrado), cliente/mascota genéricos y roles; `ensure_schedule_integrity` repara días faltantes al leer. La señal **traga excepciones** con un `logger.error` (`signals.py` ≈L38-39). |
| Lectura de reglas | `get_org_setting(org, key)` (`utils.py` ≈L33-37) lee `org.settings` en cada petición; sin caché → un cambio aplica en la siguiente petición. |
| `Service` (`billing/models.py` ≈L15-34) | `name`, `description`, `base_price` (CHECK `> 0` en base), `specialty` (catálogo cerrado, ADR p68), `is_active`, `created_by/updated_by` del modelo organizacional. Referencias con `PROTECT` desde `CheckoutItem` y `MedicalRecordService`. Sin categoría, duración, impuesto ni clave SAT. CRUD en `/api/billing/services/` con `for_organization` y `public_id`. |
| Cuenta | `POST /api/users/change-password/` (`ChangeMyPasswordView`, `users/views.py` ≈L249-294): contraseña actual, throttle 10/h, `NotDemoAccount`, `no-store`, revoca otras sesiones (ADR p65); mínimo 8 caracteres más los validadores de Django. MFA TOTP (`/api/users/mfa/*`, ≈L625-680): solo ADMIN fuera de la demo, contraseña para activar, primer código, 10 códigos de respaldo, throttle 20/h. |

### 2.3 Permisos y seguridad [E]

**Backend — autorización por endpoint.** Todas las vistas de configuración usan
`HybridPermission` con `resource_name="organization"`; `_method_to_action` traduce `GET` sin pk a
`list` y `PATCH`/`PUT` a `update` (`core/permissions.py` ≈L198-248). Resultado:

| Operación | Permiso exigido | Quién lo tiene por defecto |
|---|---|---|
| Leer clínica, reglas, horario, agregado | `organization.list` | ADMIN, VET, ASSISTANT |
| Editar clínica, reglas **y** horario | `organization.update` (sensible) | Solo ADMIN |
| Leer servicios | `service.list` / `service.retrieve` | Todos los roles de clínica y AGENT |
| Crear, editar, eliminar servicios | `service.create/update/destroy` | Solo ADMIN |
| Cambiar la propia contraseña | `IsAuthenticated` + `NotDemoAccount` | Cualquiera fuera de la demo |
| MFA | `IsAuthenticated` + `NotDemoAccount`; `available` solo ADMIN | ADMIN |

- `test_implemented_method_without_the_code_is_still_403` comprueba que un VET recibe 403 en
  `PATCH /api/organizations/me/`. **No hay prueba equivalente** para `settings/` ni `schedule/` ni
  para ASSISTANT [E].
- **ADR p69 hace delegable `organization.update`**: no está en `ADMIN_RESERVED`
  (`core/permission_catalog.py` ≈L144-147). Otro ADMIN puede quitárselo a un ADMIN (probado en
  `test_member_permissions.py` ≈L150-157) o concedérselo a un VET o ASSISTANT. Nadie puede
  quitárselo a sí mismo.
- Un solo código gobierna tres cosas de peso distinto: identidad (teléfono, dirección), horario
  que usa el agente y reglas financieras (crédito, caja obligatoria).

**Aislamiento multi-tenant.** Sin identificadores de organización en URL ni en cuerpo; servicios
por `for_organization` y `public_id` (cross-tenant = 404). La demo (`is_demo`) se restaura cada 30
minutos (ADR p49) y sus ADMIN pueden editar la configuración por diseño. No se encontró ninguna vía
para modificar la configuración de otra clínica [E].

**Frontend — escenarios de acceso.**

| Escenario | Comportamiento comprobado |
|---|---|
| Sin `organization.update`, entra por URL a `/config` | Ve los 5 apartados. Clínica y Horario con campos y «Guardar» activos → 403 al guardar [E] (403 de `me/` probado; de `schedule/` inferido del mismo mecanismo [I]). No hay redirección. |
| VET por URL, apartado Reglas | `canManage` es `true` (no es ASSISTANT): interruptores activos → 403 al guardar [E]. |
| ASSISTANT con `organization.update` concedido por p69 | Ve el ítem del menú, pero Reglas queda deshabilitado con «Solo un administrador puede cambiar estas reglas» [E]. |
| ADMIN al que otro ADMIN quitó `organization.update` | Pierde el ítem del menú y, con él, el único camino de navegación a **Cuenta** (contraseña y MFA) [E]. |
| Usuario con `service.update` sin `service.create` | No ve «Nuevo servicio», sí editar; ve «Eliminar» aunque no tenga `service.destroy` (el botón no se condiciona) [E]. |
| Subsecciones | No tienen ruta propia; el apartado se elige por estado del router (`location.state.section`), no por URL [E]. |

Comparado con Equipo: Equipo corrigió en su Fase 1 la ruta abierta (redirección por capacidad);
Configuración conserva el patrón que Equipo dejó atrás. Aquí **no hay exposición de datos**: lo
que se ve por URL ya era legible con `organization.list`. El problema es de coherencia, no de
fuga.

**Seguridad de valores sensibles.**

- Teléfono: regla real en backend (10 dígitos, sin relleno) [E].
- Zona horaria: backend exige un identificador IANA válido; la UI la captura como texto libre y el
  cambio no recalcula nada (C1) [E].
- Reglas financieras: `require_open_cash_session` y `allow_post_unpaid` se aplican **en el
  servidor**, bajo lock, en todos los comandos de cobro (§3) [E].
- Precios: CHECK `base_price > 0` en base de datos; el precio se copia al Checkout/factura, así que
  cambiarlo no reescribe documentos emitidos [E].
- Escalación de privilegios: ninguna vía de Configuración cambia roles o permisos [E].

---

## 3. Integración con otros módulos

| Módulo | Configuración consumida | Implementación comprobada | Problema o riesgo |
|---|---|---|---|
| Agente WhatsApp — horario | `OrganizationSchedule` | `agent/clinic_context.py` (`weekday_ranges`, `effective_business_hours`, `humanize_schedule`) y `appointments/creation.schedule_windows`, compartida con la escritura autorizada del agente (`require_schedule=True`). La creación toma `FOR SHARE` sobre la fila del día (`_share_rows`), así que un `PUT` del horario y una cita del agente se serializan [E]. Sin filas → «sin configurar», no inventa horario. | **Integración funcional.** Sin cierres excepcionales: el agente ofrece citas en un festivo si el día de la semana está abierto [E]. |
| Agente — contacto y urgencias | `phone`, `whatsapp`, `email`, `website`, dirección (incluye `address_line2`), mapa, indicaciones | `clinic_facts` / `clinic_phone`, defensivo ante errores; plantilla de urgencia con número o `T0_EMERGENCY_NO_PHONE` (`tier0.py` ≈L79-83, L246-257) [E]. | Gate del kill switch solo al **encender** (`agent/serializers.py` ≈L240-263); Configuración permite vaciar el teléfono después (C2). `address_line2` lo lee el agente pero la UI no lo ofrece [E]. |
| Agente — nombre y precios | `Organization.name`, `Service` activos, `currency_code` | Saludo y contexto con `organization.name` (`prompts.py` ≈L305, L561; `tier0.py` ≈L273); catálogo con `base_price` como «precio» (`tools.py` ≈L674-702) [E]. | `display_name` («Nombre comercial») no llega al agente. El precio citado no incluye el IVA que el Checkout suma (C3). |
| Agente — kill switch y FAQ | `AgentSettings.enabled`, `faq_facts` | El interruptor vive en Inbox (`agentinbox.config`) y enlaza a `/config` si falta el teléfono [E]. | `faq_facts` (aviso de privacidad, estacionamiento) **no tiene UI** en ninguna parte del frontend [E]. |
| Onboarding | `phone` (hito `has_clinic_contact`), existencia de `Service` (`has_services`) | `dashboard_activation` deriva del estado real, sin flags (`dashboard/views.py` ≈L766-819); el layout de Configuración devuelve al Dashboard con la señal de celebración [E]. | **Funcional.** No pregunta la zona horaria, que nace en `America/Mexico_City` (relevante para C1) [E]. |
| Citas — reglas | `require_confirmation_before_start`, `auto_create_medical_record`, `allow_anonymous_walkin`, `show_status_change_history` | Las tres primeras en `appointments/views.py` (≈L359-367, ≈L396-409, ≈L764-770) sobre la fila bloqueada; la cuarta solo en frontend (`appointments.jsx` ≈L1192) [E]. | `auto_create_medical_record` solo actúa en el cambio manual a `done`; crea un expediente vacío abierto después de la cita [E] y su comentario cita una señal de facturas ya retirada (ADR p62). |
| Citas — horario y duración | Horario, `default_appointment_duration_minutes`, `appointment_buffer_minutes`, `week_starts_on` | El calendario fija `slotMinTime="07:00"`, `slotMaxTime="20:00"`, `slotDuration="00:30"`, `firstDay={1}` (`appointments.jsx` ≈L1190); el staff crea citas sin `require_schedule` [E]. | **Sin consumidor**: los tres ajustes de agenda no se usan; el horario no restringe ni avisa al staff; una clínica abierta hasta las 21:00 no ve esa franja [E]. |
| Cobros | `allow_post_unpaid`, `credit_default_days`, `tax_rate` | Crédito aplicado en servidor (`checkout_services.py` ≈L1357-1360, ≈L1676-1690); `credit_default_days` solo como valor inicial del vencimiento en `billing.jsx` (≈L170-173); `tax_rate` copiado al Checkout al crearlo (≈L532, L678) y total = subtotal + subtotal × tasa (`billing/money.py` ≈L26-32) [E]. | Integración funcional en crédito. `tax_rate` no es visible ni editable por la clínica: lo fija plataforma al provisionar (por defecto 0.16, `platform/serializers.py` ≈L51-56) [E]. |
| POS / Caja | `require_open_cash_session` | `_resolve_cash_session_for_payment` (`billing/services.py` ≈L124-151), llamado desde el pago de Checkout (`checkout_services.py` ≈L1656), el pago de factura y el refund (`services.py` ≈L268, L351, L505) [E]; reversals según `system-module-operations.md` §1 [D]. La UI lo lee para avisar (`pos/index.jsx` ≈L58-59) [E]. | **Funcional**, con bloqueo bajo lock. |
| PDFs (consulta, receta, cobro) | Identidad | `render_branded_pdf` usa solo `organization.name` (`core/pdf/document.py` ≈L119-131); tema fijo `DEFAULT_THEME` («Fase 2» de branding pendiente, `theme.py` ≈L62-71) [E]. | Sin teléfono, dirección, `display_name` ni logo de la clínica en sus documentos [E]. |
| Historial clínico | `auto_create_medical_record` | Ver Citas. La consulta usa servicios activos (`ConsultationForm.jsx` ≈L342) [E]. | Un servicio no se puede desactivar desde Configuración (C11), así que tampoco retirarse de la consulta. |
| Sesión y fechas | `timezone` | Llega al frontend como `user.organization_timezone` en `/me/` [E]. | Guardar otra zona no refresca la sesión: el resto de la app usa la anterior hasta recargar [E]. |
| Analítica | `timezone` | Excluida del piloto (`modules/frontend.md`, § Esqueletos de carga) [D]; los snapshots diarios se agrupan por fecha local de la organización (`system-module-operations.md` §9) [D]. | Afectada por C1 [I]. |

**Configuración sin consumidor efectivo [E]:** `allow_emergency_walkin` (visible en la UI como
«Urgencias sin cita»), `default_appointment_duration_minutes`, `appointment_buffer_minutes`,
`week_starts_on`, `OrganizationSettings.locale` y `Organization.display_name`. `currency_code`
solo lo usa el agente; los montos de la UI y los PDFs no lo leen [I].

---

## 4. Documentación histórica y decisiones

| Documento / decisión | Lo que establece | Estado actual en código | Evaluación |
|---|---|---|---|
| ADR p53 — estado | «Aceptado (diseño) — sin implementación aún» | Implementado: tres agregados, cuatro endpoints, UI conectada [E] | **Desactualizado**; induce a pensar que falta construirlo |
| ADR p53 — tres agregados con un motivo de cambio | Identidad / reglas / horario separados | Respetado en modelos y escrituras [E] | Vigente y bien aplicado |
| ADR p53 — lectura agregada + escrituras separadas; horario de 7 días atómico | `GET /settings/configuration/`, `PUT` completo en una transacción | Implementado y probado [E] | Vigente |
| ADR p53 — `Organization` incluirá logo y datos fiscales | Campos futuros | No existen [E] | Pendiente, coherente con «futuros» |
| ADR p53 — «conectar consumidores posteriores (agenda, dashboard, WhatsApp, reportes)» | Paso 8 | WhatsApp y onboarding conectados; agenda del staff no [E] | Implementado parcialmente |
| Diseño técnico §1.4 — «ningún consumidor reimplementa apertura/cierre» | Un servicio de disponibilidad | `schedule_windows` compartido por lectura y escritura del agente [E]; el calendario usa horas fijas [E] | Cumplido en backend; el calendario no consume el horario |
| Diseño técnico §5.3 — escrituras solo ADMIN | Por rol | `organization.update`, delegable por ADR p69 [E] | Evolucionó; la doc no lo refleja |
| Diseño técnico §7.3 — «errores por campo mapeados por sección» | Regla frontend | Solo toasts (`toast.promise`) [E] | No implementado |
| Diseño técnico §11 — pruebas frontend (guardado por sección, UI degradada sin permisos) | Estrategia | No existen [E] | No implementado |
| Diseño técnico §13 — `display_name` canónico para clientes, `name` interno | Recomendación | `display_name` sin ningún consumidor; agente, PDFs y sesión usan `name` [E] | Implementado distinto; el campo no cumple lo que promete la UI |
| Diseño técnico §13 — `locale` con allowlist `es-MX`; `tax_rate` fuera de la pantalla | Recomendación | `locale` acepta cualquier texto de 16 caracteres y no se usa; `tax_rate` sigue fuera [E] | Sin allowlist; decisión de IVA nunca retomada |
| `modules/organizations.md` — tabla de toggles | 11 campos | Omite `allow_post_unpaid` y `credit_default_days`; describe como efectivos 4 ajustes sin consumidor («Duración sugerida al crear citas nuevas», «Intervalo entre citas», «Permite urgencias sin cita») [E] | **Desactualizado con riesgo**: describe comportamiento inexistente |
| `organizations.md` — «Solo `ADMIN` puede escribir» el horario | Por rol | Por capacidad delegable (p69) [E] | Desactualizado |
| `organizations.md` — zona horaria «solo se soporta México» | Restricción | Cualquier zona IANA válida, capturada como texto libre [E] | Contradicción |
| `modules/agent.md` — gate del kill switch | «No debe existir `enabled=True` + teléfono vacío; ese estado no debe ser alcanzable» | Alcanzable vaciando el teléfono en Configuración (C2) [E] | **Contradicción con efecto de seguridad** |
| `modules/frontend.md` — formularios con `handleFormError` | Obligatorio en POST/PATCH | Clínica, Horario, Reglas y Servicios no lo usan; MFA sí [E] | Incumplido |
| `frontend/CLAUDE.md` y `design-system.md` §0.4 / §5 | `can()` nunca rol; sin estilos inline fijos | Dos chequeos por rol; bloque de crédito y botones con `style={{}}` fijos (`RulesSection.jsx` ≈L60-80) [E] | Incumplido |
| `system-module-operations.md` §1 — toggles operativos | Lista de toggles y efectos | Coincide en los cinco con consumidor; no menciona los que no tienen efecto [E] | Vigente, incompleto |

No se proponen reescrituras por diferencias de redacción. Las tres que pueden provocar decisiones
erróneas son: el estado de ADR p53, la tabla de toggles de `organizations.md` y el gate del
kill switch de `agent.md`.

---

## 5. Evaluación de madurez

Escala: 1 Inicial · 2 Básica · 3 Funcional · 4 Madura · 5 Avanzada. Se usan medios puntos cuando
backend y producto difieren.

| Dimensión | Nivel | Evidencia y fortalezas | Limitaciones | Por qué no el siguiente nivel |
|---|---|---|---|---|
| 1. Datos de la clínica e identidad | **2 Básica** | 14 campos editables; teléfono con regla real; datos consumidos por el agente [E] | `display_name` sin consumidor; `name` no editable desde UI; zona horaria en texto libre sin protección (C1); sin logo, RFC ni datos en PDFs; `whatsapp` sin validación y con etiqueta engañosa | Para 3 debería llegar a los documentos y el cliente debería ver el nombre que la clínica escribe |
| 2. Horario y disponibilidad | **3 Funcional** | Semana con descanso, 7 días atómicos, validación doble (serializer y modelo), lock compartido con el agente, defaults sembrados [E] | Sin festivos ni cierres por fecha; la agenda del staff lo ignora; en ≤880 px se ocultan las columnas de descanso [E/I] | Para 4: cierres excepcionales y agenda que lo respete |
| 3. Reglas operativas | **2.5** | Cinco reglas con efecto, aplicadas en servidor bajo lock (caja, crédito, confirmación, atención sin mascota) [E] | Una visible sin efecto; cuatro ocultas sin efecto; etiquetas ambiguas («Atención sin cita» solo controla la atención sin **mascota**); sin explicación de impacto | Para 3, todo lo visible debe tener efecto y nombre exacto |
| 4. Catálogo de servicios | **2.5** | CRUD con `public_id`, precio > 0 en base, especialidad ligada a Equipo, `PROTECT` contra borrar historia, precio congelado en el cobro [E] | No se puede desactivar desde la UI; borrar un servicio usado falla con mensaje genérico; sin impuesto, categoría ni duración; precio sin aclarar IVA | Para 3: ciclo de vida activo/inactivo y precio claro |
| 5. Cuenta y seguridad | **3.5** | Cambio de contraseña con contraseña actual, throttle, revocación de sesiones; MFA TOTP con respaldo y throttle; credenciales `no-store` [E] | Cuenta personal metida en la configuración de la clínica e inalcanzable desde el menú para quien no la configura; botón de la barra que no hace nada fuera del apartado Cuenta; mínimo de 8 caracteres | Backend ≈4; la UX lo baja |
| 6. Permisos | **2.5** | Backend correcto y probado en `me/`; aislamiento total; capacidades separadas para servicios [E] | Ruta sin guarda; dos decisiones por rol; desalineado con p69; un solo permiso para identidad, horario y reglas financieras; sin pruebas de 403 en `settings/` y `schedule/` | Para 3: UI por capacidad y ruta protegida |
| 7. Auditoría de cambios | **1.5** | `OrganizationTimezoneAudit`; `updated_by` en servicios (último escritor) [E] | Nada registra quién activó el crédito, desactivó la caja obligatoria, cambió el horario o un precio; sin eventos de log; sin vista | Para 2, al menos un evento persistido por guardado |
| 8. UX | **2.5** | Shell consistente, esqueletos con la forma real, carga perezosa, enlace profundo desde el onboarding, confirmación al borrar servicio [E] | Carga fallida = esqueleto infinito; sin indicador de cambios pendientes; errores en toast; zona horaria en texto libre; estilos inline; etiquetas en mayúsculas en Servicios | Para 3: estados de error y de cambios pendientes, errores en el campo |
| 9. Integración | **2.5** | Agente y onboarding conectados con fuente única; reglas de caja y crédito en servidor; cambios inmediatos sin caché [E] | 6 campos sin consumidor; calendario con horas fijas; IVA invisible; PDFs sin datos de clínica; invariante del agente rompible | Para 3, cada campo editable debe tener un efecto verificable |

**Valoración general: 2.4/5 (Básica alta).** El promedio simple de la tabla da 2.5, pero no se usa
tal cual por dos motivos: (1) la auditoría (1.5) y los P1 de C1–C3 afectan dinero, agenda y
urgencias, que pesan más que la UX; (2) la nota alta de Cuenta (3.5) es casi toda de backend y no
compensa que Configuración muestre controles que no hacen nada. Fortaleza estructural: el modelo de
p53 y el aislamiento son correctos, así que las mejoras no exigen rediseñar la persistencia.

---

## 6. Evaluación individual del frontend

### 6.1 Clínica (`ClinicSection.jsx`)

| Aspecto | Hallazgo |
|---|---|
| Objetivo | Identidad, contacto y ubicación que usan el agente y el onboarding [E] |
| Información | Cabecera con inicial, nombre y meta; nombre comercial, teléfono, WhatsApp, correo, sitio, zona horaria, dirección (5 campos), mapa, indicaciones [E]. No muestra `name`, `address_line2`, coordenadas ni IVA |
| Acciones | Editar y «Guardar cambios» [E] |
| Obtención | Del agregado cargado por el layout [E] |
| Persistencia | `PATCH /api/organizations/me/` con los 14 campos siempre, cambien o no (≈L15-30) [E] |
| Validación frontend | Ninguna (solo `type="email"` sin uso de `checkValidity`) [E] |
| Validación backend | Teléfono, correo, URL, zona IANA, coordenadas [E] |
| Carga | Esqueleto del layout [E] |
| Error | Toast con `apiError`; no marca el campo [E] |
| Vacío | Placeholders; nombre comercial usa `name` como placeholder [E] |
| Confirmación | Toast de éxito; en onboarding avisa si falta el teléfono [E] |
| Error de red | Toast; lo tecleado se conserva [E] |
| Cambios sin guardar | Persisten en memoria al cambiar de apartado, sin indicador; la cabecera ya muestra los valores no guardados como si lo estuvieran; se pierden al salir sin aviso [E] |
| Permisos | Ninguno en UI; backend `organization.update` [E] |
| Dependencias | Cambiar la zona horaria cambia la interpretación de toda la agenda sin confirmación (C1) [E] |

### 6.2 Horarios (`ScheduleSection.jsx`)

| Aspecto | Hallazgo |
|---|---|
| Objetivo | Horario semanal que usa el agente para ofrecer citas y el aviso de fuera de horario [E] |
| Información | Tabla de 7 filas: abierto, entrada, salida, descanso, desde, hasta [E] |
| Acciones | Abrir/cerrar día (pone 09–18 al abrir), activar descanso (13–14), editar horas, «Guardar horario» [E] |
| Obtención | Agregado del layout [E] |
| Persistencia | `PUT /api/organizations/schedule/` con los 7 días; atómico [E] |
| Validación frontend | Ninguna: se puede enviar salida < entrada [E] |
| Validación backend | Exacta (7 días, orden, descanso dentro) con errores por `day_N` [E]. Un elemento que no sea objeto o un `weekday` de texto produce un error de tipo no controlado (≈L180-182) → 500 [E por lectura, no ejecutado] |
| Carga / error / vacío | Esqueleto; toast; no hay vacío (siempre 7 filas) [E] |
| Confirmación | Toast «Horario guardado» [E] |
| Error de red | Toast; conserva la edición [E] |
| Cambios sin guardar | Igual que Clínica [E] |
| Permisos | Ninguno en UI [E] |
| Responsive | ≤880 px oculta Descanso, Desde y Hasta (`config.module.css` ≈L579): no se puede editar el descanso en tablet o móvil [E CSS / I visual] |
| Dependencias | No hay cierres por fecha (decisión de p53 Fase 1) [D] |

### 6.3 Reglas operativas (`RulesSection.jsx`)

| Aspecto | Hallazgo |
|---|---|
| Objetivo | Reglas de citas, cobros y caja [E] |
| Información | 7 interruptores + plazo de crédito al activar crédito [E] |
| Acciones | Alternar y «Guardar reglas» [E] |
| Obtención | Agregado del layout [E] |
| Persistencia | `PATCH /api/organizations/settings/` con **el objeto completo**, incluidos los 6 ajustes ocultos [E] |
| Validación frontend | Plazo acotado 1–365 en el `onChange` [E] |
| Validación backend | Rangos [E] |
| Carga / error / vacío | Esqueleto; toast; n/a [E] |
| Confirmación | Toast; ninguna confirmación para reglas con peso operativo (caja obligatoria, crédito) [E] |
| Error de red | Toast [E] |
| Cambios sin guardar | Sin indicador: un interruptor movido parece aplicado hasta guardar [E] |
| Permisos | `canManage` por rol (≈L42-46 con el valor de `index.jsx` ≈L69) [E] |
| Contenido | «Urgencias sin cita» no tiene efecto; «Atención sin cita» describe otra cosa que su etiqueta; «Historial clínico automático» crea un expediente vacío después de completar la cita [E] |
| Estilo | Bloque de crédito con estilos inline fijos [E] |

### 6.4 Servicios (`ServicesSection.jsx`)

| Aspecto | Hallazgo |
|---|---|
| Objetivo | Catálogo que se cobra y que el agente cotiza [E] |
| Información | Nombre, especialidad, «Inactivo», precio con 2 decimales y sin símbolo de moneda ni IVA [E] |
| Acciones | Crear, editar, eliminar [E] |
| Obtención | `GET /api/billing/services/` (todos, activos e inactivos) [E] |
| Persistencia | `POST`/`PATCH`/`DELETE /api/billing/services/{public_id}/`; refetch tras éxito [E] |
| Validación frontend | Nombre obligatorio, precio > 0 [E] |
| Validación backend | Sanitizado, regex del nombre, precio > 0 y CHECK en base [E] |
| Carga / error / vacío | Esqueleto; toast; `EmptyState` con acción condicionada por permiso [E] |
| Confirmación | `useConfirm` al eliminar [E] |
| Error de red | Toast [E] |
| Error al eliminar | Mensaje fijo «puede estar en uso», ignora el `409` y su `protected_count` [E] |
| Cambios sin guardar | Cerrar el modal descarta sin preguntar [E] |
| Permisos | Solo «Nuevo» por `can("service.create")`; editar y eliminar sin condición [E] |
| Ciclo de vida | `is_active` viaja en el formulario pero no tiene control: no se puede desactivar un servicio, y uno usado no se puede borrar (`PROTECT`) [E] |
| Estilo | Etiquetas en mayúsculas («NOMBRE *», «PRECIO BASE *») frente al resto del sistema [E] |

### 6.5 Cuenta (`AccountSection.jsx`)

| Aspecto | Hallazgo |
|---|---|
| Objetivo | Acceso personal [E] |
| Información y acciones | Fila «Contraseña» con modal de `ChangePasswordForm`; MFA debajo [E] |
| Persistencia | `POST /api/users/change-password/`; tokens nuevos y `refreshUser` [E] |
| Validación | Frontend y backend con `handleFormError` [E] |
| Estados | Errores en el campo; confirmación por toast [E] |
| Permisos | Ninguno; se muestra también a la cuenta demo, que el backend rechaza (`NotDemoAccount`) [E] |
| Acceso | Solo dentro de `/config`, que el menú oculta a quien no tiene `organization.update` [E] |
| Barra superior | «Cambiar contraseña» dispara un evento que solo escucha `AccountSection`, montado únicamente con el apartado Cuenta activo: desde Clínica (el apartado por defecto) el botón no hace nada [E] |

### 6.6 MFA (`MfaSettings.jsx`)

| Aspecto | Hallazgo |
|---|---|
| Objetivo y alcance | Verificación en dos pasos opcional para ADMIN (ADR p68) [E] |
| Flujo | Contraseña → clave tecleable o enlace `otpauth://` → primer código → 10 códigos de respaldo; desactivar o regenerar con contraseña + código [E] |
| Validación y errores | Campos obligatorios en frontend, errores del servidor en el campo (`handleFormError`) [E] |
| Estados | Botones deshabilitados durante la petición; textos de carga [E] |
| Riesgo | El modal se puede cerrar con × en el paso de códigos de respaldo; quedan inaccesibles aunque el MFA ya esté activo [E] |
| Pruebas | 4 casos [E] |

### 6.7 Navegación y componentes compartidos

| Aspecto | Hallazgo |
|---|---|
| Organización | Menú lateral de ajustes (patrón habitual de páginas de configuración); un apartado a la vez [E] |
| Carga fallida | Si falla `getConfiguration`, `org` queda `null` y el layout muestra el esqueleto **indefinidamente**, sin mensaje ni reintento (`index.jsx` ≈L85-87, L112) [E] |
| Guardado | Por apartado; no hay riesgo de que un guardado sobrescriba otro agregado. Sí entre dos personas: cada `PATCH` reenvía el agregado completo sin precondición, así que gana el último [E] |
| Mezcla de alcances | Clínica, reglas y catálogo (de la organización) conviven con Cuenta (de la persona) [E] |
| Subtítulo | «Información, horarios y reglas operativas» omite servicios y cuenta [E] |

---

## 7. Benchmark competitivo: módulos de configuración

### 7.1 Comparabilidad y método

La comparación tiene dos niveles: **cómo está armado el módulo de configuración** de cada sistema
(punto de entrada, secciones, niveles de alcance, permisos, forma de editar y guardar, qué queda
fuera, ayudas en pantalla) en §7.2 y §7.3, y **qué cubre** en §7.4.

Los competidores con documentación pública venden sobre todo a clínicas y hospitales en EE. UU.,
Canadá, Europa y Australia, con equipos y presupuestos de otra escala; Provet y Vetspire
configuran además por sede. Los productos de habla hispana (Okvet, QVET) y Covetrus Pulse no
publican la estructura de su configuración. Una casilla «NV» **no** significa que el competidor
carezca de algo: significa que no se pudo verificar en fuentes públicas el 2026-11-26. Las
páginas de ezyVet no se pudieron leer (el sitio devuelve un aviso de navegador no soportado): su
estructura se reconstruye con los títulos de los artículos oficiales y los extractos del buscador.

| Producto | Mercado principal | Segmento aparente | Estructura del módulo documentada | Limitaciones |
|---|---|---|---|---|
| ezyVet (IDEXX) | EE. UU., Oceanía, Reino Unido [I] | Clínicas medianas, hospitales y grupos | Parcial (rutas de menú y títulos) | Contenido de los artículos no legible |
| Provet Cloud (Nordhealth) | Europa y Reino Unido [I] | Clínicas y hospitales, multisede | Sí, a nivel de sede | El artículo de encabezado, pie y logo da 404 |
| Vetspire | EE. UU. y Canadá (moneda USD/CAD documentada) | Clínicas y grupos | Sí: organización, preferencias, sede y usuario | Contraseña y 2FA personales no documentados en las páginas leídas |
| Digitail | Europa y EE. UU. [I] | Clínicas pequeñas y medianas | Sí: perfil, preferencias, fiscal, series, seguridad | Rutas de menú inconsistentes entre artículos («Administration» frente a «Settings») |
| Shepherd | EE. UU. (solo dólares) | Clínicas pequeñas y medianas | Sí: árbol completo de «Clinic Settings» | Configuración personal no documentada |
| Covetrus Pulse | Norteamérica | Clínicas y grupos | No | Solo material comercial («altamente personalizable», sin decir dónde) |
| Okvet | Latinoamérica [I] | Clínicas pequeñas | No | Solo fichas de directorios |
| QVET (QSOFT) | España y Latinoamérica [I] | Clínicas y hospitales | No | Solo fichas de directorios |

### 7.2 Anatomía del módulo en cada sistema

#### SaaSLyVet (punto de comparación) [E]

- **Entrada:** menú lateral, grupo Admin → «Configuración» (`/config`), visible con
  `organization.update`. En el mismo grupo están Equipo e Importar datos.
- **Estructura:** 5 apartados planos y sin agrupar: Clínica · Horarios · Reglas operativas ·
  Servicios · Cuenta. Unos 30 campos editables en total.
- **Niveles:** uno solo, la organización, con la cuenta personal mezclada dentro.
- **Acceso:** `organization.update` para clínica, horario y reglas; `service.*` para servicios;
  ruta abierta por URL (§2.3).
- **Edición:** formularios siempre editables, guardado explícito por apartado y sin indicador de
  cambios.
- **Fuera del módulo:** usuarios, permisos y ausencias (Equipo); productos (Inventario);
  interruptor del agente (Inbox); FAQ del agente (sin UI); IVA (solo plataforma).
- **Ayudas:** una línea de descripción por apartado y por regla; el asistente de primer uso lleva
  directo al apartado según el estado real de la clínica.

#### Shepherd [C]

- **Entrada:** «Admin > Clinic Settings», en mosaicos que se abren por su encabezado o por un
  elemento.
- **Estructura (orden de la página):**
  1. *Clinic Profile & Operations:* General Information (nombre, correo, teléfono, fax, sitio,
     dirección, zona horaria, moneda, logo), Office Hours & Closures, Subscription & Billing,
     Feature Settings.
  2. *Financial Settings:* Shepherd Pay, Tax Settings, Invoice Settings, Production Settings,
     Finance Charges, Payment Types, Client & Patient Discounts.
  3. *Practice Management:* Prescription Settings, Notes & Disclaimers, Clinic Shortcuts,
     Locations, Referral Sources, Client Types.
  4. *Clinical Settings:* SOAP Vitals, Default Dose, Diagnoses Settings, Diagnoses List, Body Maps,
     Physical Exam Templates.
  5. *Label Management.*
  6. *AI Settings.*
- **Niveles:** toda la práctica («apply across the entire practice»).
- **Acceso:** según el rol; una sección puede verse sin poder tocarse («your user role may not
  have permission»).
- **Edición:** botón «Edit» por mosaico; el guardado del resto no se documenta.
- **Fuera:** usuarios y cierre automático de sesión (Admin > Users > Settings), impresoras y
  etiquetas. Edición masiva («Bulk Edit») de clientes, productos, recordatorios y citas en la
  misma colección de ayuda.
- **Ayudas:** bloque «Can't find a section?», enlaces «Learn more», valores recomendados.

#### Digitail [C]

- **Entrada:** icono de perfil → Administration, con varias páginas: Clinic Profile (pestaña
  Preferences), Company Fiscal Information (con Tax Rates), Series and Numbers y Team.
- **Estructura de Preferences (8 grupos):** General (cierre por inactividad, lista blanca de IP,
  2FA, reloj checador); Languages; Units & Formats (peso, temperatura; zona horaria fijada por el
  país y **no editable**); Records; Inventory & Billing (impuestos de productos y servicios,
  cargo por dispensación, descuentos, alertas de stock); Invoices & Statements (columnas, datos
  fiscales, QR, recordatorios en factura); Appointments (reglas de reserva en línea); Pet Parents
  Portal/App.
- **Datos fiscales:** página propia con identificación fiscal, razón social, dirección,
  administrador, si paga impuestos y datos bancarios; las tasas, una vez guardadas, **no permiten
  cambiar porcentaje ni área**, solo el nombre.
- **Niveles:** clínica (con opciones para grupos de clínicas) y persona: «My Profile» concentra
  2FA individual, PIN, contraseña, firma y horario de atención.
- **Acceso:** permisos con nombre: «Manage Clinic Preferences», «Manage Clinic Settings» y
  acceso de administración para impuestos.
- **Edición:** «Save» por página.
- **Fuera:** servicios y precios (Inventory Settings), recordatorios y formularios (Clients
  Settings), protocolos y plantillas (Medical Settings), salas y tipos de visita (Appointments
  Settings), usuarios y roles (Team).
- **Ayudas:** preguntas frecuentes, «How to Verify It Works», avisos de lo que no se puede
  deshacer, valores por defecto descritos.

#### Provet Cloud [C, parcial]

- **Entrada:** botón con el nombre de la clínica (arriba a la izquierda) → selector de sede →
  Settings.
- **Estructura documentada:** Settings > (General) > Clinic location, con: *Clinic location
  profile* (contacto, país, identificadores financieros, color de la barra), *Clinic location
  settings* (8 áreas: notas clínicas, diagnósticos, requisitos de ficha, precios y presupuestos,
  agenda y comunicación externa, medicamentos y recetas, inventario, modo hospital), pestaña
  *Finance*, *Scheduling & Calendar*, *Booking Settings*, *Reminder* y logo y color. Además,
  *Print settings*, *Lists & Templates* e *Integrations*.
- **Niveles:** por sede, con una «sede central» y grupos de sedes (artículos enlazados, no
  leídos).
- **Acceso:** Settings solo visible con permisos; la pestaña Finance tiene permiso propio de
  lectura y escritura.
- **Edición:** lápiz junto al título de cada bloque (modo edición explícito).
- **Datos reutilizados:** el contacto de la sede sale en los impresos según la configuración de
  impresión.
- **Ayudas:** tooltip con descripción larga en cada ajuste; se configura «usually during
  implementation».

#### Vetspire [C]

- **Entrada:** «More > Admin»: «where preferences, location settings, users, integrations, and
  configurations are set».
- **Áreas de Admin (orden de la página):** Organization Settings; Preferences; Manage User
  Settings; User Roles and Permissions; Locations; Payment Processors and Payment Methods;
  PrintNode; API Keys; Online Booking Widget; Configure; rDVM Mass Upload; Price Changes;
  Automation Triggers; Protocols Migrator.
- **Niveles con herencia:** *organización* (nombre, control de horas, unidad de peso, logo);
  *Preferences* (unos 35 ajustes «que aplican a todas las sedes»: tiempo de inactividad,
  contraseñas complejas, cédula estatal obligatoria…); *sede* (datos básicos, zona horaria,
  impuestos, recargo, moneda, recordatorios, SMS, impresión, marketing, horario por día y por
  profesional; el logo de la sede **sustituye** al de la organización); *usuario* (Admin > Staff >
  Users, con historial de cambios del perfil).
- **Edición:** «a Save button displays at the top of the screen» solo cuando hay cambios.
- **Ayudas:** límites y valores por defecto documentados por ajuste (por ejemplo, de 3 minutos a
  14 días para la inactividad).

#### ezyVet [C por títulos y extractos]

- **Entrada:** pestaña principal Admin, donde están «all system settings».
- **Estructura conocida:** Admin > Settings > System (pantalla System Settings, con pestaña
  Communication y sección Business Settings); Integration (reserva en línea, Vello); Site
  configuration («applicable to a full ezyVet site»); Address configuration (dirección, teléfono y
  correo de la organización); Admin > Financial > Tax Rates; Admin > Templates > Template Settings
  (logo); seguridad y acceso con bloqueo de módulos.
- **Acceso:** «practice managers or persons who have the Super User role».
- **Edición, niveles y ayudas:** NV.

#### Covetrus Pulse, Okvet, QVET [NV]

No se encontró documentación pública de la estructura de su configuración. No se concluye que
carezcan de ella.

### 7.3 Comparación de los módulos

| Rasgo | SaaSLyVet | Shepherd | Digitail | Provet | Vetspire | ezyVet |
|---|---|---|---|---|---|---|
| Entrada | Menú «Configuración» | Admin > Clinic Settings | Perfil > Administration | Nombre de clínica > Settings | More > Admin | Pestaña Admin |
| Organización | 5 apartados planos | 6 grupos por dominio, ≈26 secciones | Páginas por tema + 8 grupos de preferencias | Perfil, ajustes por área, finanzas, agenda, impresión, plantillas | 14 áreas de Admin | Settings / Integration / Site / Financial / Templates |
| Niveles | Organización | Práctica | Clínica (+ grupos) y persona | Sede (+ central y grupos) | Organización → sede → usuario, con herencia | Sitio |
| Cuenta personal | Dentro de Configuración | NV | Separada («My Profile») | NV | Perfil en Staff; contraseña NV | NV |
| Área fiscal / impuestos | No existe | Financial Settings | Fiscal Information + Tax Rates | Identificadores financieros + pestaña Finance | Impuestos por sede | Financial > Tax Rates |
| Permisos para configurar | Uno para clínica, horario y reglas; otro para servicios | Por rol | Permisos con nombre por página | Permiso propio para Finance | NV | Practice manager / Super User |
| Edición y guardado | Siempre editable, guardar por apartado, sin indicador | «Edit» por mosaico | «Save» por página | Lápiz por bloque | «Save» aparece al haber cambios | NV |
| Ayudas | Una línea por ajuste | «Can't find a section?», «Learn more» | FAQ, verificación, avisos | Tooltip por ajuste | Límites y defaults | NV |
| Datos de la clínica en documentos | Solo el nombre legal | Logo e información en impresos | Datos fiscales en factura (ocultables) | Contacto en impresos | Nombre visible en facturas, logo en PDF | Logo en plantillas |
| Protección de datos de arranque | Zona horaria libre y editable | NV | Zona por país no editable; tasa inmutable tras guardar | «Usually configured during implementation» | NV | NV |
| Primer uso guiado | Sí, por estado real | NV | NV | NV | NV | NV |

### 7.4 Lectura de la comparación

1. **Tamaño.** El de SaaSLyVet es el módulo más pequeño y el único plano. Para 1–15 personas el
   tamaño no es el problema; la diferencia está en que los demás **agrupan por dominio de
   negocio** (identidad, finanzas, práctica clínica, agenda, comunicaciones, seguridad) y así
   dejan claro qué toca el dinero. En SaaSLyVet, caja obligatoria y crédito comparten apartado con
   la confirmación de citas [E].
2. **Clínica y persona separadas.** Donde está documentado (Digitail, y Vetspire para el perfil),
   la configuración personal vive aparte de la de la clínica. SaaSLyVet es el único caso
   verificado que las mezcla, y por eso el personal no llega a su contraseña (C6).
3. **Finanzas con área propia.** Los cinco competidores documentados tienen un lugar para
   impuestos y datos fiscales; Provet le da además un permiso propio. SaaSLyVet no tiene área ni
   tasa visible (C3, C4).
4. **Permisos por área.** Digitail y Provet separan quién configura preferencias, documentos o
   finanzas. SaaSLyVet tiene un solo código que, con ADR p69, se puede delegar completo.
5. **Datos que se reutilizan.** Provet, Vetspire y Shepherd documentan que lo capturado en el
   perfil aparece en impresos y facturas. En SaaSLyVet el «Nombre comercial» no aparece en ningún
   lado y los PDFs solo llevan el nombre legal (C7, C13).
6. **Protección de datos de arranque.** Digitail no deja editar la zona horaria (la toma del país)
   ni cambiar una tasa ya guardada; Provet asume que estos ajustes se fijan en la implementación.
   SaaSLyVet deja la zona en texto libre y editable en cualquier momento (C1).
7. **Edición explícita.** Vetspire muestra «Save» solo cuando hay cambios; Provet y Shepherd entran
   en modo edición por bloque. SaaSLyVet guarda por apartado, pero sin señal de cambios pendientes
   (C10, §9.2).
8. **Ayuda en pantalla.** Tooltips por ajuste (Provet), guía de «no encuentro la sección»
   (Shepherd) y límites documentados (Vetspire) frente a una línea por ajuste en SaaSLyVet.
9. **Niveles.** Organización → sede → usuario con herencia (Vetspire) y configuración por sede
   (Provet) responden a grupos y hospitales. Un solo nivel es correcto para SaaSLyVet (ADR p48):
   **no es brecha**.
10. **Ventaja relativa posible.** El primer uso de SaaSLyVet lleva al apartado según el estado real
    de la clínica (teléfono, servicios). En las páginas leídas de los competidores no aparece un
    asistente equivalente, pero eso es NV, no una ausencia comprobada.

### 7.5 Cobertura funcional por dimensión

C = confirmado (evidencia pública explícita), I = inferido, NV = no verificado.

| Dimensión | ezyVet | Provet | Vetspire | Digitail | Shepherd | Pulse | Okvet | QVET |
|---|---|---|---|---|---|---|---|---|
| 1. Datos generales | C (título) | C | C | C | C | NV | NV | NV |
| 2. Horario de atención | C | C (rango y bloqueo) | C | C | C | NV | NV | NV |
| 3. Festivos y cierres | NV | C (por país) | NV | C (título) | C | NV | NV | NV |
| 4. Impuestos | C | I (pestaña Finance) | C | C | C | NV | I | I |
| 5. Catálogo y precios | C | I (precios y presupuestos) | C (Price Changes, recargo) | C (títulos) | I (edición masiva) | NV | NV | NV |
| 6. Plantillas y documentos | C | C | I | C | C | NV | NV | NV |
| 7. Recordatorios | C (título) | C | C | C (títulos) | C (parcial) | NV | I | NV |
| 8. Marca / logo | C | C | C | C | C | NV | NV | NV |
| 9. Integraciones | C | C | C | C | C | NV | NV | NV |
| 10. Seguridad y permisos | C | C | C | C | C | I | I | I |

### 7.6 Patrones aplicables (no para copiar)

- **Agrupar por dominio, no por tabla.** Un área de «Cobros e impuestos» separada de las reglas de
  atención hace evidente qué afecta al dinero (Shepherd, Digitail, Provet).
- **Persona fuera de la clínica.** La contraseña y el MFA en un perfil accesible para todos
  (Digitail «My Profile»).
- **Datos de arranque protegidos.** Zona horaria derivada o confirmada, y tasas que no se
  reescriben en silencio (Digitail).
- **Edición explícita con señal de cambios** (Vetspire, Provet).
- **Lo que se captura, se usa.** Contacto y logo de la clínica en todos los impresos (Provet,
  Vetspire, Shepherd).
- **Horario base con excepciones por fecha** (Shepherd, Digitail; Provet con festivos del país).
- **Señal de mercado mexicano:** un directorio atribuye a Wakyma Vets facturación compatible con
  CFDI 4.0 [I]; la emisión fiscal es un requisito comercial probable en México, pero es una
  decisión de producto mayor, no de Configuración (§12).

---

## 8. Matriz SaaSLyVet vs. mercado

| Capacidad | SaaSLyVet | Referencia competitiva | Nivel de mercado | Brecha | Prioridad |
|---|---|---|---|---|---|
| **Estructura del módulo** por dominio de negocio | 5 apartados planos; caja y crédito junto a reglas de citas | Shepherd (6 grupos), Digitail (páginas por tema y 8 grupos), Vetspire (14 áreas de Admin), Provet (áreas por sede) | Estándar | Media: no se distingue qué afecta al dinero | P2 |
| Configuración de clínica separada de la cuenta personal | Mezcladas en `/config` | Digitail («My Profile»), Vetspire (perfil en Staff), Shepherd (sesión en Users) | Estándar | Alta en coherencia (C6) | P2 |
| Área fiscal / de impuestos dentro de configuración | No existe | Shepherd, Digitail, Provet, Vetspire, ezyVet | Estándar | Alta (C3, C4) | P1 / P2 |
| Permisos por área de configuración | Un código para clínica, horario y reglas | Digitail (permisos por página), Provet (Finance con permiso propio) | Estándar | Media, más visible con la delegación de p69 | P3 |
| Edición con señal de cambios | Siempre editable, sin indicador | Vetspire (Save al haber cambios), Provet y Shepherd (modo edición) | Estándar | Media (C10) | P2 |
| Ayuda contextual por ajuste | Una línea | Provet (tooltips), Shepherd («Can't find a section?»), Vetspire (límites documentados) | Estándar | Baja-media | P3 |
| Datos de arranque protegidos | Zona horaria libre y editable siempre | Digitail (zona por país no editable, tasa inmutable) | Estándar | Alta (C1) | P1 |
| Niveles organización → sede → usuario | Un nivel | Vetspire, Provet | Empresarial | No aplica (ADR p48) | — |
| Primer uso guiado hacia la configuración | Sí, por estado real | NV en las páginas leídas | NV | Posible ventaja | — |
| Datos de contacto y ubicación | Sí, 14 campos, teléfono validado | Provet, Vetspire, Shepherd | Básico | Baja en captura; alta en uso: el nombre comercial no llega a ningún lado | P2 |
| Datos de la clínica en documentos | Solo `name` en el membrete | Provet, Vetspire, Shepherd | Estándar | Media: receta y cobro sin teléfono ni dirección de la clínica | P2 |
| Logo / marca | No | ezyVet, Provet, Vetspire, Shepherd | Estándar | Media, no urgente | P3 |
| Horario semanal | Sí, una franja + descanso, atómico | Todos con evidencia | Básico | Baja; la agenda del staff no lo usa | P2 |
| Cierres excepcionales / festivos | No | Shepherd, Digitail, Provet | Estándar | Alta en cuanto el agente agende | P2 (P1 con agente activo) |
| Horario por profesional | Ausencias en Equipo (ADR p67), sin horario propio | Vetspire, Digitail | Estándar | Media; pertenece a Equipo/Citas | P3 |
| Impuestos | Una tasa por organización, invisible e inmodificable por la clínica | ezyVet, Vetspire, Digitail, Shepherd | Estándar | Alta en transparencia; media en granularidad | P1 (precio con/sin IVA, C3) / P2 (tasa visible, C4) / P3 (granularidad) |
| Datos fiscales y CFDI | No («Cobro» sin facturación fiscal) | Digitail (series, datos fiscales); Wakyma (CFDI, inferido) | Estándar en México [I] | Alta comercialmente; fuera del alcance de Configuración | P3 (decisión de producto) |
| Catálogo de servicios | CRUD + especialidad; sin activar/desactivar, categoría, duración ni impuesto | ezyVet | Estándar | Media | P2 |
| Reglas operativas | 7 visibles (6 con efecto) y 6 ocultas sin efecto | Digitail (preferencias) | Estándar | Media en calidad, no en cantidad | P2 |
| Recordatorios configurables | No (el agente tiene configuración propia en Inbox) | Provet, Vetspire | Estándar | Alta, dependiente de WhatsApp | P3 |
| Integraciones | Canal de WhatsApp provisionado por plataforma | Vetspire, Shepherd, Provet | Avanzado | No aplica todavía | — |
| Seguridad de la cuenta | Contraseña con revocación de sesiones + MFA para ADMIN | Digitail (2FA, IP, cierre por inactividad) | Estándar | Baja | P3 |
| Permisos de configuración | Un código para todo, UI por rol | Digitail («Manage Clinic Preferences»), Shepherd | Estándar | Media en coherencia | P2 |
| Auditoría de cambios de configuración | Solo zona horaria | ezyVet (change logs, ver auditoría de Equipo) | Avanzado | Media | P2 |

---

## 9. Brechas de UX/UI

Perspectiva: administrador de una clínica pequeña que también atiende, cobra o recibe.

### 9.1 Navegación

- El menú lateral es el patrón adecuado para una página de ajustes y no necesita las pestañas del
  panel de Equipo. Lo que falla es el **contenido**: mezcla lo de la clínica con lo de la persona.
  La contraseña y el MFA deberían estar a un clic para todos (por ejemplo, desde el avatar), no
  dentro de una página que el menú oculta a la mayoría [E]. Es lo que hacen Digitail («My
  Profile» frente a «Clinic Preferences») y Vetspire (perfil del usuario en Staff) (§7.2).
- Los competidores agrupan los ajustes por dominio (Shepherd: perfil y operación, finanzas,
  práctica, clínica…). Con 5 apartados no hace falta más profundidad, pero sí separar lo que toca
  el dinero de lo que toca la agenda [I].
- Los apartados no tienen URL propia: no se puede enlazar «Horarios» desde un aviso del agente o de
  Citas [E].
- Falta jerarquía entre lo esencial (teléfono, horario, servicios) y lo raro (reglas de caja o
  crédito): todo pesa igual [I].

### 9.2 Guardado

- El guardado por apartado es correcto y no hay riesgo de pisar otro agregado [E].
- Faltan: indicador de cambios pendientes (el punto que Equipo pone en la pestaña con cambios es
  reutilizable), aviso al salir con cambios, y que la cabecera de identidad no muestre valores no
  guardados como si fueran reales [E].
- Las reglas con peso operativo (caja obligatoria, crédito) se activan sin explicar su efecto ni
  confirmar [E].

### 9.3 Formularios

- Errores siempre en toast, nunca en el campo; en el horario, el mensaje no dice qué día falló [E].
- Sin validación previa en Clínica y Horario [E].
- Zona horaria en texto libre con un valor técnico («America/Mexico_City»), sin lista ni
  explicación de consecuencias [E].
- «WhatsApp — Número del asistente virtual» sugiere que cambia el número del asistente; el canal
  real lo provisiona plataforma (`ChannelAccount`) [E]. Mismo problema con «Nombre comercial —
  Como aparece ante tus clientes» (§3).
- Precio sin moneda ni indicación «sin IVA» [E].
- Etiquetas de Reglas en voz de sistema («Historial clínico automático», «Historial de cambios»)
  sin ejemplos del efecto [I].

### 9.4 Consistencia visual

- Cumple el design system en shell, botones, inputs, esqueletos y `EmptyState` [E].
- Se aparta en: estilos inline fijos (Reglas, botones de modales), etiquetas en mayúsculas en
  Servicios, decisiones por rol, y tabla de horario que pierde columnas en móvil [E].
- **Reutilizable de Equipo:** errores en el campo, indicador de cambios sin guardar, una acción a
  la vez con estado de carga, textos cortos y color solo para lo que pide atención (D6), resumen
  en el encabezado («Falta el teléfono», «2 servicios inactivos»).
- **No reutilizable:** el panel lateral con pestañas (Configuración no es una lista de entidades),
  las pastillas con popover y la densidad de la tabla de Equipo.
- Revelado progresivo con sentido: dejar visibles teléfono, horario y servicios; agrupar caja y
  crédito como «Cobros» con explicación; esconder lo que no tiene efecto hasta que lo tenga.

---

## 10. Fortalezas y debilidades

### 10.1 Fortalezas comprobadas

1. **Modelo de datos correcto (ADR p53).** Identidad, reglas y horario separados por motivo de
   cambio; escrituras separadas y lectura agregada [E]. Las mejoras propuestas no exigen
   rediseñar la persistencia.
2. **Aislamiento multi-tenant sin fisuras** en todos los endpoints de configuración y servicios;
   organización nunca aceptada del cliente; probado [E].
3. **Horario atómico y serializado con el agente**: `PUT` de 7 días con `select_for_update`, y el
   agente lee la fila con `FOR SHARE` antes de escribir una cita [E].
4. **Reglas financieras aplicadas en servidor bajo lock**, no solo en la UI: caja obligatoria en
   pagos y refunds [E] (y reversals según la documentación [D]); crédito en `post_checkout` [E].
5. **Teléfono validado con una regla única** compartida con clientes, que da sentido al hito del
   onboarding y a la plantilla de urgencia [E].
6. **El agente usa una sola fuente** para horario y contacto, y es defensivo: sin datos no inventa
   [E].
7. **Historia protegida en servicios**: `PROTECT`, precio congelado en Checkout/factura y CHECK de
   precio positivo [E].
8. **Cuenta segura en backend**: contraseña actual, throttle, revocación de sesiones, MFA con
   respaldo y respuestas `no-store` [E].

### 10.2 Debilidades y problemas

| ID | Severidad | Problema | Evidencia | Impacto | Alcance | Recomendación |
|---|---|---|---|---|---|---|
| C1 | **P1** | Cambiar la zona horaria desalinea las citas existentes, sin aviso ni protección | Campo de texto libre (`ClinicSection.jsx` ≈L89-91); `OrganizationSerializer.update` solo audita (≈L59-76); `appointment_interval` calcula `start/end_datetime` en UTC al crear (`appointments/creation.py` ≈L98-118); nada recalcula ni lee `timezone_updated_at` [E] | Citas creadas antes conservan su instante UTC y las nuevas se calculan con otra zona: la restricción de no-solapamiento (INV-D) compara instantes y puede dejar pasar dos citas que la agenda muestra a la misma hora, o rechazar huecos libres; agente, recordatorios y analítica se desplazan [I]. Escenario realista: la zona nace en `America/Mexico_City`, el onboarding no la pregunta y una clínica de Quintana Roo o Baja California la corrige semanas después. La sesión sigue con la zona vieja hasta recargar [E] | Citas, agente, analítica, Inbox | Tratar la zona como dato de puesta en marcha: selección cerrada de zonas de México, confirmación explícita y decisión de producto sobre qué hacer con citas futuras (bloquear el cambio, advertir con conteo o recalcular) |
| C2 | **P1** (latente) | Se puede vaciar el teléfono con el agente encendido | `validate_phone(..., allow_blank=True)` sin consultar el agente; el gate solo actúa al encender (`agent/serializers.py` ≈L240-263); `agent.md` declara ese estado inalcanzable [E] | La plantilla de urgencia pierde el número y cae al texto sin teléfono (`tier0.py` ≈L79-83) [E]. Mitigado: el agente no está activado en producción [D] | Agente, Configuración | Mantener el invariante en las dos direcciones: no permitir vaciar el teléfono mientras el agente esté encendido, o apagarlo explícitamente con aviso. Respetar la frontera entre dominios (organizations no debe importar agent) |
| C3 | **P1** (latente) | El precio que ven clínica y agente no es el que se cobra | El agente cita `base_price` como precio (`agent/tools.py` ≈L690-700) y no menciona impuesto; el Checkout suma `subtotal × tax_rate` (`billing/money.py` ≈L26-32); el formulario dice «PRECIO BASE» sin aclarar [E] | Con la tasa por defecto de provisión (16 %), el cliente que cotiza «$500» por WhatsApp paga $580 [I]; quien carga el catálogo no sabe si escribir precio con o sin IVA [I] | Agente, Servicios, Cobros, POS | Mostrar y comunicar siempre si un precio incluye IVA, con la misma regla en catálogo, agente y cobro |
| C4 | P2 | IVA invisible e inmodificable para la clínica | `tax_rate` de solo lectura (`organizations/serializers.py` ≈L22-25); lo fija plataforma (por defecto 0.16) [E]; no aparece en ninguna pantalla de Configuración [E] | La clínica no sabe qué tasa se aplica a todos sus cobros ni puede corregirla sin soporte. Una tasa única no distingue conceptos con tasas distintas; si la clínica lo necesita, depende de su régimen fiscal [NV] | Cobros, POS | Mostrar la tasa vigente en Configuración; decidir con criterio fiscal quién puede cambiarla y con qué confirmación |
| C5 | P2 | Permisos de la UI por rol y ruta sin guarda | `canManage = role !== "ASSISTANT"` (`index.jsx` ≈L69); `/config` sin redirección (`App.jsx` ≈L158); editar y eliminar servicios sin condición (`ServicesSection.jsx` ≈L106-111) [E] | Controles activos que terminan en 403, y delegaciones de p69 que la UI bloquea. Sin exposición de datos | Configuración | Decidir cada control por la capacidad del endpoint que llama, y la ruta por capacidad |
| C6 | P2 | Cuenta personal inalcanzable para la mayoría y botón de la barra que no funciona | Menú condicionado a `organization.update` (`Sidebar.jsx`); evento escuchado solo con el apartado Cuenta montado (`AccountSection.jsx` ≈L11-15, `Layout.jsx` ≈L95-101) [E] | VET, ASSISTANT y un ADMIN sin ese permiso no encuentran dónde cambiar su contraseña o activar MFA; el botón de la barra no hace nada en el apartado por defecto | Cuenta, Layout | Sacar «Mi cuenta» de la configuración de la clínica y hacerla accesible a todos |
| C7 | P2 | Opciones sin efecto, una de ellas visible | `allow_emergency_walkin` en la UI y sin consumidor; `default_appointment_duration_minutes`, `appointment_buffer_minutes`, `week_starts_on`, `locale` y `display_name` sin consumidor (§3) [E]; `organizations.md` describe su efecto [D] | El ADMIN cree haber configurado algo que no ocurre; la documentación orienta mal a quien mantiene el código | Configuración, Citas, documentación | Conectar cada una o retirarla de la UI y de la documentación; mientras no tenga efecto, que no se ofrezca |
| C8 | P2 | La agenda del staff ignora el horario | Calendario 07–20 con 30 min y lunes fijos (`appointments.jsx` ≈L1190); creación del staff sin `require_schedule` [E] | Citas fuera de horario sin aviso; franjas de clínicas que cierran después de las 20:00 invisibles en el calendario | Citas | Que el calendario muestre el horario de la clínica y advierta (no necesariamente bloquee) fuera de él |
| C9 | P2 | Sin auditoría de cambios de configuración | Sin `updated_by` ni eventos en `Organization`, `OrganizationSettings`, `OrganizationSchedule`; solo `OrganizationTimezoneAudit` [E] | «¿Quién activó el crédito?», «¿quién cambió el horario que usa el agente?» sin respuesta; `organization.update` es delegable (p69) | Configuración | Registro mínimo de qué cambió, quién y cuándo, legible por ADMIN |
| C10 | P2 | Carga fallida muestra esqueleto infinito | `org` queda `null` y no hay estado de error (`index.jsx` ≈L85-87, L112) [E] | El ADMIN no sabe si esperar o recargar | Configuración | Estado de error con reintento |
| C11 | P2 | Servicios: sin desactivar, borrado bloqueado y mensaje genérico | `is_active` sin control en el formulario; `PROTECT` en `CheckoutItem`/`MedicalRecordService`; error fijo «puede estar en uso» (`ServicesSection.jsx` ≈L68) [E] | Un servicio que ya se cobró no se puede retirar ni de la consulta ni del POS ni del agente | Servicios, Historial, POS, agente | Ciclo de vida activo/inactivo; explicar por qué no se puede eliminar y ofrecer desactivar |
| C12 | P2 | Errores en toast y sin validación previa | Sin `handleFormError` en Clínica, Horario, Reglas y Servicios (contrato de `frontend.md`) [E] | Correcciones a ciegas, sobre todo en el horario | Configuración | Errores en el campo y por día |
| C13 | P2 | PDFs sin datos de la clínica | `render_branded_pdf` solo usa `name` (`core/pdf/document.py` ≈L129) [E] | Receta y cobro sin teléfono ni dirección de quien los emite; si la normativa de recetas lo exige, no se pudo verificar [NV] | PDFs | Reutilizar los datos de Clínica en el membrete |
| C14 | P2 | Documentación desactualizada con efecto en decisiones | ADR p53 «sin implementación», tabla de toggles, «solo ADMIN», gate del kill switch (§4) [E] | Mantenimiento sobre supuestos falsos | Documentación | Corregir los tres documentos citados en §4 |
| C15 | P3 | Horario no editable en móvil y tablet | Columnas de descanso ocultas ≤880 px [E CSS] | Recorte no probado en navegador [I] | Horario | Disposición apilada en pantallas angostas |
| C16 | P3 | Último escritor gana entre dos administradores | `PATCH` completos sin precondición [E] | Raro con 1–15 personas | Configuración | Precondición o envío solo de lo cambiado |
| C17 | P3 | FAQ del agente sin UI; interruptor del agente fuera de Configuración | `faq_facts` sin referencias en el frontend; kill switch en Inbox [E] | El aviso de privacidad del agente solo se configura por API | Agente | Decidir dónde vive la configuración del asistente |
| C18 | P3 | Estilo y voz | Estilos inline, mayúsculas, etiquetas técnicas (§9) [E] | Percepción | Configuración | Alinear con el design system |
| C19 | P3 | Robustez del `PUT` de horario | Elemento no objeto o `weekday` de texto → excepción de tipo (≈L180-182) [E por lectura] | 500 en vez de 400 ante una petición mal formada | API | Validar tipos antes de comparar |
| C20 | P3 | Detalles menores | Señal de inicialización que traga excepciones; `id` expuesto junto a `public_id` (deuda POST-BETA-001); comentario obsoleto sobre facturas en `appointments/views.py` ≈L396; MFA cerrable antes de guardar los códigos [E] | Bajo | Varios | Limpieza oportunista futura |

Severidades revisadas: C1 es P1 y no P0 porque requiere una acción deliberada del ADMIN y no
expone datos; C2 y C3 son P1 por tocar urgencias y dinero comunicado al cliente, pero quedan
marcados como latentes mientras el agente no se active.

---

## 11. Funcionalidades recomendadas

Ordenadas por valor para una clínica de 1–15 personas. Ninguna es un plan técnico.

| # | Tipo | Propuesta | Problema | Frecuencia | Impacto | Relación con lo existente | Complejidad conceptual | Dependencias / riesgo |
|---|---|---|---|---|---|---|---|---|
| 1 | Corrección | Zona horaria protegida (lista de México, confirmación, decisión sobre citas futuras) | C1 | Una vez por clínica | Alto | Campo y auditoría ya existen | Baja-media | Decidir política sobre citas existentes |
| 2 | Corrección | Invariante teléfono/agente en ambas direcciones | C2 | Rara | Alto (urgencias) | Gate ya existe en una dirección | Baja | Frontera organizations ↔ agent |
| 3 | Corrección | Transparencia de IVA: tasa visible y precios marcados con/sin IVA en catálogo, agente y cobro | C3, C4 | Diaria | Alto | `tax_rate` ya se copia a cada Checkout | Baja (visibilidad) / media (edición) | Quién puede cambiar la tasa |
| 4 | Corrección | Permisos de la UI por capacidad, ruta protegida y «Mi cuenta» accesible a todos | C5, C6 | Diaria | Medio-alto | Patrón ya resuelto en Equipo | Baja | Ninguna |
| 5 | Mejora | Retirar o conectar lo que no tiene efecto; etiquetas exactas y explicación del efecto | C7 | — | Medio | — | Baja | Decidir qué ajuste se conecta (duración por defecto es el candidato natural) |
| 6 | Mejora | Estados de error, cambios pendientes y errores en el campo | C10, C12 | Cada edición | Medio | `handleFormError`, patrón de Equipo | Baja | Ninguna |
| 7 | Mejora | Servicios activos/inactivos con explicación al no poder borrar | C11 | Mensual | Medio | `is_active` ya filtra POS, consulta y agente | Baja | Ninguna |
| 8 | Mejora | Registro de cambios de configuración visible para ADMIN | C9 | Ocasional | Medio | `StaffAccessEvent` como precedente | Media | Datos a registrar sin PII innecesaria |
| 9 | Mejora | Datos de la clínica en el membrete de PDFs | C13 | Diaria | Medio | Campos ya capturados | Baja | Verificar requisitos de receta [NV] |
| 10 | Nueva | Cierres excepcionales del horario (días festivos, cierres puntuales) respetados por el agente y visibles en la agenda | Brecha de mercado | Mensual | Alto con agente activo | Ausencias por veterinario (p67) es el precedente de días completos | Media | Amplía ADR p53 Fase 1 (requiere ADR) |
| 11 | Mejora | Agenda del staff con el horario de la clínica y aviso fuera de él | C8 | Diaria | Medio | `schedule_windows` existente | Baja-media | No bloquear al staff sin decisión del PO |
| 12 | Espera | Logo de la clínica en documentos | Marca | — | Bajo-medio | Branding «Fase 2» ya previsto | Media | Almacenamiento de archivos |

---

## 12. Funcionalidades que no conviene agregar todavía

| Idea | Por qué esperar | Condición para reconsiderar |
|---|---|---|
| CFDI / facturación fiscal desde Configuración (RFC, régimen, certificados, PAC) | Decisión de producto mayor con proveedor, obligaciones legales y soporte; el producto la excluye explícitamente («Cobro» mientras no haya facturación fiscal) | Demanda confirmada de clínicas piloto y decisión de PAC |
| Tasas de impuesto por producto o compuestas | Sin visibilidad de la tasa única, la granularidad agrega riesgo de errores de cobro | Tras la transparencia de IVA y validación con contador |
| Varias franjas por día o horario semanal por veterinario | p53 lo descartó por sobrediseño; ausencias (p67) cubren el caso frecuente | Casos reales de clínicas con turnos partidos que el descanso no resuelve |
| Multisede | ADR p48: un usuario pertenece a una sola clínica | Cliente con dos sucursales |
| Editor de plantillas de documentos o de colores | Mantenimiento alto, valor bajo para el segmento | Después de logo + datos de contacto en PDFs |
| Recordatorios configurables (reglas, plantillas, canales) | Dependen de WhatsApp en producción y de plantillas aprobadas por Meta | Agente activo y estable |
| Moneda, idioma o semana configurables | Sin consumidores y producto México-only | Expansión a otro país |
| Lista blanca de IP, cierre de sesión por inactividad, MFA obligatorio por clínica | Útiles en hospitales; para 1–15 personas, MFA opcional basta hoy | Exigencia de un cliente o incidente |
| Reserva en línea | Producto distinto, depende de disponibilidad por profesional | Agente con escritura abierta y estable |
| Integraciones contables | Sin demanda demostrada | Facturación fiscal resuelta |

---

## 13. Roadmap de producto

Priorización de evolución, no plan técnico.

| Fase | Mejora | Problema que resuelve | Prioridad | Complejidad | Módulos tocados | Riesgos |
|---|---|---|---|---|---|---|
| **0 Riesgos** | Zona horaria protegida | C1 | P1 | Baja-media | organizations, Citas, sesión | Política sobre citas futuras |
| 0 | Invariante teléfono ↔ agente | C2 | P1 | Baja | organizations, agente | Frontera entre dominios |
| 0 | Precio con/sin IVA explícito en catálogo, agente y cobro | C3 | P1 | Baja | Servicios, agente, POS | Coherencia del redondeo |
| **1 Consolidación** | UI por capacidad, ruta protegida, «Mi cuenta» para todos | C5, C6 | P2 | Baja | frontend | Bajo |
| 1 | Retirar o conectar ajustes sin efecto; etiquetas exactas | C7 | P2 | Baja | Configuración, Citas, docs | Decidir duración por defecto |
| 1 | Tasa de IVA visible (edición según decisión) | C4 | P2 | Baja-media | organizations, Cobros | Quién cambia la tasa |
| 1 | Estados de error, cambios pendientes, errores en el campo | C10, C12 | P2 | Baja | frontend | Bajo |
| 1 | Servicios activos/inactivos | C11 | P2 | Baja | Servicios | Bajo |
| 1 | Registro de cambios de configuración | C9 | P2 | Media | organizations | Volumen de eventos bajo |
| 1 | Corrección de documentación (p53, toggles, kill switch) | C14 | P2 | Baja | docs | Ninguno |
| **2 Operatividad** | Cierres excepcionales del horario | Brecha de mercado | P2 (P1 con agente activo) | Media | organizations, agente, Citas | Requiere ADR que amplíe p53 |
| 2 | Agenda del staff con horario y aviso | C8 | P2 | Baja-media | Citas | No bloquear sin decisión |
| 2 | Datos de la clínica en PDFs | C13 | P2 | Baja | PDFs | Requisitos de receta [NV] |
| 2 | Horario usable en móvil; FAQ del agente con UI | C15, C17 | P3 | Baja | frontend, agente | Bajo |
| **3 Diferenciación** | Logo en documentos | Marca | P3 | Media | PDFs, almacenamiento | Archivos subidos por usuarios |
| 3 | Preparación fiscal (solo si se decide CFDI) | Requisito comercial México [I] | P3 | Alta | billing, organizations | Proveedor y obligaciones legales |

---

## 14. Top 5 de mejoras con mayor ROI

Sin usuarios reales, el ROI es una **hipótesis fundamentada**, no un resultado medido.

| Posición | Mejora | Valor generado | Esfuerzo estimado | ROI esperado | Justificación |
|---|---|---|---|---|---|
| 1 | Precio con/sin IVA explícito y tasa visible | Elimina la diferencia entre lo cotizado y lo cobrado; la clínica sabe qué cobra | Bajo | Alto | Afecta cada cobro y cada cotización del agente; cambio pequeño sobre datos que ya existen |
| 2 | Zona horaria protegida | Evita citas desalineadas y solapes no detectados | Bajo-medio | Alto | Un error de configuración temprano y probable con efectos en toda la agenda |
| 3 | Invariante teléfono ↔ agente | Mantiene la plantilla de urgencia con número | Bajo | Alto | Es el riesgo de mayor gravedad potencial y su cierre es acotado |
| 4 | UI por capacidad + «Mi cuenta» para todos | Coherencia con p69; cada persona gestiona su contraseña y MFA | Bajo | Alto | Reutiliza el patrón de Equipo; resuelve C5 y C6 juntos |
| 5 | Limpieza de ajustes sin efecto + estados de error y cambios pendientes | Lo que se ve hace lo que dice; menos dudas al guardar | Bajo | Medio-alto | Mayor salto de confianza percibida con cambios pequeños |

---

## 15. Propuesta de alcance ideal del módulo

**«Cómo es y cómo opera la clínica»**, configurado una vez y ajustado rara vez. No es el lugar de
la cuenta personal ni de la operación diaria.

- **Responsabilidades que concentra:** identidad y contacto (lo que ven clientes, agente y
  documentos), horario base y sus excepciones, reglas operativas con efecto real explicado,
  catálogo de servicios con precio claro, impuesto vigente, y el registro de quién cambió qué.
- **Responsabilidades que quedan en otros módulos:** cuenta personal (contraseña, MFA) en un menú
  de perfil; equipo, permisos y ausencias en Equipo; kill switch y operación del agente en Inbox
  (Configuración puede enlazarlo); productos en Inventario; facturación fiscal, cuando exista, en
  Cobros.
- **Esenciales (siempre visibles):** nombre que ve el cliente, teléfono, dirección, horario,
  servicios y tasa de IVA vigente.
- **Avanzadas (agrupadas y explicadas):** caja obligatoria, crédito y plazo, confirmación previa,
  atención sin mascota registrada, expediente automático.
- **Una sola vez, con confirmación:** zona horaria; cambiarla después es excepcional y advierte de
  sus efectos.
- **Modificables durante la operación:** horario y sus cierres, servicios y precios, reglas.
- **Con valores predeterminados razonables:** horario sembrado, reglas apagadas salvo el historial
  de cambios, duración de cita de 30 minutos.
- **Permisos especiales:** reglas financieras e impuesto solo para quien tenga la capacidad de
  configuración; que ese permiso siga delegable (p69) exige el registro de cambios.
- **Organización de la experiencia:** menú lateral de ajustes con URL por apartado, guardado por
  apartado con indicador de cambios, errores en el campo y un resumen de lo que falta para operar
  bien (teléfono, servicios, horario revisado).
- **Agrupación por dominio**, en la línea de los competidores (§7.3) pero al tamaño de una
  clínica pequeña: *Clínica* (identidad, contacto y lo que se imprime) · *Horario* (semana base y
  cierres) · *Cobros e impuestos* (IVA, caja obligatoria, crédito) · *Atención* (confirmación,
  atención sin mascota, expediente automático) · *Servicios*. La cuenta personal sale del módulo;
  el asistente de WhatsApp puede enlazarse desde aquí.

---

## 16. Conclusión sobre competitividad

1. **Madurez actual:** 2.4/5, Básica alta. La base técnica (modelo p53, aislamiento, horario
   atómico, reglas en servidor) es Madura; el producto es Básico.
2. **Adecuación a 1–15 personas:** suficiente para poner en marcha una clínica con un dueño que
   administra y atiende, siempre que nadie cambie la zona horaria después de agendar y que la
   clínica sepa que los precios del catálogo no incluyen IVA. Insuficiente cuando se delega la
   configuración (p69), cuando el agente empiece a agendar en días festivos o cuando el personal
   necesite cambiar su contraseña sin conocer la URL.
3. **Por encima de lo esperable en esta etapa:** la integración del horario con el agente
   (fuente única, lock compartido, defensiva ante datos faltantes), la regla única de teléfono y
   el cumplimiento en servidor de las reglas de caja y crédito.
4. **Por debajo de las soluciones consolidadas:** sin cierres excepcionales, sin impuesto visible
   ni configurable, sin datos de la clínica en documentos, sin logo y sin registro de cambios.
   Como módulo (§7.3), es el único plano, el único verificado que mezcla la cuenta personal con la
   clínica, no tiene área fiscal y no protege los datos de arranque.
5. **Mayor diferencia competitiva:** transparencia de precios con IVA en catálogo, cobro y
   WhatsApp, y cierres excepcionales que el agente respete; juntas cubren la promesa de «el
   asistente da información correcta».
6. **No necesita todavía:** CFDI, multisede, horarios por veterinario completos, plantillas
   editables, recordatorios configurables, moneda o idioma configurables.

Valoración: Configuración no tiene riesgos de aislamiento ni de escalación, pero tiene tres
inconsistencias que afectan agenda, urgencias y dinero comunicado al cliente, y varias opciones que
no hacen lo que dicen. Corregirlas no exige rediseño: la mayor parte del trabajo es hacer visible y
coherente lo que el backend ya modela.

---

## Fuentes externas

Consultadas el 2026-11-26.

- [ezyVet: configure your organization's staffed hours](https://docs.ezyvet.com/en/browse-documentation/vet-radar/staffed-hours/configure-your-organizations-staffed-hours)
- [ezyVet: configure the tax rate that a site automatically uses](https://docs.ezyvet.com/browse-documentation/ezyvet/invoicing/tax/tax-configuration/configure-the-tax-rate-that-a-site-automatically-uses)
- [ezyVet: configure a composite tax rate](https://docs.ezyvet.com/browse-documentation/ezyvet/invoicing/tax/tax-configuration/configure-a-composite-tax-rate)
- [ezyVet: configure the tax rate of a product](https://docs.ezyvet.com/browse-documentation/ezyvet/products/product-configuration/product-configuration-for-financial-work/product-tax-configuration/configure-the-tax-rate-of-a-product)
- [ezyVet: upload an organization logo to show in documents](https://docs.ezyvet.com/browse-documentation/ezyvet/document-management/document-templates/document-template-configuration-images-and-logos/upload-an-organization-logo-to-show-in-documents)
- [ezyVet: background templates](https://docs.ezyvet.com/browse-documentation/ezyvet/document-management/document-templates/document-template-configuration-images-and-logos/background-templates)
- [ezyVet: configure the time range that ezyVet uses to send messages](https://docs.ezyvet.com/browse-documentation/ezyvet/clients/client-messaging/automatically-send-messages-to-clients/communication-task-configuration/configure-the-time-range-that-ezyvet-uses-to-send-messages)
- [Vello (IDEXX): planning guides to configure available appointment times](https://help.vello.idexx.com/browse-documentation/for-practices/vello/configuration/online-booking-configuration/ezyvet-only-planning-guides-as-a-method-to-configure-available-appointment-times)
- [Provet: Appointment Settings](https://support.provet.com/hc/en-gb/articles/10336095019677)
- [Provet: Overview of Clinic Location Profile and Clinic Location Settings](https://support.provet.com/hc/en-gb/articles/24880029539740)
- [Provet: Overview of Header, Footer, and Logo Configuration](https://support.provet.com/hc/pt-pt/articles/25342648152860--en-Overview-of-Header-Footer-and-Logo-Configuration)
- [Provet: Appointment Confirmation and Reminder Settings](https://support.provet.com/hc/en-gb/articles/10364261339677)
- [Provet: Reminder Settings and Templates](https://support.provet.com/hc/en-gb/articles/9228231509405)
- [Vetspire: Locations — Add a New Location & Location Settings](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/admin-locations)
- [Vetspire: Edit Location Scheduling Details](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/location-settings-scheduling)
- [Vetspire: set tax rates for product types](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/set-tax-rates-for-product-types)
- [Digitail: Set up the Clinic's Preferences](https://help.digitail.io/en/articles/10045906-set-up-the-clinic-s-preferences)
- [Digitail: Clinic Settings (colección)](https://help.digitail.io/en/collections/2839667-clinic-settings)
- [Digitail: Set your Schedule](https://help.digitail.io/en/articles/5043046-set-your-schedule)
- [Shepherd: Clinic Settings](https://help.shepherd.vet/en/articles/4480588-clinic-settings)
- [Shepherd: Clinic Settings & Configuration (colección)](https://help.shepherd.vet/en/collections/3436557-clinic-settings-configuration)
- [Shepherd: General Clinic Settings (colección)](https://help.shepherd.vet/en/collections/3436560-general-clinic-settings)
- [Digitail: Set up the Clinic's Profile](https://help.digitail.io/en/articles/5043097-set-up-the-clinic-s-profile)
- [Digitail: Set up the Clinic's Fiscal Information](https://help.digitail.io/en/articles/5043104-set-up-the-clinic-s-fiscal-information)
- [Digitail: Set up Series & No. for Documents](https://help.digitail.io/en/articles/5043100-set-up-series-no-for-documents)
- [Digitail: Tax Rates — Setup & Management](https://help.digitail.io/en/articles/14844680-tax-rates-setup-management)
- [Digitail: Manage Login and Security Settings](https://help.digitail.io/en/articles/12000849-manage-login-and-security-settings-in-digitail)
- [Digitail: Setup & Configurations (colección)](https://help.digitail.io/en/collections/2812035-setup-configurations)
- [Provet: Overview of Clinic Location Profile and Clinic Location Settings (portal actual)](https://ticketportal.provetcloud.com/hc/en-gb/articles/24880029539740)
- [Vetspire: Admin](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/admin)
- [Vetspire: Organization Settings](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/org)
- [Vetspire: Preferences — General Organization Settings](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/preferences)
- [Vetspire: Edit User Profile Settings](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/user-settings)
- [ezyVet: glosario — system settings](https://docs.ezyvet.com/browse-documentation/ezyvet/glossary/system-settings)
- [ezyVet: site configuration](https://docs.ezyvet.com/browse-documentation/ezyvet/ezyvet-administration/site-configuration)
- [ezyVet: change the address, phone and email information of your organization](https://docs.ezyvet.com/browse-documentation/ezyvet/ezyvet-administration/address-configuration/change-the-address-phone-and-email-information-of-your-organization)
- [Covetrus: EVetPractice FAQ (otro producto, citado como límite)](https://software.covetrus.com/download/1507)
- [Covetrus Pulse](https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/covetrus-pulse/why-pulse/)
- [Comparasoftware: Okvet](https://www.comparasoftware.com/okvet)
- [Comparasoftware: QVET](https://www.comparasoftware.com/qvet)
- [Capterra: Wakyma Vets](https://www.capterra.ca/software/1237586/Wakyma-Vets)
