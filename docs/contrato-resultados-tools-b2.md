# B2 — Contrato de resultados y capacidades del agente

Enmienda vigente del 2026-09-14 al catálogo y a los contratos históricos de tools.
Fuente: fase B2/C3 del [plan canónico](plan-implementacion-auditoria-agente-whatsapp-2026-09md).
El [acta B2](implementacion-b2-agente-whatsapp-2026-09-15.md) registra validación y cierre.

## Transporte y resultado

`RequestsTransport` y `ToolExecutor.call` entregan `TransportResponse` en memoria:
status HTTP nullable, data parseada, body recibido, `parse_valid`, error técnico,
timeout e incertidumbre de aceptación. Body/data se excluyen de `repr`; no se
registran en logs. Un body ausente o JSON inválido conserva `data=None` y parseo
inválido. Los transportes de API real del harness y del eval usan el mismo parser.

La iteración `(status, data)` permanece temporalmente para preparadores legacy:
un 2xx no parseable presenta 599 a ese caller, conservando el status HTTP real en
el objeto y en auditoría. Los tests que inyectan tuples se adaptan como JSON ya
decodificado; los nuevos casos de parseo usan `TransportResponse` explícito.
Esto no acredita éxito de negocio. Los consumidores B2 no usan ese adaptador.

`ToolOutcome` es el único contrato de negocio, sin nuevo modelo o tabla:

| Variante | Evidencia y significado |
| --- | --- |
| `READ` | Proyección validada, scope técnico org/conversación/contacto y filtros del endpoint o filtros locales identificados, completeness, observación temporal opcional, has_more/cursor solo respaldados. |
| `EFFECT` | Acción, entidad, referencia real y estado compatible; resultado `success` o `already_done`. `operation_key` conserva la clave de idempotencia cuando existe. No autoriza ejecución. |
| `ERROR` | `forbidden`, `not_found`, `validation_error`, `conflict`, `transport_error`, `malformed_response`, `provider_error` o `uncertain`. Origen/retryability se dejan desconocidos si no se pueden determinar. |

El compuesto supervisado existente puede devolver ERROR con `partial_effects`
que prueban solo la mascota registrada; no se confunde con truncamiento READ.
No se implementa un ledger, saga ni recuperación automática.

`ok` es una propiedad derivada temporal. El argumento constructor legacy `ok=`
adapta preparación/control a READ/ERROR **sin** establecer `validated=True`.
Un `ok=True` legacy no acredita precio, disponibilidad o efecto. Los renderers
exigen la variante, validación, campos compatibles y scope del `TurnContext`.

`empty` requiere READ validada, colección vacía y `completeness=complete`.
`observed_at` queda ausente cuando el endpoint no devuelve evidencia temporal;
no se inventa usando el reloj del worker. Los errores de red en una mutación
tienen aceptación incierta; no se reintentan como si se conociera el desenlace.

## Endpoints y cobertura

| Fuente existente | Validación y alcance |
| --- | --- |
| `GET /api/pets/?owner=<UUID>` | Array de mascotas con UUID/id/nombre/especie y owner anidado compatible. El endpoint acota a 20 sin paginar; la proyección a 10. Un corte local es truncated; llegar al límite del proveedor no prueba completitud. |
| `GET /api/appointments/?pet=<UUID>` | UUIDs de cita/mascota/owner, estado canónico, fecha/horas/instantes válidos. Verifica owner y mascota consultados; conserva citas antiguas. Recorta por cercanía a 5 y propaga la cobertura de mascotas. |
| `GET /api/appointments/?date=…` | Misma estructura, día aplicado, veterinario e intervalos. Solo agenda completa permite derivar huecos; compara solapamiento de intervalos. Las sugerencias siguen limitadas a 3. |
| `GET /api/vaccines/?pet=<UUID>` | UUID, mascota exacta, nombre, fechas y estado administrativo conocido. No es evaluación clínica. Límite de proyección 10. |
| `GET /api/billing/services/` | UUID/nombre/activo/base_price. Filtrado local explícito por nombre/activo. Decimal DRF interpretado estructuralmente; moneda del selector existente `get_org_setting(..., currency_code)`. |
| `GET /api/inventory/products/?active=true[&category=…]` | UUID, nombre, categoría, flags, stock y presentaciones con stock/precio válidos. Precios solo para productos disponibles; asociación producto/presentación/monto/moneda. |
| `GET /api/appointments/<UUID>/` | Entidad y owner de la cita exacta; la consulta de asistencia sigue en `get_appointments`, no en la capacidad mutadora. |
| `POST /api/appointments/`, `PATCH /api/appointments/<UUID>/[status/]` | Solo componentes supervisados/inactivos: entidad, estado y argumentos de efecto compatibles. Un 409 no es confirmación; GET fresco compatible puede demostrar already_done, sin segundo PATCH. |
| `POST /api/pets/`, `POST /api/appointments/create-with-patient/` | Solo componentes supervisados/inactivos: entidad/relación y estado válidos antes de registrar efecto o enlazar la respuesta existente. El compuesto mascota+cita preserva efectos parciales. |

Los arrays planos de citas/vacunas/servicios/productos son completos por el
contrato de sus vistas actuales sin paginación global, no por el status HTTP.
El envelope DRF requiere count/next/previous consistentes para probar cobertura.
Un envelope solo con results queda unknown. El recorte local nunca desaparece.
No se recorren páginas ni se fabrican cursores. `has_more` cuando existe describe
el paginador del proveedor, no elimina un recorte local de la proyección.

Todos los accesos HTTP conservan JWT del AGENT, RBAC y filtro tenant del dominio.
Las respuestas que explicitan otro scope se rechazan; las personales además
deben coincidir con owner/mascota/cita esperados. Los serializers que no publican
org dependen de su endpoint autenticado tenant-scoped; no se crea RLS.

Fuentes locales públicas: datos configurados de clínica y especialidades con
servicio/personal activos. La FAQ textual no acredita importes ni efectos.
La memoria de consultas de productos conserva solo producto/fecha y cobertura
unknown; los summaries históricos no se convierten en recibos actuales.

## Manifiesto estático y acceso

`capabilities.EFFECTS` es un mapping inmutable del servidor y `TOOL_SPECS` declara
effect, identidad, autorización, schema de argumentos y contrato de resultado.
Las escrituras declaran su kind y la idempotencia/precondición que ya existe.

| Effect | Capacidades |
| --- | --- |
| `READ_PUBLIC` | get_clinic_info, get_service_catalog, get_offered_specialties, check_product_availability, find_available_slots, check_appointment_slot |
| `READ_PERSONAL` | list_my_pets, get_appointments, get_vaccine_status, get_recent_product_queries |
| `WRITE_BUSINESS` | create_appointment, confirm_appointment, cancel_appointment, reschedule_appointment, register_new_client_and_pet, register_pet_and_schedule, register_pet_only |
| `CONTROL` | set_client_path, identify_client, begin_operation, request_human |

READ pública y solicitud humana no requieren onboarding ni abren un goal para
obtener permiso. Las lecturas personales requieren vínculo vigente existente;
los controles conservan sus reglas particulares (`begin_operation` no queda
habilitada al modelo y `request_human` conserva su visibilidad interna).
La comparación de manifest y registro falla si una tool queda sin clasificar.

**WRITE autónomo sigue cerrado** por B0 en catálogo/dispatch/pending y ahora
también en el executor HTTP. Una capacidad READ no puede emitir mutaciones
HTTP aunque se equivoque su handler. Los tests legacy supervisados conservan
su override explícito exclusivamente de pruebas; no hay flag de producción.
Una pregunta de asistencia nunca obtiene autoridad del tool choice.

## Rendering y diagnóstico

Precio, stock/disponibilidad, citas, vacunas administrativas, cobertura y efectos
se proyectan a texto determinista desde el resultado validado. Los precios
requieren Decimal tipado, concepto y moneda compatibles; IDs/duración/teléfono
coincidentes no acreditan monto. El planner conserva el `TurnContext` B1 y
rechaza resultados fuera de su scope al construir la respuesta.

El texto libre posterior no reescribe ni añade afirmaciones al recibo. La
contención clínica B0 sigue activa. Sin resultado protegido el borrador conserva
los guards, que no conceden autoridad por números o `tool_ran=True`; el éxito
no respaldado pasa a infracción HARD. No se introduce un verificador universal.

- Unknown/truncated: mostrar resultados verificados con límite explícito;
  colección vacía sin cobertura completa no prueba ausencia.
- Malformed/errores: fallback sin datos inventados.
- Efecto ambiguo: solicitar revisión antes de repetir; no afirmar éxito/fallo.
- Handoff local: «solicitud registrada», sin afirmar aviso, entrega o atención.
- Compuesto parcial: mascota registrada; resultado de cita no verificado.

`ToolExecution.result_summary_redacted._outcome_v1` contiene solo kind,
validated, completeness y error_kind de nuevas ejecuciones validadas por el
adaptador READ, dispatch o commit supervisado, cuando hay una fila de la misma
tool, organización y conversación. No copia bodies, transcript, precios, labels o
IDs personales. Los logs de HTTP usan vocabulario de errores cerrado y la
correlación existente; nunca el detail arbitrario del proveedor. No hay backfill.

## Límites vigentes

PENDING_ACTIVATION_REQUIREMENTS continúa. B2 no entrega sender durable, prueba
de entrega Meta, atención humana durable, consentimiento exacto, autorización
persistente o ejecución autónoma. B3–B9, E1–E5 y P-A/P-B no se implementan aquí.
H05/H14/H20 quedan mitigados técnicamente en estas rutas; la garantía end-to-end
de nuevas escrituras sigue pendiente de sus fases. H04 solo se acota en wording;
la atención humana corresponde a B5.
