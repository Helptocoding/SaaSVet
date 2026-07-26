# Plan: capturar los datos de la clínica en el onboarding de primer uso

**Fecha**: 2026-07-26
**Estado**: PLAN — sin código
**Decisión del PO**: se cambia el onboarding (`FirstRunAssistant`) para que la
clínica capture sus datos de contacto en la primera sesión. El riesgo de que el
overlay reaparezca en organizaciones ya activadas queda **aceptado**; la demo se
resuelve sembrándole un número genérico (la demo no ejercita la automatización
de WhatsApp).
**Contratos afectados**: [`modules/frontend.md`](modules/frontend.md)
§FirstRunAssistant · [`modules/organizations.md`](modules/organizations.md)
§OrganizationSchedule · ADR p53 · ADR p54.

---

## 1. Por qué

`Organization.phone` es hoy el número que el agente de WhatsApp pone en su
**plantilla de urgencia**. Verificado en producción el 2026-07-26: la clínica de
pruebas lo tiene vacío, así que un cliente que escribe *"mi perro convulsiona"*
recibe *"acude de inmediato a la clínica"* **sin número al que llamar**.

No hay ninguna superficie que obligue —ni sugiera— capturar esos datos: existen
en Configuración → Clínica desde ADR p53, y nada lleva al ADMIN hasta ahí.

## 2. Alcance

**Entra**: un tercer hito de activación derivado del teléfono de la clínica, su
paso correspondiente en el asistente de primer uso, el arreglo del retorno
automático desde `/config`, y el número genérico de la demo.

**No entra** (deliberado):
- Gatear el encendido del agente en `/inbox` (defensa complementaria — §9).
- Promover los datos de clínica a los PDFs (p36 Fase 2).
- Cambiar el orden de los dos pasos existentes.

## 3. Hallazgos de la investigación que condicionan el diseño

### 3.1 El retorno automático solo funciona en el paso 1

`pages/pets.jsx:724` navega a `/` con `state.onboardingStep` tras crear un
paciente. **Ninguna sección de `pages/config/` lo hace**, pese a que
`modules/frontend.md` afirma que sí. Efecto actual: al crear el primer servicio
el onboarding no celebra ni cierra — el usuario se queda en Configuración y
tiene que volver a mano.

Es un defecto preexistente, y **bloquea** el paso nuevo: si el CTA lleva a
`/config` y el guardado no devuelve la señal, el hito nuevo tampoco cerraría
solo. Se arregla en el mismo trabajo.

### 3.2 El horario NO es una señal derivable

El principio del onboarding es duro: *estado real, nunca flags*. Funciona porque
"tiene pacientes" y "tiene servicios" son hechos observables.

"La clínica confirmó su horario" **no lo es**: `create_default_schedule` siembra
las 7 filas (L-V 9-18, sáb 9-14) al crear la organización, así que
`has_schedule` es `true` desde el segundo cero. Distinguir "es el default" de
"la clínica lo revisó" exige un flag o un timestamp — exactamente lo prohibido.

**Decisión**: el horario se edita dentro del paso nuevo pero **no gatea** el
cierre. El teléfono sí, porque nace vacío y por tanto es observable. Ver §8 para
la alternativa que sí lo haría derivable.

### 3.3 Hoy el único consumidor es el agente

Grep sobre todo el backend: fuera de `apps/agent`, nadie lee `phone`,
`address_line1`, `google_maps_url` ni `arrival_instructions`. Los PDFs no los
usan todavía.

Consecuencia asumida: el paso nuevo le cobra ~1 minuto a toda clínica, incluidas
las que nunca usarán WhatsApp. Se acepta porque son datos de identidad que
cualquier clínica debería tener capturados y que p36 Fase 2 consumirá.

## 4. Qué se toca

| Archivo | Cambio | Riesgo |
|---|---|---|
| `apps/dashboard/views.py::dashboard_activation` | +`has_clinic_contact`; `completed` pasa a incluirlo | **Contrato** — es lo que reabre el overlay en orgs existentes (§7) |
| `apps/dashboard/tests/test_activation_endpoint.py` | +casos del hito nuevo; ajustar los 3 que asertan `completed` | — |
| `components/dashboard/FirstRunAssistant.jsx` | +entrada en `STEPS`, +preview en `STEP_PREVIEW`, +componente de preview | Bajo — el resto del componente es genérico |
| `pages/config/ClinicSection.jsx` | Emitir `navigate("/", {state:{onboardingStep:"has_clinic_contact"}})` tras guardar si venía de onboarding | Bajo |
| `pages/config/ServicesSection.jsx` | Lo mismo para `has_services` (arregla 3.1) | Bajo |
| `pages/config/index.jsx` | Leer `location.state.fromOnboarding` y pasarlo a las secciones | Bajo |
| `management/commands/seed_demo_clinic.py` | Teléfono genérico a la org demo, idempotente | Bajo |
| `docs/modules/frontend.md` | Actualizar §FirstRunAssistant (hitos, orden, retorno) | — |

**No se toca**: `hooks/activationContext.jsx` (el provider ya refetchea con
`dashboard:refresh` y bajo demanda), el motor de progreso/celebración/cierre, ni
`OrganizationSchedule`.

## 5. Diseño

### 5.1 Señal

```
has_clinic_contact = bool(organization.phone)
```

Derivada, sin flags, coherente con los otros dos hitos. Se elige **solo el
teléfono** y no la dirección porque es el dato crítico (plantilla de urgencia) y
porque una señal simple es más fácil de razonar que un `and` de cuatro campos.
La dirección, el mapa y las indicaciones se capturan en el mismo paso, sin
gatear.

```
completed = has_patients and has_services and has_clinic_contact
```

### 5.2 Posición del paso: al final

`pacientes → servicios → datos de tu clínica`.

Los dos primeros producen valor visible rápido; el tercero es administrativo.
Abrir con un formulario de identidad enfriaría el arranque.

**Contrapartida a asumir**: hoy el cierre del onboarding lo da "servicios", que
es un final más satisfactorio que un formulario de contacto. El copy del último
paso tiene que cargar con eso ("ya casi: cómo te encuentran tus clientes").
Decisión de producto, reversible cambiando el orden del array.

### 5.3 Contenido del paso

- **Título**: datos de contacto de la clínica.
- **Lead**: por qué importan — es lo que ven tus clientes y lo que usa el
  asistente para orientarlos.
- **CTA primario** → `/config` (sección Clínica).
- **Sin CTA secundario** (no hay ruta alterna real, igual que el paso de
  servicios).
- **Preview** (columna derecha, no interactiva): tarjeta con nombre, teléfono,
  dirección — misma estética que las dos existentes.

## 6. Plan incremental

| PR | Contenido | Est. |
|---|---|---|
| **PR-1** | Retorno automático desde `/config` para `has_services` (arregla 3.1). Independiente y desplegable solo | 0.5 d |
| **PR-2** | Backend: `has_clinic_contact` en el endpoint + tests. **Aún no gatea `completed`** | 0.5 d |
| **PR-3** | Teléfono genérico de la demo en `seed_demo_clinic` + backfill de las orgs internas | 0.5 d |
| **PR-4** | Frontend: paso nuevo + preview + retorno; y recién aquí `completed` pasa a incluir el hito | 1 d |

El orden importa: **PR-3 antes que PR-4**. Si el hito gatea antes de sembrar el
teléfono de la demo, la demo arranca con el overlay encima — y es la superficie
de venta.

## 7. Riesgos

| Riesgo | Nivel | Mitigación |
|---|---|---|
| Orgs ya activadas sin teléfono ven reaparecer el overlay full-screen | **Alto** | **Aceptado por el PO.** Mitigado en las tres orgs de producción: demo por seed (PR-3), interna y de pruebas por captura manual antes del deploy. Verificable con una query antes de desplegar PR-4 |
| El overlay tapa la app a un ADMIN que ya operaba | Medio | Solo se monta en `/`; el resto de módulos conservan su navegación. Aun así, es intrusivo para alguien que ya venía trabajando |
| Alarga el onboarding y baja el completado | Medio | El paso es de 1 campo obligatorio; medir con `has_clinic_contact` en el tiempo |
| Erosionar el principio "sin flags" | Bajo | La señal elegida es derivable. El horario se deja fuera del gate justo para no violarlo |
| `FirstRunAssistant` no tiene tests | Bajo-medio | El gate de Vitest cubre utils y `PaymentLinesEditor`. Añadir un smoke del array de pasos y del gate por permiso |
| Reset de la demo borra el teléfono | Bajo | El reset (ADR p49) purga el subgrafo operativo, no la fila `Organization`. Sembrarlo en `seed_demo_clinic` de forma idempotente lo hace sobrevivir a re-seeds |

**Query de verificación antes de desplegar PR-4**:

```
Organization.objects.filter(phone='').values_list('name', flat=True)
```

Si devuelve algo, esas organizaciones verán el overlay al siguiente login.

## 8. Decisión abierta para el PO

**¿Sembrar el horario por defecto como cerrado en vez de L-V 9-18?**

Hoy toda clínica nace con un horario que puede ser mentira, y el agente ofrece
huecos sobre él sin que nadie lo haya confirmado. Si los 7 días nacieran
`is_closed=True`, entonces "algún día abierto" pasaría a ser señal **derivable**
de configuración real, y el horario podría gatear el onboarding sin violar el
principio.

- A favor: desaparece un default que puede ser falso; el agente falla en seguro
  (no ofrece huecos) en vez de ofrecer horarios equivocados.
- En contra: cambia comportamiento de ADR p53 y toca a las orgs existentes;
  una clínica que abra Configuración vería todo cerrado.

Fuera del alcance de este plan; se decide aparte.

## 9. Defensa complementaria (recomendada, no incluida)

Bloquear el encendido del agente en `/inbox` mientras falten teléfono y horario.
Dispara exactamente cuando el dato pasa a ser crítico y no depende de que el
ADMIN haya hecho el onboarding con esta versión. El onboarding educa; el gate
del kill switch garantiza. Son complementarios, no alternativos.

## 10. Aprobación

- [ ] PR-1 retorno desde `/config`
- [ ] PR-2 hito en el endpoint (sin gatear)
- [ ] PR-3 demo + backfill
- [ ] PR-4 paso nuevo + gate
- [ ] §8 decisión sobre el seed del horario
- [ ] §9 gate del kill switch (plan aparte)
