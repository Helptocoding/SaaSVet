# Subprocesadores

**Fecha**: 2026-06-24
**Estado**: vigente / interim (DPAs estándar pendientes de aceptar/archivar — P0)

Lista de subprocesadores (terceros) que intervienen en el tratamiento de datos de
SaaslyVet. Tono factual: **no** se afirma que existan DPAs firmados; donde aplica,
el DPA estándar del proveedor está **disponible y pendiente de aceptar/archivar**.

---

## 1. Tabla de subprocesadores

| Proveedor | Uso | Tipo de datos | Ubicación | Estado |
|-----------|-----|---------------|-----------|--------|
| Hetzner Online GmbH | Hosting VPS (base de datos, app) | Todos los datos (residen ahí) | Alemania / Finlandia (UE) | Activo · transferencia internacional · DPA pendiente |
| Backblaze, Inc. (B2) | Almacenamiento de backups | Cifrados (age, zero-knowledge — el proveedor no puede leerlos) | EE.UU. | Activo · DPA pendiente |
| Functional Software, Inc. (Sentry) | Monitoreo de errores | Técnicos, PII-scrubbed (sin datos clínicos/financieros) | EE.UU. | Activo · DPA pendiente |
| Healthchecks.io | Ping deadman de backups | Sin PII | — | Activo |
| Let's Encrypt (vía Caddy) | Certificados TLS | Dominio, email ACME | — | Activo |
| Redis | Cache + contadores de throttle | Sin PII clínica | Self-hosted (mismo VPS) | Activo |
| Discord Inc. | Canal interno de reportes de soporte (botón "Reportar problema") | Mensaje + usuario/clínica + captura opcional (puede incluir PII si el usuario la adjunta) | EE.UU. | Activo · transferencia internacional · DPA pendiente · mitigación: aviso en UI |

---

## 2. Notas

- **Sin proveedor de email / SMTP**: hoy **no se envían correos transaccionales**.
  No hay un subprocesador de correo en la cadena.
- **Stripe NO está conectado**: la integración de pagos en línea es **futura (P1)**.
  No procesa datos actualmente.
- **Transferencia internacional**: Hetzner (UE), Backblaze (EE.UU.), Sentry
  (EE.UU.) y Discord (EE.UU.) tratan datos **fuera de México**. Esta transferencia
  internacional **debe divulgarse en el Aviso de Privacidad**.
- **Tarea P0**: aceptar y archivar los **DPAs estándar** de Hetzner, Backblaze,
  Sentry y Discord.
- **Discord (soporte)**: el botón "Reportar problema" envía el mensaje + usuario/
  clínica + captura opcional a un canal de Discord (EE.UU.). La captura puede
  contener PII clínica si el usuario la adjunta; mitigación actual = aviso en el
  modal de no incluir datos sensibles. Evaluar un canal sin transferencia a
  EE.UU. (o sin captura) si la exposición lo amerita.
