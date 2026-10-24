# SaaSLyVet — Decisión de política de retención y purga de medios de WhatsApp

**Fecha:** 22 de octubre de 2026  
**Estado:** Decisión de política definida; validación operativa pendiente  
**Ámbito:** Medios entrantes del Inbox de WhatsApp almacenados en el backend de medios de SaaSLyVet  
**Dependencias:** B2, mantenimiento de medios, autorización de acceso, observabilidad y restauración de backups

## 1. Decisión

SaaSLyVet adopta la siguiente política de retención y purga para los medios entrantes comprendidos en este ámbito:

1. **Disponibilidad máxima:** 180 días naturales desde la persistencia correcta del medio, tomando `persisted_at` como referencia.
2. **Expiración:** al alcanzar el vencimiento, el medio deja de estar disponible para consulta o descarga, independientemente de que la purga física haya finalizado.
3. **Purga operativa:** la eliminación del objeto y de las versiones y marcadores de borrado pertinentes debe completarse dentro de un máximo de siete días naturales posteriores a la expiración.
4. **Reintentos:** los fallos de purga se reintentan mediante el proceso de mantenimiento diario, con registro persistente del estado y del siguiente intento.
5. **Alertas y escalamiento:** se genera una alerta desde el primer fallo. Si el problema continúa sin resolverse durante 24 horas, se escala obligatoriamente para su atención.
6. **Restauraciones:** ninguna restauración puede reabrir el acceso a medios expirados o revocados. Antes de reabrir tráfico, debe completarse la reconciliación de expiraciones, revocaciones y purgas pendientes.
7. **Incumplimiento:** superar el plazo máximo de purga constituye un incidente de cumplimiento. El requisito no puede declararse cerrado mientras el incidente siga sin resolver y sin evidencia verificable.

Esta decisión define el objetivo de producto y operación. No constituye evidencia de que la infraestructura actual ya cumpla los plazos.

## 2. Inicio y cálculo de la retención

El plazo se calcula a partir de `persisted_at`, registrado cuando la persistencia del medio se completa correctamente.

El sistema debe mantener el vencimiento asociado a esa persistencia y no renovarlo por:

- Una consulta o descarga del archivo.
- Una nueva entrega del mismo contenido a un usuario autorizado.
- Un reintento de lectura o recuperación.
- Una copia interna o restauración de la base de datos.
- La repetición de un trabajo de mantenimiento.

La fecha de expiración se conserva como dato persistido y no se recalcula a partir de la fecha de lectura ni de la fecha de restauración.

El cálculo debe utilizar una referencia temporal consistente y verificable. La implementación debe documentar cómo se representan los timestamps, cómo se tratan las diferencias de reloj y cómo se manejan las ejecuciones que se producen cerca del instante de vencimiento.

## 3. Revocación de acceso al expirar

Al vencer el plazo de 180 días, el sistema debe impedir que el archivo vuelva a servirse.

La comprobación de autorización debe considerar, como mínimo:

- La identidad y los permisos del usuario.
- La organización o clínica a la que pertenece.
- El estado del medio.
- El vencimiento calculado a partir de `persisted_at` y la política aplicable.
- La existencia de una revocación o solicitud de eliminación anticipada.

La comprobación de vencimiento debe producirse antes de recuperar el binario desde el almacenamiento. Un fallo del proceso de purga no puede restaurar la disponibilidad del archivo.

Los errores y estados deben ser observables para el operador, sin exponer binarios, credenciales, tokens ni datos personales innecesarios en los registros.

## 4. Plazo y alcance de la purga operativa

La purga debe completarse dentro de los siete días naturales posteriores a la expiración.

El proceso debe contemplar:

- El objeto correspondiente a la clave exacta.
- Todas las versiones pertinentes del objeto.
- Los marcadores de borrado y demás elementos que impidan considerar completa la eliminación.
- Los errores parciales al enumerar o eliminar objetos.
- Los reintentos y la verificación posterior.
- Los trabajos pendientes que pudieran volver a crear o recuperar una referencia al medio.
- Las restauraciones que recuperen metadatos antiguos.

La confirmación de una solicitud de borrado por parte del proveedor no se considerará, por sí sola, evidencia suficiente de que la purga operativa terminó. La implementación debe verificar el resultado mediante el mecanismo de comprobación disponible y conservar evidencia del resultado.

El plazo de siete días es un límite operativo para el proceso de purga gestionado por SaaSLyVet. No constituye una afirmación sobre el instante exacto en que el proveedor elimina físicamente todos los bloques internos de su infraestructura.

Tampoco implica la eliminación automática de archivos que una clínica haya descargado, copias conservadas por Meta, información incluida en backups independientes o datos presentes en otros sistemas. Esas ubicaciones requieren un tratamiento y unas políticas propios.

## 5. Fallos, reintentos y escalamiento

### 5.1 Primer fallo

Ante un fallo de purga, el sistema debe:

- Mantener el medio expirado e inaccesible.
- Registrar un evento identificable, por ejemplo `MEDIA_PURGE_FAILED`.
- Registrar el estado del trabajo, la causa técnica disponible y el momento del fallo.
- Registrar el siguiente intento previsto.
- Generar una alerta operativa que pueda ser recibida por el responsable designado.

### 5.2 Reintentos diarios

Los reintentos se realizarán mediante el mantenimiento diario. El proceso debe ser idempotente: volver a ejecutar una purga no debe reactivar el archivo, renovar su retención ni afectar objetos ajenos.

El calendario del mantenimiento, el tamaño máximo de los lotes, la capacidad de procesamiento y el tratamiento de los errores parciales deben permitir cumplir el límite de siete días, incluso cuando exista una acumulación de trabajos.

Programar un reintento no equivale a ejecutarlo. La operación debe demostrar que los trabajos se procesan con la frecuencia y capacidad previstas.

### 5.3 Escalamiento a las 24 horas

La alerta debe emitirse desde el primer fallo. Si el fallo permanece sin resolver durante 24 horas, debe activarse el escalamiento obligatorio.

El procedimiento operativo debe identificar:

- El responsable que recibe la alerta.
- El canal de notificación.
- El mecanismo de seguimiento y reconocimiento.
- El procedimiento de recuperación.
- La evidencia necesaria para cerrar el incidente.

Si no existe una persona o canal de atención configurado, no se considerará que la alerta está operativamente cubierta.

### 5.4 Superación del límite

Si transcurren siete días naturales desde la expiración sin que se haya completado la purga, debe abrirse o mantenerse un incidente de cumplimiento.

El incidente debe registrar, como mínimo, el medio afectado mediante identificadores internos, las fechas relevantes, el motivo del retraso, los intentos realizados, el responsable de seguimiento y la evidencia final de resolución.

El sistema no puede marcar la purga como completada ni cerrar el requisito de cumplimiento basándose únicamente en que el trabajo fue ejecutado.

## 6. Restauración y recuperación ante desastres

Antes de reabrir el tráfico después de restaurar una base de datos o recuperar un servicio, debe ejecutarse una reconciliación obligatoria.

Esta reconciliación debe:

1. Identificar los medios cuyo plazo de disponibilidad haya vencido.
2. Recuperar o reconstruir las revocaciones que no puedan depender exclusivamente de la copia restaurada.
3. Impedir el acceso a medios expirados o revocados antes de habilitar el tráfico.
4. Identificar las purgas pendientes y contrastarlas con el estado real del almacenamiento.
5. Evitar que los trabajos recuperados vuelvan a descargar o procesar medios cuya disponibilidad ya fue revocada.
6. Ejecutar o programar las purgas pendientes con prioridad suficiente para respetar la política.
7. Conservar evidencia del resultado de la reconciliación y de las excepciones encontradas.

La restauración no modifica el `persisted_at` original, no reinicia los 180 días y no anula una revocación anterior.

Si no puede garantizarse la reconciliación de las revocaciones, no debe reabrirse el acceso a los medios afectados hasta recuperar el control.

## 7. Otras copias y ubicaciones

La política debe distinguir el almacenamiento operativo de los demás lugares en los que puede existir contenido relacionado:

- **Almacenamiento operativo B2:** objeto y versiones sometidos al plazo de disponibilidad y purga descrito.
- **Spool temporal del worker:** sujeto a limpieza, límites de permanencia y tratamiento de archivos abandonados tras una caída.
- **Memoria y cachés del cliente:** el acceso debe detenerse al expirar o revocarse el medio; no se puede garantizar la eliminación remota de bytes ya recibidos por un dispositivo.
- **Descargas de la clínica:** requieren controles y políticas propios de la organización que conserva el archivo.
- **Backups de PostgreSQL:** deben respetar el procedimiento de restauración y reconciliación. Si contienen referencias o estados antiguos, estos no deben reactivar la disponibilidad.
- **Copias que conserve Meta u otro proveedor:** están sujetas a sus condiciones y a los procedimientos aplicables; la purga de B2 no acredita su eliminación.
- **Réplicas, versiones o servicios adicionales:** deben inventariarse y verificarse cuando se configure la infraestructura real.

La documentación pública debe describir únicamente las garantías que correspondan al tratamiento real y que hayan sido aprobadas para su comunicación.

## 8. Criterios de aceptación verificables

La política se considerará técnicamente implementada únicamente cuando se aporte evidencia suficiente de los siguientes criterios.

### Retención y acceso

- [ ] `persisted_at` se registra al completar correctamente la persistencia.
- [ ] El vencimiento se conserva y no se renueva por lecturas, copias o restauraciones.
- [ ] El medio vencido es inaccesible incluso si la purga no se ha ejecutado.
- [ ] Los controles de permisos y aislamiento entre organizaciones se mantienen.
- [ ] Las pruebas cubren límites temporales y diferencias de reloj relevantes.

### Purga y reintentos

- [ ] La purga incluye todas las versiones y marcadores pertinentes.
- [ ] Los fallos parciales quedan registrados y pueden recuperarse.
- [ ] Los reintentos son idempotentes y no afectan objetos vecinos.
- [ ] La capacidad del mantenimiento diario permite cumplir el plazo máximo.
- [ ] La verificación posterior demuestra que el objeto y las versiones pertinentes ya no están presentes.
- [ ] Los errores persistentes generan un incidente y no se ocultan mediante una ejecución aparentemente exitosa.

### Alertas y operación

- [ ] La alerta se emite desde el primer fallo.
- [ ] Se verifica la recepción de la alerta por el responsable designado.
- [ ] El escalamiento a las 24 horas funciona y queda registrado.
- [ ] Los incidentes superados los siete días bloquean el cierre del requisito.
- [ ] Existe un procedimiento documentado de recuperación y cierre.

### Restauración

- [ ] Se ejecuta un simulacro con una copia de base de datos que contenga referencias antiguas.
- [ ] Las revocaciones se conservan o reconstruyen de forma fiable.
- [ ] Los medios expirados no pueden servirse después de la restauración.
- [ ] Los trabajos pendientes no pueden reactivar contenido revocado.
- [ ] La reconciliación queda registrada y debe completarse antes de reabrir el tráfico.

### Evidencia de cierre

Para cada criterio aprobado se conservará el resultado de la prueba o verificación, la fecha, la versión evaluada, el responsable y las incidencias encontradas. La evidencia no debe contener binarios de pacientes, credenciales, tokens ni datos personales innecesarios.

Las pruebas locales o con servicios simulados acreditan únicamente el comportamiento cubierto por esas pruebas. No sustituyen una validación del proveedor ni de la infraestructura real.

## 9. Estado actual y límites de esta decisión

Esta decisión formaliza los parámetros de retención y purga seleccionados para SaaSLyVet. No acredita que las garantías estén implementadas de extremo a extremo.

En particular, permanecen pendientes de demostración:

- La configuración y el funcionamiento del almacenamiento B2 real.
- La ejecución operativa del mantenimiento y su capacidad para respetar los plazos.
- La entrega y atención de alertas.
- La verificación de purga en el almacenamiento real.
- La reconciliación de revocaciones y expiraciones durante una restauración.
- La evidencia de un simulacro de recuperación.

**Estado de B2:** pendiente de validación real.

**Estado de publicación del aviso de privacidad:** pendiente; esta decisión no publica ni sincroniza el aviso.

**Estado de activación de WhatsApp:** no autorizado por este documento; requiere completar las verificaciones y aprobaciones aplicables.

La política no podrá declararse plenamente cumplida hasta que los criterios de aceptación correspondientes se hayan demostrado y las incidencias que bloqueen el cierre estén resueltas.

## 10. Registro de aprobación

**Decisión de política:** parámetros definidos.

**Responsable de aprobar la política de producto y operación:** pendiente de registrar.

**Revisión jurídica o contractual, cuando corresponda:** pendiente de registrar.

**Evidencia de aprobación:** pendiente.

**Validación técnica y operativa:** pendiente.

La aprobación de esta política no debe interpretarse como aceptación de contratos con proveedores, aprobación jurídica definitiva, publicación del aviso de privacidad ni autorización para activar el procesamiento de medios en producción.

---
Registro de incorporación al proyecto: **23-10-2026**, por instrucción directa
del usuario que declara que estas son sus decisiones. Se conservan arriba los
campos pendientes del documento original: no se inventan nombre, firma ni
aceptación contractual. La decisión de parámetros queda registrada como definida;
su cumplimiento operativo sigue pendiente. Excepción posterior: responsable y
canal de alertas pendientes operativos **no bloqueantes**, según la decisión del
23-10 enlazada abajo.

[Excepción operativa de alertas](2026-10-23-inbox-media-alert-ops-deferred.md).
