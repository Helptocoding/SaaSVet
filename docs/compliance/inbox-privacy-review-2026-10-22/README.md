# Expediente de revisión: WhatsApp y media

Estado: **PREPARADO PARA REVISIÓN**, 22 de octubre de 2026. No publicado, firmado ni
aceptado. B2 operativo aún no existe por confirmación del usuario. Meta/recepción
se validarán después. El procesamiento de media permanece apagado.

## Aviso preparado

[Aviso completo en Astro](aviso-de-privacidad.astro) y
[parche para LandingSaaS](aviso-de-privacidad.patch). Se parte del borrador local
existente, conservando sus cláusulas ajenas al Inbox. El parche incluye los cinco
tipos entrantes, cómputo de 180 días desde el almacenamiento, acceso restringido,
eliminación periódica con acceso bloqueado si falla y distinción entre cifrado
operativo de B2 y backups cifrados con age. No promete antivirus, interpretación
de adjuntos por IA ni media saliente.

La fecha propuesta `2026-10-22` identifica este borrador; debe cambiarse a la fecha
real de publicación si se publica otro día. La copia no es un proyecto Astro
independiente y no se ha compilado como landing. Aplicar el parche al repo de
landing solo después de revisar su estado local y compilar allí antes de publicar.
La transformación de sintaxis con el compilador Astro instalado pasó sin
diagnósticos; [recibo de sintaxis](../../evals/inbox-readiness-2026-10-22/privacy-syntax.json).

La consulta web del aviso público mostró un texto anterior (24 de junio de 2026).
La descarga directa posterior falló en el handshake TLS; por tanto, **la versión
viva debe comprobarse de nuevo antes de promover la versión legal**. No se ha
desactivado la comprobación TLS. Las fuentes y sus hashes están en
[preparation.json](preparation.json); las descargas oficiales se conservan en el
directorio privado ignorado del expediente de ejecución.

## Ficha preparada para DPA y tratamiento internacional

| Campo del expediente | Contenido propuesto / situación |
|---|---|
| Cliente del proveedor | Operador de SaaslyVet; verificar identidad contractual y cuenta B2 al crearla. El aviso identifica a Felipe Díaz. |
| Cadena de instrucciones | Clínica responsable → SaaslyVet encargado → proveedor de almacenamiento. |
| Finalidad | Conservar y entregar adjuntos entrantes del Inbox a personal autorizado de la clínica; gestionar expiración y solicitudes de derechos. |
| Titulares | Clientes/contactos de la clínica y personas identificables incidentalmente en los mensajes/archivos; personal que participa en la conversación. |
| Datos | Teléfono/identificadores asociados en la aplicación, binarios de imagen/audio/video/documento/sticker, captions/metadatos; los objetos pueden incluir datos personales sensibles incidentales. |
| Operaciones del proveedor | Almacenamiento, recuperación, cifrado gestionado por el proveedor y eliminación de objetos/versiones. No utilización para fines propios ni entrenamiento autorizado por este expediente. |
| Conservación operativa | Disponibilidad de binarios durante 180 días desde `persisted_at`; tombstone y texto separados. Purga física periódica con incidencias visibles. Validar y aprobar el plazo de purga física efectivo antes de activar. |
| Ubicación | Región B2, ubicación efectiva y posibles accesos internacionales: **POR DEFINIR**, no asumir México ni que la sede corporativa equivale a región del bucket. |
| Seguridad exigida | Bucket privado dedicado, SSE-B2/AES256, TLS, key mínima separada de backups, sin Object Lock, proxy autenticado por clínica, purga de todas las versiones. |
| Subencargados / incidentes | Revisar lista vigente del proveedor, condiciones de cambios, notificación de incidentes, asistencia a derechos y terminación. Archivar versiones aplicables al contratar. |
| Responsable de aprobar | Titular autorizado del contrato de SaaslyVet, con revisión del tratamiento/ubicación y de la relación con las clínicas. **Sin aprobación registrada.** |

Fuente contractual localizada: [DPA de Backblaze para EEA/EU](https://www.backblaze.com/company/policy/dpa-for-eea-eu-residents),
fecha indicada 20-09-2022. Su ámbito declarado depende de GDPR. **No basta archivar
este enlace para acreditar un DPA aplicable a la operación mexicana**: confirmar
con el proveedor qué contrato/addendum cubre la cuenta y los tratamientos descritos.
Determinar también la clasificación y requisitos de la comunicación internacional
(encargo/remisión/transferencia, según corresponda); la redacción del aviso debe
reflejar esa decisión y la región elegida.

Para cerrar el expediente se conservarán: contrato/addendum aplicable y versión,
identidad del cliente, cuenta y región, mecanismo de adhesión/aceptación realmente
utilizado, fecha, aprobador y evidencia privada con hash. No registrar aquí claves,
documentos de identidad ni adjuntos de pacientes. Ninguno de estos campos de
aceptación se ha completado artificialmente.

## Publicación y reconsentimiento preparados

1. Revisar aviso y ficha DPA, resolver ubicación y purga física y aprobar el texto.
2. Aplicar el parche en la landing; ajustar la fecha efectiva, ejecutar su build y
   publicar mediante el release autorizado. Verificar texto y fecha por HTTPS.
3. Después de publicar, promover **solo privacy** siguiendo
   [legal-version-sync](../../runbooks/legal-version-sync.md). Desde `backend`, el
   comando preparado es el siguiente, sustituyendo ambas fechas por la publicada:

   ```powershell
   rtk proxy python manage.py seed_legal_documents --doc-type privacy --version 2026-10-22 --effective-date 2026-10-22 --url https://www.saaslyvet.com/aviso-de-privacidad
   ```

4. Con cuentas de prueba de ADMIN/VET/ASSISTANT, verificar que la nueva versión
   exige aceptación, aceptar personalmente como usuario de prueba y verificar su
   registro. Conservar las aceptaciones anteriores. Nunca aceptar por usuarios
   reales ni fabricar evidencia. No cambiar términos/cookies por este hito.
5. Registrar la aprobación y publicación reales; solo entonces evaluar activación
   junto a B2, Meta/recepción y los demás gates. El comando anterior **no se ejecutó**.

## ARCO y restauraciones

Procedimiento operativo actualizado en [arco.md](../arco.md), incluida la purga
anticipada con fencing, borrado de versiones y verificación del proxy. El registro
de una solicitud debe contener folio, organización, verificación de identidad,
instrucción de la clínica, alcance y fundamento de retención, UUID afectados,
ejecutor, fecha de bloqueo y purga, resultado y controles tras restauración.
Mantener ese registro fuera de repositorios y separado del ciclo de backups que
pueda restaurar los datos. No incluir binarios ni PII en recibos técnicos.

Los plazos de respuesta/ejecución y ampliación se contrastaron con los artículos
2.VIII y 31 de la [LFPDPPP vigente](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf).
La recepción de la solicitud se registra inmediatamente; los requisitos de identidad
no autorizan inventar una nueva fecha de recepción.
