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
| `apps/organizations/serializers.py::validate_phone` | Validación real (hoy solo quita no-dígitos): 10 dígitos MX + rechazo de relleno, vía helper compartido en `apps/core` | **Contrato de escritura** — rechaza payloads que hoy pasan |
| `apps/dashboard/views.py::dashboard_activation` | +`has_clinic_contact`; `completed` pasa a incluirlo | **Contrato** — es lo que reabre el overlay en orgs existentes (§7) |
| `apps/agent/views.py` (settings del inbox) | `enabled=True` exige teléfono válido (§9) | **Seguridad** — cierra el estado agente-ON-sin-teléfono |
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

### 5.1 Señal: que el campo no pueda guardar basura

Revisión del PO: `bool(phone)` es una señal débil — `1111111111` la satisface y
el dato sigue siendo inútil. Al verificarlo apareció algo peor:
**`OrganizationSerializer.validate_phone` solo quita los no-dígitos y
devuelve**. Sin longitud ni formato. Hoy:

- `"5"` se guarda como `"5"`.
- `"no sé"` se guarda como `""` **en silencio** → el ADMIN guarda, cree que
  terminó, y el onboarding reaparece sin explicación.

Mientras tanto `OwnerSerializer.validate_phone` exige 10 dígitos MX: el teléfono
del cliente está validado y el de la propia clínica no.

**Decisión: no se construye un predicado "válido" en el endpoint de activación.
Se arregla el campo.** La validación vive en el serializer (donde ya vive la del
Owner) y la señal vuelve a ser trivial, porque si el campo no puede contener
basura, *existir* equivale a *ser válido*:

| Capa | Regla | Dónde |
|---|---|---|
| Formato | Normalizar a dígitos; exigir exactamente 10 (México-only, misma decisión Q5 que `Owner.phone` y `normalize_wa_id`) | Serializer, bloquea el guardado |
| Relleno evidente | Rechazar todos los dígitos iguales (`1111111111`, `0000000000`) y secuencias triviales (`1234567890`) | Serializer, bloquea el guardado |
| Existencia | `bool(phone)` | Endpoint de activación |

Se comparte un helper (`apps/core`) para que la regla tenga **un solo** dueño y
lo consuman los dos serializers.

**Límite honesto**: esto sube el piso de "cualquier cosa" a "plausible". No
prueba que el número sea real — un número válido pero equivocado pasa igual, y
la única prueba de verdad es un OTP o una llamada, que el PO excluyó. El
residual queda registrado y se asume.

**Deuda que esto expone**: hay filas existentes con teléfonos que no pasarían la
regla nueva. Con 3 organizaciones en producción, la limpieza es manual (§7).

### 5.2 Posición del paso: en medio

`pacientes → datos de tu clínica → servicios`.

**Corrección al plan original** (que lo ponía al final): la propuesta del PO es
mejor en los dos ejes que estaba tratando de equilibrar.

- Sigue abriendo con **pacientes**, que es donde está el valor visible — el
  argumento de "no abrir con un formulario" se conserva intacto.
- Los datos de contacto son **identidad**; los servicios son **configuración
  operativa**. Identidad antes que configuración es el orden natural.
- Y sobre todo: `modules/frontend.md` documenta como decisión deliberada que
  *"el servicio cierra como final de readiness"*. Ponerlo al final la rompía sin
  justificarlo. Este orden la **preserva**.

### 5.3 Contenido y copy del paso

El paso hace dos trabajos a la vez —identidad de la clínica y requisito del
agente— y el copy debe hablar del beneficio, no de la administración. Nada de
"completa tus datos".

- **Título**: *¿Cómo pueden encontrarte tus clientes?*
- **Lead**: el teléfono al que te llaman, el WhatsApp por el que te escriben y
  la dirección a la que llegan. Es lo que el asistente les comparte cuando
  preguntan cómo llegar — y el número que da si hay una emergencia.
- **CTA primario** → `/config` (sección Clínica).
- **Sin CTA secundario** (no hay ruta alterna real, igual que el paso de
  servicios).
- **Preview** (columna derecha, no interactiva): tarjeta con nombre, teléfono y
  dirección — misma estética que las dos existentes.

El copy final se ajusta con la clínica piloto; lo vinculante es que hable de
llamadas, WhatsApp y emergencias, no de "completar información".

## 6. Plan incremental

| PR | Contenido | Est. |
|---|---|---|
| **PR-1** | Validación real de `Organization.phone` (helper compartido: 10 dígitos MX + rechazo de relleno) + limpieza de las filas existentes que no pasen. Cierra la asimetría con `Owner.phone`; **independiente del onboarding y desplegable solo** | 0.5 d |
| **PR-2** | Retorno automático desde `/config` para `has_services` (arregla 3.1). También independiente | 0.5 d |
| **PR-3** | Backend: `has_clinic_contact` en el endpoint + tests. **Aún no gatea `completed`** | 0.5 d |
| **PR-4** | Teléfono genérico de la demo en `seed_demo_clinic` + captura en las orgs internas | 0.5 d |
| **PR-5** | Frontend: paso nuevo + copy + preview + retorno; y recién aquí `completed` pasa a incluir el hito | 1 d |
| **PR-6** | **Gate del kill switch**: `enabled=True` exige teléfono válido (§9) | 0.5 d |

Dos restricciones de orden:

1. **PR-1 antes que PR-3.** Si el hito se deriva de un campo que acepta basura,
   la señal nace inservible.
2. **PR-4 antes que PR-5.** Si el hito gatea antes de sembrar el teléfono de la
   demo, la demo arranca con el overlay encima — y es la superficie de venta.

PR-6 no depende de los demás: puede ir primero si se quiere cerrar el agujero de
seguridad antes que el de UX.

## 7. Riesgos

| Riesgo | Nivel | Mitigación |
|---|---|---|
| Orgs ya activadas sin teléfono ven reaparecer el overlay full-screen | **Alto** | **Aceptado por el PO**: solo afecta al ADMIN, ocurre una vez, tiene causa clara y solución inmediata — no se inventan excepciones. Mitigado en las tres orgs de producción: demo por seed (PR-4), interna y de pruebas por captura manual antes de desplegar PR-5 |
| Filas con teléfono inválido preexistente (`"5"`, `""` por letras) | Medio | PR-1 las detecta; con 3 orgs la limpieza es manual. Sin esto, `bool(phone)` daría por bueno un `"5"` viejo |
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

## 8. Seed del horario: NO se toca (decisión del PO)

Se evaluó sembrar los 7 días como `is_closed=True` para que "algún día abierto"
fuera señal derivable de horario confirmado. **Descartado por ahora.**

Razón del PO: hoy el sistema garantiza *crear clínica → ya tiene horario*, y
romper esa expectativa tiene muchas más implicaciones que este onboarding.
Merece su propio ADR, no un efecto colateral de un cambio de UX.

**Residual asumido**: el horario sigue sin gatear nada, así que una clínica
puede operar —y el agente ofrecer huecos— sobre el default sembrado que nadie
confirmó. Es la razón por la que el paso incluye el horario editable aunque no
lo exija.

## 9. Gate del kill switch: OBLIGATORIO (decisión del PO)

Deja de ser "recomendado, no incluido" y entra al plan como **PR-6**.

**No es UX, es seguridad.** No debe existir la combinación:

```
AgentSettings.enabled = True   +   Organization.phone = ""
```

Porque el agente atiende urgencias: un cliente que reporta que su perro
convulsiona recibiría *"acude de inmediato a la clínica"* sin número al que
llamar. Ese estado no debe ser alcanzable, independientemente de si el ADMIN
hizo el onboarding con esta versión o venía de antes.

- `PATCH /api/inbox/settings/` con `enabled: true` valida que
  `Organization.phone` pase la regla de PR-1; si no, **400** con mensaje
  accionable que apunta a Configuración → Clínica.
- La UI del kill switch en `/inbox` muestra el motivo y el enlace, no un error
  crudo.
- El horario **no** entra en este gate: sin la decisión de §8 no hay forma de
  distinguir "confirmado" de "sembrado", y bloquear sobre una señal que siempre
  es verdadera no protege de nada.

**División de responsabilidades**: el onboarding **educa** (te lleva al dato
cuando arrancas), el gate **garantiza** (impide el estado peligroso). Hacen
cosas distintas y ninguno sustituye al otro.

## 10. Aprobación

- [x] PR-1 validación real de `Organization.phone` (`apps/core/validators.py`,
      compartido con `OwnerSerializer`) — **limpieza de filas pendiente** (manual, §7)
- [x] PR-2 retorno desde `/config` (`config/index.jsx` dueño del navigate;
      además deep-link de sección, que faltaba)
- [x] PR-3 hito `has_clinic_contact` en el endpoint + tests
- [x] PR-4 demo (`DEMO_ORG_CONTACT` + `_ensure_org_contact`, idempotente) —
      **captura manual en las orgs internas pendiente**
- [x] PR-5 paso nuevo + copy + preview + `completed` incluye el hito + smoke Vitest
- [x] PR-6 gate del kill switch (`AgentSettingsSerializer.validate_enabled` + UI)

**Ejecutado el 2026-07-26.** Los 6 PRs se implementaron en un solo árbol; las
restricciones de orden del §6 son de **despliegue**, no de edición: al desplegar,
la limpieza de teléfonos (PR-1) y la captura en las orgs internas (PR-4) deben
completarse **antes** de que PR-5 llegue a producción, o esos ADMIN verán el
overlay.
