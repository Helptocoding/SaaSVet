# Orden 3 — Privacidad de la web pública y proveedores actuales

Fecha: **30 de octubre de 2026**. Estado: **PLAN ACORDADO PARA IMPLEMENTACIÓN LOCAL**. Este documento prepara el trabajo de otro agente; no acredita remediación, publicación, aceptación contractual ni cumplimiento integral.

Base: [priorización](plan-remediacion-priorizado-2026-10-28.md), [inventario original](pendientes-documentados-2026-10-27.md) y respuestas del usuario en este chat. Ejecución: [metaprompt](metaprompt-remediacion-orden-3-2026-10-30.md).

## 1. Decisiones vinculantes

| Tema | Decisión del usuario / límite de ejecución |
|---|---|
| Alcance | Privacidad de la web pública y proveedores actuales. WhatsApp y sus requisitos específicos quedan aplazados. |
| Trabajo del futuro agente | Implementar cambios locales, preparar documentación y probar en entornos aislados. El usuario gestiona proveedores y publicación. |
| Repositorios | Verificar y trabajar localmente en `C:/Users/LAP/Desktop/VeterinariaSaaS` y `C:/Users/LAP/Desktop/LandingSaaS`. Respetar instrucciones y cambios existentes en ambos. |
| Infraestructura | VPS excluido: sin SSH, reactivación, pagos, despliegues ni comprobaciones remotas de sus servicios. La base habitual tampoco se modifica. |
| GA4 | Conservarlo; cargar únicamente tras aceptación explícita. Permitir rechazo y retirada posterior. No habilitar publicidad, remarketing ni consentimiento avanzado con envíos previos a la aceptación. |
| Formspree | Conservarlo. Mantener nombre, apellido, clínica y correo obligatorios; teléfono opcional. Esta elección concreta prevalece sobre una reducción adicional de campos. Minimizar datos accesorios y copias. |
| Finalidad del formulario | Atender la solicitud y dar seguimiento sobre ese acceso o demo. Sin campañas generales, newsletters ni finalidades nuevas. |
| Conservación de prospectos | Solicitudes sin relación activa: **180 días naturales desde el último contacto efectivo sobre la solicitud**. Mensajes automáticos y campañas no reinician el plazo. |
| Relaciones activas | Identificarlas y justificar su finalidad vigente. La excepción no convierte todos los prospectos en clientes ni permite conservar indefinidamente el formulario original. Separar categorías y plazos del servicio. |
| Datos históricos | Preparar inventario, selección y procedimiento; la eliminación en Formspree, correo, exportaciones y otras cuentas la ejecuta el usuario. No borrar datos reales por este encargo. |
| Aprobación | El usuario aprueba el aviso, decisiones de conservación e instrumentos contractuales. El agente entrega propuestas y marca lo pendiente; no firma ni acepta en su nombre. |
| Correo y hosting de landing | El usuario prefirió no identificar esos servicios. Dejarlos **NO IDENTIFICADOS / PENDIENTES DE ACREDITAR**, sin nuevas preguntas que detengan trabajo independiente. No inventar proveedores ni declarar completa la cadena. |
| Entrega | Entregas pequeñas con pruebas y criterios de cierre. Sin commit, push, PR, publicación ni promoción de versión legal automáticos. |

## 2. Alcance conciliado por ID

El alcance se redujo expresamente frente a la categoría original. Cada ID conserva su trazabilidad; el aplazamiento no equivale a remediación.

| ID | Tratamiento en esta entrega | Criterio / pendiente externo |
|---|---|---|
| O11 | **Principal: implementar y verificar localmente** consentimiento GA4 y privacidad/conservación de Formspree | Evidencia de navegador, formulario y textos coherentes. Publicación y configuración de cuentas por el usuario. |
| O10 | **Preparar expediente de proveedores actuales** y conciliar documentación | Instrumento aplicable, cuenta, región, finalidades y aceptación real solo con evidencia del usuario. Nunca cerrar por enlazar una política pública. |
| O05 | **Parcial: preparar aviso y cookies de web/proveedores actuales** | Revisión final, fecha efectiva y publicación por el usuario. No cerrar el aviso de WhatsApp por esta entrega. |
| O06 | **Solo preparación condicionada** del procedimiento de sincronización legal | La versión vigente de la app no cambia. Evaluar materialidad y promover solo después de publicación comprobada y nueva instrucción. |
| O09 | **Solo paquete de entrega de landing**: build, revisión y rollback propuesto | Sin release de app, migraciones de producción ni despliegues. El ID global permanece abierto en su alcance restante. |
| O02 | **Aplazado**: B2 dedicado a media | No provisionar, configurar ni activar. |
| O03 | **Aplazado**: purga/restore reales de media | No ensayos de proveedor, restauraciones ni confundirlo con los prospectos del formulario. |
| O04 | **Aplazado**: decisión B2 media / Meta | O10 sí incluye B2 de backups como tratamiento documentado actual o histórico por confirmar. |
| O07 | **Aplazado**: Meta y aceptación de recepción | No mensajes, pruebas de ticks ni activación. |
| O08 | **Aplazado**: cobertura y autorización de WhatsApp | No inventar responsables ni reabrir la excepción de alertas ya aceptada. |
| O12 | **Fuera del alcance de implementación**: endpoints ARCO de la app | Se conserva el procedimiento manual. Su coherencia con el aviso de prospectos sí se revisa documentalmente. |
| O15 | **Aplazado**: limpieza/captura de teléfonos de clínicas | Sin cambios masivos de registros ni rediseño del onboarding. |
| G06 | **Aplazado**: retención/purga de chat, metadata, flow y evidencias | Los 180 días de prospectos no se trasladan a estas categorías ni a los binarios WhatsApp. |

## 3. Evidencia local de partida y discrepancias

Inspección de archivos realizada el 30-10-2026; sin ejecutar la landing, enviar formularios, acceder a cuentas ni verificar lo publicado. El ejecutor debe revalidar sobre su candidato: ambos repositorios tienen cambios o archivos ajenos que deben preservarse.

| Fuente | Observación | Consecuencia para el plan |
|---|---|---|
| `LandingSaaS/frontend/src/components/seo/GoogleAnalytics.astro` | Ya contiene `consent default denied`, lectura de `ga_consent`, carga diferida y limpieza de cookies. La retirada cambia el consentimiento pero no demuestra por sí sola que un tag ya cargado deje de emitir. | El registro antiguo «sin banner/Consent Mode» es insuficiente como diagnóstico actual. Reparar brechas verificadas y probar la transición con el runtime cargado. |
| `LandingSaaS/frontend/src/components/ui/CookieConsentBanner.astro` | Ya permite aceptar, rechazar y reabrir preferencias. `stored() !== 'denied'` marca analítica cuando falta la elección; valores inválidos también requieren tratamiento consistente. | La analítica opcional debe empezar desmarcada sin una aceptación válida. No confundir ausencia de elección con consentimiento. |
| `LandingSaaS/frontend/src/layouts/Base.astro` y footer | Hay inclusiones de GA4/banner y control de preferencias. | Verificar orden real en HTML/build, todas las páginas y navegación; evitar duplicar componentes. |
| `LandingSaaS/frontend/src/components/ui/RegisterModal.astro` | El formulario real está en el modal; `contacto.astro` muestra canales de correo. Usa POST directo/AJAX a Formspree y checkbox de finalidad. | Probar ese modal, su fallback, validaciones y resultado. No modificar solo la página de contacto y declarar resuelto el formulario. |
| `LandingSaaS/frontend/src/pages/aviso-de-privacidad.astro` | Borrador local con fecha 22-08-2026, analítica opcional y **12 meses desde el envío** en varias secciones. | Conciliar todas las menciones con los nuevos 180 días y el evento de inicio aprobado. La fecha local no acredita una versión pública. |
| El mismo aviso, procedimiento ARCO | Usa «solicitud completa» como inicio del plazo; el procedimiento del repo principal registra la recepción original. | Preparar corrección y revisión del cómputo con fuente vigente; no posponer automáticamente la recepción hasta verificar identidad. |
| [vendors](compliance/vendors.md) | Incluye estados activos históricos y brechas que no incorporan todo el código actual de la landing. | Separar observación local, configuración de cuenta, operación histórica, suspensión y verificación pública. VPS inaccesible no demuestra eliminación de datos. |
| [paquete de privacidad 23-10](compliance/inbox-privacy-review-2026-10-23/README.md) | Aviso y parche preparados, no publicados, con cambios condicionales de WhatsApp. | Comparar versiones; no aplicar el parche completo sobre una landing diferente ni sobrescribir mejoras. Conservar decisiones y marcar lo ajeno a este alcance. |
| `LandingSaaS/frontend/package.json` | Astro; scripts de build/dev/preview; no suite de pruebas declarada en este archivo. | Reutilizar herramientas disponibles. Si hace falta, agregar pruebas de comportamiento acotadas; no inventar un comando de tests existente. |

## 4. Contrato técnico de GA4

1. Una primera visita, almacenamiento inexistente/inválido/inaccesible y rechazo deben mantener bloqueada la analítica: sin carga del tag, `config` efectivo, eventos, pings sin cookies ni conexiones anticipadas a sus dominios. La navegación y el formulario siguen funcionando. Un valor arbitrario de almacenamiento no debe activar ni ocultar definitivamente el banner.
2. Aceptar analítica es una acción específica. La preferencia opcional no aparece marcada por defecto. Los estados de publicidad permanecen denegados. No condicionar acceso o envío del formulario a aceptar GA4.
3. Aceptación válida carga una sola integración, incluso con múltiples clics/eventos. Si no hay Measurement ID, el sitio funciona sin tag ni error; no fabricar un ID real para probar.
4. Rechazar después de aceptar debe detener la medición posterior y conservar la negativa para la siguiente navegación/recarga. Resolver también el tag ya cargado: cambiar `analytics_storage` a `denied` o borrar el `<script>` no prueba por sí solo el cese. Elegir una estrategia compatible y demostrarla; puede requerir deshabilitar medición y recargar en estado denegado. No afirmar que se pueden retirar solicitudes ya enviadas o en vuelo.
5. Limpiar cookies propias de GA alcanzables en los dominios/rutas reales sin borrar sesión de app u otras cookies. Documentar límites de cookies inaccesibles; no prometer borrado de datos alojados por Google desde el navegador.
6. Mantener una sola fuente de estado y un esquema explícito. Si se agrega versión o caducidad de la preferencia, justificar la transición de `ga_consent` y documentarla; no atribuirle un plazo legal inventado ni confundirlo con los 180 días de prospectos. Ante materialidad incompatible, solicitar una nueva elección en lugar de migrar automáticamente una aceptación a finalidades ampliadas.
7. Reabrir preferencias desde todas las páginas pertinentes. Probar teclado, foco, etiquetas, móvil y controles de aceptación/rechazo utilizables. No convertirlo en un rediseño global de la landing.
8. No enviar campos del formulario, correo, teléfono, nombres, identificadores de cuenta ni PII de query strings/referrers a analítica. Revisar medición automática y eventos existentes. Restringir URLs/parametrización o redacción según lo necesario; no afirmar anonimato irreversible por usar GA4.

La elección técnica corresponde al modo básico: [Google distingue bloqueo previo del tag y modo avanzado con mediciones sin cookies](https://developers.google.com/tag-platform/security/concepts/consent-mode). La secuencia de configuración se contrasta con su [guía oficial](https://developers.google.com/tag-platform/security/guides/consent). La configuración real de la propiedad, retención, integraciones publicitarias y aceptación contractual siguen reservadas al usuario.

## 5. Formulario, finalidad y conservación

- Conservar exactamente los campos elegidos. No agregar texto libre, adjuntos, datos clínicos, contraseñas o información bancaria. Aplicar límites y validación razonables; retirar propiedades accesorias innecesarias. El cliente no garantiza por sí solo que el proveedor rechace envíos manipulados.
- El teléfono debe ser realmente opcional en UI, validación y payload. Solicitar acceso no equivale a autorizar campañas generales ni WhatsApp. No agregar newsletter ni casillas premarcadas.
- Mantener una confirmación específica para el tratamiento de la solicitud, con vínculo accesible al aviso y propósito comprensible. Mantener independiente la decisión GA4. Incorporar versión del aviso de forma coherente cuando proceda, sin afirmar que un campo oculto prueba identidad o consentimiento por sí solo.
- Verificar el POST tanto en el flujo AJAX como en el comportamiento sin JavaScript. Validación nativa, `novalidate`, casilla requerida, errores del proveedor y reintentos deben ser consistentes; si el fallback no puede cumplir el contrato, bloquearlo con explicación accesible y un canal alterno. No mostrar éxito si falla el envío.
- Evitar PII en URL, logs, capturas, mensajes técnicos, analítica y almacenamiento del navegador. No crear un CRM ni una nueva base de prospectos para resolver este encargo.
- El evento de inicio de retención será el envío hasta que exista un contacto efectivo posterior sobre esa solicitud. Un envío automático, recordatorio o campaña no lo actualiza. La evidencia de interacción debe ser trazable y mínima. Un correo saliente automático o no atendido no acredita relación activa.
- Definir en el procedimiento cómo registrar relación activa y su finalización; al terminar, documentar qué datos siguen sujetos al plazo de prospectos y qué documentación pertenece a otra finalidad justificada. No reiniciar de oficio el reloj para retener datos históricos vencidos.
- Preparar selección con fechas y casos sintéticos: exactamente en el límite, después de 180 días, contacto efectivo, automático, relación activa, revocación y ausencia de fecha. Las fechas desconocidas requieren revisión del usuario; nunca inventarlas ni usar la fecha de despliegue como sustituto silencioso.
- Cubrir Formspree, buzón destinatario, enviados/reenviados, papelera, exportaciones, hojas de cálculo e integraciones que el usuario confirme. Definir revisión periódica, eliminación, incidencias y prueba mínima sin contenido. Los backups/ciclos del proveedor requieren explicación diferenciada y confirmación; una eliminación en el dashboard no demuestra borrado de todas las copias.
- La eliminación real la ejecuta el usuario. Entregar un procedimiento verificable; no construir una supuesta automatización local que no alcanza los servicios externos. La retención técnica de GA4, preferencias y datos de clientes de la app no hereda este plazo.

[Formspree documenta su tratamiento y conservación](https://formspree.io/legal/privacy-policy/) y permite [exportaciones de solicitudes](https://help.formspree.io/articles/form-and-project-settings/exporting-submissions/). Esas fuentes no acreditan la cuenta, configuración ni un contrato aplicable del usuario. No confundir Formspree con FormStride o Formspark ni inventar una URL de DPA.

## 6. Proveedores y revisión del aviso

Preparar una ficha por tratamiento, no solo por marca: Google/GA4; Formspree; hosting de landing y correo no identificados; y los servicios actuales/históricos del proyecto documentados como Hetzner, B2 backups, Sentry y Discord. Conciliar también servicios auxiliares del registro, sin convertir componentes self-hosted en contratos de terceros. Detectar en archivos públicos nuevos destinos si existen, sin activar ni probar integraciones. Meta y B2 media quedan planificados, separados y aplazados.

Cada ficha debe contener finalidad, rol real, categorías de datos, origen/destino, cuenta sin secretos, región efectiva confirmada o desconocida, subproveedores, retención y borrado, instrumento aplicable/versionado, mecanismo de adhesión, aprobador/fecha y referencia privada a evidencia. Estado por campo: preparado, pendiente del usuario, acreditado con evidencia o no aplicable justificado. Una política pública no equivale a aceptación contractual; ubicación de sede no equivale a región efectiva. No importar automáticamente una conclusión GDPR a una cuenta mexicana ni llamar «transferencia» a toda comunicación sin revisar roles.

Actualizar borradores de aviso y cookies alrededor del tratamiento real: formulario y finalidad aprobada, 180 días, mecanismo de derechos/revocación, analítica opcional, proveedores y límites de eliminación. Mantener condicionales las secciones de WhatsApp existentes; no activarlas, ampliar promesas ni reabrir su diseño. Evitar contradicciones entre copia de landing, revisión 23-10 y documentos del repo principal; preservar los expedientes históricos y generar una conciliación nueva.

La [LFPDPPP publicada por la Cámara de Diputados](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf), consultada el 30-10-2026, indica reforma 14-11-2025. El artículo 31 parte de la recepción de la solicitud; preparar la corrección de «solicitud completa» y comprobar el cómputo aplicable con el procedimiento vigente. La aprobación del usuario queda pendiente hasta disponer de un texto concreto revisable. No afirmar certificación jurídica por compilar Astro ni copiar plazos o conclusiones sin fuente vigente.

La versión candidata y la fecha de revisión se distinguen de la fecha efectiva. Mientras no se publique, no modificar `LegalDocument.is_current`, no ejecutar seeds de promoción ni fabricar aceptaciones. Entregar instrucciones según [legal-version-sync](runbooks/legal-version-sync.md); materialidad y promoción posterior requieren decisión humana. Una publicación futura de este alcance no cierra los requisitos pendientes de WhatsApp.

## 7. Entregas y criterios de cierre

| Entrega | Trabajo concreto | Cierre verificable |
|---|---|---|
| E0 — Línea base | Leer instrucciones de ambos repos; registrar revisiones y cambios previos, contrastar índice/grafo con fuentes reales, inventariar destinos y textos. Crear matriz de los 13 IDs de §2. | Mapa de archivos y discrepancias; alcance reducido explícito; sin atribuir estado público a archivos locales. |
| E1 — Contrato y borradores | Registrar decisiones de este plan, reconciliar aviso/cookies/vendors, diseñar registro mínimo y procedimiento de conservación de prospectos; preparar fichas contractuales. | Propuesta concreta revisable, sin inventar proveedor, fecha, DPA o aprobación. Trabajo técnico independiente continúa mientras el usuario revisa. |
| E2 — Consentimiento GA4 | Corregir únicamente brechas observadas en integración/banner/preferencias; cubrir primer acceso, aceptación y retirada con runtime cargado. | Pruebas de DOM/estado y solicitudes intentadas; sin analítica antes de aceptar ni tras rechazo/retirada resuelta, sin duplicados ni publicidad. Limitaciones de simulación declaradas. |
| E3 — Formulario | Mantener campos/propósito acordados; alinear aviso resumido, validación y payload; errores y fallback; eliminar PII de analítica accidental. | Casos positivos/negativos y de teléfono vacío, consentimiento independiente, sin envíos reales al proveedor ni éxito falso. |
| E4 — Conservación y proveedores | Validar reglas con dataset sintético; documentar copias, selección, ejecución manual, incidencias y evidencia que aportará el usuario. Conciliar vendors con operación desconocida. | Casos de frontera y reloj demostrados; procedimiento aplicable; cada incertidumbre identificada. Sin eliminación ni aceptación externa. |
| E5 — Entrega integrada | Build y pruebas pertinentes; revisión visual local; paquete de publicación/rollback para usuario, matriz de resultados y lista breve de decisiones finales. | Candidato reproducible en ambos repos, cambios delimitados y documentación consistente. No declarar cerrado el orden 3 completo ni publicar. |

E2 y E3 pueden avanzar con las decisiones ya fijadas, sin esperar cuentas externas. El agente debe implementar el alcance local; no detenerse tras repetir este plan. Una aprobación que aún falte se solicita al final sobre el texto/cambio concreto, salvo que sea indispensable para una parte dependiente. Otras entregas continúan.

## 8. Verificación aislada

1. Usar un proceso local propio y puertos libres, ligado a loopback. Leer scripts antes de iniciarlos: los actuales anuncian `0.0.0.0`; ajustar la invocación de prueba sin exponer el servidor a la red. No detener servicios ajenos.
2. Reutilizar dependencias/herramientas instaladas compatibles con locks; no actualizar stacks por este encargo. Ejecutar el build existente y las comprobaciones que realmente estén configuradas. No presentar `astro build` como prueba de comportamiento de consentimiento.
3. Navegador con contextos limpios, ID sintético y datos sintéticos. Interceptar y bloquear todo tráfico de analítica, Formspree, correo y demás efectos externos antes de navegar. Probar solicitudes **intentadas**, no solo cookies o respuestas de red abortadas. No contactar el endpoint real ni dar de alta prospectos.
4. GA4: sin ID, sin elección, denegación, aceptación, doble clic, recarga, navegación, reapertura, almacenamiento bloqueado/corrupto y retirada tras carga. Incluir cookies de host/apex y el mismo estado en pestañas ya abiertas; sincronizar la negativa cuando corresponda. Probar que el formulario no alimenta medición de PII y que aceptar el formulario no acepta analítica.
5. Los mocks del tag prueban el contrato local de carga/eventos. No acreditan por sí solos todos los efectos de la biblioteca externa. Para afirmar cese tras retirada, aportar prueba compatible con el runtime correspondiente y tráfico interceptado, o declarar esa parte no acreditada y mantenerla como requisito de cierre. Nunca enviar mediciones a una propiedad real para obtener evidencia.
6. Formulario: payload exacto, campos obligatorios, teléfono vacío, casilla sin marcar, rechazar GA4 y enviar, respuesta no JSON/4xx/5xx, desconexión, doble envío y reintento. Pruebas con JavaScript activado y desactivado. Mocks explícitos; no simular aceptación por el usuario real.
7. Conservación: reloj controlado y ejemplos sintéticos, registros históricos sin fecha, relación activa/finalizada, retirada y copias. El procedimiento define evidencia de eliminación y fallos; no cerrar ejecución real con una simulación.
8. Teclado, foco, controles legibles, enlaces a privacidad/cookies, móvil y consistencia del texto renderizado. Capturas y recibos sin PII, claves, IDs de cuentas reales ni contenido de formularios reales.
9. No se requieren cambios de DB para el alcance web. Si surge una necesidad real, justificarla y limitar validación a una base aislada con datos sintéticos y allowlist de conexión; nunca usar la habitual por ser demo. No añadir migraciones o nuevos endpoints ARCO por conveniencia.
10. Registrar comando, repositorio/revisión, entorno, resultado y limitación. Comprobar diff y enlaces; no ocultar errores existentes ni confundir archivos sin seguimiento con entregables propios. No ejecutar escaneos de seguridad nuevos, campañas B9/D29, restore ni remediación de otros órdenes.

## 9. Entregables del ejecutor y cierre

Crear expediente `docs/remediaciones/orden-3/` en VeterinariaSaaS con:

- `README.md`: estado del alcance local, candidato de ambos repositorios y límites.
- `DECISIONES.md`: contrato implementado y conciliación de borradores, sin atribuir aprobaciones nuevas.
- `MATRIZ.md`: los 13 IDs de §2 con evidencia, parte cerrada y parte aplazada/pendiente.
- `EVIDENCIA.md`: comandos, resultados, pruebas de navegador, fixtures y límites de simulación.
- `RETENCION-PROSPECTOS.md`: procedimiento de 180 días, copias, casos y ejecución reservada al usuario.
- `PROVEEDORES.md`: fichas/índice saneado, estado por campo y pendientes; contratos/datos privados fuera de Git.
- `PUBLICACION-Y-ROLLBACK.md`: diff/candidato, aprobaciones pendientes, build, pasos del usuario para publicar y verificar HTTPS, evaluación de materialidad y promoción legal posterior separada. Rollback no puede reactivar analítica sin consentimiento ni prometer restaurar datos ya eliminados.

El resultado local podrá declararse **IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE** solo para criterios con pruebas suficientes. El conjunto quedará **PENDIENTE_DE_APROBACION_Y_OPERACION_EXTERNA** mientras falten aprobación final, evidencia contractual/configuración, conservación ejecutada o publicación. Las partes excluidas se mantienen **APLAZADAS_POR_ALCANCE**. No se permite convertir pendientes desconocidos en PASS ni usar el cierre parcial para habilitar WhatsApp.

El final debe distinguir cambios realizados, pruebas, riesgos o límites concretos y acciones del usuario. Incluir rutas de ambos repositorios y lista corta de cuestiones realmente pendientes. No repetir preguntas ya respondidas ni pedir credenciales.
