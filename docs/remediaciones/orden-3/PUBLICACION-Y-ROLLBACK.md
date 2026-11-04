# Paquete para revisión, publicación futura y rollback

## Candidato local

Landing en `C:/Users/LAP/Desktop/LandingSaaS`, rama base `feature/migration-astro`, HEAD base `55c9c72867677be894f301727d964dd023564269`. Archivos de cambio: `frontend/src/components/seo/GoogleAnalytics.astro`, `frontend/src/components/ui/CookieConsentBanner.astro`, `frontend/src/components/ui/RegisterModal.astro`, `frontend/src/layouts/Base.astro`, `frontend/src/pages/aviso-de-privacidad.astro`, `frontend/src/pages/cookies.astro` y `frontend/scripts/orden3-privacy-browser.py`. El repo SaaslyVet aporta este expediente; su app no cambia.

Build actual usa Astro static y salida local `frontend/dist/`. `dist/` no es una publicación ni una aprobación. Sin commit, push, PR, release, publicación, promoción legal ni cambio de cuenta en este encargo.

## Antes de publicar — tarea del usuario

1. La aprobación textual ya fue recibida para [`aviso-de-privacidad.astro`](../../../../LandingSaaS/frontend/src/pages/aviso-de-privacidad.astro), [`cookies.astro`](../../../../LandingSaaS/frontend/src/pages/cookies.astro) y la regla de 180 días. Antes de publicar, completar la acreditación de proveedores y cotejar que los hechos de cuenta/destinatarios coincidan con la operación; fecha efectiva sigue pendiente.
2. Completar fichas O10 desde cuentas y contratos privados. Identificar hosting/correo, región efectiva, subproveedores, retención y mecanismo de aceptación. Confirmar Formspree (incluida exportación/destino/borrado), Google (ID, enlaces de productos/ajustes de anuncios, retención/términos) y proveedores históricos. No usar enlaces públicos como aceptación.
3. Confirmar el identificador público GA4 a usar en el entorno de build, sin compartir valores privados. El código ignora un valor ausente o inválido y deja el sitio operativo sin tag. No compilar con dato de cuenta de producción en un test que no intercepte todo el tráfico.
4. Ejecutar build reproducible con lockfile/runtime del proyecto, luego pruebas locales de navegador. Antes de navegar, bloquear toda solicitud externa, incluidos Google, Formspree, correo y otros destinos. Revisar el consentimiento con el runtime GA4 efectivo y el tráfico de recolección interceptado; el mock actual no cierra cese tras retirada.
5. Elegir fecha efectiva solo al aprobar; verificar por HTTPS que páginas de aviso y cookies muestran el texto aprobado. No sustituir la fecha de borrador por una fecha actual automática.
6. Evaluar materialidad. Cambios de finalidades, destinatarios, retención/derechos son materialmente relevantes para revisar; decisión y promoción corresponden al usuario según [`legal-version-sync.md`](../../runbooks/legal-version-sync.md). Solo después de publicación verificada decidir manualmente la versión/app y su reaceptación. No ejecutar seeds durante este expediente.
7. Ejecutar procedimiento de retención/eliminación real con registros elegibles y datos históricos, en cuentas del usuario; archivar prueba saneada mínima y respuesta sobre backups. No tomar la simulación como borrado real.

## Secuencia técnica propuesta (manual)

1. Guardar revisión previa y build de landing actualmente publicada bajo control del operador.
2. Aplicar únicamente el diff listado; revisar `rtk git diff` y archivos sin seguimiento para excluir trabajo ajeno. Instalar dependencias solo según lockfile si el operador necesita reproducir; esta entrega no actualizó dependencias.
3. Ejecutar `npm run build` en `LandingSaaS/frontend`; ejecutar el script con servidor preview restringido a loopback y tercero interceptado. Guardar resultado sin valores de IDs ni formularios.
4. Desplegar por el proceso de hosting que el titular identifique y autorice. Comprobar rutas por HTTPS, links/fecha y ausencia de llamadas previas a consentimiento. No abrir tráfico de formulario de prueba a Formspree real.
5. Tras publicación, iniciar una sesión limpia, verificar decisión inicial, aceptar y retirar con runtime real. Repetir en una segunda pestaña. Confirmar que la captura no contenga PII. Registrar lo observado y cualquier solicitud en vuelo.

## Rollback seguro

- Si falla visual/build, volver a la revisión de landing aprobada previamente; no alterar datos de usuario ni tocar cuenta de proveedor.
- Si el retorno de código anterior reintroduce medición, desplegarla con GA deshabilitado (ID ausente/inválido) hasta corregir y probar el consentimiento. No usar una versión que cargue GA sin aceptación; preservar/revocar la preferencia de forma conservadora.
- Un rollback de UI no borra solicitudes ni revierte eliminaciones ya ejecutadas. No restaurar prospectos eliminados desde exportaciones/backups por este proceso.
- Registrar revisión anterior/nueva, hora de decisión, motivo, páginas comprobadas y responsable. Después del rollback volver a revisión/aprobación; no promover documento legal o versión de app.

## Aprobaciones externas que faltan

Evidencia contractual/configuración y cadenas de proveedores; cierre del cese del runtime GA real; ejecución externa de retención/borrado; fecha efectiva y publicación HTTPS; evaluación humana de materialidad/sincronización posterior. La aprobación del texto ya quedó registrada. WhatsApp, Meta, B2 media y restantes IDs aplazados no se habilitan por este paquete.
