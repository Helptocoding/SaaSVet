# Metaprompt listo para el agente ejecutor — Orden 1

Copia el bloque siguiente como encargo del nuevo agente. El plan enlazado contiene los criterios detallados y las decisiones ya respondidas por el usuario.

---

Trabaja sobre `C:\Users\LAP\Desktop\VeterinariaSaaS`. Ejecuta **solo el diagnóstico pasivo del orden 1: seguridad, secretos, dependencias y recuperación**, conforme a `docs/plan-diagnostico-orden-1-2026-10-28.md`.

Tu resultado es un diagnóstico con evidencia y un plan de remediación posterior. **No implementes remediaciones** ni amplíes el encargo a una auditoría completa o pentest.

## Decisiones del usuario: ya acordadas

- El VPS contiene demos/datos de prueba.
- Tienes autorización para inspeccionar repositorio local y VPS mediante el SSH existente; el usuario maneja cuentas de proveedores.
- Descubre el alias SSH configurado y comprueba host, usuario y raíz de instalación sin cambiar nada. No presupongas que la ruta histórica `/home/deploy/apps/SaaSVet` sigue vigente.
- Revisa **los últimos 90 días respecto al inicio de tu ejecución**, registrando intervalo y zona del host.
- Solo puedes inspeccionar archivos, configuración, metadatos y registros existentes. No nuevos escaneos ni pruebas activas.
- Sobre secretos, únicamente nombres de claves, permisos, owner y fechas. No valores, comparaciones, longitudes/prefijos, hashes ni fingerprints. El usuario confirmará después si hubo rotación.
- El usuario hará después la descarga, el descifrado y la prueba de restauración del backup. No solicites ni leas la clave privada age.
- Incluye SSH, sudo, permisos de archivos y servicios expuestos según configuración/metadatos locales. No probes accesibilidad desde Internet ni credenciales históricas.
- El usuario toleraría reinicios por necesidad, pero este plan es de lectura: no programes reinicios/reloads ni los uses como atajo. Si una comprobación los exige, déjala fuera y explica el dato pendiente.

No repitas esas preguntas. Pregunta solo ante una ambigüedad real de host/ruta/identidad SSH o una fuente imprescindible no accesible; continúa los bloques independientes.

## Antes de actuar

1. Lee AGENTS.md, la referencia RTK y el plan detallado; conserva cambios existentes del usuario.
2. Usa el grafo codebase-memory-mcp para descubrir código. Si no está indexado, sigue las instrucciones de indexación del repositorio; no trates nombres de grafo obsoletos como prueba de la fuente actual.
3. Prefija comandos con RTK conforme a las instrucciones. Usa `rtk proxy` cuando no exista filtro. No instales RTK en el VPS: envolver el SSH local no exige modificar el host remoto.
4. Registra commit/estado local y versión desplegada mediante metadatos existentes; no mediante requests HTTP o importando la app.
5. SSH: usa autenticación y host-key checking existentes. No editar known_hosts ni aceptar una clave desconocida/cambiada automáticamente. Si hay varios destinos plausibles, pregunta cuál es.

## Límites de ejecución y privacidad

- Nada de upgrades, instalaciones, rotaciones, seeds, migraciones, tests, builds, `manage.py`, scripts del repo, `pip-audit`, `pnpm audit`, Gitleaks, curl/pings, escaneos de puertos, probes de login, dumps, restore o nuevas bases.
- No alterar código, configuración, firewall, SSH, sudo, permisos, usuarios, cron, servicios, CI, lockfiles o políticas de proveedores. No commit/push/deploy/activación.
- No ejecutar `.env`/config como shell ni cargar settings Django. Inspección estática y comandos administrativos de lectura acotada solamente.
- Nunca devolver `cat .env`, entorno completo, `docker inspect` completo, `docker compose config` completo, rclone config, claves privadas, argumentos con credenciales o logs crudos.
- Para archivos sensibles, procesar en el equipo de origen y devolver **solo nombres de claves/metadatos**. Para logs, filtrar y sanear antes de salir del host. Si no puedes garantizarlo, registrar la limitación y no exportar el contenido.
- Informes saneados únicamente. No secretos, PII, dumps, logs crudos ni detalles privados de infraestructura en Git/chat/artefactos. No guardar material crudo para redactarlo posteriormente.
- Usar solo privilegios ya disponibles para lectura; no probar permisos mediante acciones de escritura ni pedir contraseñas por chat.
- No consultar cuentas externas. No generar nuevas automations, monitores, alertas o envíos de prueba.

## Secuencia de trabajo

### 0. Mapa de evidencia

Identifica versión local/desplegada, host lógico, rutas verificadas, configuración relevante y cobertura de registros de 90 días. Diferencia el contenido del repo de lo que está desplegado. Si algo es desconocido, no lo asumas.

### 1. O13 — Secretos

Revisa el plan de exposición histórica, ignorados/plantillas y metadatos de archivos activos. Extrae solo nombres de variables. No abras blobs históricos de `.env` con salida sin filtrar ni compares credenciales. Construye una matriz por secreto y deja confirmación de rotación al usuario.

Inspecciona estáticamente usos de `SECRET_KEY`, JWT y cifrado WhatsApp. En `backend/apps/channels/crypto.py`, `_fernet()` usa `AGENT_TOKEN_ENC_KEY` si tiene valor; en otro caso deriva la clave de `SECRET_KEY`. **Nombre presente no demuestra valor efectivo**. Explica qué debe comprobarse antes de recomendar una rotación futura, sin cambiar ni descifrar nada.

### 2. Accesos VPS

Inspecciona SSH (includes/overrides y configuración efectiva observable), sudo/grupos relevantes, owner/permisos de rutas sensibles, puertos/binds/publicaciones Docker/proxy/firewall y registros agregados de acceso. No hagas pentest.

No confundas puerto en escucha con exposición pública comprobada. Si falta firewall del proveedor, deja ese extremo sin verificar. Configuración en archivo no demuestra necesariamente el estado activo si no hay evidencia de carga.

### 3. O01 — Dependencias

Revisa manifiestos, locks, metadatos instalados/desplegados legibles e informes de auditorías ya disponibles. Registra fecha/commit/runtime-dev/alcance, deduplica lo que permitan las fuentes y distingue versiones declaradas de instaladas.

El corte del 22-10 registra 162 avisos Python en 11 paquetes y resumen pnpm 8 bajos/39 moderados/38 altos; no sumes eso como vulnerabilidades únicas actuales. No consultes advisories ni ejecutes un escaneo nuevo. Si falta información actual, consérvala como límite. CI mantiene Gitleaks bloqueante y auditorías advisory; no cambies esa política.

### 4. O14 — Backups, restore y monitoreo

Lee scripts/configuración sin ejecutarlos. Revisa scheduler real, zonas horarias, logs de etapas, manifests/metadatos disponibles, fecha del último éxito y huecos. No descargues ni descifres objetos B2.

Hay un restore offsite documentado el 20-06-2026; acredita esa fecha histórica, no recuperabilidad actual. Los runbooks fijan backup diario/RPO 24h, drill offsite manual mensual y >35 días como umbral documental de seguimiento. No conviertas objetivos RPO/RTO en mediciones.

Concilia la contradicción de documentación/scripts antiguos que hablan de restore por cron con `cron-jobs.md` y `crontab.example`, que mantienen drill manual. No edites el cron. El script existente puede crear una DB temporal en el cluster del VPS: no ejecutarlo y no presentarlo como aislamiento completo.

Inspecciona evidencia existente de deadman/Sentry/monitor/alertas de disco sin enviar eventos ni pings. Configurado no equivale a alerta entregada. Deja al usuario una checklist para la prueba real posterior de descarga→descifrado→restore aislado→auditorías→recibo.

### 5. B3 y consolidación

Lee el fallback RBAC y agregados existentes de `RBAC_FALLBACK_ALLOWED`. No elimines fallback ni cambies permisos. El gate exige siete días sin fallback permitido, ≥500 requests y cobertura de endpoints críticos; no deduzcas cumplimiento completo de silencio en logs incompletos.

Consolida sin confundir falta de evidencia con fallo confirmado. No reabras B9/D29, deudas aceptadas, GA4/Formspree, B2 media o los demás órdenes.

## Formato de resultados

Usa estos estados, separados de prioridad/severidad:

- `EVIDENCIA_CONFORME`: criterio específico con evidencia suficiente y fecha/entorno.
- `DESVIACION_CONFIRMADA`: configuración o incumplimiento demostrado; describir efecto/alcance sin exagerar.
- `PENDIENTE_USUARIO`: confirmación de rotación, proveedores o restore reservado al usuario.
- `NO_VERIFICABLE_EN_ESTE_ALCANCE`: requiere comprobación activa, comparación de valores, fuente externa o acceso faltante.
- `NO_APLICA`: justificar con evidencia.

La ausencia de un recibo no es una vulnerabilidad crítica. Describe exposición/impacto solo hasta donde los datos lo demuestren. Si algo parece urgente, informa de inmediato sin revelar secretos y entrega recomendación; no lo corrijas por iniciativa propia.

## Entregables y cierre

Crea un expediente nuevo fechado en `docs/diagnosticos/orden-1/`, sin sobrescribir ejecuciones previas, que contenga:

1. `README.md`: resumen ejecutivo, revisiones/entornos/intervalo y límites.
2. `matriz-evidencias.csv`: ID, categoría, criterio, estado, fuente lógica, fecha, revisión/entorno, prioridad, limitación y siguiente acción.
3. `hallazgos.md`: desviaciones demostradas y recomendación mínima.
4. `pendientes-usuario.md`: confirmaciones/recibos/prueba de restore con criterios para cerrarlos.
5. `plan-remediacion-propuesto.md`: futuro trabajo por prioridad, dependencias, validación y reversión conceptual; sin ejecutarlo.

No incorpores datos privados de hosts, IPs o claves al repositorio. Solo archivos saneados y referencias lógicas de evidencia. Verifica cobertura de todos los bloques, referencias y ausencia de contenido sensible; informa cualquier hueco. No afirmes “seguridad aprobada”, “backup recuperable” o “go-live autorizado”.

Puedes terminar el diagnóstico con puntos pendientes del usuario: enuméralos con precisión. La tarea completa aquí es **inspeccionar y documentar**, no cerrar todas las remediaciones. Entrega una síntesis breve de lo confirmado, lo incierto y los siguientes pasos, con enlaces al expediente.

---

## Nota para quien entrega el encargo

No hace falta proporcionar secretos en el prompt. Si la conexión SSH no es inequívoca, el agente preguntará por el alias correcto. La lectura disponible y la evidencia real decidirán los resultados; este metaprompt no preclasifica el VPS como seguro ni comprometido.
