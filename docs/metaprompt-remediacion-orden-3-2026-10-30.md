# Metaprompt ejecutor — Orden 3: web pública y proveedores actuales

Preparado el **30-10-2026**. Copiar el bloque siguiente al agente que implementará. Este archivo no inicia la ejecución ni acredita cambios de aplicación.

---

Actúa como agente implementador de SaaslyVet. Implementa el alcance local del orden 3 mediante entregas pequeñas y evidencia. El usuario ya completó las decisiones principales; tu trabajo es ejecutar el plan, no volver a producir únicamente otra propuesta.

Lee completo y usa como contrato `C:/Users/LAP/Desktop/VeterinariaSaaS/docs/plan-remediacion-orden-3-2026-10-30.md`. Si una instrucción posterior del usuario lo modifica, registra la decisión y su efecto. No amplíes el alcance por el nombre general «orden 3».

## Objetivo autorizado

Preparar un candidato local verificable que respete el consentimiento de GA4, el propósito y la conservación de prospectos de Formspree, y deje aviso/cookies y expediente de proveedores actuales listos para revisión. El usuario gestiona cuentas externas, aprobaciones, eliminación real de copias y publicación.

Repositorios autorizados: `C:/Users/LAP/Desktop/VeterinariaSaaS` y `C:/Users/LAP/Desktop/LandingSaaS`; verifica que sean los correctos antes de editar. Si hay límites del entorno para escribir en la segunda ruta, usa el mecanismo de acceso autorizado o entrega un parche exacto y comprobable con esa limitación explícita; no declares aplicado lo que no pudiste aplicar.

## Decisiones que no debes volver a preguntar

- GA4 se conserva y solo carga tras aceptación explícita. Rechazo y retirada posterior disponibles. No publicidad, remarketing ni pings previos a aceptación.
- Formspree se conserva. **Nombre, apellido, clínica y correo obligatorios; teléfono opcional.** No elimines estos campos alegando minimización: la elección concreta del usuario manda. Minimiza datos accesorios, copias y medición accidental.
- Finalidad: atender solicitud y seguimiento de ese acceso/demo, sin campañas generales ni newsletters. La aceptación del formulario es independiente de GA4.
- Solicitudes sin relación activa: **180 días naturales desde el último contacto efectivo sobre esa solicitud**. Si no hubo contacto posterior, parte del envío. Correos automáticos y campañas no reinician el plazo. No inventar fechas ni llamar relación activa a un envío automático.
- La eliminación real en Formspree, correo, exportaciones y demás cuentas la hará el usuario. Tú preparas procedimiento y pruebas sintéticas. No borrar datos reales.
- El usuario revisa y aprueba aviso, plazos e instrumentos contractuales. Entrega propuestas concretas sin fabricar aprobaciones, contratos o fechas efectivas.
- El usuario prefirió no identificar hosting de landing ni proveedor de correo: consérvalos como **NO IDENTIFICADOS / PENDIENTES DE ACREDITAR**. No vuelvas a detener el trabajo para preguntarlos ni declares completo ese inventario.
- Puedes cambiar código local y probar aisladamente. Conserva la base habitual, aunque tenga datos demo. El VPS queda excluido: sin conexiones, pagos, reactivación, despliegues ni pruebas de sus servicios.
- Sin commit/push/PR/merge, publicación, promoción legal ni aceptación de cuentas automáticos.

## Frontera del encargo

Implementación principal: **O11**. Expediente de proveedores actuales: **O10**. Preparación parcial del aviso: **O05**; instrucciones futuras condicionadas: **O06** y parte de **O09** correspondiente a entregar la landing. Mantén la matriz de 13 IDs del plan.

**O02, O03, O04, O07, O08, O15 y G06 quedan aplazados; O12 no incluye implementación de endpoints.** No activar WhatsApp, crear B2 media, cambiar su política, hacer restore, enviar mensajes Meta ni ensayos de recepción. B2 backups es un tratamiento separado que sí se documenta en O10, sin operar su cuenta. No abrir trabajo de órdenes 1/2, arquitectura, analítica clínica, identidad fuerte o nuevas capacidades del bot. Conservar excepciones aceptadas B9/D29 y alertas de purga.

## Preflight

1. Lee AGENTS.md e instrucciones aplicables en ambos repositorios, además de RTK. Prefiere grafo MCP para descubrir código; comprueba proyecto/indexación. Si resulta insuficiente para Astro o está desactualizado, explica el fallback y contrasta archivos actuales. Usa RTK en comandos cuando corresponda.
2. Registra revisiones, estado inicial y cambios existentes. No limpies, restablezcas, sobrescribas ni incluyas archivos ajenos como tuyos. Hay trabajo de otros órdenes en VeterinariaSaaS y archivos sin seguimiento en LandingSaaS.
3. Revisa scripts/configuración no sensibles antes de ejecutar. No leas/exportes valores de secretos, archivos privados de cuentas o datos de prospectos. Usa IDs y datos sintéticos, no endpoints reales para enviar pruebas.
4. Elige runtime y dependencias compatibles con locks. Reutiliza lo instalado; no actualices stacks ni instales globalmente para facilitar el encargo. Si necesitas una herramienta adicional, justifica y limita su uso.
5. Los servidores de prueba serán tuyos, en loopback y puertos libres. Los scripts actuales de landing anuncian `0.0.0.0`; ajusta la invocación de prueba. No cierres procesos ajenos. Sin DB habitual ni efectos externos.

## Puntos de partida que debes revalidar

- `frontend/src/components/seo/GoogleAnalytics.astro` en LandingSaaS **ya** tiene default denied y carga diferida. No lo presentes como ausente ni implementes un segundo GA4. Retirada con tag cargado exige comprobar comportamiento, no solo estado de cookies.
- `frontend/src/components/ui/CookieConsentBanner.astro` ya permite preferencias. La expresión `stored() !== 'denied'` puede marcar analítica sin elección previa; la primera elección opcional debe estar desmarcada. Armoniza valores inválidos, fallos de almacenamiento y carga del banner.
- `frontend/src/layouts/Base.astro` integra GA4 y banner; el footer reabre preferencias. Revisa todas las rutas y el HTML generado.
- El formulario real está en `frontend/src/components/ui/RegisterModal.astro`, con POST/AJAX a Formspree. `contacto.astro` no contiene ese formulario. Valida también sin JavaScript y el efecto de `novalidate`.
- `frontend/src/pages/aviso-de-privacidad.astro` y `cookies.astro` ya tienen contenido de consentimiento. El aviso repite **12 meses desde el envío**, contrario a la nueva decisión de 180 días desde contacto efectivo. Corrige todas las referencias relacionadas sin alterar plazos ajenos.
- El aviso local usa recepción de «solicitud completa» en ARCO; contrástalo con recepción original y fuentes vigentes. La revisión del usuario se hace sobre una propuesta concreta.
- `docs/compliance/vendors.md` mezcla información histórica con estados por confirmar. Una suspensión del VPS no acredita eliminación de datos ni estado actual de todos los proveedores.
- `docs/compliance/inbox-privacy-review-2026-10-23/README.md` enlaza un aviso/patch no publicados. Compáralos; no apliques ciegamente el parche de WhatsApp ni sobrescribas contenido actual. Mantén sus secciones condicionales sin cambiar la política ni atribuir activación.
- `docs/runbooks/legal-version-sync.md` separa publicación y promoción humana de versión. No ejecutes seeds ni cambies `is_current`.

## Ejecución E0–E5

Sigue las entregas del plan: E0 línea base; E1 contratos/borradores; E2 GA4; E3 formulario; E4 conservación/proveedores; E5 verificación y entrega. Continúa con lo independiente mientras se resuelven aprobaciones realmente necesarias. No pidas permiso para decisiones ya fijadas ni uses pendientes de cuentas externas para dejar sin implementar el alcance local autorizado.

GA4: estado válido único, denegación por defecto, carga una sola vez tras aceptación, ausencia de pings previos y de PII. Preferencias siempre accesibles. Resolver negativa/retirada con runtime previamente cargado, incluidas recarga, navegación y pestañas abiertas. Cambiar consent a denied o remover el script no basta como evidencia. Elegir una estrategia compatible y probarla; documentar solicitudes que ya estuvieran enviadas/en vuelo y el límite de cookies accesibles. No borrar cookies ajenas. No trasladar los 180 días de prospectos a la preferencia o a Google por analogía.

Formulario: campos pactados, teléfono opcional real, propósito explícito y consentimiento independiente de cookies. Sin adjuntos ni campos clínicos nuevos. Límites razonables de entrada y payload, sin PII en URL/analítica/logs. Éxito solo con respuesta exitosa simulada; errores/reintento/doble clic coherentes. Revisar el fallback sin JavaScript: los controles nativos deben seguir protegiendo el envío, o el fallback se debe bloquear con información accesible y alternativa. No afirmar validación server-side propia cuando el endpoint pertenece a Formspree.

Conservación: procedimiento de 180 días para solicitudes sin relación activa con registro de contacto efectivo, selección de vencidos, cierre de relaciones y revisión de fechas desconocidas. Incluir Formspree, buzón, reenvíos, enviados, papelera, exportaciones e integraciones confirmadas; explicar copias/respaldos del proveedor sin prometer borrado físico no comprobado. No crear un CRM o retención indefinida para resolverlo. La ejecución real queda para el usuario.

Proveedores: ficha por tratamiento; Google, Formspree, hosting/correo no identificados y servicios actuales/históricos registrados del proyecto (Hetzner, B2 backups, Sentry, Discord y auxiliares pertinentes). Finalidad, rol, categorías, región efectiva, subproveedores, conservación, instrumento/versionado, mecanismo de aceptación y evidencia. Marca campo desconocido. Un enlace público no prueba adhesión. No confundir proveedores de nombres similares ni inventar DPA; las cuentas y contratos las confirma el usuario. No realizar envíos, aceptación ni cambios en servicios externos.

Aviso/cookies: presentar un texto candidato consistente con código y decisiones. Revisar fuentes oficiales vigentes enlazadas en el plan; separar información factual de decisión jurídica pendiente. No certificar cumplimiento por tests. Sin cambiar fecha efectiva a una publicación inexistente. Preparar materialidad/sincronización legal posterior, sin promover versión.

## Pruebas y evidencia obligatorias

- Build real de la landing, comprobaciones configuradas y pruebas de comportamiento pertinentes. No afirmar que existe una suite que package.json no declara; agregar pruebas acotadas si es necesario. No hacer un rediseño global o arreglar todo el lint de la app.
- Navegador local con contextos limpios; interceptar/bloquear terceros **antes** de navegar. Registrar solicitudes intentadas a GA/Formspree sin permitir envíos reales, correo o mediciones a cuentas existentes. ID y datos sintéticos.
- GA4: ID ausente, ninguna elección, rechazo, preferencia desmarcada, aceptación/doble evento, carga única, navegación, persistencia, almacenamiento inválido/bloqueado y retirada tras carga. Sin publicidad ni PII por campos/URL/referrer. Cookies de host/apex y negativa en pestañas abiertas.
- Los mocks prueban el contrato local; no prueban todos los efectos del código externo. Para cerrar cese tras retirada, aporta prueba compatible con runtime cargado y tráfico interceptado o registra la parte como no acreditada. Nunca conviertas un mock en PASS operativo de Google.
- Formulario: obligatorios, teléfono vacío, checkbox sin marcar, enviar tras rechazar GA4, payload, 4xx/5xx/no JSON, desconexión, reintento, doble clic y sin JS. No solicitudes reales a Formspree.
- Reloj/dataset sintético: antes, en y después del límite de 180 días; contacto efectivo y automático; relación activa/finalizada; revocación y fecha desconocida. No eliminar datos reales ni copiar históricos a fixtures.
- Teclado/foco, móvil, enlaces y texto renderizado coherentes. No recopilar PII en capturas o recibos. Las pruebas no sustituyen revisión contractual/configuración ni publicación.
- Diff y enlaces de documentación comprobados en ambos repositorios. Registra comandos, revisión y resultados honestos; separa fallos previos, del cambio y límites del entorno.

## Entrega final

Crea `C:/Users/LAP/Desktop/VeterinariaSaaS/docs/remediaciones/orden-3/` con los siete documentos del plan: README, DECISIONES, MATRIZ, EVIDENCIA, RETENCION-PROSPECTOS, PROVEEDORES y PUBLICACION-Y-ROLLBACK. Enlaza los cambios concretos de LandingSaaS. Guarda solo índices saneados en Git; evidencia contractual privada, documentos de identidad y PII quedan fuera del repositorio/chat.

En cada ID distingue la parte implementada localmente, la aplazada y la pendiente externa. El cierre técnico puede declararse solo para criterios probados. El conjunto permanece **PENDIENTE_DE_APROBACION_Y_OPERACION_EXTERNA** hasta aprobación final, configuración/contratos, eliminación real y publicación donde corresponda. No declarar cerrado todo el orden 3 ni habilitar WhatsApp por este trabajo.

Termina con un resumen breve de cambios, pruebas, límites reales y acciones del usuario. Si necesitas aprobación final, presenta el texto/diff listo para revisar y la decisión concreta; no pidas una autorización genérica para seguir. No hagas commit, push, PR, despliegue, promoción legal ni aceptación contractual.

---

Fuentes y criterios detallados: [plan acordado](plan-remediacion-orden-3-2026-10-30.md).
