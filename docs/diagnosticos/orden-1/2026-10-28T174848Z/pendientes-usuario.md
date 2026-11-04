# Pendientes del usuario y criterios de cierre

Los siguientes pasos son **posteriores** a este diagnóstico. No se ejecutó ninguno que requiera proveedor, VPS o restore. No entregar secretos, claves privadas, hashes/fingerprints de credenciales, logs crudos ni datos personales. Estados y fuentes en [matriz](matriz-evidencias.csv).

**Aplazamiento vigente aplicado el 28-10-2026:** U01/U02 quedan aplazados hasta nueva instrucción del usuario; tampoco se programa su consulta al proveedor. Las partes remotas de U06/U07 y P08/P09 permanecen sin acreditar y aplazadas. Estos huecos no impiden aceptar la corrección documental local ni planificar H01/dependencias/recuperación localmente. Las listas siguientes conservan los criterios para una eventual reanudación; no son tareas de ejecución actual.

## U01 — Precisar disponibilidad y conservación del VPS

**Estado:** `PENDIENTE_USUARIO`. **Planificación:** aplazado hasta nueva instrucción, sin consulta al proveedor ni reactivación programadas. **Prioridad si se retoma:** alta para recuperar evidencia remota; no bloquea el diagnóstico local.

- [ ] Consultar personalmente al proveedor si conserva instancia, volúmenes, snapshots y registros, y su plazo de retención. No asumir pérdida o suspensión solo por falta de pago.
- [ ] Decidir si desea habilitar más adelante una ventana de lectura pasiva. No se solicita pagar, reactivar ni desplegar como parte de esta ejecución.
- [ ] Si se retoma la lectura, indicar referencia privada de la conexión ya existente; resolver un único destino/identidad antes de conectar. Mantener host-key checking existente; clave desconocida/cambiada requiere aclaración, no aceptación automática.

**Cierre esperado:** recibo saneado con fecha, decisión y disponibilidad/retención confirmadas, sin IDs de cuenta, IP, host o datos de facturación privados.

## U02 — Reanudar el mapa remoto, solo cuando exista acceso

**Estado técnico actual:** `NO_VERIFICABLE_EN_ESTE_ALCANCE`. **Planificación:** aplazado hasta nueva instrucción. **Prioridad si se retoma:** alta antes de actuar sobre producción, sin exigir acceso remoto para el análisis local.

- [ ] Identificar host lógico, usuario efectivo, raíz real y zona del host; revisionar checkout/imagen mediante archivos, etiquetas y metadatos existentes. Registrar diferencias repo/desplegado. No HTTP ni import de app.
- [ ] Leer SSH incluyendo includes/overrides y configuración efectiva observable; restricciones de usuarios/grupos y forwarding; distinguir configuración candidata de estado cargado. No reiniciar para obtener el dato.
- [ ] Leer sudo/grupos relevantes y permisos/owner/fechas de raíz de instalación, env activos, SSH y backups; extraer únicamente nombres de claves de archivos sensibles.
- [ ] Relacionar listeners/binds con publicaciones Docker, proxy y firewall host; el usuario aporta aparte firewall del proveedor. No probes de Internet ni credenciales históricas.
- [ ] Agregar en origen accesos SSH/sudo y eventos de seguridad dentro de la ventana, con fechas de cobertura, rotaciones de log y huecos. No exportar mensajes, actores, IP ni rutas privadas.
- [ ] Inventariar versiones instaladas/desplegadas legibles, scheduler real cron/timers, logs/manifest por etapas de backup y configuración de monitores. No ejecutar scripts, manage.py ni escáneres.

**Cierre esperado si se encarga posteriormente:** nuevo recibo/expediente de lectura remota con revisión, zona, **nueva ventana de 90 días** y cobertura real. El intervalo histórico original y su hueco permanecen intactos y separados; si los logs antiguos expiraron, registrar esa limitación sin reconstruir continuidad ficticia o sustituirlos silenciosamente.

## U03 — Confirmar ciclo de vida de secretos, por clave lógica

**Estado:** `PENDIENTE_USUARIO`. **Prioridad:** alta para `SECRET_KEY`, DB y admin; demás según uso demostrado.

- [ ] Para `SECRET_KEY`: confirmar si sustituyó/no reutilizó la credencial histórica, fecha, entorno y alcance. Resolver U04 antes de una nueva rotación.
- [ ] Para la credencial DB (alias PGPASSWORD/DB_PASSWORD y configuración POSTGRES_PASSWORD/DATABASE_URL): confirmar modificación real del rol/servicio y coordinación de consumidores; no basta mtime o un nombre en env.
- [ ] Para `DJANGO_SUPERUSER_PASSWORD`: confirmar cambio efectivo de la cuenta. El bootstrap actual no resetea contraseñas existentes.
- [ ] Revisar según uso la custodia/ciclo de vida de Redis, WhatsApp app/verify/access, LLM, Sentry upload, webhooks/URLs deadman, B2 backups y accesos al repo/proveedores. Confirmar cuáles no aplican, en lugar de asumirlos activos.
- [ ] Aclarar el alcance y revocación de la exposición B2 mencionada por CI, sin reabrir media B2 ni modificar la política histórica Gitleaks.
- [ ] Confirmar si `VITE_DISCORD_WEBHOOK_URL` tiene uso efectivo en un bundle; su nombre local por sí solo no lo demuestra. No enviar mensajes de prueba.
- [ ] Revisar necesidad de los principales de la ACL local heredada usando referencias privadas del operador; documentar solo clases de acceso autorizadas.

**Cierre esperado por fila:** nombre lógico, entorno, fecha de la intervención anterior, responsable lógico y confirmación/recibo de sustitución o revocación pertinente. Ningún valor, comparación, longitud, prefijo, hash o fingerprint. Si no hay recibo anterior, declarar «no confirmado»; no convertir eso en credencial vigente comprobada.

## U04 — Resolver dependencias de cifrado/firma antes de rotar

**Estado:** `PENDIENTE_USUARIO` para configuración efectiva. H01 permanece demostrado en el código local. **Prioridad:** alta.

El alcance y diseño del wiring local pueden prepararse con F04/F05, sin U01/U02 ni recuperar el VPS. Las confirmaciones siguientes condicionan una futura transición/rotación y validación en un entorno real, no el análisis local. No se implementa el diseño ni se ejecutan pruebas activas en esta corrección documental.

- [ ] Confirmar módulo/revisión efectivos, si el ajuste independiente de Fernet existe como atributo de settings y cómo llega a ese atributo. No basta agregar una línea a env.
- [ ] Comprobar privadamente presencia de valor efectivo/validez de la clave independiente y dependencias de los tokens persistidos; devolver solo conclusión operacional, sin datos derivados de la clave.
- [ ] Preparar continuidad/reprovisión de tokens WhatsApp y tratamiento de firmas/JWT/sesiones para una eventual intervención posterior.
- [ ] Separar clave de cifrado, token de proveedor, `SECRET_KEY` y contraseñas; no tratarlas como una sola rotación.

**Cierre esperado:** recibo saneado del modelo de dependencia y decisión de transición, sin descifrado dentro de este diagnóstico. La corrección y sus pruebas requieren un encargo posterior.

## U05 — Restore real posterior: descarga → descifrado → restore aislado → auditorías → recibo

**Estado:** `PENDIENTE_USUARIO`. **Prioridad:** alta para obtener evidencia actual de recuperación. El recibo de junio no sustituye esta tarea.

Continúa **reservado al usuario para después**. No se ejecuta como sustituto del acceso al VPS ni es requisito para aceptar la corrección local del inventario Python.

### Preparación privada

- [ ] Elegir un backup **offsite** existente y su manifest; registrar referencia lógica, fecha de generación, formato y versión Postgres. No descargar nada durante este diagnóstico.
- [ ] Confirmar disponibilidad/custodia de la clave privada age en los medios offline del operador, sin mostrarla, copiarla al VPS o enviarla al agente.
- [ ] Preparar un **cluster/stack realmente separado** del VPS, con volumen, roles, red y configuración aislados. Una DB con otro nombre dentro del mismo cluster del VPS no cumple ese aislamiento.
- [ ] Bloquear envíos reales: workers, webhooks, email, Sentry/deadman y credenciales de proveedores no deben producir efectos en la prueba. Elegir código/imagen compatible con el backup y registrar revisión.
- [ ] Determinar espacio/compatibilidad y procedimiento de limpieza del entorno descartable. No apuntar scripts al cluster live por heredar defaults/env.

### Ejecución a cargo del usuario

- [ ] Descargar el objeto cifrado y **también** su manifest desde su cuenta de proveedor, fuera del VPS. Mantener ambos privados; el fetch opcional del script no es criterio suficiente.
- [ ] Descifrar privadamente con age; comprobar integridad contra manifest antes de restaurar. No basta poder leer el catálogo de `pg_restore --list`.
- [ ] Restaurar únicamente en el cluster aislado y registrar resultado/errores de forma saneada. La cadena no cuenta completa si solo se restauró un dump plano local.
- [ ] Verificar conteos e integridad estructural; no publicar filas o PII.
- [ ] Ejecutar en ese entorno las auditorías de esquema Billing, anchors y payment ledger y las invariantes tenant/signo financiero pertinentes. El drill actual solo invoca automáticamente las dos últimas auditorías; no asumir cobertura de esquema.
- [ ] Registrar comienzo/fin y antigüedad del backup elegido; distinguir tiempo observado de prueba, RPO que realmente permite ese objeto y objetivos RPO 24h/RTO 1–2h. No convertir el objetivo en resultado.
- [ ] Limpiar el entorno descartable y los temporales descifrados conforme a la custodia del operador; no copiar material crudo al repo.

**Recibo mínimo para cerrar la tarea:** fecha y zona, referencia lógica del objeto/manifest, revisión usada, confirmación de descarga/descifrado/integridad, aislamiento del cluster, resultado individual de restore/auditorías, tiempos observados y limitaciones. Sin clave age, fingerprints de secretos, rutas privadas, dumps o logs crudos. Un resultado fallido también debe dejar recibo con la etapa fallida; no declararlo «recuperable».

## U06 — Evidencia de monitoreo y proveedor

**Estado:** `PENDIENTE_USUARIO`. **Prioridad:** media; alta si no hay otra vía de enterarse de fallos.

La recopilación de evidencia remota/de proveedor y P08 están aplazados; no hay consultas o envíos programados. Los criterios se conservan para cuando el usuario decida retomarlos.

- [ ] Aportar desde cuentas propias configuración vigente y recibos **ya existentes** de deadman backup/planner/sender, monitor externo, Sentry y disco: fecha, entorno lógico, regla/canal lógico y resultado de notificación/recepción.
- [ ] Separar «monitoreo configurado», «evento recibido por servicio» y «alerta entregada al responsable». No enviar eventos, pings o correos de prueba para cerrar este diagnóstico.
- [ ] Confirmar política y existencia actuales de objetos de backups y permisos/retención de la key de backups. No aportar rclone config completo ni ampliar a otros buckets/órdenes.
- [ ] Confirmar firewall del proveedor con referencia lógica saneada; no se acredita accesibilidad desde Internet por reglas locales.

**Cierre esperado:** recibos fechados por control. Si faltan, queda la limitación; una prueba activa posterior requeriría un encargo distinto.

## U07 — Evidencia de gate B3

**Estado:** `NO_VERIFICABLE_EN_ESTE_ALCANCE` con fuente remota pendiente. **Prioridad:** media, antes de proponer retirar el fallback.

U07 y la parte remota de P09 están **aplazados hasta nueva instrucción**. No se cerrarán con supuestos ni con logs locales; el análisis estático local no implica cumplir el gate.

- [ ] Aportar agregados existentes de **7 días consecutivos** con cobertura continua conocida y cero `RBAC_FALLBACK_ALLOWED` permitidos.
- [ ] Acreditar **≥500 requests** con definición/deduplicación del denominador.
- [ ] Acreditar **≥1 request por endpoint crítico** de la matriz contractual, solo con nombres lógicos/agregados, sin actores o IDs.

**Cierre esperado:** los tres componentes en un mismo intervalo/entorno/revisión. Ausencia de eventos en logs incompletos no cierra el gate. No crear tráfico de prueba, seeds o permisos ni retirar fallback en este trabajo.
