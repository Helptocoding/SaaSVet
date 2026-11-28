# Plan de respuesta a incidentes

**Fecha**: 2026-06-24
**Estado**: vigente / interim (capacidades reales; sin SOC/SIEM/MFA aún)

Este plan describe cómo detectar, contener y responder a incidentes de seguridad
o de datos personales en SaaslyVet, **usando únicamente las capacidades reales**
del sistema. No se asume SOC2, ISO, SIEM ni un SOC 24/7.

- **Contacto**: privacidad@saaslyvet.com / soporte.

---

## 1. Capacidades reales (con qué contamos)

### Logging
- Logs estructurados en **JSON a stdout** (Docker).
- Eventos clave: `RBAC_DENIED`, `TENANT_MISMATCH_DETECTED`,
  `MUST_CHANGE_PASSWORD_BLOCKED`, `LOGIN_FAILED`, `PLATFORM_*`.
- **Correlación end-to-end** vía `X-Request-ID` (`RequestIDMiddleware`): un mismo
  request se rastrea a través de logs, Sentry y la respuesta.

### Audit trail (modelos append-only en DB)
`InvoiceAuditLog`, `AppointmentStatusChange`,
`Payment` / `RefundPayment` / `RefundReversal`, `VitalSigns`, `CashMovement`,
`OrganizationConfigEvent` (cambios de Configuración, incluida la zona horaria; ADR p70 D9),
`DashboardSnapshotAudit`.

Estos modelos son de solo inserción: sirven como evidencia inmutable durante una
investigación.

### Monitoreo de errores
- **Sentry** con `send_default_pii=False` + `before_send` (scrubbing).
- **No** se envía PII clínica ni financiera a Sentry.

### Backups
- **Nightly cifrado** (age, zero-knowledge) **offsite** a Backblaze B2.
- **Drill de restauración documentado**: ver
  [`docs/runbooks/RUNBOOK-RESTORE.md`](../runbooks/RUNBOOK-RESTORE.md).
- **Deadman ping** vía Healthchecks.io (alerta si el backup nightly no corre).

### Hosting
- **VPS único** en Hetzner.
- **TLS** vía Caddy.

---

## 2. Proceso de respuesta

### 2.1 Detección
Fuentes de detección:
- Alerta de **Sentry** (excepción en producción).
- **Logs** JSON (picos de `LOGIN_FAILED`, `RBAC_DENIED`,
  `TENANT_MISMATCH_DETECTED`, eventos `PLATFORM_*`).
- **Deadman** de Healthchecks.io (backup no ejecutado).
- **Reporte** manual (cliente, clínica, miembro del equipo).

### 2.2 Clasificación de severidad
Clasificar el incidente para decidir urgencia y si hay impacto a datos personales:
- **Crítica**: posible acceso/exfiltración de datos personales, cross-tenant
  confirmado (`TENANT_MISMATCH_DETECTED`), pérdida de datos.
- **Alta**: degradación seria, fallo de backups sostenido, escalación de
  privilegios.
- **Media / Baja**: errores aislados sin impacto a datos personales.

### 2.3 Contención
Acciones inmediatas para limitar el alcance (según el caso): invalidar sesiones o
forzar cambio de contraseña del actor afectado, revocar acceso comprometido,
aislar el componente afectado en el VPS. Preservar evidencia (logs, audit trail)
antes de remediar.

### 2.4 Evaluación de impacto a datos personales
Determinar **qué datos personales** estuvieron involucrados y de **qué tenant(s)**,
usando el audit trail y los logs correlacionados por `X-Request-ID`. Identificar a
los titulares afectados y si SaaslyVet actúa como Responsable (staff/clínica) o
Encargado (clientes/pacientes de una clínica) — ver `docs/compliance/arco.md`.

### 2.5 Notificación al titular (LFPDPPP art. 19)
Cuando haya vulneración que afecte significativamente los derechos patrimoniales o
morales de los titulares, **notificar de forma inmediata** a los titulares
afectados (o, si SaaslyVet es Encargado, a la clínica Responsable para que esta
notifique), conforme al art. 19 de la LFPDPPP.

**Plantilla breve de aviso de vulneración**:

```
Asunto: Aviso de incidente de seguridad — SaaslyVet

Estimado(a) [titular / clínica]:

Le informamos que el [fecha] detectamos un incidente de seguridad que
[pudo afectar / afectó] los siguientes datos personales: [enumerar].

Naturaleza del incidente: [descripción breve].
Medidas tomadas: [contención y remediación].
Recomendaciones para el titular: [p. ej. cambiar contraseña].

Para más información: privacidad@saaslyvet.com.
```

### 2.6 Recuperación
Restaurar el servicio y los datos según corresponda. Para restauración desde
backup seguir [`docs/runbooks/RUNBOOK-RESTORE.md`](../runbooks/RUNBOOK-RESTORE.md).
Verificar integridad tras la recuperación.

### 2.7 Post-mortem
Reconstruir la línea de tiempo usando `X-Request-ID` para correlacionar logs,
Sentry y respuestas. Documentar causa raíz, impacto, acciones de contención y
recuperación, y acciones correctivas/preventivas. Registrar lecciones aprendidas.

---

## 3. Lo que NO tenemos (todavía)

Declarado honestamente para evitar suposiciones falsas:
- **SIEM / alerting de seguridad** dedicado — futuro (P1/P2).
- **MFA** (autenticación multifactor) — futuro (P1/P2).
- **On-call formal** (rotación de guardia) — futuro (P1/P2).
- **Detección automatizada de brechas** — futuro (P1/P2).

La detección hoy depende de Sentry, revisión de logs, el deadman de backups y
reportes manuales.
