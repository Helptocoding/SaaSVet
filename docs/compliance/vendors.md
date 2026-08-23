# Subprocesadores

**Fecha**: 2026-06-24
**Última actualización**: 2026-08-22 (Backblaze B2 media operativa, ADR p60; Formspree y GA4 agregados; brechas reales de aviso/consentimiento registradas)
**Estado**: vigente / interim (brechas P0 de DPAs, aviso y consentimiento; proveedores planificados bloqueados por gates)

Lista de subprocesadores (terceros) que intervienen en el tratamiento de datos de
SaaslyVet. Tono factual: **no** se afirma que existan DPAs firmados; para los
proveedores activos indicados falta confirmar, aceptar cuando corresponda y
archivar el instrumento contractual aplicable.

---

## 1. Tabla de subprocesadores

| Proveedor | Uso | Tipo de datos | Ubicación | Estado |
|-----------|-----|---------------|-----------|--------|
| Hetzner Online GmbH | Hosting VPS (base de datos, app) | Todos los datos (residen ahí) | Alemania / Finlandia (UE) | Activo · transferencia internacional · DPA pendiente |
| Backblaze, Inc. (B2) | Almacenamiento de backups | Cifrados (age, zero-knowledge — el proveedor no puede leerlos) | EE.UU. | Activo · DPA pendiente |
| Backblaze, Inc. (B2, media operativa WhatsApp) | Bucket privado dedicado y separado de backups para adjuntos del Inbox; proxy Django autenticado es la única vía de lectura v1; sin Object Lock ni presigned GET | Binarios de imágenes/audio/documentos potencialmente personales; cifrado at-rest del proveedor, no zero-knowledge | EE.UU. | **Planificado y bloqueado** · no activar hasta DPA archivado + aviso/ARCO/transferencia actualizados + bucket/key/lifecycle verificados |
| Functional Software, Inc. (Sentry) | Monitoreo de errores | Técnicos, PII-scrubbed (sin datos clínicos/financieros) | EE.UU. | Activo · DPA pendiente |
| Healthchecks.io | Ping deadman de backups | Sin PII | — | Activo |
| Let's Encrypt (vía Caddy) | Certificados TLS | Dominio, email ACME | — | Activo |
| Redis | Cache + contadores de throttle | Sin PII clínica | Self-hosted (mismo VPS) | Activo |
| Discord Inc. | Canal interno de reportes de soporte (botón "Reportar problema") | Mensaje + usuario/clínica + captura opcional (puede incluir PII si el usuario la adjunta) | EE.UU. | Activo · transferencia internacional · DPA pendiente · mitigación: aviso en UI |
| Formspree, Inc. | Formulario de acceso anticipado de la landing → reenvío a soporte@saaslyvet.com | Nombre, apellido, clínica, correo y teléfono opcional de prospectos | EE.UU. | Activo · transferencia internacional · DPA pendiente · plazo de conservación pendiente de definir y aviso pendiente de actualizar/publicar |
| Google LLC (Google Analytics 4) | Analítica agregada del sitio público | Datos de navegación seudónimos (cookies `_ga`) | EE.UU. | Activo · transferencia internacional · DPA pendiente · **brecha P0**: al existir ID, `GoogleAnalytics.astro` carga `gtag/config` sin Consent Mode ni banner; consentimiento denegado por defecto pendiente de implementar |
| Meta Platforms, Inc. (WhatsApp Cloud API) | Canal de mensajería WhatsApp + Inbox | Número, mensajes, captions, estados, timestamps y adjuntos de clientes finales de las clínicas | EE.UU. | **Planificado y bloqueado** · DPA por archivar y aviso/ARCO/transferencia pendientes de actualizar/publicar · retención binarios 180 días en B2 media operativa |

---

## 2. Notas

- **Sin proveedor de email / SMTP**: hoy **no se envían correos transaccionales**.
  No hay un subprocesador de correo en la cadena.
- **Stripe NO está conectado**: la integración de pagos en línea es **futura (P1)**.
  No procesa datos actualmente.
- **Transferencias activas**: Hetzner (UE), Backblaze backups, Sentry, Discord,
  Formspree y Google (EE.UU.) ya tratan datos **fuera de México** y deben quedar
  divulgados correctamente en el Aviso de Privacidad. **Transferencias
  planificadas**: Backblaze media y Meta (EE.UU.) no se activan hasta actualizar
  y publicar aviso/ARCO/transferencia y cerrar sus demás gates.
- **B2 tiene dos tratamientos y buckets distintos**: backups Postgres `age`
  zero-knowledge ya activos (p40) y media operativa legible por el servicio,
  todavía planificada (p60). Los dumps Postgres pueden contener texto/captions y
  metadatos de media, pero nunca incluyen el binario del bucket operativo. El
  ciclo p40 sigue intacto y todo restore debe reaplicar purgas/anonimizaciones y
  reconciliar expiraciones antes de abrir tráfico. El bucket operativo no usa
  Object Lock; lifecycle debe permitir los 180 días y borrados ARCO anticipados.
  El segundo tratamiento no hereda automáticamente la justificación, DPA ni
  controles del primero y no puede marcarse activo hasta cerrar sus gates.
- **Lectura de media v1**: exclusivamente proxy Django autenticado y org-scoped.
  Los `presigned GET` están fuera de v1 y requerirían ADR y revisión de seguridad
  futura; no hay URL pública o persistente compartible.
- **Tareas P0 — proveedores activos**: confirmar/aceptar y archivar los
  instrumentos contractuales aplicables de Hetzner, Backblaze backups, Sentry,
  Discord, Formspree y Google; corregir el aviso para las transferencias activas;
  definir/documentar el plazo de Formspree; e implementar para GA4 banner y
  Consent Mode con consentimiento denegado por defecto antes de cargar
  `gtag/config`.
- **Gates — proveedores planificados**: Backblaze media y Meta permanecen
  bloqueados. Su activación exige cobertura contractual/DPA archivada, aviso,
  ARCO y transferencia actualizados/publicados y, para B2 media,
  bucket/key/lifecycle verificados.
- **Discord (soporte)**: el botón "Reportar problema" envía el mensaje + usuario/
  clínica + captura opcional a un canal de Discord (EE.UU.). La captura puede
  contener PII clínica si el usuario la adjunta; mitigación actual = aviso en el
  modal de no incluir datos sensibles. Evaluar un canal sin transferencia a
  EE.UU. (o sin captura) si la exposición lo amerita.
