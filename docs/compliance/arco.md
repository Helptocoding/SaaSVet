# Proceso ARCO manual (LFPDPPP)

**Fecha**: 2026-06-24
**Última actualización**: 2026-10-22 (media implementada localmente, activación pendiente)
**Estado**: vigente / interim (proceso manual; endpoints automatizados son P1)

Este documento describe cómo atender **manualmente** las solicitudes de derechos
ARCO (Acceso, Rectificación, Cancelación, Oposición) bajo la Ley Federal de
Protección de Datos Personales en Posesión de los Particulares (LFPDPPP).

**No existen endpoints automatizados de ARCO todavía.** Toda solicitud se atiende
mediante el procedimiento manual descrito aquí.

- **Contacto del Responsable**: privacidad@saaslyvet.com
- **Plazo de respuesta (SLA)**: ≤ 20 días hábiles a partir de la recepción de la
  solicitud (LFPDPPP arts. 2.VIII y 31). Si procede, ejecutar dentro de los
  15 días hábiles siguientes a comunicar la respuesta. Una ampliación por periodo
  igual requiere justificación y comunicación. Registrar siempre la recepción
  original; la verificación de identidad no reinicia por sí sola el plazo.

Fuente contrastada el 22-10-2026: [texto vigente de la LFPDPPP](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf),
reforma indicada 14-11-2025.

---

## 1. Rol de SaaslyVet: Responsable vs Encargado

Esta distinción determina **quién debe atender** cada solicitud y es la decisión
más importante del proceso.

- **SaaslyVet es Responsable** de los datos de la **cuenta**: el personal (staff)
  de cada clínica y los datos de la organización (clínica) misma. Estas
  solicitudes las atiende SaaslyVet directamente.
- **SaaslyVet es Encargado (procesador)** de los datos de los **clientes finales y
  pacientes** de cada clínica. El **Responsable** de esos datos es **la clínica**.

**Regla de ruteo**: si el solicitante es un **cliente final** (un `patients.Owner`
de una clínica, p. ej. el dueño de una mascota), la solicitud **debe canalizarse a
SU CLÍNICA** (que es el Responsable). SaaslyVet asiste a la clínica en su carácter
de Encargado (por ejemplo, ejecutando una exportación o una corrección que la
clínica solicite), pero **no responde directamente al titular** en estos casos.

---

## 2. Mapa de datos personales

| Dato | Modelo · App Django | Rol de SaaslyVet | Tenant |
|------|---------------------|------------------|--------|
| Staff: username, email, nombre, rol, especialidad, hash de contraseña | `User` · users | Responsable | `organization` |
| Clínica: nombre, timezone, tax_rate, settings | `Organization` / `OrganizationSettings` · organizations | Responsable | — |
| Cliente final: nombre, teléfono, nº expediente anterior, historial migrado | `patients.Owner` (campos `name`, `phone`, `legacy_id`, `extra_data`) · patients | Encargado | `organization` |
| Paciente: nombre, especie, raza, fecha nacimiento, sexo, color | `patients.Pet` · patients | Encargado | `organization` |
| Clínico: diagnóstico, tratamiento, notas, signos vitales, vacunas | `MedicalRecord` / `VitalSigns` / `VaccineRecord` · medical_records | Encargado | `organization` |
| Recetas: dosis, duración, instrucciones | `Prescription` / `PrescriptionItem` · prescriptions | Encargado | `organization` |
| Cobros: facturas, pagos (solo método: efectivo/tarjeta/transferencia, **SIN** datos de tarjeta), prescriptor externo | `Invoice` / `Payment` / `ExternalPrescriptionAttestation` · billing | Encargado | `organization` |
| Citas | `Appointment` · appointments | Encargado | `organization` |
| Caja | `CashSession` / `CashMovement` · cash | Encargado | `organization` |
| Migración (PII cruda staged) | `ImportJob.rows` (JSON) · imports | Encargado | `organization` |
| WhatsApp: identidad de contacto, conversaciones y texto/captions | `ContactIdentity` / `Conversation` · agent; `Message` · channels | Encargado | `organization` |
| WhatsApp media (implementada localmente, aún no activa) | `MessageMedia` · channels + objeto privado B2 | Encargado | `organization` + key/prefix B2 |

Notas sobre el mapa:
- En cobros **nunca** se almacenan datos de tarjeta. Solo se registra el método de
  pago (efectivo / tarjeta / transferencia).
- `ImportJob.rows` contiene PII cruda staged de la migración (JSON con filas del
  sistema anterior). Considerarlo en solicitudes de Cancelación/Acceso de clientes
  migrados.
- Cuando media WhatsApp se active, el binario canónico vivirá en un bucket B2
  privado dedicado, separado de backups y sin Object Lock. V1 lo servirá
  únicamente mediante proxy Django autenticado y org-scoped; no habrá URLs
  públicas ni `presigned GET`. La activación permanece bloqueada hasta archivar
  el DPA y actualizar aviso, ARCO y divulgación de transferencia internacional.

---

## 3. Verificación de identidad

Antes de ejecutar cualquier derecho ARCO se debe verificar la identidad del
solicitante y, en su caso, la representación legal. La solicitud debe acreditar
que el titular es quien dice ser (identificación oficial) y, cuando aplique,
documento que acredite la representación. **No** ejecutar Acceso, Rectificación,
Cancelación ni Oposición sin esta verificación.

---

## 4. Acceso

**Qué existe hoy**: no hay endpoint de auto-servicio de exportación. El acceso se
atiende con una **exportación filtrada manual** (consulta o dump de la base de
datos).

Procedimiento:
1. Verificar identidad (§3) y rol (§1). Si es cliente final → rutear a su clínica.
2. Identificar al titular por `organization` + `User.public_id` (staff) o
   `Owner.public_id` (cliente final).
3. Ejecutar consulta/dump filtrada por `organization` y por el `public_id` del
   titular, recorriendo los modelos del mapa de datos (§2) que correspondan.
   Cuando media WhatsApp esté activa, incluir chats, captions y adjuntos aún
   vigentes; los expirados se informan como tombstone sin prometer recuperar el
   binario eliminado. El proxy responde `410 media_expired` para el titular de
   la organización y la UI muestra «Archivo expirado»; una organización ajena
   sigue recibiendo 404.
4. Entregar la información dentro del SLA (§ inicio).

---

## 5. Rectificación

**Qué existe hoy**:
- Los datos de **cliente/paciente** se editan desde la propia aplicación por la
  clínica, mediante los endpoints **PATCH existentes** (p. ej. actualización de
  `Owner`, `Pet`, etc.). Si la solicitud viene de un cliente final, se canaliza a
  su clínica, que realiza la corrección en la app.
- El **perfil propio del staff** **no** tiene endpoint `PATCH /me/` todavía → la
  corrección de datos de staff se hace de forma **manual** (ajuste directo del
  registro `User` por SaaslyVet como Responsable).

---

## 6. Cancelación

**Qué existe hoy**:
- La cancelación se implementa como **borrado lógico** (`is_active=False`).
- El **borrado físico está bloqueado** por `on_delete=PROTECT` donde existen
  dependencias (p. ej. facturas, expedientes). En esos casos no es posible
  eliminar el registro: la vía es la **anonimización**, no la eliminación.

**Obligaciones de retención**: existen deberes de conservación **clínicos y
fiscales** sobre expedientes y comprobantes. La Cancelación no puede vulnerar
estas obligaciones de retención; por eso, ante dependencias clínicas/fiscales, la
respuesta es anonimizar/conservar lo legalmente exigible, no borrar.

**WhatsApp/media (ADR p60; aún sin activación real)**: cuando proceda una cancelación antes de los
180 días, eliminar el objeto B2 operativo y dejar la fila `MessageMedia` como
tombstone/`expired` sin referencia descargable; anonimizar o conservar el texto
solo conforme al alcance y obligaciones aplicables. Los backups Postgres p40
contienen texto/captions y metadatos/referencias, pero **nunca el binario B2**.
Su ciclo permanece intacto (local 14 días, `daily/` 30 días, `monthly/` 12
meses) y no se reescribe retroactivamente; una restauración debe reaplicar las
purgas/anonimizaciones procedentes y ejecutar el reconciliador de expiraciones
antes de abrir el servicio al tráfico.

### 6.1 Procedimiento manual de cancelación de media

Este procedimiento queda preparado; no se ejecutó contra datos reales. No hay
endpoint ARCO ni comando de borrado por titular. La bandera general de media
apagada vuelve inerte `maintain_inbox_media`: no activarla globalmente solo para
tramitar una solicitud. El operador debe ejecutar una intervención autorizada y
acotada con las primitivas existentes o mediante la herramienta operativa aprobada.

1. Registrar folio, identidad verificada y, para clientes finales, la instrucción
   de su clínica responsable. Delimitar UUID y organización explícitos. Resolver
   y documentar conservación aplicable; la retención de una factura no justifica
   conservar automáticamente todo adjunto del chat.
2. Resolver cada `MessageMedia` por `organization` y `public_id`; comprobar también
   clínica/cuenta del mensaje. Rechazar cruces de tenant y listas por teléfono sin
   verificar. No registrar el contenido ni object keys en recibos públicos.
3. Bajo `transaction.atomic()` y `select_for_update()`, bloquear la entrega:
   `status='expired'`, `expires_at` y `expired_at` al momento de la intervención;
   revocar `worker_token`/`lease_until` y limpiar `next_attempt_at`. Conservar el
   valor de `file` hasta confirmar purga. Guardar usando la vía de transición
   server-owned existente (`save(validate=False, update_fields=...)`). Esto impide
   que un worker con token anterior publique un resultado tardío. No dejar una
   fila `pending`/`failed` reencolable ni borrar la fila que conserva el tombstone.
4. Fuera de la transacción, borrar el key exacto mediante `row.file.storage.delete`.
   El adaptador B2 elimina todas sus versiones y markers. Comprobar el resultado
   real con el operador del proveedor; si falla, conservar el key, mantener el
   bloqueo y registrar reintento. No declarar cancelación física completada por
   haber recibido únicamente una respuesta 410.
5. Bajo un nuevo lock scoped, volver a comprobar identidad/estado y el key exacto
   antes de limpiar `file`. Verificar que el proxy devuelve 410 a un usuario
   autorizado y 404 a otra clínica. Revisar que no hay un upload en vuelo o spool
   residual del adjunto; el fencing obliga a descartar resultados tardíos, pero
   un proceso interrumpido requiere comprobar también las versiones del key.
6. Resolver captions/texto, payload crudo, referencias de contacto y demás datos
   dentro del alcance autorizado. Expirar el binario no anonimiza el mensaje ni
   equivale a borrar íntegramente al titular. Conservar únicamente lo que tenga
   fundamento documentado y entregar respuesta por el canal seguro acordado.
7. Registrar UUID internos, fechas, ejecutor, resultado físico, errores genéricos
   y evidencia privada. Mantener el registro de purgas/anonimizaciones separado
   del backup restaurable. Tras un restore, con tráfico cerrado, reaplicar ese
   registro antes de reconciliar, probar entrega/denegación y reabrir. Un backup
   antiguo no debe rehabilitar el adjunto ni reencolar su descarga desde Meta.

El [expediente de revisión](inbox-privacy-review-2026-10-22/README.md) y la
[preparación B2](inbox-privacy-review-2026-10-22/b2-preparacion.md) distinguen
documentación preparada de DPA, provisión y validaciones reales pendientes.

---

## 7. Oposición

**Qué existe hoy**: no hay mecanismo automatizado. La Oposición se atiende
mediante el **registro manual de la solicitud** (bitácora de la solicitud y de la
acción tomada). Se documenta la oposición del titular y se aplica conforme a su
alcance.

---

## 8. Nota de cierre

Este es un **proceso manual interino**. Los endpoints automatizados de ARCO
(exportación de auto-servicio, rectificación de perfil propio del staff,
cancelación/anonimización guiada) son **P1** (posterior a la fase de testers,
previo a la integración de Stripe).


### Actualización 23-10-2026: política y herramientas de medios

La [política definida por el usuario](../decisions/2026-10-22-inbox-media-retention-policy.md)
fija 180 días y purga operativa verificada en hasta siete días tras expirar.
Usar el [procedimiento vigente de medios](../runbooks/inbox-media.md), con ledger
independiente del dump, `INBOX_MEDIA_ACCESS_HOLD=True`, workers/webhooks detenidos,
`inbox_media_ops restore-check --workers-stopped`, mantenimiento y comprobación
de inventario del proveedor antes de autorizar tráfico. El comando no reabre
tráfico. ARCO anticipado usa `inbox_media_ops revoke`: ledger duradero primero,
fencing/estado DB después; no borrar la key antes de verificar la purga.

Responsable y canal de alertas quedan pendientes operativos no bloqueantes por
decisión expresa del usuario; no registrar entrega/atención como comprobadas.
Los incidentes de purga que superan siete días sí mantienen el cierre pendiente.
