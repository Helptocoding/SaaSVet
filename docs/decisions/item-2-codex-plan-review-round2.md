REQUEST CHANGES

# Segunda revisión de planificación — Item 2

## Dictamen

Los cierres de los P0/P1 de la primera revisión son suficientes en nueve de los
diez puntos. Hay un bloqueo nuevo, encontrado al contrastar F1 con todas las
vías reales de alta y edición: el plan no incorpora la creación anidada desde
`/api/pets/` ni el cambio de teléfono de un `Owner`. Por ello todavía no puede
afirmar que la resolución por teléfono sea única, serializada y coherente con
`phone_normalized`.

## Bloqueantes para seguridad/corrección

### P0 — F1 no cubre todas las escrituras reales de teléfono

F1 enumera `create-with-patient`, `POST /api/owners/` e importación como
consumidores del servicio único (`item-2-implementation-plan.md:208-215`), y
la decisión exige que todo camino que resuelva un expediente por teléfono lo
use (`item-2-decision.md:820-870`). Sin embargo, `PetViewSet` expone el
serializer de mascotas (`backend/apps/patients/views.py:34-52`) y
`PetSerializer.create()` aún ejecuta directamente
`Owner.objects.get_or_create(name, phone, organization)`
(`backend/apps/patients/serializers.py:115-132`). Esa vía puede crear otro
Owner con el mismo teléfono en paralelo o elegir una semántica distinta de
`owner_exists`/`owner_ambiguous`.

Además, `OwnerSerializer.update()` asigna y guarda `phone` directamente
(`backend/apps/patients/serializers.py:134-147`). F1 establece que el teléfono
normalizado se deriva siempre por el dominio (`item-2-implementation-plan.md:200-205`),
pero no agenda esta escritura. Así puede quedar desincronizado o introducir
duplicados nuevos fuera del lock de aviso.

Cambio requerido: ampliar F1 y P2-12 para que `POST /api/pets/`, las
creaciones/ediciones de `Owner` y cualquier escritor no genérico de `phone`
pasen por una única operación de dominio. Esta debe normalizar, tomar el lock
transaccional `(organización, teléfono normalizado)`, mantener
`phone_normalized` consistente y aplicar la política explícita ante uno o más
candidatos. El gate no debe limitarse a un grep de
`get_or_create(...phone...)`: debe detectar también creaciones multirrenglón y
asignaciones seguidas de `save()` fuera del servicio autorizado.

Sin esto, P0-16/P0-17 solo acreditan un subconjunto de las rutas y el cierre de
INV-C no es válido.

## P0/P1 de la primera revisión que sí quedan resueltos

| Punto | Evidencia de cierre |
|---|---|
| No solapamiento PostgreSQL | F0·b define `btree_gist`, exclusión parcial por organización/veterinario/intervalo y traducción por nombre de restricción (`item-2-implementation-plan.md:116-159`); cubre creación, PATCH, walk-in y reactivación (`item-2-decision.md:546-579`). |
| Transición pendiente → suspendido + handoff | Helper único, `atomic()` y `select_for_update()` copia el staged, elimina el pending y crea/retiene el handoff en un commit; se prohíbe `clear_pending` en esa rama (`item-2-decision.md:1123-1167`; plan:249-257). |
| Release, lease y claim | F3 usa testigo de suspensión, estado, claim, lease y handoff; R3 no muta ante diferencias y claim/release/close se serializan (`item-2-implementation-plan.md:294-314`; decisión:1221-1250). |
| F4 después de F3 | El grafo la hace dependiente de F3 y exige feature gate hasta desplegarla; P0-15 es el gate de aceptación (`item-2-implementation-plan.md:48-77, 325-333`). |
| DELETE, status y assign-patient | Los tres entran en el contrato con lock y precondición; `DELETE` se depreca y `complete_appointment_on_record_close` queda excluida con justificación (`item-2-decision.md:521-534`; plan:101-114). |
| Aprobación de staff ligada al caso | F4 deriva tenant/conversación/contacto/actor en servidor, resuelve el candidato scoped y exige última aprobación del mismo candidato y handoff abierto bajo locks (`item-2-implementation-plan.md:337-346`; decisión:1051-1077). |
| Conflictos de negocio fuera de telemetría técnica | F2 cambia `executor.py` para declarar outcomes de negocio, emitir evento redactado y conservar `ToolExecution` sin `AGENT_TOOL_HTTP_ERROR` (`item-2-implementation-plan.md:249-258`; decisión:979-989). |
| Item 1 y cuarta vía auditada | F4 hace DoD actualizar Item 1 y el docstring de reset; P2-8 verifica que solo la vía auditada limpia el bloqueo (`item-2-implementation-plan.md:376-392`). |
| Walk-ins y reactivaciones | La exclusión no admite excepciones: ambos devuelven `slot_taken`, sin fuerza ni sobrecupo, y P0-20 lo ancla (`item-2-implementation-plan.md:125-159`; decisión:605-624). |

## Mejoras recomendadas no bloqueantes

- En F3, declarar de forma literal que R3 vuelve a comprobar que el handoff
  identificado por el testigo sigue abierto, además de que conserve el mismo
  id. La decisión ya habla de «handoff abierto observado»
  (`item-2-decision.md:1221-1229`); precisarlo reduce ambigüedad al implementar
  el compare-and-set.
- Clasificar o retirar `appointments.services.create_appointment`: aunque hoy
  no tiene llamadores de producción, conserva un `exists()` seguido de
  `Appointment.objects.create()` (`backend/apps/appointments/services.py:29-43`).
  Dejarlo sin matriz ni traducción de la restricción permitiría reintroducir una
  vía read-then-write al reutilizarlo.

## Pruebas obligatorias previas a merge

1. Todas las pruebas PostgreSQL ya declaradas: P0-16/P0-17 (teléfono),
   P0-18/P0-20 (exclusión de agenda), P0-19 (transición atómica), P1-14 y
   P1-19 a P1-22 (precondición y release concurrente), P1-16 (autorización
   concurrente) y P0-15 (FLUJO-C completo).
2. Añadir dos conexiones reales para `POST /api/pets/` contra
   `create-with-patient` y contra `POST /api/owners/`, con el mismo teléfono:
   un solo Owner nuevo o el desenlace cerrado correspondiente; repetir con dos
   Owners históricos y exigir `owner_ambiguous`, sin mascotas ni escrituras.
3. Probar edición de teléfono: normaliza y serializa contra alta concurrente;
   no deja `phone_normalized` obsoleto ni permite crear/ocultar un duplicado
   nuevo. Definir y probar el 409 o la reutilización que corresponda al
   contrato de producto.
4. Mantener los gates funcionales y estáticos de P2-12 para impedir toda
   creación, resolución o cambio de teléfono fuera del servicio único.
5. Ejecutar la línea base completa de `appointments`, `patients`, `imports` y
   `agent` en PostgreSQL antes del merge.
