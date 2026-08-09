# Plan de implementación — Item 2

**Fecha**: 2026-08-08 (rev. 5 — F1 incorpora los **lectores** de identidad:
bloqueador de la revisión OCR)
**Estado**: PLAN — no se escribió código ni se modificó ningún archivo de
producción. Este documento ordena el trabajo que
[`item-2-decision.md`](item-2-decision.md) aprobó; **no reabre decisiones**.
**Decisión de origen**: [`item-2-decision.md`](item-2-decision.md) — invariantes
INV-A (precondición atómica como garantía de dominio), INV-B (el teléfono
localiza, no autoriza), **INV-C** (un teléfono normalizado ⇒ como máximo un
expediente; si hay más, `owner_ambiguous`), **INV-D** (un veterinario no tiene
dos citas activas solapadas, garantizado en PostgreSQL y **sin excepciones**:
atención sin cita §9.14 y reactivación §9.15) y FLUJO-C (caso de verificación de
identidad).
**Revisiones respondidas**:
[`item-2-codex-plan-review.md`](item-2-codex-plan-review.md) — REQUEST CHANGES
(1ª), y [`item-2-codex-plan-review-round2.md`](item-2-codex-plan-review-round2.md), que devolvió un **P0**: F1 no cubría
`POST /api/pets/` ni la edición del teléfono de `Owner`. **Ninguna revisión se
modifica**; su cierre punto por punto está en §12 y §12.1 de la decisión, y su
reflejo operativo, aquí. **Revisión OCR ronda 1**
(`.ocr/sessions/2026-08-08-task-2782bc85-…/rounds/round-1/final.md`,
REQUEST CHANGES): bloqueador de los lectores de identidad del agente + dos
ajustes (preview del importador, `Owner` genérico). Artefacto de OCR **no se
modifica**; cierre en §12.2 de la decisión.

> Toda referencia `§n` remite a `item-2-decision.md`. Las referencias internas de
> este plan se escriben como «plan §n».

---

## 1. Principios que ordenan las fases

1. **La garantía antes que su consumidor.** El dominio debe poder rechazar una
   escritura obsoleta *antes* de que el agente empiece a restaurar propuestas.
   Invertir el orden significa tener durante días exactamente el bug que la
   revisión de seguridad rechazó.
2. **Una garantía no se declara: se prueba en PostgreSQL.** Ninguna fase puede
   afirmar atomicidad apoyándose en una lectura previa (`exists()`,
   `get_or_create`) ni en una prueba que corra en SQLite. Es el motivo por el
   que la revisión de plan devolvió el trabajo.
3. **Cada fase deja el sistema mejor que antes, y es mergeable sola** — salvo
   donde una dependencia de seguridad lo impide, y esas están declaradas en el
   grafo, no implícitas en el criterio de quien mergea.
4. **Ninguna fase introduce una regresión en `/appointments` ni en la bandeja.**
   La precondición de estado es opt-in hasta F5 (§1.2); `require_new_owner` solo
   lo envía el agente. INV-D **sí** cambia comportamiento desde el día 1 (§3.4)
   y por eso lleva auditoría y limpieza previa.
5. **Los tests de la fase se escriben en la fase**, no al final. Los P0 de §8
   son gate de merge de su fase, no del Item completo.

---

## 2. Mapa de fases

| Fase | Qué entrega | Depende de | Cierra |
|---|---|---|---|
| **F0** | Precondición atómica en **todas** las mutaciones de cita (INV-A, matriz de §3.3) + **restricción de no-solapamiento** (INV-D, sin excepciones: §9.14, §9.15) con su auditoría y limpieza previa | — | P0-4, P0-7, P0-9, P0-18, P0-20, P1-14, P1-23, P2-4 |
| **F1** | Identidad de expediente por teléfono (INV-C): teléfono normalizado, servicio único (resolver + **cambiar teléfono**), y **todas** las vías del inventario §4.7.4 — incluidas `POST /api/pets/` y la edición del teléfono de `Owner` (hallazgo Z) | — (paralelizable con F0) | P0-6ᵃ, P0-9ᵇ, P0-16, P0-17, P0-21…P0-28, P2-5, P2-12, P2-14, P2-15 |
| **F2** | El agente consume las garantías: snapshot con precondición, revalidación de identidad en el commit, **transición atómica** ante `owner_exists`/`owner_ambiguous` y separación de los 409 de negocio en telemetría | F0, F1 | P0-2, P0-3, P0-5, P0-6ᵇ, P0-8, P0-10, P0-19, P1-11, P1-12, P1-13, P2-6, P2-7, P2-11, P2-13 |
| **F3** | Servicio de release: testigo, compare-and-set, `409 release_conflict`, serialización de claim/release/close | F2 (para que el «sí» posterior sea seguro) | P0-1, P1-1…P1-10, P1-19…P1-22, P2-1, P2-2, P2-3 |
| **F4** | Caso de verificación de identidad: backend + Inbox (FLUJO-C), con enlace estricto aprobación↔candidato↔handoff↔conversación↔tenant | **F2 y F3** | P0-11…P0-15, P1-15…P1-18, P1-24, P2-8, P2-9, P2-10 |
| **F5** | Frontend envía la precondición; después, obligatoria para todos + sunset de `DELETE` | F0 | §9.9 (decisión de producto pendiente) |

**F0 y F1 son paralelizables**: tocan módulos y funciones distintas
(`AppointmentDetailView`/`update_status`/`walk_in`/modelo de citas vs.
`create_with_patient` + `patients`). Comparten un único punto de contacto —
`create-with-patient` participa de INV-D (crea cita) y de INV-C (resuelve
expediente)—, así que quien mergee segundo corre la suite de ambos.

**F3 no debe mergear antes que F2**: restaurar propuestas sin la precondición
activa es precisamente el escenario que el dictamen de seguridad bloqueó.

**F4 depende de F3 para despliegue, no solo para orden de trabajo** (hallazgo S
de la revisión). El motivo es concreto: F4 habilita verificar, autorizar y
liberar, y **el release anterior a F3 no restaura `flow['suspended']`**. Una
autorización correcta seguida de un release dejaría la intención congelada, sin
confirmación nueva y sin ejecución posterior: el staff haría el trabajo bien y
el cliente no recibiría nada. Reglas:

- El backend y la UI de F4 permanecen **feature-gated** hasta que F3 esté
  desplegada; si por planificación F4 estuviera lista antes, se mergea apagada.
- El recorrido completo `owner_exists → verificar → autorizar → liberar →
  primer «sí» (re-paráfrasis, cero escrituras) → segundo «sí» (único commit)` es
  **prueba de aceptación** (P0-15) y gate de despliegue de F4.

**F5 no es parte de Item 2**; se lista porque INV-A no queda completo sin ella y
alguien tiene que agendarla (§9.9).

```
F0 ─┐
    ├─► F2 ─► F3 ─► F4        (F4 no se despliega sin F3)
F1 ─┘
F0 ─────────► F5              (fuera de Item 2)
```

---

## 3. F0 — Garantías de agenda: precondición atómica (INV-A) y no-solapamiento (INV-D)

**Objetivo**: ningún actor sobrescribe una cita cuyo estado cambió desde que se
confirmó la intención (§3.2, §3.3), y ningún actor puede ocupar dos veces el
mismo hueco del mismo veterinario (§3.4). Sin tocar al agente.

### F0·a — Precondición atómica (INV-A)

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/appointments/serializers.py` | Campo **declarado** `expected_state` (write-only, `required=False`) en `AppointmentSerializer`; validación de forma (`status`, `date`, `start_time`) y comparación contra `self.instance`. **Declararlo es el punto**: si no se declara, DRF lo ignora en silencio y la precondición no existe (§3.2, exigencia 1) |
| `backend/apps/appointments/views.py` | `AppointmentDetailView.update()` envuelto en `transaction.atomic()` con la fila tomada por `select_for_update()`; `update_status()` **mueve la lectura de la cita dentro** de su `atomic()` existente (hoy lee fuera) y la lockea; **`AppointmentDetailView.destroy()`** pasa por el mismo lock y acepta la misma precondición, además de emitir las cabeceras de deprecación; **`assign_patient`** lockea la fila y acepta la precondición (§3.3). Todos devuelven `409 appointment_changed` con `current` |
| `backend/apps/appointments/tests/test_preconditions.py` *(nuevo)* | P0-4, P0-7, P0-9ᵃ, P1-14, P1-23, P2-4 |

**Matriz de alcance obligatoria** (§3.3): `PATCH` detalle, `PATCH /status/`,
`DELETE`, `assign-patient` → dentro. `POST` y `create-with-patient` → sin
precondición de estado (no hay estado previo). `walk-in` → sin precondición.
`complete_appointment_on_record_close` → **excluida con justificación escrita**
(UPDATE condicional deliberado, evita un orden de locks
`Appointment↔MedicalRecord` que generaría ABBA con `assign-patient`).
`appointments.services.create_appointment` (helper legacy, sin llamadores y
roto de hecho — filtra por un campo `datetime` inexistente) → **se retira**:
conserva el patrón `exists()` + `create()` que INV-D prohíbe y sería una vía
read-then-write lista para reutilizarse por error.

`DELETE` entra **y** queda deprecado a favor de `/status/`: cabeceras
`Deprecation`/`Sunset` (RFC 8594) + el log `DEPRECATED_ENDPOINT_HIT` que el
proyecto ya tiene; la retirada (`410 endpoint_sunset`) es de F5.

### F0·b — No-solapamiento garantizado (INV-D)

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/appointments/management/commands/audit_appointment_overlaps.py` *(nuevo)* | Detecta pares de citas activas solapadas por veterinario, por organización, con `public_id`. Exit 0 limpio / 1 con hallazgos / 2 error — patrón `audit_stock_integrity`. **Se ejecuta antes de la migración y se queda como red de seguridad** |
| `backend/apps/appointments/migrations/0014_*` *(nuevo)* | Extensión `btree_gist` + restricción de exclusión sobre `(organization, veterinarian, intervalo)` con predicado parcial de estados activos y campos no nulos (§3.4) |
| `backend/apps/appointments/views.py`, `serializers.py` | Traducción de la violación de la restricción **por nombre** al desenlace de negocio existente (`400` + `code: 'slot_taken'`). Nunca capturar `IntegrityError` a ciegas. La validación previa del serializer **se conserva** como mensaje |
| `backend/apps/appointments/tests/test_no_overlap.py` *(nuevo, `TransactionTestCase`)* | P0-18 (concurrencia) y **P0-20** (atención sin cita + reactivación) — **PostgreSQL, no SQLite** |

**Sin excepciones, por decisión de producto (§9.14, §9.15).** Los dos caminos
que hoy pueden crear un solape quedan cubiertos y su comportamiento nuevo está
**aprobado**:

| Camino | Comportamiento nuevo | Qué NO se implementa |
|---|---|---|
| `walk-in` con el veterinario ocupado | `400 slot_taken`; **cero** citas creadas; recepción escoge alternativa | ninguna bandera `force`/`allow_overlap`, ningún permiso que lo salte, ningún sobrecupo |
| Reactivación `canceled`/`no_show → scheduled` sobre hueco ocupado | `400 slot_taken`; la cita sigue en su estado terminal; hay que programar de nuevo | nada se desplaza ni se reubica automáticamente |

Espera, sobrecupo y múltiples recursos son **feature separada** (plan §11).

**Secuencia obligatoria de F0·b** (no es negociable: PostgreSQL no admite añadir
una restricción de exclusión `NOT VALID`):

1. Correr `audit_appointment_overlaps` en cada entorno (incluida producción).
2. **Remediación humana** por clínica de lo que reporte. No se corrige solo:
   cancelar o mover una cita real sin que nadie lo decida es peor que el solape.
3. Aplicar la migración en ventana de deploy — construir el índice GiST toma un
   lock fuerte de la tabla (segundos con el volumen del piloto).
4. Volver a correr la auditoría post-deploy.

### Verificación de la fase

- P0-4 falla si alguien borra la declaración del campo (el fail-open invisible).
- P1-14 (`TransactionTestCase`, PostgreSQL) prueba que hay **lock**, no solo
  comparación: dos escrituras concurrentes con el mismo `expected_state` → una
  escribe, la otra recibe 409.
- P0-18 (`TransactionTestCase`, PostgreSQL) prueba que el cupo es una garantía:
  dos creaciones y dos reprogramaciones concurrentes al mismo hueco → una sola
  cita activa. Incluye la reactivación `canceled → scheduled`.
- P0-20 prueba el comportamiento aprobado sin concurrencia: `walk-in` sobre un
  veterinario ocupado y reactivación sobre un hueco ocupado → `slot_taken`, cero
  escrituras, cero `AppointmentStatusChange`; con el hueco libre, ambas siguen
  funcionando como hoy. También ancla que **no existe** ninguna bandera de
  forzado.
- P1-23 prueba que `DELETE` respeta la precondición y **no** genera una segunda
  `AppointmentStatusChange` bajo conflicto.
- P2-4 protege al frontend actual: sin `expected_state`, comportamiento idéntico.

### Riesgos de la fase

- Envolver `update()` en una transacción con lock cambia el perfil de
  concurrencia de un endpoint que usa el frontend. Mitigación: el lock es de una
  fila y de duración de request; medir si la agenda tiene picos de escritura
  concurrente sobre la misma cita (no debería).
- `update_status` mueve una lectura dentro del `atomic()`: revisar que los
  toggles (`auto_create_medical_record`) y el `AppointmentStatusChange` sigan en
  el mismo orden. Hay tests existentes de estado que deben quedar en verde.
- **INV-D cambia comportamiento el día 1**, a diferencia de INV-A. Los dos casos
  —**atención sin cita** con el veterinario ocupado y **reactivación** de una
  cita cancelada cuyo hueco ya se dio a otro— están **aprobados** (§9.14,
  §9.15), así que no hay nada que ratificar durante la implementación. Lo que sí
  hay es una **tarea de comunicación**: avisar a recepción antes del deploy y
  dejar claro el gesto siguiente (escoger otro veterinario u otro horario;
  programar de nuevo). El primer rechazo en mostrador no puede ser la forma en
  que se enteran.
- La migración puede **fallar** si la limpieza del paso 2 quedó incompleta. Es
  el comportamiento correcto (fail-closed), pero conviene correr la auditoría el
  mismo día del deploy, no una semana antes.

---

## 4. F1 — Identidad de expediente por teléfono (INV-C) y `require_new_owner`

**Objetivo**: que el dominio pueda **negarse** a reutilizar un `Owner` por
teléfono —de forma atómica, no optimista— y que un teléfono con varios
expedientes falle cerrado en vez de elegir uno (§4.3 C5, §4.7, §4.8).

La revisión de plan rechazó la versión anterior de esta fase con razón: añadir el
flag dentro del `atomic()` no lo hace atómico si nada impide que dos
transacciones observen a la vez la ausencia de la fila. El trabajo real de F1 es
**construir esa serialización**, y el flag es su consumidor.

**El alcance de F1 se amplió dos veces.** Primero por el hallazgo Z (2ª
revisión): faltaban `POST /api/pets/` —que resolvía identidad con **su propia
regla**, por `(nombre, teléfono)`— y la **edición del teléfono de `Owner`**.
Después por la **revisión OCR**, que encontró el punto ciego de categoría: el
inventario cubría *escrituras*, y **los lectores de identidad del agente**
(`agent/services.py`) comparan un valor normalizado contra `Owner.phone` en
crudo. Dos expedientes que solo coinciden tras normalizar dan **una** coincidencia
cruda → el agente vincula la `ContactIdentity` a esa fila. Es una elección
automática entre duplicados históricos: lo que INV-C prohíbe.

F1 no está completa sin las cinco familias del inventario §4.7.4
(**A** crear `Owner` · **B** asociar `Pet` · **C** mutar `phone` · **D**
normalizar · **E** *leer* identidad). Ese inventario es su criterio de
aceptación.

**Respuesta explícita a la pregunta de la revisión OCR**: sí — «`patients`, el
importador y el agente convergen» **incluye** la creación de contacto y el
rematch de `agent/services.py` (filas E1 y E2). Y sí, `phone_normalized = NULL`
es la representación prevista para el `Owner` genérico, backfill incluido
(§4.12).

### F1·a — El teléfono normalizado y su servicio (dominio `patients`)

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/patients/models.py` | Campo de **teléfono normalizado** persistido en `Owner` (10 dígitos nacionales; **`NULL`** si no hay teléfono, si no alcanza a 10 dígitos y **siempre** para `is_generic=True`), derivado siempre por el dominio + índice `(organización, teléfono normalizado)` (§4.7.2, §4.12). Es la **clave de lectura y de escritura**: `ContactIdentity.phone_normalized` ya existe y la unión es normalizado ↔ normalizado |
| `backend/apps/patients/migrations/0018_*` *(nuevo)* | Migración **aditiva**: columna + índice + backfill por lotes derivado del `phone` existente. **Los genéricos reciben `NULL`**, sin pasar por la normalización. No borra ni modifica `phone`. Sin restricción única (§4.7.1: incompatible con INV-C) |
| `backend/apps/core/validators.py`, `patients/utils.py`, `organizations/signals.py` | El *bypass* de la validación de teléfono de cliente (que rechaza rellenos como `0000000000`) queda acotado a **`is_generic=True`** y solo ahí; el genérico conserva su `phone` de texto pero **no** deriva clave (§4.12) |
| `backend/apps/patients/services.py` *(nuevo)* | **Fuente única**, con **tres operaciones**: (1) *resolver expediente por teléfono* — lock de aviso transaccional sobre `(organización, teléfono normalizado)`, conteo bajo el lock, desenlaces `created`/`reused`/`owner_exists`/`owner_ambiguous` (§4.7.3); (2) *cambiar el teléfono de un expediente* — lock de **las dos claves** (anterior y nueva) en **orden total** por la clave normalizada, conteo y escritura en el mismo bloque (§4.10); (3) **modo lectura** — mismos desenlaces, **sin lock y sin escribir**, para los lectores de identidad del agente y las tres pasadas del importador (§4.11, §4.8). El conteo **excluye los `Owner` genéricos y las filas sin clave normalizada**. PostgreSQL-only: falla ruidosamente en otro motor, **nunca** degrada a no-op |
| `backend/apps/core/validators.py` | La normalización del servicio **deriva de `validate_mx_phone`/`phone_digits`** (D1 del inventario). No se escribe una segunda; las de `imports` y `agent` convergen a ella |
| `backend/apps/patients/management/commands/audit_owner_phone_duplicates.py` *(nuevo)* | Detección de duplicados históricos por organización (exit 0/1/2). **Diagnóstico, no remediación**: no fusiona ni elige (§4.8) |
| `backend/apps/patients/tests/test_owner_phone_identity.py` *(nuevo, `TransactionTestCase`)* | P0-16, P0-17, **P0-21…P0-25**, **P0-28**, P2-12, P2-14, P2-15 — **PostgreSQL** |
| `backend/apps/agent/tests/test_identity_readers.py` *(nuevo, `TransactionTestCase`)* | **P0-26** — los lectores de `agent/services.py` (creación de contacto y rematch) sobre la clave normalizada, con un duplicado histórico distinguible **solo tras normalizar**. **PostgreSQL** |
| `backend/apps/imports/tests/` | **P0-27** — paridad preview ↔ dry-run ↔ commit ante un duplicado histórico |

### F1·b — Los consumidores del servicio (inventario §4.7.4)

Cada fila **usa el servicio** o queda **excluida con evidencia**. No hay
categoría implícita.

| Archivo / vía | Familia | Cambio previsto |
|---|---|---|
| `backend/apps/appointments/views.py` — `create_with_patient` | A1·B2 | Sustituye `Owner.objects.get_or_create(phone=…)` por el servicio; acepta `require_new_owner` (bool, default `False`); `409 owner_exists` (un expediente) y `409 owner_ambiguous` (dos o más, **también sin el flag**) sin crear nada. Sin el flag y con cero o un expediente, comportamiento actual intacto |
| `backend/apps/patients/views.py` — `OwnerViewSet.perform_create` | A2 | El alta manual pasa por el servicio (si no, una alta de recepción concurrente crea el duplicado que el agente acaba de evitar) |
| `backend/apps/patients/serializers.py` — **`PetSerializer.create`** | A3·B1 | **P0 del hallazgo Z**: deja de resolver el cliente con `get_or_create(name, phone, organization)`. Dos modos explícitos (§4.9): **referencia** (cliente ya elegido por `public_id`) y **alta** (datos del cliente → servicio, bajo el lock). Resolución del `Owner` y creación de la `Pet` en **una sola transacción**. Desenlaces: 0 → crea; 1 con nombre coincidente → reutiliza (igual que hoy); 1 con nombre distinto → `409 owner_exists` **con el candidato**; ≥2 → `409 owner_ambiguous` |
| `backend/apps/patients/serializers.py` — **`PetSerializer.update`** | C2 | **P0 del hallazgo Z**: la escritura anidada `owner.phone = …; owner.save()` pasa por la operación de cambio de teléfono (§4.10). Los dos `save()` sueltos actuales quedan dentro del mismo `atomic()`: un `409` no deja ni el teléfono cambiado ni los campos de la mascota guardados |
| `backend/apps/patients/serializers.py` — `OwnerSerializer` (PATCH/PUT) | C1 | Mismo tratamiento que C2. La comprobación **no** vive en `validate()` — DRF valida y guarda en pasos separados, y esa es justo la ventana que §4.10 elimina |
| `backend/apps/patients/serializers.py` — `PHONE_REGEX` | D4 | Se reemplaza por `validate_mx_phone`: hoy es una tercera regla de formato, más laxa (no rechaza rellenos) |
| `backend/apps/imports/services.py` — `_resolve_owner` / `_create_owner` | A4·B3·C3 | Usa el servicio por fila. El `.first()` sobre duplicados **desaparece**: pasa a error de fila `owner_ambiguous` (la fila se salta y se reporta — su política vigente). No muta el teléfono de owners existentes (C3 queda excluida) |
| `backend/apps/imports/services.py` — pasadas de **validación/preview** y de **dry-run** | E3 | **Ajuste OCR**: son **dos lecturas más**, distintas de la del commit, y también usan `.first()`. Pasan al modo lectura del servicio, con los mismos cuatro desenlaces: el preview **no puede mostrar una reutilización que el commit rechazaría**; la fila ambigua aparece como omitida desde el principio y el conteo de importables ya la excluye (§4.8) |
| **`backend/apps/agent/services.py` — creación de `ContactIdentity`** | E1 | **Bloqueador OCR**: hoy compara el valor normalizado del `wa_id` contra `Owner.phone` **crudo**. Pasa al modo lectura del servicio sobre `phone_normalized`, tenant-scoped y con `is_generic=False`. 0 → `unknown`; 1 → `phone_match` (igual que hoy); ≥2 → `is_ambiguous=True` **sin vincular**, sin subir nivel y **sin tocar `auto_rematch_blocked`** (§4.11) |
| **`backend/apps/agent/services.py` — `_rematch_owner`** | E2 | **Bloqueador OCR**: mismo patrón, y corre en **cada** mensaje de un contacto `unknown`. Mismo tratamiento que E1. El flag `auto_rematch_blocked` sigue gateando la vía **y nunca se limpia aquí** |
| `backend/apps/agent/tools.py` — `_wa_id_to_local10`; `agent/services.normalize_wa_id` | D2 | Convergen con la normalización del dominio: el mismo número debe producir la misma clave. Es la razón de persistir el campo — y la ausencia de esa convergencia fue el bypass de lectura |
| `backend/apps/patients/views.py` — `OwnerViewSet ?search` | E4 | **Excluida con evidencia** (búsqueda para que una persona elija, no resolución de identidad), con una corrección: añadir `is_generic=False` para que el genérico no aparezca como candidato |
| `patients.utils.get_or_create_generic_patient`, `organizations.signals` | A5 | **Excluidos con evidencia**: `is_generic=True`, protegidos por su `UniqueConstraint`, y el conteo del servicio excluye genéricos → su teléfono de relleno no colisiona (P2-15) |
| `seed_demo_clinic`, `agent_eval` | A6 | **Excluidos con evidencia**: siembra single-writer sobre tenants propios |
| `appointments.assign_patient` | B5 | **Excluida con evidencia**: cambia `Appointment.pet`, no `Pet.owner`; no resuelve ningún `Owner` |
| `patients/admin.py` | C4 | **Excluida con evidencia**: `Owner` no está registrado en el admin. Queda anotado en el ADR: registrarlo lo devuelve a C1 |
| `backend/apps/appointments/tests/test_preconditions.py` | — | P0-6ᵃ, P0-9ᵇ, P2-5 |
| `frontend/src/pages/pets.jsx`, `frontend/src/api/pets.js` | A3·C2 | Manejo del `409 owner_exists` con candidato: preguntar «¿es este cliente?» y reenviar en **modo referencia**; `409 owner_ambiguous` → mensaje de dato por ordenar. Convenciones de `docs/modules/frontend.md` (distinguir por `code`, `handleFormError`, doble-submit bloqueado) |

### Notas de diseño (ya decididas, no reabrir)

- El flag es **opt-in**: recepción y el registro rápido siguen reutilizando el
  expediente cuando hay exactamente uno, y es correcto — el staff está
  verificado por su sesión (§4.4).
- `owner_ambiguous` **no** es opt-in: si el dominio no sabe cuál es el
  expediente, ningún actor puede fingir que sí (§4.7.3).
- **El teléfono localiza, no autoriza, también en `/api/pets/`**: asociar una
  mascota a un expediente exige que el usuario lo haya **elegido** (modo
  referencia), no que el número coincida (§4.9).
- La comprobación vive dentro de la transacción y bajo el lock a propósito: una
  pre-consulta desde el llamador sería TOCTOU, y por `?search` sería además
  `icontains` acotado a 20 filas (`patients/views.py`).
- **Ninguna migración fusiona ni borra duplicados.** Los que existan se
  reportan y los ordena una persona (§4.8, INV-C).
- **El flujo de staff aprobado no cambia**: cliente nuevo → crea; mismo cliente
  → reutiliza; corregir un teléfono mal capturado sigue siendo posible desde
  Clientes y desde la ficha de la mascota. Lo nuevo es que el caso ambiguo
  pregunta en vez de inventar (P2-14 lo ancla).

### Riesgos de la fase

- El backfill toca todas las filas de `Owner`. Va por lotes y es derivado (no
  destructivo): si sale mal, se recalcula.
- Una clínica con duplicados verá `owner_ambiguous` en altas que hoy «funcionan»
  reutilizando un expediente arbitrario. Es el resultado pedido, pero hay que
  avisarlo con el reporte de la auditoría en la mano.
- Cambiar el importador exige correr su suite completa: es la vía con más
  volumen por transacción y la única que crea `Owner` sin teléfono. Además, su
  conteo de filas importadas bajará en clínicas con duplicados (pasan a
  reportarse como ambiguas).
- **El cambio de teléfono es la operación con más riesgo de deadlock** de todo
  el Item: dos cambios cruzados (A→B y B→A) sin orden total se bloquean
  mutuamente. El orden total de claves es obligatorio y P0-22 lo prueba.
- `PetSerializer` es una superficie compartida por el alta y la edición de
  mascota; envolverla en una transacción cambia el perfil de un endpoint muy
  usado por recepción. La red es P2-14 (iron rule).
- **Los lectores del agente cambian conducta en el caso ambiguo**: un contacto
  que hoy queda vinculado (porque solo una fila coincide en crudo) pasará a
  quedar `is_ambiguous` cuando dos expedientes coincidan tras normalizar. Es la
  conducta correcta —el vínculo actual apunta a un expediente elegido a
  ciegas—, pero para esa clínica el cliente deja de ser reconocido hasta que
  alguien ordene el dato. Se despliega con el reporte de duplicados a la vista.
- **El backfill y el `NULL` del genérico van juntos**: si el backfill
  normalizara `'0000000000'`, el genérico entraría en la deduplicación de todas
  las organizaciones a la vez. P0-28 es el gate, no una comprobación opcional.
- El modo lectura **no** toma el lock (§4.11): un alta concurrente puede volver
  ambiguo lo que se acaba de leer como único. Aceptado y documentado — el
  `phone_match` no autoriza nada por sí solo y el siguiente mensaje reevalúa.

---

## 5. F2 — El agente consume las garantías

**Objetivo**: que toda escritura del agente viaje con su precondición y que el
alta revalide identidad (§3.2, §4.3).

### Archivos previstos

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/agent/tools.py` | **Staging**: `create_appointment` añade `pet_public_id` al staged; `cancel_appointment` añade `expected_status`/`expected_date`/`expected_start_time`; `reschedule_appointment` añade `from_date`/`from_start_time`/`expected_status` (§6.1). **Commits**: `commit_cancel_*` y `commit_reschedule_*` envían `expected_state` y mapean `409` → `appointment_changed` / `already_done` en vez de caer en `tool_failure`; `commit_register_*` aplica C1–C5 (re-lectura fresca de `ContactIdentity`, `owner_id`, `is_ambiguous`, teléfono recomputado, `require_new_owner`) |
| `backend/apps/agent/planner.py` | Ramas nuevas en `_commit_pending` para `appointment_changed`, `already_done`, `identity_changed`, `owner_exists` y `owner_ambiguous`, cada una con su plantilla. **Y el cambio estructural de §5.5.4**: `_commit_pending` deja de llamar a `clear_pending` a ciegas justo después del handler; la limpieza pasa a cada desenlace, y las ramas que suspenden lo hacen dentro de la transición atómica |
| `backend/apps/agent/confirmations.py` (o `agent/services.py`) | **Helper idempotente de suspensión** (§5.5.4): bajo un solo `transaction.atomic()` + `select_for_update()` de `Conversation`, mueve el staged íntegro a `flow['suspended']` con `suspension_id`/`suspended_at`/`handoff_reason`, crea o retiene el `HumanHandoff` de identidad y elimina el pendiente — **un commit**. `escalate_to_human` pasa a usarlo también, para que no queden dos formas de suspender |
| `backend/apps/agent/executor.py` | **Separación de los 409 de negocio (§5.4)**: cada llamada declara sus desenlaces de negocio esperados; los declarados generan `AGENT_TOOL_BUSINESS_CONFLICT` (redactado) en vez de `AGENT_TOOL_HTTP_ERROR`, siguen creando su fila de `ToolExecution` y no cuentan como fallo de integración. Lo no declarado no cambia |
| `backend/apps/agent/tests/test_write_tools.py` | P0-2, P0-3, P0-5, P0-6ᵇ, P0-8, P0-10, P0-19, P1-12, P1-13, P2-6 |
| `backend/apps/agent/tests/test_planner.py` | P1-11, P2-7, P2-11 |
| `backend/apps/agent/tests/test_executor.py` | P2-13 |
| `docs/modules/agent.md` | Los `client_error` nuevos, su comportamiento y la clasificación de eventos |

### Orden interno sugerido

1. Snapshot (staging) — sin efecto observable todavía, seguro de mergear.
2. Clasificación de desenlaces de negocio en el executor (§5.4): habilita medir
   los pasos siguientes sin ensuciar alertas.
3. Commits de `cancel`/`reschedule` con precondición + mapeo del 409.
4. Helper de suspensión atómica + adopción por `escalate_to_human`, **con la
   regresión P2-11 en verde antes de tocar el planner**.
5. Commit de `register` con C1–C5 y las ramas `owner_exists`/`owner_ambiguous`.
6. Ramas del planner + plantillas (§9.8 puede cambiar los textos; el
   comportamiento no).

### Riesgos específicos

- El `already_done` de cancelación depende de que el dominio distinga «ya está
  como querías» de «conflicto». Si F0 no lo expone con claridad, el agente
  volverá a escalar por nada — que es el bug que P0-3 cubre. Validar el contrato
  del 409 con F0 antes de escribir la rama.
- **Mover la limpieza del pendiente es la parte delicada de esta fase.** Es un
  cambio en el camino que recorren todos los desenlaces, no solo los nuevos. La
  red es P2-11 (iron rule): los desenlaces existentes deben dejar `flow`
  exactamente como hoy. Escribirla **antes** del cambio, no después.
- El helper de suspensión lo usan dos rutas (escalada ordinaria e identidad). Si
  se implementa solo para la segunda, queda la primera con el mismo bug que la
  revisión describió; por eso la adopción por `escalate_to_human` está en el
  alcance de esta fase, no en «más adelante».

---

## 6. F3 — Servicio de release

**Objetivo**: retomar la propuesta suspendida sin perder nada, sin pisar al
worker y sin ejecutar nada por un «sí» viejo (§2, §5, §7).

### Archivos previstos

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/agent/policy.py` | `escalate_to_human` escribe `suspension_id`, `suspended_at` y `handoff_reason` en `flow['suspended']` a través del helper atómico de F2 (§6.1). `nudge_abandoned_flows` reclama el derecho a enviar bajo lock, en vez de leer-y-enviar (§0-G) |
| `backend/apps/agent/services.py` *(o `views.py`)* | Servicio de release (§5.6): **R1** con `select_for_update` + respeto del lease (`409 turn_in_progress`) + captura del **testigo** (suspensión, estado, claim, lease, id del hand-off abierto); **R2** chequeo de dominio **fuera** del lock vía `ToolExecutor` de la org de la conversación; **R3** compare-and-set del testigo completo — si difiere, **no muta nada**, reintenta el ciclo una vez y luego `409 release_conflict` con su `reason`. Validación de forma del `suspended` (legacy vs. corrupto, §7) |
| `backend/apps/agent/views.py` | `release_conversation` delega en el servicio; resuelve **el hand-off identificado en R1**, no «el último abierto», y solo si **sigue abierto** (mismo id **y** `resolved_at` nulo en R3). `claim_conversation` y `close_conversation` pasan a serializarse sobre la misma fila (`select_for_update` + comparación explícita), sin lo cual el testigo no significa nada |
| `backend/apps/agent/tests/test_inbox_api.py` | P0-1, P1-2, P1-5, P1-8, P1-9, P2-1, P2-2, P2-3 |
| `backend/apps/agent/tests/test_policy.py` | P1-10 (matriz por tool), P1-4 |
| `backend/apps/agent/tests/test_release_concurrency.py` *(nuevo, `TransactionTestCase`)* | P1-6, P1-7, **P1-19, P1-20, P1-21, P1-22** — **PostgreSQL, no SQLite** |
| `docs/modules/agent.md` | Ciclo de vida de `flow['suspended']`, del release y del `409 release_conflict` |
| `docs/system-module-operations.md` | Sección de la bandeja: liberar, reclamar y cerrar tienen ahora precondiciones, serialización y efectos |
| `docs/modules/frontend.md` | La bandeja debe manejar `release_conflict` recargando el caso y volviendo a preguntar; **nunca** reintentando en bucle |

### Interleavings que esta fase debe cubrir (hallazgos R y T)

Los tres son pruebas, no notas: `R1 → nueva suspensión → R3`,
`R1 → el worker toma el lease → R3` y `R1 → otro staff reclama → R3`. En los
tres, el resultado correcto es **ninguna mutación** y una respuesta de
reintento/conflicto. Ninguna transición nueva puede liberarse, sobrescribirse ni
perderse.

### Nota de secuencia

F3 es la fase que *usa* todo lo anterior. Si por planificación tuviera que
adelantarse a F2, **no debe mergearse**: restaurar propuestas sin precondición
en el commit reintroduce el P0 de la revisión de seguridad. Y F4 **no se
despliega** hasta que F3 esté en producción (§2).

---

## 7. F4 — Caso de verificación de identidad (FLUJO-C)

**Objetivo**: que el `409 owner_exists` / `owner_ambiguous` tenga salida dentro
del sistema, con verificación humana, RBAC y auditoría (§5.5).

**Dependencia de despliegue: F3.** No es una preferencia de orden — sin el
release de F3, autorizar correctamente y liberar deja la intención congelada
(§2). Hasta que F3 esté desplegada, los endpoints y la UI de F4 permanecen
feature-gated.

### Backend

| Archivo | Cambio previsto |
|---|---|
| `backend/apps/agent/models.py` | Modelo nuevo `ContactIdentityVerification` (append-only): `organization`, `contact`, `owner_candidate`, `conversation`, **`handoff`**, `decision`, `evidence_kind`, `evidence_note`, `actor`, `created_at` (§5.5.3). El invariante de organización (todas las FKs en el mismo tenant) se valida **en el modelo**, no solo en la vista |
| `backend/apps/agent/migrations/0015_contact_identity_verification.py` *(nuevo)* | Migración aditiva; sin backfill (no hay datos previos que interpretar) |
| `backend/apps/agent/identity.py` | `link_staff_verified(contact, owner, actor)` — cuarta y única vía nueva que eleva a `staff_verified`, fija `linked_via='staff'` y limpia `auto_rematch_blocked` |
| `backend/apps/agent/views.py` | Dos endpoints: registrar verificación (aprobada/rechazada) y autorizar el vínculo. Ambos con `agentinbox.identity_verify` y `_get_conversation` (tenant). **Todo se deriva del servidor** (organización, contacto, conversación, actor); el candidato se resuelve **solo** con `Owner.objects.for_organization(conversation.organization)` por `public_id`. El de vínculo lockea `ContactIdentity` **y** el `HumanHandoff`, y exige que la **última** verificación sea `approved`, del **mismo** candidato y del **mismo** hand-off abierto (§5.5.2) |
| `backend/apps/agent/urls.py` | Dos rutas nuevas bajo `/api/inbox/conversations/<pk>/` |
| `backend/apps/agent/serializers.py` | Serializer del registro de verificación; la conversación expone el caso abierto y **qué pidió el cliente** (staged proyectado, sin volcar el `flow` crudo) |
| `backend/apps/core/permissions_codes.py` | Código nuevo `agentinbox.identity_verify` + concesión a ADMIN (§5.5.2) |
| `backend/apps/agent/tests/test_inbox_api.py` | P0-11, P0-12, P0-13, P0-14, **P0-15**, P1-18, **P1-24**, P2-8, P2-9 |
| `backend/apps/agent/tests/test_write_tools.py` | P0-10 y P0-19 llegan de F2 (el caso se crea y la intención se preserva); F4 los **reusa como precondición**, no los reescribe |
| `backend/apps/agent/tests/test_identity.py` | P1-15, P2-10 |
| `backend/apps/agent/tests/test_release_concurrency.py` | P1-16 (dos autorizaciones simultáneas) |

### Frontend (Inbox)

| Archivo | Cambio previsto |
|---|---|
| `frontend/src/api/inbox.js` | Dos funciones nuevas (verificar, autorizar), siguiendo el patrón existente de `resetContactIdentity`/`unlinkFamily` |
| `frontend/src/pages/inbox/index.jsx` | Banner del caso con lo que pidió el cliente; modal de verificación (tipo de evidencia + nota) y acción de autorizar/rechazar. `useConfirm` para autorizar (transición con peso operativo), `handleFormError`, `apiError`, doble-submit bloqueado — convenciones de `docs/modules/frontend.md` |
| `frontend/src/pages/inbox/inbox.module.css` | Estilos del banner/modal, solo tokens |
| `frontend/src/pages/inbox/*.test.jsx` *(nuevo)* | El CTA no se muestra sin `can('agentinbox.identity_verify')`; el flujo verificar→autorizar deshabilita botones mientras corre; el rechazo no ofrece autorizar |
| `docs/modules/frontend.md` | El código de error nuevo y las acciones de la bandeja |
| `docs/modules/agent.md` | El caso, sus estados y quién puede actuar |

### Reglas de esta fase (no negociables, vienen de §5.5)

- Verificar y autorizar son **dos acciones distintas**; no unificarlas en un
  endpoint con booleano.
- La evidencia es **externa al teléfono**: el enum de `evidence_kind` no ofrece
  ninguna opción basada en el número.
- El sistema **registra** el juicio humano; no lo valida ni lo puntúa.
- **Nada de automatización de la verificación** (§5.5.6). P2-10 es el gate.
- El permiso es **nuevo**, no se reutiliza `agentinbox.config`; `seed_permissions`
  lo propaga en el deploy.
- **Una aprobación vale para un candidato y un caso, y para nada más** (§5.5.2):
  aprobación de A no autoriza a B; un hand-off cerrado invalida lo aprobado bajo
  él; cross-tenant es 404 **sin** filas de auditoría ni vínculo.

### DoD documental de F4 (coordinación con Item 1, hallazgo Y)

Las dos correcciones son parte del mismo PR, no un ticket posterior. Sin ellas,
Item 1, su documentación operativa y el código describirían un número distinto
de vías de promoción, y la revisión futura del bloqueo `auto_rematch_blocked`
partiría de una frase falsa:

1. `docs/whatsapp-agent-identity-context-fixes-plan.md` §Item 1 — «se limpia en
   `identity._promote`, `identity.link_self_registered` y `identity.link_family`
   — **las tres únicas** funciones que elevan a `confirmed_in_chat`/
   `staff_verified`» pasa a **cuatro**, nombrando `link_staff_verified` y su
   condición (verificación humana registrada + permiso).
2. Docstring de `reset_contact_identity` (`agent/views.py`) — hoy describe el
   reset como irreversible salvo por el reto triple; debe nombrar la vía
   auditada de FLUJO-C como la forma legítima de deshacerlo.
3. **P2-8 sigue siendo regresión bloqueante**: una verificación de staff limpia
   `auto_rematch_blocked` **solo** por la vía auditada.

---

## 8. F5 — Cierre de INV-A (fuera de Item 2)

Depende de la decisión de producto §9.9 (calendario). Se lista para que no se
pierda: sin ella, INV-A solo protege al agente.

| Paso | Archivos previstos |
|---|---|
| El frontend envía la precondición | `frontend/src/api/appointments.js`, `frontend/src/pages/appointments.jsx`, `frontend/src/components/dashboard/AppointmentQuickModal.jsx` |
| La UI maneja el 409 (recargar + volver a preguntar, nunca reintentar) | los mismos + `frontend/src/utils/apiError.js` si hace falta afinar el mensaje |
| El frontend deja de usar `DELETE /appointments/<id>/` y pasa a `/status/` | `frontend/src/api/appointments.js` y sus consumidores |
| La precondición pasa a **obligatoria** (`400 precondition_required`) y `DELETE` responde `410 endpoint_sunset` | `backend/apps/appointments/serializers.py`, `views.py` + ventana de deprecación (Sunset RFC 8594) y entrada en el ADR p57 |

---

## 9. Trabajo transversal

### Migraciones

| Fase | Migración | Naturaleza | Riesgo / precaución |
|---|---|---|---|
| F0·b | `appointments/0014_*` — extensión `btree_gist` + restricción de exclusión de no-solapamiento | **Estructural, no reversible en caliente.** Cubre todas las filas activas | **Falla si hay solapes históricos** (PostgreSQL no admite `NOT VALID` en exclusiones). Exige la auditoría + limpieza previa de plan §3 (F0·b) y ventana de deploy: construir el índice GiST toma un lock fuerte |
| F1·a | `patients/0018_*` — teléfono normalizado + índice + backfill por lotes | Aditiva y derivada; no toca `phone` | Backfill sobre toda la tabla `Owner`. Por lotes; recalculable. **Sin restricción única** (§4.7.1) |
| F4 | `agent/0015_contact_identity_verification` | Aditiva, tabla nueva, sin backfill | No bloquea escrituras existentes |

`expected_state` y `require_new_owner` **no** se persisten: viajan en el request
(§6.2). Lo que sí toca el esquema es todo lo demás de arriba — la revisión de
plan tenía razón en que el mapa anterior («ninguna otra fase toca el esquema»)
era falso en cuanto la garantía deja de ser una lectura previa.

### Comandos de auditoría (quedan en el repositorio)

| Comando | Fase | Para qué |
|---|---|---|
| `audit_appointment_overlaps` | F0·b | Pre-migración **y** red de seguridad permanente de INV-D |
| `audit_owner_phone_duplicates` | F1·a | Ver los duplicados que INV-C tolera; nunca los corrige |

Ambos siguen el patrón de `audit_stock_integrity` (exit 0/1/2) para poder
colgarse de un cron sin inventar convenciones nuevas.

### Permisos

`agentinbox.identity_verify` se añade en F4 a `PERMISSION_CODES` y al rol ADMIN.
`seed_permissions` corre en cada deploy, así que no hace falta paso manual —
pero sí verificar en staging que un ADMIN existente lo recibe sin recrear roles.

### Documentación (regla de `docs/CLAUDE.md`: cambian contratos)

| Documento | Fase |
|---|---|
| ADR p57 (nuevo) | F0 (se crea, con INV-A e INV-D), F1 (INV-C + mapa de migraciones), F4 (FLUJO-C) |
| `docs/modules/appointments.md` | F0 (matriz de mutaciones, `expected_state`, 409, no-solapamiento, deprecación de `DELETE`), F1 (`require_new_owner`, `owner_ambiguous`) |
| `docs/modules/agent.md` | F2 (desenlaces nuevos + clasificación de eventos), F3 (release y `release_conflict`), F4 (el caso) |
| `docs/modules/frontend.md` | F3 (manejo de `release_conflict`), F4, F5 |
| `docs/modules/patients.md` | F1 — teléfono normalizado, servicio único (resolver + cambiar teléfono), `owner_ambiguous`, **el contrato nuevo de `POST /api/pets/`** (modos referencia/alta) y el del cambio de teléfono, comando de auditoría, e **inventario de vías** (§4.7.4) como contrato del módulo |
| `docs/modules/imports.md` | F1 — el importador comparte la resolución de expediente; el `.first()` desaparece de las **tres** pasadas y el preview muestra el mismo desenlace que la escritura |
| `docs/modules/agent.md` | F1 — la creación de contacto y el rematch resuelven por clave normalizada; qué significa `owner_ambiguous` para un contacto (sin vínculo, sin promoción, sin tocar `auto_rematch_blocked`) |
| `docs/modules/patients.md` (§genérico) | F1 — el `Owner` genérico: `phone_normalized = NULL`, excluido de búsqueda, locks, deduplicación e identidad |
| `docs/modules/frontend.md` | F1 — `owner_exists` con candidato en el alta de mascota y `owner_ambiguous`; qué pregunta la UI y qué **no** decide por el usuario |
| `docs/system-module-operations.md` §2 (alta de cliente), §3 (cita) y bandeja | F0, F1, F3, F4 |
| `docs/system-reference.md` §1 (diagnóstico), §3 (invariantes INV-A…INV-D), §4 (reglas que nunca se rompen) | F0, F1, F3, F4 |
| `docs/whatsapp-agent-identity-context-fixes-plan.md` (Item 1) | **F4 — DoD**: «las tres únicas funciones» → cuatro (§4.4) |
| Docstring de `reset_contact_identity` | **F4 — DoD**: nombrar la vía auditada de FLUJO-C |

### Entorno de pruebas

La revisión de seguridad no pudo ejecutar la suite en este worktree
(`ModuleNotFoundError: No module named 'django'`). **Antes de F0**: dejar el
entorno operativo, con **PostgreSQL**, y correr la línea base de `agent/` y
`appointments/` en verde. La lista completa de pruebas que exigen PostgreSQL
está en plan §12.3; ninguna de ellas vale en SQLite, donde los tres mecanismos que
este Item adopta (lock de aviso, restricción de exclusión, compare-and-set bajo
`select_for_update`) no existen o son no-ops.

---

## 10. Definition of done por fase

Una fase está terminada cuando, además de su código:

1. Sus pruebas P0 pasan y son **bloqueantes** en CI.
2. La suite completa de `agent/` y `appointments/` queda en verde — más
   `patients/` e `imports/` en F1. **Antes del merge de F1, la línea base de los
   cuatro (`appointments`, `patients`, `imports`, `agent`) corre en PostgreSQL**,
   no solo la de los módulos tocados: el servicio de identidad los atraviesa.
3. La documentación de la tabla de plan §9 está actualizada **en el mismo PR** — un
   contrato que cambia sin su documento es deuda desde el minuto uno.
4. Ningún test existente se borró ni se debilitó para pasar (regla del proyecto).
5. Las regresiones marcadas *iron rule* (P2-3, P2-4, P2-5, P2-6, **P2-11**)
   siguen verdes.
6. Las pruebas de concurrencia de la fase corrieron **en PostgreSQL** (plan §12.3).
7. Las migraciones estructurales (plan §3 F0·b, §4 F1·a) llevan su auditoría previa
   ejecutada y su resultado adjunto al PR.

---

## 11. Lo que este plan NO incluye

- **Cualquier automatización de la verificación de identidad** (§5.5.6): no es
  una fase futura de este plan; sería un diseño nuevo con su propio ADR.
- **Fusión de expedientes duplicados**, automática o asistida (INV-C, §4.8).
- **Restricción única de teléfono por organización**: descartada, no aplazada
  (§4.7.1).
- **Capacidad o concurrencia configurable por clínica** (varias citas simultáneas
  por veterinario): fuera de alcance por §9.13.
- **Lista de espera, sobrecupo y múltiples recursos** (varios consultorios,
  agendas paralelas): **feature separada** con su propio diseño y ADR (§9.14,
  §9.15). No es una fase posterior de este plan.
- **Cualquier bandera de forzado del solape** (`force`, `allow_overlap`, permiso
  que lo salte): no existe y no se añade en Item 2.
- Tope duro de antigüedad de la suspensión (§9.4).
- Mensaje proactivo al descartar por «ya resuelto» (§9.5).
- Tool de alta de mascota para cliente conocido (§9.10).
- Visibilidad de la propuesta congelada en hand-offs que no son de identidad
  (§9.11).
- Claves de idempotencia para los PATCH de cancelar/reprogramar: la precondición
  cubre el caso (§6.3).

---

## 12. Cierre

### 12.1 Decisiones cerradas (no se reabren en implementación)

| # | Decisión | Origen |
|---|---|---|
| 1 | **INV-A** — precondición atómica de estado como garantía de dominio, para cualquier actor; opt-in hasta F5 | §9.1 |
| 2 | **INV-B** — el teléfono localiza, no autoriza: escribir sobre un `Owner` existente exige identidad verificada | §9.2 |
| 3 | **INV-C** — un teléfono normalizado ⇒ como máximo un expediente. Con dos o más: `owner_ambiguous` y escalada. **Nunca** se fusiona ni se elige | §9.12 (2ª ronda) |
| 4 | **INV-D** — un veterinario no tiene dos citas activas solapadas; garantía atómica en PostgreSQL, para todos los actores. Capacidad configurable, fuera de alcance | §9.13 (2ª ronda) |
| 4a | **Atención sin cita sin excepción** — un `walk-in` no puede crear una cita activa solapada: `slot_taken` y recepción escoge alternativa | §9.14 (3ª ronda) |
| 4b | **Reactivación sin desplazamiento** — `canceled`/`no_show → scheduled` no puede solaparse ni mover nada: `slot_taken` y programación nueva | §9.15 (3ª ronda) |
| 4c | **Sin banderas de forzado** (`force`, `allow_overlap`, permiso que lo salte). Espera, sobrecupo y múltiples recursos = feature separada | §3.4, §9.14, §9.15 |
| 5 | **FLUJO-C** — el `owner_exists`/`owner_ambiguous` se resuelve con caso visible, verificación humana auditada y RBAC propio; **nada se automatiza** | §9.6, §5.5.6 |
| 6 | La unicidad de teléfono se logra con **lock de deduplicación**, no con restricción única | §4.7.1 |
| 6a | **Inventario cerrado por familias** (crear `Owner` · asociar `Pet` · mutar `phone` · normalizar): cada vía usa el servicio o queda excluida **con evidencia**. «Cualquier vía futura» deja de ser cobertura válida | §4.7.4 (hallazgo Z) |
| 6b | **`POST /api/pets/` no resuelve identidad por teléfono**: modo referencia (cliente elegido por `public_id`) o modo alta (servicio, bajo lock). Nombre distinto con teléfono existente → `409 owner_exists` con el candidato; nunca un segundo expediente | §4.9 |
| 6c | **Cambiar `Owner.phone` bloquea las dos claves** (anterior y nueva) en orden total, comprueba y guarda **sin ventana**, y falla cerrado (`owner_exists` / `owner_ambiguous`). Aplica también a la escritura anidada desde `PATCH /api/pets/` | §4.10 |
| 6d | **Leer identidad también es decidir**: los lectores de `agent/services.py` (creación de contacto y rematch) y las tres pasadas del importador usan el resolvedor sobre `phone_normalized`; ninguna consulta `Owner.phone` crudo ni elige entre duplicados | §4.7.4 (familia E), §4.11 (revisión OCR) |
| 6e | **Ambigüedad en lectura = sin vínculo, sin promoción y sin limpiar `auto_rematch_blocked`**; escalada segura cuando el flujo lo requiera | §4.11 |
| 6f | **El preview del importador usa el mismo contrato que la escritura** (0 · 1 · `owner_exists` · `owner_ambiguous`): nunca muestra una elección que el commit rechazaría | §4.8 |
| 6g | **`Owner` genérico**: `phone_normalized = NULL` siempre; excluido de búsqueda, locks, deduplicación y decisiones de identidad; su teléfono de relleno **nunca es identidad** | §4.12 |
| 7 | El solape se traduce al desenlace de negocio existente (`400 slot_taken` + `code`), no a un 409 nuevo | §3.4 |
| 8 | `DELETE /appointments/<id>/` entra al contrato **y** queda deprecado a favor de `/status/` | §3.3 |
| 9 | `assign-patient` entra (lock + precondición); `complete_appointment_on_record_close` queda **excluida** con justificación | §3.3 |
| 10 | Suspender una intención es **una sola transición atómica**; la rama de identidad no usa el `clear_pending` genérico | §5.5.4 |
| 11 | El release solo aplica el veredicto sobre el testigo que verificó; si cambió, reintenta una vez y luego `409 release_conflict` | §5.6 |
| 12 | Los conflictos de negocio salen de la telemetría de fallos técnicos | §5.4 |
| 13 | **F4 no se despliega sin F3** | §2 |
| 14 | Las dos correcciones documentales de Item 1 son DoD de F4 | §7 |

### 12.2 Riesgos residuales aceptados

| Riesgo | Por qué se acepta | Mitigación |
|---|---|---|
| **La atención sin cita puede ser rechazada por cupo** (INV-D) | **Comportamiento aprobado** (§9.14), no consecuencia pendiente: dos atenciones simultáneas del mismo veterinario nunca fueron reales | Riesgo residual = **operativo**: avisar a recepción antes del deploy y dejar claro el gesto siguiente (otro veterinario u otro horario). Sin bandera de forzado |
| **La reactivación `canceled → scheduled` puede fallar** si el hueco se reasignó | **Comportamiento aprobado** (§9.15); coherente con el guard de fecha pasada que ya vive en esa transición | Mensaje `slot_taken` existente; la UI ya sabe ofrecer otra hora. Nada se desplaza automáticamente |
| **Solapes históricos bloquean la migración** hasta que cada clínica los ordene | Corregirlos automáticamente sería cancelar o mover citas reales sin que nadie lo decida | `audit_appointment_overlaps` + remediación humana + re-auditoría post-deploy |
| **Duplicados de teléfono degradan la experiencia** de esa clínica (`owner_ambiguous` también en su alta manual) | INV-C: mezclar dos expedientes clínicos es peor | `audit_owner_phone_duplicates` + mensaje que explica qué falta |
| **Un contacto vinculado hoy puede quedar ambiguo** cuando dos expedientes coinciden tras normalizar (§4.11) | El vínculo actual apunta a un expediente **elegido a ciegas**; dejarlo sería mantener el bypass | Reporte de duplicados a la vista en el despliegue; el contacto se vincula solo cuando el dato queda ordenado |
| **El modo lectura no toma el lock**: un alta concurrente puede volver ambiguo lo recién leído | Un `phone_match` no autoriza nada por sí solo (`_verification_ok` exige `owner_id` y nivel) | `_rematch_owner` reevalúa en el siguiente mensaje; lo que queda cerrado es la **elección** entre duplicados |
| **El gate estático puede quedarse corto**: un grep de una línea sobre `get_or_create(...phone...)` es justo lo que dejó pasar el hallazgo Z | Ningún linter conoce la intención; el gate hay que escribirlo para lo que la gente escribe de verdad | **P2-12 doble**: funcional (todas las vías producen los desenlaces del servicio y ninguna deja el normalizado obsoleto) + estático (cubre `get_or_create(...name..., ...phone...)`, construcciones multirrenglón `Owner(` … `.save()` y asignaciones a `phone` seguidas de `save()`) |
| **El lock de deduplicación cubre a quien lo toma**: una vía nueva que cree `Owner`, le asocie una `Pet` o mute su teléfono fuera del servicio reabre el hueco | No hay restricción de base que lo impida (por INV-C). La 2ª revisión demostró que el riesgo es real: faltaban dos vías vivas | Inventario cerrado por familias (§4.7.4) + P2-12 ampliada + regla en `system-reference.md` §4 + grep gate sobre `get_or_create(...phone...)` y `get_or_create(...name..., ...phone...)` |
| **El alta de mascota pregunta donde antes inventaba**: teléfono conocido con otro nombre → `409` con candidato | Seguir creando un segundo expediente fabricaba justo los duplicados que INV-C obliga a tratar como ambiguos | La UI ofrece elegir el expediente o corregir el teléfono; el caso «mismo cliente, mismo nombre» sigue siendo silencioso (P2-14) |
| **El importador deja de elegir entre duplicados**: filas que hoy reutilizan la primera coincidencia pasan a reportarse | INV-C: elegir una fila arbitraria es exactamente lo prohibido | Política vigente de filas problemáticas (se salta y se reporta, no aborta el import); el conteo de importadas baja en clínicas con dato sucio |
| **`Owner` no está en el admin de Django** — la exclusión C4 vale mientras nadie lo registre | Registrarlo es un cambio de una línea que reabre el vector | Anotado en el ADR y en `modules/patients.md`; si se registra, entra en C1 |
| **INV-A no es universal hasta F5**: entre sí, dos escrituras del frontend siguen en último-escritor-gana | Limitación del rollout, declarada | §9.9 fija el calendario; el agente queda protegido desde el día 1 |
| **`release_conflict` traslada trabajo al staff** cuando el mundo se mueve dos veces | La alternativa era aplicar un veredicto sobre un caso no verificado | Un reintento automático antes de responder; el mensaje dice qué cambió |
| **La verificación manual vale lo que valga la persona** | Automatizar el juicio es justo lo que §5.5.6 prohíbe | Trazabilidad: toda vinculación tiene nombre, caso y fecha |
| **Resolución fuera de banda** (teléfono, mostrador): indetectable | Estructural | D1 + D2; para identidad, FLUJO-C; el resto sigue en §9.11 |
| **Cierre silencioso de conversaciones a 24 h** (§6.4) | Preexistente; Item 2 lo hace más frecuente, no lo introduce | Pendiente de §9.4 |
| **La migración de exclusión toma un lock fuerte** mientras construye el índice | Volumen del piloto: segundos | Ventana de deploy; si el volumen creciera, se evalúa la construcción concurrente |

### 12.3 Pruebas PostgreSQL obligatorias (no valen en SQLite)

Todas con `TransactionTestCase` y **dos conexiones reales**. Son gate de merge
de su fase; una suite verde en SQLite no acredita ninguna de ellas.

| # | Prueba | Fase | Qué acredita |
|---|---|---|---|
| P0-16 | Dos conexiones y dos claves de idempotencia, misma organización y teléfono | F1 | Exactamente **un** `Owner` nuevo o un `409` cerrado. Repetir mezclando actor agente y recepción |
| P0-17 | Dos `Owner` históricos con el mismo teléfono normalizado | F1 | `409 owner_ambiguous` para agente **y** recepción; cero escrituras; jamás se elige uno |
| **P0-21** | `POST /api/pets/` contra `create-with-patient`, mismo teléfono, dos conexiones | F1 | Exactamente **un** `Owner` o un `409` cerrado; ningún duplicado fabricado por la vía de mascotas |
| **P0-22** | Dos cambios de teléfono concurrentes al **mismo** número nuevo, más el caso **cruzado** (A→B y B→A a la vez) | F1 | Uno gana, el otro `409`; **ningún deadlock** gracias al orden total de claves; ningún duplicado nuevo |
| **P0-23** | Cambio de teléfono contra alta nueva sobre el mismo número (`/api/pets/`, `/api/owners/`, `create-with-patient`) | F1 | Exactamente una operación persiste; la otra `409`. Cubre la clave que «se libera» y la que «se ocupa» |
| **P0-24** | Duplicado histórico frente a **todas** las vías del inventario | F1 | `owner_ambiguous` (error de fila en el importador) con cero escrituras; ninguna vía elige una fila |
| **P0-25** | Aislamiento por tenant + ausencia de escrituras parciales | F1 | Un `Owner` con el mismo teléfono en otra organización no interfiere (ni bloquea, ni cuenta, ni aparece); ante `409` no queda `Owner`, `Pet`, `Appointment`, teléfono cambiado ni campos de la mascota guardados |
| **P0-26** | Lectores de identidad del agente (creación de contacto y rematch) con un duplicado histórico **distinguible solo tras normalizar** (`"55 1234 5678"` vs `"5512345678"`) | F1 | `owner_ambiguous`: cero vínculo, `is_ambiguous=True`, nivel sin subir, `auto_rematch_blocked` intacto. Con un único candidato de formato distinto → `phone_match`, como hoy |
| **P0-27** | Importador: preview, dry-run y commit sobre el mismo duplicado histórico | F1 | Los tres coinciden en `owner_ambiguous`; el conteo de importables ya excluye la fila; ninguna pasada usa `.first()` |
| **P0-28** | `Owner` genérico creado por `patients.utils` y por el signal de alta de organización, más el backfill | F1 | `phone_normalized = NULL` en los tres casos; no cuenta, no bloquea, no aparece en búsqueda de identidad y ningún contacto puede vincularse a él por teléfono |
| P0-18 | Dos `POST` y dos `PATCH` simultáneos al mismo veterinario e intervalo | F0·b | Solo una cita activa persiste; la otra recibe `slot_taken`. Incluye reactivación desde `canceled` |
| P0-20 | `walk-in` sobre veterinario ocupado; reactivación sobre hueco ocupado | F0·b | `slot_taken` en ambos, cero escrituras y cero `AppointmentStatusChange`; con el hueco libre siguen funcionando. Ancla que **no existe** bandera de forzado (§9.14, §9.15). Corre en PostgreSQL porque la garantía es la restricción, no el pre-chequeo |
| P0-19 | Excepción inyectada entre el `409 owner_exists` y la transición local | F2 | El staged íntegro sigue en `suspended` y el hand-off de identidad abierto — o nada ocurrió. Nunca a medias |
| P1-14 | Dos escrituras con el **mismo** `expected_state` | F0·a | Hay lock, no solo comparación: una escribe, la otra recibe 409 |
| P1-6 | Release y nudge concurrentes | F3 | Como máximo un nudge |
| P1-7 | Dos releases concurrentes | F3 | Un solo consumo/restauración; sin pérdida de `deferred_at` ni de otras claves de `flow` |
| P1-19 | `R1 → nueva suspensión → R3` | F3 | Ninguna mutación; retry/conflicto; la suspensión nueva intacta |
| P1-20 | `R1 → el worker toma el lease → R3` | F3 | Ninguna mutación; `409` con `reason='turn_in_progress'` |
| P1-21 | `R1 → otro staff reclama → R3` | F3 | El claim ajeno no se pisa; `409` con `reason='claim_changed'` |
| P1-22 | Dos `claim` simultáneos; `claim` + `release` simultáneos | F3 | Serialización sobre la misma fila; sin estado mixto |
| P1-16 | Dos autorizaciones simultáneas del vínculo | F4 | Un solo vínculo; la segunda recibe `409 already_linked` |
| P0-15 | Recorrido completo de FLUJO-C | F4 | `owner_exists` → verificar → autorizar → liberar → primer «sí» sin escrituras → segundo «sí» con el único commit permitido |

Complementos no concurrentes pero igualmente bloqueantes, listados aquí para que
no se pierdan al planificar la ejecución: `expected_state` en `PATCH` detalle,
`/status/` y `DELETE` (éxito, 409, **cero** `AppointmentStatusChange` adicional
en conflicto, compatibilidad mientras la precondición sea opt-in); tenant/RBAC
del caso de verificación (404 sin auditoría ni vínculo, aprobación de A no
autoriza B, rechazo o hand-off cerrado invalida una aprobación previa); y la
clasificación de `appointment_changed`/`owner_exists`/`owner_ambiguous`/
`slot_taken` como evento de negocio redactado, sin `AGENT_TOOL_HTTP_ERROR`, sin
contar como fallo técnico y sin crear un hand-off de `tool_failure`.
