# Diseño técnico — Configuración de clínica (Fase 1)

**Fecha:** 2026-07-21
**Estado:** diseño técnico previo a implementación
**Base arquitectónica:** `docs/decisions/2026-07-21-p53-clinic-configuration-aggregates.md`

## Objetivo

Bajar ADR p53 a un diseño implementable de backend, API y frontend para reemplazar la
configuración actual centrada en toggles por una configuración de clínica basada en tres
agregados:

- `Organization`
- `OrganizationSettings`
- `OrganizationSchedule`

Este documento **no cambia todavía** los contratos vigentes; define el contrato objetivo
para la implementación.

## Alcance de Fase 1

Incluye:
- identidad y contacto de la clínica
- ubicación
- reglas operativas base
- horario semanal base
- lectura agregada para la pantalla de configuración

No incluye:
- feriados o excepciones por fecha
- múltiples ventanas horarias por día
- horarios por veterinario
- plantillas conversacionales
- multi-sucursal

## 1. Modelo de datos

### 1.1 `Organization`

Se mantiene como la fuente de verdad de identidad de clínica.

Campos existentes relevantes:
- `public_id`
- `name`
- `timezone`
- `timezone_updated_at`
- `tax_rate`

Campos nuevos propuestos:
- `display_name: CharField(max_length=255, blank=True, default='')`
- `phone: CharField(max_length=32, blank=True, default='')`
- `whatsapp: CharField(max_length=32, blank=True, default='')`
- `email: EmailField(blank=True, default='')`
- `website: URLField(blank=True, default='')`
- `address_line1: CharField(max_length=255, blank=True, default='')`
- `address_line2: CharField(max_length=255, blank=True, default='')`
- `district: CharField(max_length=120, blank=True, default='')`
- `city: CharField(max_length=120, blank=True, default='')`
- `state: CharField(max_length=120, blank=True, default='')`
- `postal_code: CharField(max_length=16, blank=True, default='')`
- `country: CharField(max_length=80, blank=True, default='Mexico')`
- `google_maps_url: URLField(blank=True, default='')`
- `latitude: DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)`
- `longitude: DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)`
- `arrival_instructions: TextField(blank=True, default='')`

Notas:
- `name` sigue siendo el nombre canónico interno.
- `display_name` permite un nombre comercial visible sin romper consumidores actuales de `name`.
- `timezone` **permanece aquí** por compatibilidad.
- `tax_rate` permanece aquí porque hoy es parte del contrato financiero vigente.
- `latitude` y `longitude` se mantienen como campos escalares en Fase 1 por simplicidad,
  pero conceptualmente deben entenderse como parte de un bloque de `location`.
  Si en fases futuras aparece soporte multi-provider (`Google Maps`, `OpenStreetMap`,
  `Apple Maps`, `Waze`, geocoding), convendrá evolucionar a una abstracción explícita de
  ubicación en lugar de seguir agregando campos dispersos.

### 1.2 `OrganizationSettings`

Mantiene toggles actuales y agrega reglas operativas base.

Campos existentes:
- `auto_create_medical_record`
- `auto_create_invoice_on_done`
- `require_confirmation_before_start`
- `allow_anonymous_walkin`
- `show_status_change_history`
- `require_open_cash_session`

Campos nuevos propuestos:
- `locale: CharField(max_length=16, default='es-MX')`
- `currency_code: CharField(max_length=3, default='MXN')`
- `default_appointment_duration_minutes: PositiveSmallIntegerField(default=30)`
- `appointment_buffer_minutes: PositiveSmallIntegerField(default=0)`
- `allow_emergency_walkin: BooleanField(default=False)`
- `week_starts_on: PositiveSmallIntegerField(default=1)`

Convenciones:
- `week_starts_on=1` representa lunes.
- `currency_code` se limita a ISO-4217 uppercase en serializer.
- `locale` se mantiene corto y controlado en Fase 1 (`es-MX` inicialmente, extensible después).

### 1.3 `OrganizationSchedule`

Nuevo agregado. Una fila por día de la semana por organización.

Campos:
- `organization: ForeignKey(Organization, CASCADE, related_name='schedules')`
- `weekday: PositiveSmallIntegerField()`
- `is_closed: BooleanField(default=False)`
- `opens_at: TimeField(null=True, blank=True)`
- `closes_at: TimeField(null=True, blank=True)`
- `has_break: BooleanField(default=False)`
- `break_start: TimeField(null=True, blank=True)`
- `break_end: TimeField(null=True, blank=True)`

Constraints propuestos:
- `UniqueConstraint(fields=['organization', 'weekday'], name='org_schedule_unique_weekday')`
- `CheckConstraint(weekday BETWEEN 1 AND 7)`

Validaciones de negocio en serializer/model clean:
- si `is_closed=True`:
  - `opens_at`, `closes_at`, `break_start`, `break_end` deben ser `null`
  - `has_break` debe ser `False`
- si `is_closed=False`:
  - `opens_at` y `closes_at` son obligatorios
  - `opens_at < closes_at`
- si `has_break=True`:
  - `break_start` y `break_end` son obligatorios
  - `opens_at < break_start < break_end < closes_at`
- si `has_break=False`:
  - `break_start` y `break_end` deben ser `null`

## 1.4 Invariantes del dominio

Estas reglas deben considerarse binding para implementación y futuras refactorizaciones:

- toda `Organization` tiene exactamente un `OrganizationSettings`
- toda `Organization` tiene exactamente siete filas de `OrganizationSchedule`
- nunca existen dos `OrganizationSchedule` con el mismo `weekday` para una misma organización
- `OrganizationSettings` pertenece a una única `Organization`
- `OrganizationSchedule` pertenece a una única `Organization`
- los endpoints tenant-scoped nunca aceptan `organization_id` enviado por el cliente
- toda escritura sobre configuración ocurre tenant-scoped usando `request.user.organization`
- ningún consumidor de horario debe reimplementar reglas de apertura/cierre fuera del servicio de dominio definido para disponibilidad

## 2. Semillas y defaults

Al crear una `Organization`, además de los artifacts actuales, deben generarse automáticamente:

- `OrganizationSettings` con defaults
- 7 filas de `OrganizationSchedule`

Los defaults no deben quedar hardcodeados en múltiples lugares. La implementación debe
tener una única fuente de verdad, por ejemplo `DEFAULT_ORGANIZATION_SCHEDULE`.

Default semanal recomendado:

```text
Lunes a Viernes: 09:00-18:00, sin descanso
Sábado: 09:00-14:00, sin descanso
Domingo: cerrado
```

Razón:
- da una base editable real
- evita una UI vacía o 7 días cerrados sin contexto

## 2.1 Helpers de materialización e integridad

Separar responsabilidades:

- `create_default_schedule(organization)`
  - crea las 7 filas iniciales a partir de `DEFAULT_ORGANIZATION_SCHEDULE`
- `ensure_schedule_integrity(organization)`
  - detecta faltantes o corrupción estructural
  - completa filas faltantes de forma segura
  - devuelve la colección completa ordenada

No concentrar ambas cosas en un único helper genérico `ensure_org_schedule()` porque mezcla
creación de defaults con reparación de integridad.

## 3. Contratos de API

## 3.1 Lectura agregada

### `GET /api/settings/configuration/`

Respuesta objetivo:

```json
{
  "organization": {
    "id": 12,
    "public_id": "uuid",
    "name": "Clinica San Pedro",
    "display_name": "Clinica Veterinaria San Pedro",
    "timezone": "America/Mexico_City",
    "timezone_updated_at": "2026-07-21T18:00:00Z",
    "tax_rate": "0.1600",
    "phone": "5512345678",
    "whatsapp": "5512345678",
    "email": "hola@clinicasanpedro.mx",
    "website": "https://clinicasanpedro.mx",
    "address_line1": "Av. Principal 123",
    "address_line2": "Local 4",
    "district": "Centro",
    "city": "Puebla",
    "state": "Puebla",
    "postal_code": "72000",
    "country": "Mexico",
    "google_maps_url": "https://maps.google.com/...",
    "latitude": "19.043300",
    "longitude": "-98.201900",
    "arrival_instructions": "Estacionamiento por la calle lateral."
  },
  "settings": {
    "auto_create_medical_record": false,
    "auto_create_invoice_on_done": false,
    "require_confirmation_before_start": false,
    "allow_anonymous_walkin": false,
    "show_status_change_history": true,
    "require_open_cash_session": false,
    "locale": "es-MX",
    "currency_code": "MXN",
    "default_appointment_duration_minutes": 30,
    "appointment_buffer_minutes": 0,
    "allow_emergency_walkin": false,
    "week_starts_on": 1
  },
  "schedule": [
    {
      "weekday": 1,
      "is_closed": false,
      "opens_at": "09:00:00",
      "closes_at": "18:00:00",
      "has_break": false,
      "break_start": null,
      "break_end": null
    }
  ]
}
```

Notas:
- endpoint tenant-scoped; nunca acepta organization id del cliente
- para usuarios sin organización asignada: `404`
- `schedule` siempre debe devolver 7 filas ordenadas por `weekday`
- `ConfigurationAggregateSerializer` debe tratarse como contrato estable desde Fase 1 para
  permitir evolución compatible con consumidores futuros (SPA, móvil, integraciones)

## 3.2 Escritura de identidad

### `PATCH /api/organizations/me/`

Amplía el serializer actual de `Organization` con campos identitarios nuevos.

Campos editables en Fase 1:
- `name`
- `display_name`
- `timezone`
- `phone`
- `whatsapp`
- `email`
- `website`
- `address_line1`
- `address_line2`
- `district`
- `city`
- `state`
- `postal_code`
- `country`
- `google_maps_url`
- `latitude`
- `longitude`
- `arrival_instructions`

Se mantienen read-only:
- `id`
- `public_id`
- `timezone_updated_at`
- `created_at`

No se toca por ahora:
- `tax_rate` desde esta pantalla de configuración general; si ya existe edición en otro flujo,
  se preserva el contrato actual.

## 3.3 Escritura de reglas operativas

### `PATCH /api/organizations/settings/`

Amplía `OrganizationSettingsSerializer` con:
- `locale`
- `currency_code`
- `default_appointment_duration_minutes`
- `appointment_buffer_minutes`
- `allow_emergency_walkin`
- `week_starts_on`

Validaciones:
- `default_appointment_duration_minutes` entre `5` y `240`
- `appointment_buffer_minutes` entre `0` y `120`
- `currency_code` en mayúsculas, longitud 3
- `week_starts_on` en `1..7`
- `locale` contra lista allowlist en Fase 1 (`es-MX` inicialmente; `en-US` opcional si se habilita)

Semántica explícita:
- `default_appointment_duration_minutes` **solo** define el valor inicial sugerido al crear
  nuevas citas
- no modifica citas existentes
- no recalcula slots existentes o futuros
- no reorganiza automáticamente la agenda

Equivale a la opción C del análisis funcional: cambia el default de creación en la UI y en
los flujos que lo consulten, pero no reescribe datos ya creados

## 3.4 Escritura del horario semanal

### `GET /api/organizations/schedule/`

Devuelve la colección completa semanal de 7 filas.

### `PUT /api/organizations/schedule/`

Body objetivo:

```json
[
  {
    "weekday": 1,
    "is_closed": false,
    "opens_at": "09:00:00",
    "closes_at": "18:00:00",
    "has_break": true,
    "break_start": "14:00:00",
    "break_end": "15:00:00"
  }
]
```

Reglas del endpoint:
- exige exactamente 7 elementos
- exige weekdays `1..7` sin duplicados
- persiste todo dentro de `transaction.atomic()`
- si cualquier fila falla validación, no guarda nada
- el order del payload no es autoritativo; el backend ordena por `weekday`

Estrategia de persistencia recomendada:
- lock de las 7 filas actuales de la org
- validar el conjunto completo en memoria
- aplicar update fila por fila dentro del mismo `atomic()`

## 4. Serializers

Nota de diseño:
- los grupos `appointment_defaults`, `billing_defaults`, `cash_defaults`, etc. son
  únicamente conceptuales
- **no** crear `JSONField`
- **no** crear subobjetos persistidos dentro de `OrganizationSettings`
- **no** introducir blobs de configuración

En Fase 1, la persistencia sigue siendo explícita y columnar.

### 4.1 `OrganizationSerializer`

Agregar validadores específicos:
- `validate_timezone()` conservar lógica actual
- `validate_phone()` / `validate_whatsapp()`:
  - sanitizar espacios y símbolos comunes
  - guardar solo dígitos en Fase 1 si se decide normalización estricta
  - aceptar vacío
- `validate_postal_code()`:
  - largo razonable, no imponer país fuera de MX por ahora
- `validate_google_maps_url()`:
  - URL válida
- `validate()`:
  - si `latitude` existe, `longitude` también y viceversa

### 4.2 `OrganizationSettingsSerializer`

Nuevos validadores:
- `currency_code = value.upper()`
- `default_appointment_duration_minutes` rango
- `appointment_buffer_minutes` rango
- `week_starts_on` rango

### 4.3 `OrganizationScheduleItemSerializer`

Serializer por fila para validación interna y para `GET /schedule/`.

### 4.4 `OrganizationScheduleBulkSerializer`

Serializer de lista para `PUT /schedule/`.

Responsabilidades:
- validar 7 items
- validar weekdays únicos
- validar presencia completa de `1..7`
- delegar validación fila a fila al item serializer

### 4.5 `ConfigurationAggregateSerializer`

Serializer de salida para `GET /api/settings/configuration/`.

Solo lectura. Compone:
- `organization = OrganizationSerializer()`
- `settings = OrganizationSettingsSerializer()`
- `schedule = OrganizationScheduleItemSerializer(many=True)`

## 5. Views

### 5.1 `OrganizationConfigurationView`

Nueva view `RetrieveAPIView` tenant-scoped para `GET /api/settings/configuration/`.

Comportamiento:
- usa `request.user.organization`
- materializa `OrganizationSettings` si falta con `get_or_create`
- materializa `OrganizationSchedule` si falta o está incompleto mediante la secuencia
  autoritativa `create_default_schedule(org)` / `ensure_schedule_integrity(org)`
- responde shape agregada

### 5.2 `OrganizationScheduleView`

Nueva view explícita con:
- `GET`
- `PUT`

Sin `PATCH` parcial en Fase 1.

### 5.3 Permisos

Recomendación:
- `GET /api/settings/configuration/`: cualquier usuario autenticado con organización
- `PATCH /api/organizations/me/`: `ADMIN`
- `PATCH /api/organizations/settings/`: `ADMIN`
- `GET /api/organizations/schedule/`: cualquier usuario autenticado con organización
- `PUT /api/organizations/schedule/`: `ADMIN`

La UI podrá ocultar edición según `can(...)`, pero el backend sigue siendo autoridad.

## 6. Materialización autoritativa del horario

Crear helpers explícitos en `apps/organizations/services.py` o `utils.py`:

- `create_default_schedule(organization)`
- `ensure_schedule_integrity(organization)`

Responsabilidades:
- centralizar la creación inicial de las 7 filas
- centralizar reparación de faltantes o integridad incompleta
- devolver siempre la colección semanal ordenada

Estas funciones deben ser la única forma autorizada de materializar horario semanal,
igual que hoy `OrganizationSettings` se materializa vía `get_or_create`.

## 6.1 Servicio de dominio futuro para disponibilidad

La lógica operacional de horario no debe quedar repartida entre `appointments`, `dashboard`,
`analytics`, `WhatsApp` o recordatorios. Debe concentrarse en un servicio de dominio
dedicado, por ejemplo `OrganizationAvailabilityService`.

No es obligatorio implementarlo en Fase 1, pero sí reservarlo como punto de extensión.

Interfaz objetivo sugerida:
- `today_schedule(organization, now=None)`
- `is_open_now(organization, now=None)`
- `is_inside_break(organization, now=None)`
- `minutes_until_close(organization, now=None)`
- `next_opening(organization, now=None)`
- `current_business_day(organization, now=None)`

Regla: ninguna otra capa debe replicar cálculos de apertura/cierre por su cuenta.

## 7. DTOs frontend

## 7.1 DTO de lectura agregada

```js
{
  organization: {
    name: "",
    display_name: "",
    timezone: "America/Mexico_City",
    phone: "",
    whatsapp: "",
    email: "",
    website: "",
    address_line1: "",
    address_line2: "",
    district: "",
    city: "",
    state: "",
    postal_code: "",
    country: "Mexico",
    google_maps_url: "",
    latitude: null,
    longitude: null,
    arrival_instructions: ""
  },
  settings: {
    auto_create_medical_record: false,
    auto_create_invoice_on_done: false,
    require_confirmation_before_start: false,
    allow_anonymous_walkin: false,
    show_status_change_history: true,
    require_open_cash_session: false,
    locale: "es-MX",
    currency_code: "MXN",
    default_appointment_duration_minutes: 30,
    appointment_buffer_minutes: 0,
    allow_emergency_walkin: false,
    week_starts_on: 1
  },
  schedule: [
    {
      weekday: 1,
      is_closed: false,
      opens_at: "09:00:00",
      closes_at: "18:00:00",
      has_break: false,
      break_start: null,
      break_end: null
    }
  ]
}
```

## 7.2 Secciones de UI

La nueva `Configuración` debe separar visualmente:
- `Clínica`
- `Horarios`
- `Operación`
- `Servicios` solo como módulo aparte o sección secundaria heredada, no como centro de la pantalla

Recomendación de carga:
- una llamada inicial: `getConfiguration()`
- guardados desacoplados:
  - `updateOrganization()`
  - `updateOrganizationSettings()`
  - `replaceOrganizationSchedule()`

## 7.3 Reglas frontend

- no inferir defaults localmente distintos al backend
- si `schedule` viene incompleto, tratarlo como error de contrato
- al guardar horario, enviar siempre 7 días completos
- si el backend devuelve errores por campo, mapearlos por sección

## 8. Migraciones

Orden recomendado:

1. migración aditiva de `Organization`
2. migración aditiva de `OrganizationSettings`
3. creación de `OrganizationSchedule`
4. data migration para poblar 7 filas por organización existente

Data migration de schedule:
- iterar organizaciones existentes
- crear 7 filas solo si no existen
- si existen parcialmente, completar faltantes y conservar las presentes

## 9. Compatibilidad y rollout

### 9.1 Compatibilidad backend

- `/api/organizations/me/` sigue vigente; solo se amplía
- `/api/organizations/settings/` sigue vigente; solo se amplía
- se agregan nuevos endpoints, no se rompen los anteriores

### 9.2 Compatibilidad frontend

Plan de rollout recomendado:
- primero exponer el endpoint agregado
- luego migrar la pantalla `config.jsx`
- finalmente mover el catálogo de servicios fuera del foco principal de configuración

### 9.3 Timezone

No mover `timezone` de `Organization` en esta fase.

Razones:
- ya existe auditoría `OrganizationTimezoneAudit`
- `appointments` y `billing` ya consumen ese contrato
- reduce impacto de rollout

## 10. Impacto en documentación de contratos

Cuando se implemente, habrá que actualizar al menos:
- `docs/modules/organizations.md`
- `docs/modules/appointments.md`
- `docs/system-operational-flow.md`

Puntos contractuales a reflejar:
- existencia de `OrganizationSchedule`
- nuevos defaults operativos de agenda
- nuevo endpoint agregado de configuración

## 11. Estrategia de tests

### Backend

- serializer `Organization`: validaciones de contacto/ubicación/coordenadas
- serializer `OrganizationSettings`: rangos y normalización
- serializer bulk de schedule: 7 días exactos, sin duplicados, con reglas de horario
- view `GET /api/settings/configuration/`
- view `PUT /api/organizations/schedule/`
- tests de permisos por rol
- tests tenant-scoped: nunca aceptar schedule de otra organización

### Frontend

- carga inicial agregada
- guardado por sección
- edición completa de horario semanal
- validaciones básicas antes de submit
- UI degradada cuando faltan permisos de edición

## 12. Orden de implementación ejecutable

1. endpoints y contratos API finales
2. modelos y migraciones
3. serializers nuevos
4. views nuevas / ampliadas
5. tests backend
6. API client frontend (`frontend/src/api/organizations.js`)
7. refactor de `frontend/src/pages/config.jsx`
8. tests frontend

## 13. Decisiones abiertas antes de codificar

Decisiones recomendadas para cerrar en implementación:

1. `display_name` vs reutilizar `name`
   - recomendación: agregar `display_name` y conservar `name` como canónico interno
2. normalización de teléfono
   - recomendación: persistir dígitos únicamente en backend
3. `locale` allowlist inicial
   - recomendación: `es-MX` solamente en Fase 1, extensible luego
4. edición de `tax_rate` en esta nueva pantalla
   - recomendación: no mezclarla en el primer rollout visual general; mantener su manejo actual hasta rediseñar facturación

## 14. Resumen de implementación recomendada

- `Organization` conserva identidad y `timezone`
- `OrganizationSettings` crece como motor de reglas operativas
- `OrganizationSchedule` nace como agregado semanal con 7 filas
- `GET /api/settings/configuration/` resuelve la carga de pantalla
- las escrituras siguen separadas por agregado
- Fase 1 soporta un solo bloque de apertura y un solo descanso por día
