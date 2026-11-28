# ADR p53: Separacion de agregados para la configuracion de la clinica

**Fecha:** 2026-07-21
**Estado:** Implementado; ampliado por [ADR p70](2026-11-26-p70-configuracion-clinica-fase-2.md)
(2026-11-27: historial de cambios, ajustes sin efecto retirados, nombre público)
**Relacionados:**
- `docs/modules/organizations.md`
- `docs/modules/appointments.md`
- `docs/modules/billing.md`
- `docs/system-operational-flow.md`
- ADR `2026-04-28-organization-settings-toggles.md`

## Contexto

La pantalla actual de `Configuración` nació como una superficie de UI pequeña y hoy ya
no representa correctamente el dominio. La configuración de una clínica afecta múltiples
módulos del sistema:

- `appointments`: confirmación previa, walk-in, duración default, horarios
- `billing` / `cash`: caja requerida, defaults financieros, moneda
- `analytics`: timezone, locale, agrupaciones diarias
- `dashboard`, recordatorios, WhatsApp, landing pública y reportes: consumen datos de
  identidad, contacto, ubicación y horario

El problema actual no es solo de campos faltantes; es de modelado. Se mezclan conceptos
con motivos de cambio distintos bajo una misma noción de "configuración":

- identidad de la clínica
- reglas operativas
- horario de atención

Eso empuja decisiones por conveniencia de la pantalla o de la tabla existente, en lugar
de responder al dominio.

## Principio rector

Cada agregado debe tener un **único motivo de cambio** (*Single Reason to Change*).

La primera pregunta al agregar un campo nuevo no es "¿en qué tabla cabe?", sino:

**¿Qué evento del negocio provoca que este dato cambie?**

Aplicación del principio:

- `Organization` cambia cuando cambia la **identidad** de la clínica
- `OrganizationSettings` cambia cuando cambia una **regla de operación**
- `OrganizationSchedule` cambia cuando cambia el **horario de atención**

Este criterio prevalece sobre la conveniencia de la UI. Una pantalla puede agrupar
campos de varios agregados; el modelo de dominio no debe deformarse para reflejar la
pantalla.

## Decisión

Se separa la configuración de clínica en tres agregados explícitos:

### 1. `Organization` = identidad de la clínica

`Organization` es la fuente de verdad de **qué es** la clínica. Contiene únicamente
información identitaria, pública o administrativa estable, por ejemplo:

- nombre
- nombre comercial / display name
- teléfonos
- email
- sitio web
- dirección
- coordenadas
- logo
- instrucciones de llegada
- datos fiscales futuros (`legal_name`, `rfc`, etc.)

Regla dura: `Organization` **nunca** modela cómo opera la clínica.

### 2. `OrganizationSettings` = reglas de operación

`OrganizationSettings` deja de entenderse como un conjunto de preferencias sueltas y pasa
a ser el **motor de reglas de negocio** de la organización.

Su responsabilidad es responder preguntas operativas del sistema, por ejemplo:

- ¿se requiere caja abierta?
- ¿se permite walk-in anónimo?
- ¿la cita debe confirmarse antes de iniciar?
- ¿cuál es la duración default de una cita?
- ¿qué moneda / locale usa la clínica?

Aunque físicamente siga siendo una sola tabla, conceptualmente agrupa defaults y reglas
consumidos por múltiples módulos (`appointments`, `billing`, `cash`, `analytics`,
notificaciones, etc.).

### 3. `OrganizationSchedule` = horario semanal de atención

El horario operativo no pertenece a `Organization` porque no es identidad ni a
`OrganizationSettings` porque no es una regla abstracta: es un agregado propio.

La estructura base de Fase 1 será una fila por día de la semana:

- `organization`
- `weekday`
- `is_closed`
- `opens_at`
- `closes_at`
- `has_break`
- `break_start`
- `break_end`

Se elige esta forma por semántica explícita. Ejemplo: `is_closed=True` es más claro que
codificar cierre con una combinación implícita de `enabled=False` y horas `NULL`.

## Responsabilidades y fronteras

### `Organization`

Responde: **¿qué clínica es?**

Motivos válidos de cambio:
- cambio de nombre o marca
- cambio de contacto
- cambio de domicilio o mapa
- alta futura de branding o datos fiscales

No debe recibir:
- toggles operativos
- defaults de agenda
- reglas de cobro
- horario semanal

### `OrganizationSettings`

Responde: **¿cómo opera la clínica?**

Motivos válidos de cambio:
- cambio de políticas operativas
- cambio de defaults funcionales
- cambio de reglas consumidas por módulos

La UI puede agrupar visualmente estas reglas por secciones, por ejemplo:
- `appointment_defaults`
- `billing_defaults`
- `cash_defaults`
- `inventory_defaults`
- `notifications_defaults`

Eso no obliga a modelar JSON anidados ni nuevas tablas en Fase 1; la agrupación es
conceptual y de contrato, no necesariamente física.

### `OrganizationSchedule`

Responde: **¿cuándo atiende la clínica?**

Motivos válidos de cambio:
- cambio del horario semanal base
- cambio del descanso dentro del día
- cierre total de un día recurrente

No debe absorber todavía:
- feriados
- vacaciones
- excepciones por fecha
- múltiples ventanas horarias por día
- horarios por veterinario
- multi-sucursal

Esas capacidades quedan deliberadamente fuera de Fase 1.

## Contratos de API

Se define como arquitectura objetivo la siguiente forma:

### Lectura agregada para la pantalla de configuración

`GET /api/settings/configuration/`

Response shape canónica:

```json
{
  "organization": { ... },
  "settings": { ... },
  "schedule": [ ...7 dias... ]
}
```

Propósito:
- una sola carga inicial para la pantalla
- dominio separado internamente
- frontend sin coordinación manual de varias peticiones para renderizar

### Escrituras desacopladas por agregado

- `PATCH /api/organizations/me/`
- `PATCH /api/organizations/settings/`
- `PUT /api/organizations/schedule/`

`PUT /api/organizations/schedule/` recibe siempre los **7 días completos** y el backend
debe validar y persistir el conjunto dentro de una sola transacción. No se soporta update
parcial día por día en Fase 1.

Razones:
- evita estados parcialmente guardados
- simplifica validaciones cruzadas del horario
- mantiene el schedule como una unidad coherente

## Compatibilidad hacia atrás

`timezone` **permanece en `Organization`** en esta fase.

Motivo:
- ya existe contrato vigente y auditado en `docs/modules/organizations.md`
- ya es consumido por citas, billing y analytics
- moverlo a `OrganizationSettings` ahora aumentaría el costo de migración y rompería
  consumidores sin aportar valor inmediato suficiente

Se permite desde Fase 1 introducir en `OrganizationSettings` otros campos operativos como:

- `locale`
- `currency_code`
- `default_appointment_duration_minutes`
- `appointment_buffer_minutes`
- `allow_emergency_walkin`
- `week_starts_on`

> **Actualización (ADR p70 D5, 2026-11-27):** `locale`, `appointment_buffer_minutes`,
> `allow_emergency_walkin` y `week_starts_on` se retiraron sin llegar a tener consumidor;
> `currency_code` quedó de solo lectura.

## Restricciones deliberadas de Fase 1

Para evitar sobrediseño, la primera iteración impone explícitamente estas restricciones:

- un solo bloque de apertura por día
- un solo descanso opcional por día
- sin feriados ni excepciones por fecha
- sin múltiples ventanas horarias por día
- sin plantillas conversacionales
- sin horarios por veterinario
- sin multi-sucursal

Estas limitaciones son decisiones deliberadas del producto, no accidentes de implementación.

## Alternativas consideradas

### 1. Guardar todo dentro de `Organization`

Descartada.

Mezcla identidad, reglas y horario bajo un mismo agregado con múltiples motivos de cambio.
Escala mal cuando aparecen consumidores transversales o nuevas capacidades operativas.

### 2. Guardar horarios en `OrganizationSettings` como JSON

Descartada para la arquitectura objetivo.

Aunque un `JSONField` puede servir para un MVP aislado, el horario ya es consultado como
semántica de negocio (`abre hoy`, `próxima apertura`, `horario para WhatsApp`, agenda,
landing pública). Tratarlo como blob complica validaciones y evolución.

### 3. Modelar desde ahora múltiples ventanas por día

Descartada por sobrediseño.

Fase 1 resuelve el caso más común: abierto/cerrado + un descanso opcional. Si producto
requiere más complejidad, el rediseño será explícito y respaldado por un ADR futuro.

### 4. Diseñar la persistencia siguiendo la estructura visual de la pantalla

Descartada.

La UI puede reorganizarse varias veces. La persistencia debe representar el dominio, no la
composición visual del formulario actual.

## Consecuencias

Positivas:
- el dominio queda explícito y con fronteras estables
- nuevos campos se asignan por motivo de cambio, no por conveniencia
- la configuración se vuelve infraestructura reusable para múltiples módulos
- la UI puede evolucionar sin obligar a rediseñar la persistencia

Costos:
- aparecen más contratos y más piezas que coordinar
- la implementación inicial requiere pensar API y DTOs antes de tocar modelos
- habrá que sostener lectura agregada + escrituras separadas

## Orden de implementación derivado de esta decisión

1. Diseñar el modelo de dominio final
2. Diseñar los contratos de API estables
3. Diseñar los DTOs / shape del frontend
4. Implementar migraciones
5. Implementar serializers
6. Implementar views
7. Implementar React
8. Conectar consumidores posteriores (agenda, dashboard, WhatsApp, reportes)

La API es el contrato prioritario; la estructura de tablas y serializers puede cambiar,
pero no debe empujar retrabajo innecesario en frontend.

## Relación con ADRs previos

Este ADR **no reemplaza** `2026-04-28-organization-settings-toggles.md`; lo encuadra.

ADR anterior:
- justificó la aparición de `OrganizationSettings` para toggles operativos

Este ADR nuevo:
- fija la frontera conceptual entre identidad, reglas operativas y horario
- define `OrganizationSettings` como motor de reglas de la organización
- incorpora `OrganizationSchedule` como agregado separado
- establece el patrón de lectura agregada + escritura desacoplada

## Regla para decisiones futuras

Cuando se proponga un nuevo campo o capacidad, evaluar en este orden:

1. ¿Qué evento del negocio cambia este dato?
2. ¿Ese cambio altera identidad, reglas operativas o horario?
3. ¿Pertenece a un agregado existente o exige uno nuevo?

Si la propuesta nace solo de la conveniencia de una pantalla, no es criterio suficiente para
elegir el modelo de persistencia.
