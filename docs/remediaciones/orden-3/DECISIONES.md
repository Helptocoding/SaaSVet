# Decisiones implementadas y aprobaciones registradas

## Contrato de implementación local

| Área | Decisión aplicada | Evidencia / pendiente |
|---|---|---|
| GA4 | Se conserva una sola integración; solo acepta Measurement ID con formato GA4. La elección ausente, inválida o inaccesible significa denegado. No hay tag antes de aceptación explícita; preferencia analítica parte desmarcada. | [`GoogleAnalytics.astro`](../../../../LandingSaaS/frontend/src/components/seo/GoogleAnalytics.astro) y [`CookieConsentBanner.astro`](../../../../LandingSaaS/frontend/src/components/ui/CookieConsentBanner.astro). Pruebas con ID sintético y sin ID. La revocación con runtime Google real cargado no queda acreditada. |
| Consentimiento y anuncios | `analytics_storage` solo pasa a concedido por aceptación de analítica; estados publicitarios permanecen denegados. No se agregaron etiquetas de anuncios, remarketing, pings anticipados ni envío de datos clínicos/contacto. El titular debe revisar integraciones y ajustes de la propiedad. | La configuración de la cuenta Google no fue inspeccionada. |
| Privacidad en analítica | `config` omite page_view automático; la página enviada es origen+ruta sin query y referrer vacío. El formulario no dispara eventos. | Verificado sobre `dataLayer` local; no prueba los datos que pueda añadir el tag externo ni una propiedad. |
| Formspree | Nombre, apellido, clínica y correo requeridos; teléfono opcional. Finalidad del checkbox: atender/seguir esa solicitud de acceso/demo, sin campañas generales/newsletters. Aceptación independiente de GA4. Sin `_subject`, honeypot, adjuntos, texto libre nuevo ni campos clínicos. | [`RegisterModal.astro`](../../../../LandingSaaS/frontend/src/components/ui/RegisterModal.astro). Envíos solo interceptados y respondidos sintéticamente. La validación propia es cliente; el endpoint es de Formspree. |
| Fallos y fallback | Controles HTML nativos, `required`, límites y tipo de correo. Envío AJAX bloquea doble submit, exige respuesta 2xx JSON para mostrar éxito y deja reintentar tras error. Sin JavaScript el botón queda deshabilitado y se ofrece Contacto, sin POST accidental. | Prueba de navegador móvil/desktop, errores simulados y JavaScript desactivado. |
| Conservación | Regla propuesta y aplicada en textos: 180 días naturales desde último contacto efectivo de esa solicitud; sin contacto posterior, desde envío. Correos automáticos/campañas no reinician. | Procedimiento y frontera en [`RETENCION-PROSPECTOS.md`](RETENCION-PROSPECTOS.md); ejecución externa pendiente. |
| Borradores | Aviso y cookies se rotulan como propuesta local sin fecha efectiva. Se elimina «12 meses desde envío», se distingue contacto de campaña, se corrige cómputo ARCO desde recepción y se separan hechos de cuenta pendientes. | [`aviso-de-privacidad.astro`](../../../../LandingSaaS/frontend/src/pages/aviso-de-privacidad.astro), [`cookies.astro`](../../../../LandingSaaS/frontend/src/pages/cookies.astro). Aprobación/publicación reservadas al usuario. |

## Decisiones que no se alteran

- **Aprobación textual registrada:** el responsable respondió «lo acepto todo» tras la explicación del aviso, política de cookies y conservación de 180 días. Se registra como aprobación del texto local y de esa regla de prospectos. No equivale a una fecha efectiva, publicación, aceptación de DPA/contrato ni confirmación de configuración/región de proveedores.

- No se modificó la app, esquema, endpoints ARCO, seeds, `LegalDocument.is_current` ni políticas de WhatsApp.
- Se mantiene WhatsApp como texto condicional e inactivo; sus políticas de mensajes, B2 media y retenciones no cambian.
- Backblaze B2 backups es un tratamiento separado de B2 media. No se accedió a ninguna cuenta ni se hizo restore.
- Las excepciones B9/D29 aceptadas y alertas de purga no se tocaron.
- No se asignaron fechas efectivas, roles contractuales, regiones ni aceptaciones que no constan en evidencia de cuenta.

## Aprobación recibida y gates restantes

La aprobación expresa recibida cubre el texto de las dos páginas Astro en su estado descrito y la regla de 180 días. La fecha efectiva permanece vacía y no se publicó ninguna versión. Antes de publicar, completar la evidencia externa de proveedores y verificar que los hechos de cuenta, región, configuración y destinatarios correspondan a la operación real; corregir cualquier discrepancia factual que se encuentre y registrar el cambio para decisión humana.

El aviso recibido el 23-10-2026 y su parche no publicado se compararon como historial; no se aplicó el parche de WhatsApp. Se conservan secciones condicionales de WhatsApp en la landing sin afirmar activación.
