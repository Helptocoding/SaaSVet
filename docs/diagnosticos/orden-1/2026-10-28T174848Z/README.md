# Orden 1 — diagnóstico pasivo del 28-10-2026

**Estado: CERRADO_CON_EXCEPCION_DE_ALCANCE — diagnóstico del orden 1.** Correcciones documentales incorporadas y revisión local aceptada; inspección del VPS aplazada por decisión del usuario. El [acta de cierre](CIERRE.md) delimita esta aceptación. No se acredita seguridad general, recuperabilidad actual ni autorización de go-live.

**Corrección documental del 28-10-2026:** aplicada la [revisión del expediente](revision-2026-10-28.md), que se conserva sin editar. Se incorpora la lectura de metadatos de `venv/` de las **19:07:12.105141 UTC / 13:07:12.105141 America/Mexico_City** y se separa del inventario global observado antes. La ventana histórica de registros de 90 días permanece intacta; esta lectura posterior no demuestra retrospectivamente el estado del venv al inicio ni el intérprete de ningún proceso. No se instalaron paquetes ni se ejecutó el venv.

## Resultado ejecutivo

- **Confirmado en el checkout local:** exposición histórica documentada de archivos de entorno; hoy solo están rastreadas tres plantillas. Los archivos locales de entorno reales están ignorados. No se conoce la vigencia de ninguna credencial histórica.
- **Desviación local relevante para una futura rotación:** `crypto.py::_fernet()` consulta `settings.AGENT_TOKEN_ENC_KEY`, pero el módulo de settings actual no define ese ajuste. Con este módulo deriva la clave de `SECRET_KEY`. Rotar sin resolver esta dependencia puede invalidar los tokens cifrados guardados; no se inspeccionaron ni descifraron esos tokens.
- **Dependencias:** persisten en el lock las versiones de los 11 paquetes señalados por el informe Python; también coincidían en el Python global inspeccionado originalmente. En el **venv del proyecto coinciden 7 y difieren 4**; no se extrapolan los avisos a esas cuatro versiones. De los 40 pins, el venv coincide en 29, difiere en 9 y no aporta metadatos de 2. Los 162 registros históricos se reducen a 124 combinaciones paquete/versión/ID, también 124 grupos por alias. El informe pnpm contiene 85 registros/IDs numéricos internos, **78 referencias GHSA distintas** y 85 combinaciones paquete/versión/GHSA en 16 paquetes. **No son un recuento de vulnerabilidades únicas actuales o explotables; no se suman ambos ecosistemas.**
- **Recuperación:** se conserva evidencia documental de un restore offsite del **20-06-2026**, 130 días calendario antes de esta ejecución. Es evidencia histórica, fuera de la ventana de 90 días. No se acreditó último backup actual, upload, existencia del objeto, restore reciente ni entrega de alertas.
- **Documentación DR:** el módulo de backup y comentarios del drill hablan de cron, mientras el runbook de cron y su plantilla fijan drill offsite manual mensual. Además, el módulo enumera una auditoría que el drill actual no invoca y presenta la comprobación del manifest sin las salvedades del código.
- **B3:** existe el fallback; el archivo local RBAC consultado es de abril y no cubre la ventana. No se acredita ninguno de los tres componentes del gate de retiro.

Desviaciones y alcance en [hallazgos.md](hallazgos.md); registro completo en [matriz-evidencias.csv](matriz-evidencias.csv); acciones reservadas al operador en [pendientes-usuario.md](pendientes-usuario.md); trabajo futuro en [plan-remediacion-propuesto.md](plan-remediacion-propuesto.md).

## 1. Ficha de ejecución y separación de entornos

| Campo | Evidencia / límite |
|---|---|
| Inicio de referencia | 2026-10-28 17:48:48.789564 UTC; 11:48:48.789564 America/Mexico_City (UTC−06:00). Primera medición explícita de reloj de la sesión. |
| Ventana fija de 90 días | **2026-07-30T17:48:48.789564Z a 2026-10-28T17:48:48.789564Z**. En America/Mexico_City: **2026-07-30T11:48:48.789564−06:00 a 2026-10-28T11:48:48.789564−06:00**. No se desplaza al redactar. |
| Zona observada del equipo local | Windows `Central Standard Time (Mexico)`, offset −06:00 en la medición. |
| Revisión local | `8886604ff77bd86649c12dee695a4742a3fe44f5`, fecha del commit 2026-10-23T19:03:58−06:00. |
| Estado inicial | Sin modificaciones rastreadas; cuatro documentos ajenos no rastreados: plan de diagnóstico, metaprompt, inventario de pendientes y plan priorizado de octubre. Preservados. El plan leído es fuente de trabajo no incorporada a HEAD. |
| Entornos instalados locales observados | **Python global:** inventario de la ejecución original, 40 pins coincidentes. **Venv del proyecto:** `venv/`, con `Scripts/python.exe`, `pyvenv.cfg` y `Lib/site-packages` legibles; cfg declara Python 3.13.2 e `include-system-site-packages = false`; inventariado por metadatos en la corrección. **Frontend:** `frontend/node_modules`, separado de ambos Python. No se importó la app ni se ejecutó el intérprete del venv. Su uso para levantar el backend es contexto aportado por la revisión, no una comprobación de procesos. Ningún inventario acredita instalación del VPS. |
| Entorno remoto lógico | **VPS-APLICACION**, con demos/datos de prueba según el usuario; sigue siendo privado. |
| Disponibilidad remota | El usuario indicó durante la ejecución que no ha pagado el VPS, que no se podrá acceder y que se dejen pendientes esas tareas. No hubo conexión SSH ni comprobación de suspensión, eliminación o retención por el proveedor. |
| Destino e identidad SSH | No se encontró configuración de usuario con alias del proyecto en Windows ni en Ubuntu WSL. La configuración de Git consultada no aportó destino del proyecto. La investigación se detuvo tras la aclaración del usuario. Alias, host, usuario e identidad efectiva **sin verificar**. |
| Instalación y revisión desplegadas | Raíz, revisión, imágenes y metadatos activos **desconocidos**. No existe `.deploy-state` ni `.env.prod` en las ubicaciones locales inspeccionadas. No se adoptó la ruta histórica del runbook como instalación actual. |
| Zona del host remoto | **No observable**. America/Monterrey es una referencia documental histórica, no una medición de esta sesión. |
| Grafo | Herramientas de grafo ausentes; listados MCP de recursos/plantillas vacíos. Configuración local MCP solo ofrecía Context7. Hay metadatos de índice fechados 2026-08-16, asociados a otra revisión; no se usaron como prueba del código actual. No se encontraron instrucciones de indexación utilizables ni se indexó. Se empleó lectura estática dirigida de las fuentes actuales. |
| Herramientas | RTK 0.48.0 verificado; comandos de consola envueltos con RTK, `rtk proxy` para inspecciones sin filtro. Lectores temporales propios fuera del repositorio; no se ejecutaron scripts del proyecto. |

## 2. Mapa de fuentes lógicas

Todas las referencias de código/configuración describen el **checkout local de la revisión anterior**, salvo indicación expresa. Los registros son observaciones saneadas en origen; no se adjuntaron archivos sensibles.

| Fuente | Referencias y alcance |
|---|---|
| F01 — contrato | [Plan de diagnóstico](../../../plan-diagnostico-orden-1-2026-10-28.md), instrucciones AGENTS/RTK y aclaración del usuario en esta sesión. |
| F02 — secretos históricos | [Plan del 19-06](../../../security/secret-rotation-plan.md), §§2, 4, 5 y 8. Metadatos/nombres extraídos de dos blobs históricos, sin valores. No se pretende recertificar todo el historial. |
| F03 — custodia local | [.gitignore](../../../../.gitignore), líneas 4–12 y 44–45; `git ls-files` y `git check-ignore`; nombres/fechas y ACL de los archivos de entorno locales. |
| F04 — cifrado | [crypto.py](../../../../backend/apps/channels/crypto.py), líneas 21–41; lectura AST de settings, sin ejecución. |
| F05 — settings/JWT | [settings.py](../../../../backend/config/settings.py), líneas 24–60, 69–103, 325–341, 371–383 y 585–683; defaults de SimpleJWT del Python global en la ejecución original y del venv en la corrección, ambos leídos como texto, sin importar paquetes. |
| F06 — bootstrap | [users/apps.py](../../../../backend/apps/users/apps.py), líneas 14–51 y 79–86. |
| F07 — Python | [requirements.txt](../../../../backend/requirements.txt), [requirements.lock](../../../../backend/requirements.lock), [Dockerfile](../../../../backend/Dockerfile); metadatos `*.dist-info/METADATA` del Python global de la ejecución original y, por separado, `venv/Lib/site-packages/*.dist-info/METADATA` y campos permitidos de `venv/pyvenv.cfg` leídos en la corrección a las 19:07:12.105141Z. Solo nombres/versiones y configuración de versión/aislamiento, sin rutas privadas del cfg. |
| F08 — frontend | [package.json](../../../../frontend/package.json), [pnpm-lock.yaml](../../../../frontend/pnpm-lock.yaml), [Dockerfile](../../../../frontend/Dockerfile); `package.json` instalados locales, incluidos los 16 paquetes del informe. |
| F09 — CI | [ci.yml](../../../../.github/workflows/ci.yml), líneas 133–197. No se consultó GitHub ni el resultado actual de sus jobs. |
| F10 — auditorías existentes | [B9-RESULTS, filas de seguridad](../../../evals/inbox-readiness-2026-10-22/B9-RESULTS.md#L8-L13); `blocks/pip-audit.json`, `blocks/pip-audit.command.json`, `blocks/pnpm-audit.command.json`, `blocks/pnpm-audit.command.log`, `preflight.json` y resumen permitido de `security-verification.json` de esa carpeta. Procesados localmente con selección de campos. No se reprodujeron logs ni fingerprints. |
| F11 — backup | [pg-backup.sh](../../../../scripts/pg-backup.sh), líneas 95–135, 147–176, 215–281 y 295–311. Lectura, no ejecución. |
| F12 — scheduler/documentación | [cron-jobs.md](../../../runbooks/cron-jobs.md), §§1 y 5.bis; [crontab.example](../../../../scripts/crontab.example), líneas 53–61, 103–131. Plantilla, no crontab efectivo. |
| F13 — restore | [RUNBOOK-RESTORE](../../../runbooks/RUNBOOK-RESTORE.md), líneas 16–25; [restore-drill.sh](../../../../scripts/restore-drill.sh), líneas 7–21, 87–125, 151–184; [pg-restore.sh](../../../../scripts/pg-restore.sh), líneas 54–59, 99–132. |
| F14 — política DR | [modules/backup.md](../../../modules/backup.md), líneas 23–43, 93–120 y 129–146; [ADR p40](../../../decisions/2026-06-12-p40-backup-offsite-disaster-recovery.md). |
| F15 — observabilidad | [monitoring.md](../../../runbooks/monitoring.md), §§1–4; [observability.md](../../../runbooks/observability.md), §§1–4; [disk-alert.sh](../../../../scripts/disk-alert.sh), líneas 24–27 y 55–73; [worker](../../../../backend/apps/agent/management/commands/run_agent_worker.py), líneas 75–107. |
| F16 — B3 | [permissions.py](../../../../backend/apps/core/permissions.py), líneas 342–441; [deuda B3](../../../deuda/fase3-prioridad-media.md#b3--rbac-fase-4--quitar-userrole-legacy), líneas 120–145; logs locales agregados en origen. |
| F17 — accesos/superficie declarada | [vps-hardening.md](../../../runbooks/vps-hardening.md), criterios SSH/firewall; [docker-compose.prod.yml](../../../../docker-compose.prod.yml), servicios y publicaciones; [Caddyfile](../../../../infra/Caddyfile), listeners/routing. Ninguno demuestra estado activo remoto. |
| F18 — observaciones de sesión | Revisión/estado Git, reloj local, aclaración de indisponibilidad remota, metadatos saneados y límites de lectura descritos aquí. Incluye la corrección documental y la decisión de aplazar tareas remotas hasta nueva instrucción, sin exigirlas para aceptar el diagnóstico local. No hay recibo remoto ni artefacto crudo adjunto. |

## 3. Cobertura de registros de los 90 días

| Fuente | Cobertura observada | Qué permite concluir |
|---|---|---|
| Logs de acceso SSH/sudo, firewall, cron, backups, Docker/proxy del VPS | **0 días inspeccionados de 90** por indisponibilidad. Retención y existencia desconocidas. | No se pueden contar accesos, fallos, éxitos de backup, huecos de ejecución ni tráfico B3. No equivale a cero eventos. |
| Archivo local RBAC | 38 líneas fechadas entre 2026-04-23T19:39:05.422420Z y 19:39:55.248169Z; mtime 2026-04-23T19:39:55.247540Z. | Fuera de ventana; cero registros temporales utilizables para el gate actual. No es log de producción acreditado. |
| Archivo local Django | 31 413 líneas; 17 570 sin timestamp reconocido (incluyen continuaciones). Fechas reconocidas sin zona entre 2026-05-09 01:53:04.922 y 2026-10-23 00:38:45.332; mtime 2026-10-23T06:38:45.333567Z. | No se atribuyeron zona ni entorno a estas líneas. No acreditan continuidad ni son denominador de requests remotos. No se exportó ningún mensaje. |
| Informes de dependencias | Corte documental 22-10; mtimes Python 2026-10-23T03:29:12.531698Z y pnpm 03:30:49.769238Z, equivalentes al 22-10 en México. | Instantánea histórica dentro de ventana; mtime no certifica instante de ejecución ni inventario desplegado. |
| Recibo documental DR | 20-06-2026, fecha sin hora. | Fuera de ventana; acredita solo el flujo histórico relatado. No hay fecha actual de backup para calcular su edad. |

**Último éxito de backup actual, edad y huecos: no determinables.** No se encontraron manifests `*.manifest.json` fuera de directorios `runtime` en la búsqueda de nombres bajo docs; no se leyeron dumps ni se extendió la revisión a campañas o media. Esto no prueba inexistencia de manifests en otras ubicaciones ni inexistencia de backups.

## 4. O13 — matriz por secreto y dependencias de rotación

### Metadatos locales

| Archivo lógico | mtime UTC | Creación observada UTC | Owner / permisos observados |
|---|---|---|---|
| `backend/.env` | 2026-08-04T20:50:02.169822Z | 2026-05-08T06:40:26.632596Z | Operador local; ACL heredada, no protegida; seis ACE Allow Modify/Synchronize para principales privados, una Allow FullControl para principal privado y FullControl para SYSTEM/Administrators. |
| `frontend/.env` | 2026-05-29T03:39:03.929803Z | 2026-05-29T03:39:03.898167Z | Mismo resumen de ACL/owner. |
| Plantilla de producción | 2026-07-26T22:44:28.734363Z | 2026-07-26T22:44:28.724305Z | Mismo resumen de ACL/owner. Es plantilla rastreada, no configuración activa acreditada. |

Se omitieron identidades privadas y SIDs. No se ensayó acceso con otros usuarios ni se resolvió la pertenencia efectiva de todos los principales; **no se afirma acceso no autorizado**. ACL Windows no equivale a modo POSIX 0600. Fechas no demuestran rotación. `.env.prod`, `.env.prod.local`, `.env` raíz y `frontend/.env.local` no existen en las ubicaciones locales consultadas; nada se deduce sobre el VPS.

Las únicas rutas de entorno rastreadas son `.env.prod.example`, `backend/.env.example` y `frontend/.env.example`. Las reglas posteriores `.env` y `.env.*` también alcanzan las plantillas al comprobar con `--no-index`; no dejan de estar rastreadas por ello. No se evaluaron valores ni siquiera de las plantillas.

**Convenciones de ubicación:** BL = nombre presente en `backend/.env`; FL = nombre presente en `frontend/.env`; PP = nombre en plantilla de producción; BP/FP = nombre en plantilla backend/frontend; C = consumidor en código/scripts/documentación. Presencia de nombre **no demuestra valor, validez, carga o uso efectivo**.

| ID | Secreto / clave lógica | Uso y ubicación observada | Estado y siguiente evidencia necesaria |
|---|---|---|---|
| S03 | `SECRET_KEY` | BL/BP/PP; requerida en settings sin default; firma y dependencia Fernet/JWT. Nombre en blob histórico seleccionado. | `PENDIENTE_USUARIO`: fecha/entorno/alcance de no reutilización o rotación. No comparar valores; resolver S07 antes de recomendar cambio. |
| S04 | `DJANGO_SUPERUSER_PASSWORD` | BL; nombre histórico. El bootstrap consume `os.environ` y no resetea la contraseña de un superusuario existente. | `PENDIENTE_USUARIO`: recibo de cambio real en la cuenta, no solo edición de un archivo o reejecución del bootstrap. |
| S05 | `PGPASSWORD` / `DB_PASSWORD`; `POSTGRES_PASSWORD` / `DATABASE_URL` | PGPASSWORD en BL/BP/PP; los dos últimos en PP. `DB_PASSWORD` es alias histórico documentado, no observado en el blob seleccionado. | `PENDIENTE_USUARIO`: acreditar sustitución de la credencial histórica y coherencia del usuario DB/configuración en cada entorno. El plan histórico agrupa alias; no se compararon credenciales actuales. Cambiar env no demuestra cambio del rol DB. |
| S06 | `REDIS_PASSWORD` / `REDIS_URL` | PP y Compose/settings. | `PENDIENTE_USUARIO`: custodia/alcance y rotación si corresponde; sin evidencia de exposición histórica de estos nombres en los dos blobs seleccionados, sin recertificar todo el historial. |
| S07 | `AGENT_TOKEN_ENC_KEY` | No figura como nombre en los archivos de entorno/plantillas inspeccionados. C en `_fernet()`; falta asignación en settings. | `DESVIACION_CONFIRMADA` en la integración local. Valor efectivo, validez y estado desplegado `NO_VERIFICABLE_EN_ESTE_ALCANCE`; ver H01. |
| S08 | `WHATSAPP_APP_SECRET` | PP; settings/webhook. | `PENDIENTE_USUARIO`: custodia y recibo de ciclo de vida; no afirmar vigencia ni necesidad de rotación por exposición no acreditada. |
| S09 | `WHATSAPP_VERIFY_TOKEN` | PP; settings/webhook. | `PENDIENTE_USUARIO`: mismo criterio, separando verificación de webhook de autorización de envío. |
| S10 | `WHATSAPP_ACCESS_TOKEN` | PP; settings y credencial de envío; puede haber tokens cifrados en DB. | `PENDIENTE_USUARIO`: inventario lógico de dependencias y procedimiento de reprovisión antes de rotar claves de cifrado. No se accedió a DB. |
| S11 | `AGENT_LLM_API_KEY` | BL/PP; proveedor de LLM. | `PENDIENTE_USUARIO`: recibo de custodia/revocaciones pertinentes; ninguna consulta de cuenta. |
| S12 | `SENTRY_AUTH_TOKEN` | PP; argumento de build en frontend/Compose. | `PENDIENTE_USUARIO`: alcance y ciclo de vida de la credencial de upload; no se inspeccionaron capas de imágenes ni proveedor. No es un DSN público. |
| S13 | `SENTRY_DSN` / `VITE_SENTRY_DSN` | BL/FL/BP/FP/PP; nombres históricos en los blobs seleccionados. | `NO_APLICA` como contraseña privada equivalente a S03: DSN de ingesta/público según contrato. Abuso/cuota y posible sustitución opcional quedan al usuario; recepción actual no acreditada. |
| S14 | `DISCORD_WEBHOOK_URL` | PP, BP y settings. | `PENDIENTE_USUARIO`: custodia/alcance si se usa; no se revisaron valores. |
| S15 | `VITE_DISCORD_WEBHOOK_URL` | FL; ausente en plantilla frontend actual y en el blob frontend seleccionado. | `NO_VERIFICABLE_EN_ESTE_ALCANCE`: nombre no prueba carga ni inclusión en bundle. Si fuese efectivo en cliente tendría capacidad de publicación; confirmar uso/ciclo de vida sin enviar pruebas. No se afirma exposición actual. |
| S16 | `HEALTHCHECK_URL`, `HEALTHCHECK_AGENT_WORKER_URL`, `HEALTHCHECK_AGENT_SENDER_URL`, `HEALTHCHECK_DEMO_RESET_URL` | Primeros dos en PP; sender en settings; demo-reset en comentarios/receta de cron. C en backup/worker/cron. | `PENDIENTE_USUARIO`: confirmar configuración del proveedor y recibos de notificación existentes. No hay valores efectivos acreditados ni pings enviados. |
| S17 | `ALERT_WEBHOOK` | C en disk-alert/runbook/comentarios de cron. | `PENDIENTE_USUARIO`: confirmar wiring y recepción de alertas ya existentes. No se infiere activación de la plantilla. |
| S18 | Application Key B2 de backups, referencia lógica de rclone | C documental; archivo activo remoto inaccesible. No se abrió rclone config. | `PENDIENTE_USUARIO`: alcance, vigencia y recibo de revocación si hubo exposición. El plan de junio dice no expuesta entonces; CI actual menciona una exposición B2 previa sin identificar aquí su alcance. No extrapolar a credenciales actuales ni a media. |
| S19 | `BACKUP_ENCRYPTION_PUBLIC_KEY` | PP/scripts; recipient público. | `NO_APLICA` como secreto privado. No se exportó valor ni se cotejó con claves. Funcionamiento pendiente de restore del usuario. |
| S20 | Clave privada age | Custodia offline prescrita; no buscada ni leída. | `PENDIENTE_USUARIO`: acreditar custodia funcional con prueba posterior, sin entregarla al agente ni incorporarla al expediente. |
| S21 | SMTP/EMAIL y credenciales de lectura del repositorio/proveedores | Referencias de ciclo de vida en el plan histórico; no nombres SMTP activos observados en los archivos examinados. | `NO_VERIFICABLE_EN_ESTE_ALCANCE`: no inventariadas las cuentas externas; el usuario precisará si aplican y sus recibos, sin valores. |

`PGUSER`/`DB_USER`, nombres de superusuario, hosts/puertos y `VITE_API_URL` son metadatos/configuración, no contraseñas. Se omiten sus valores. La ausencia de nombre en dos blobs seleccionados no acredita ausencia en todo Git.

### Antes de recomendar una rotación de SECRET_KEY

1. Identificar revisión y módulo settings realmente desplegados y la procedencia del ajuste de cifrado, mediante metadatos permitidos. No asumir que env se convierte automáticamente en un atributo de settings.
2. El usuario debe comprobar privadamente si hay una clave Fernet independiente **efectiva y válida**, sin entregar valor, longitud, prefijo, hash ni fingerprint al diagnóstico. Este dato no se obtuvo aquí.
3. Inventariar qué tokens cifrados dependen de la clave antigua y cómo se reprovisionarán; acordar continuidad y recuperación con el operador. No cambiar la clave para averiguarlo ni descifrar como prueba.
4. Considerar JWT: el `SIMPLE_JWT` local no redefine `SIGNING_KEY` ni algoritmo. Los defaults leídos de SimpleJWT 5.5.1, por separado en Python global y en el venv, son `HS256` y `settings.SECRET_KEY`. **PyJWT es otro paquete:** difiere entre el lock/global (2.13.0) y el venv (2.12.1). La configuración local fija access 15 min, refresh 7 días, rotation y blacklist. No se midió revocación ni se acredita configuración remota.
5. Una futura intervención debe coordinar firmas/sesiones/JWT y cifrado de WhatsApp. Cambiar solo la variable de superusuario tampoco demuestra rotación de su contraseña persistida.

## 5. O01 — inventario y triaje documental

### Procedencia y alcance

- F10 corresponde al **corte documental 22-10-2026**. `preflight.json` registra HEAD `194772677ca4e9fe1a1dec7f4dafa48396a6c583` y 5685 entradas en su contador de cambios rastreados; no permite atribuirlo a un checkout limpio de ese commit. No se reconstruyó el árbol exacto auditado ni se reutilizó ese HEAD como versión desplegada.
- Ambos recibos de comando constan `COMPLETED`, ejecución formal 1, `advisory=true`, exit 1. Python usó un archivo llamado `requirements.lock`; pnpm `audit --json`, sin `--prod`. No se volvieron a ejecutar.
- El reporte Python tiene 34 dependencias; el lock actual tiene **40**. Faltan en el primero `boto3`, `botocore`, `jmespath`, `python-dateutil`, `s3transfer` y `six`. Falta de cobertura no equivale a ausencia de avisos.
- El lock Python es el utilizado por el Dockerfile y no separa extras dev: incluso `tblib`, descrito como soporte del runner de tests, queda incluido. El reporte pnpm es árbol completo runtime+dev; sus findings contienen `version` y `paths`, pero todos los arrays de rutas están vacíos y no hay flag dev por finding. No se inventó deduplicación por ruta.
- **Python global, observación original:** los 40 pins coincidían con los metadatos de ese intérprete. La búsqueda inicial se limitó a rutas `Lib/site-packages` bajo `backend/venv`, `backend/.venv` y `.venv` raíz; no cubría `venv/` raíz y no justificaba inferir ausencia de un entorno virtual del proyecto. La corrección confirmó esas tres rutas de metadatos como no encontradas y `venv/` con sus metadatos como presente y legible; no hubo ruta inaccesible en esta lectura. Una ruta inaccesible se registraría como tal, nunca como inexistente.
- **Venv del proyecto, corrección a las 19:07:12.105141Z:** 38 de los 40 nombres del lock tienen metadatos legibles: 29 versiones coincidentes y 9 diferentes. No se encontraron metadatos de `django-redis` ni `redis`; no se intentó importarlos ni se diagnostica por ello un fallo del backend. Hay además 34 distribuciones con metadatos fuera del lock. El cfg declara Python 3.13.2 sin heredar system-site-packages. No se verificó el ejecutable de ningún proceso activo ni se trasladó esta observación al VPS.
- **Frontend, observación original:** los 31 paquetes directos coinciden en versión base con su importer del lock; también las versiones locales de los 16 paquetes señalados por pnpm. Es independiente del inventario Python y no demuestra contenido del bundle ni instalación remota.
- No se consultaron advisories actuales ni disponibilidad/seguridad de las versiones de solución registradas. Una versión de solución en el informe es una referencia histórica, no una recomendación de instalarla a ciegas.

### Python: paquetes con avisos registrados

En las 11 filas: **versión del informe = pin del checkout = metadato del Python global observado originalmente**. La columna venv es una lectura independiente de la corrección: **7 coinciden y 4 difieren**. No se aplican automáticamente los avisos o sus fixes a una versión distinta. Los recuentos siguientes pertenecen exclusivamente al informe histórico: deduplicación por nombre normalizado, versión e ID; unión por alias explícitos no reduce más el total. No se deduplicaron por descripciones.

| Paquete | Informe / lock / global | Venv del proyecto | Registros originales | IDs/grupos por alias | Soluciones del informe histórico, ejemplos |
|---|---|---|---:|---:|---|
| bleach | 6.3.0 | 6.3.0 — coincide | 3 | 3 | 6.4.0 |
| certifi | 2026.5.20 | **2026.2.25 — difiere** | 1 | 1 | 2026.10.19 |
| cryptography | 49.0.0 | 49.0.0 — coincide | 2 | 1 | 50.0.0 |
| django | 6.0.5 | **6.0.3 — difiere** | 19 | 10 | 6.0.6, 6.0.7, 6.0.8; otras ramas también figuran, sin elegirlas aquí |
| djangorestframework | 3.17.1 | 3.17.1 — coincide | 5 | 5 | 3.17.2, 3.18.2 |
| idna | 3.13 | 3.13 — coincide | 2 | 1 | 3.15 |
| pillow | 12.2.0 | 12.2.0 — coincide | 60 | 48 | 12.3.0, 13.0.0 |
| pyjwt | 2.13.0 | **2.12.1 — difiere** | 15 | 15 | 2.14.0, 2.15.0 |
| pypdf | 6.12.1 | 6.12.1 — coincide | 43 | 32 | 6.12.2 a 6.21.1, varias versiones por advisory; no es un único rango seguro |
| urllib3 | 2.7.0 | **2.6.3 — difiere** | 3 | 3 | 2.8.0 |
| sqlparse | 0.5.5 | 0.5.5 — coincide | 9 | 5 | 0.6.0 |
| **Total del recibo histórico** | | No es total de avisos del venv | **162** | **124** | No representa explotabilidad actual. |

Ejemplos de identificadores ya registrados: bleach `GHSA-8rfp-98v4-mmr6`; certifi `PYSEC-2026-4320`; cryptography `PYSEC-2026-3552`; django `PYSEC-2026-197`; DRF `CVE-2026-114136`; idna `PYSEC-2026-215`; pillow `GHSA-78g4-xqwv-q3g8`; PyJWT `GHSA-pxh4-856f-4h89`; pypdf `PYSEC-2026-3009`; urllib3 `PYSEC-2026-4175`; sqlparse `PYSEC-2026-3696`. El conjunto por ID/aliases/fix_versions se conserva en la fuente F10; no se incorporan sus descripciones o URLs.

**Otros 29 pins, observados en el Python global original:** asgiref 3.11.1; boto3 1.43.95; botocore 1.43.95; cffi 2.1.0; charset-normalizer 3.4.7; dj-database-url 3.1.2; django-cors-headers 4.9.0; django-redis 7.0.0; djangorestframework-simplejwt 5.5.1; et-xmlfile 2.0.0; gunicorn 26.0.0; jmespath 1.1.0; openpyxl 3.1.5; packaging 26.2; psycopg y psycopg-binary 3.3.4; pycparser 3.0; python-decouple 3.8; python-dateutil 2.9.0.post0; redis 8.0.0; reportlab 4.5.1; requests 2.33.1; sentry-sdk 2.60.0; s3transfer 0.19.2; six 1.17.0; tblib 3.2.2; tzdata 2026.2; webencodings 0.5.1; whitenoise 6.12.0. No se declara que estén libres de vulnerabilidades.

De esos 29, **22 coinciden también en el venv**, incluidos los seis nombres ausentes del informe histórico. Las siete excepciones son:

| Paquete | Lock / global original | Metadatos del venv | Contraste con informe histórico |
|---|---|---|---|
| django-redis | 7.0.0 | No encontrados | El informe incluye 7.0.0; no acredita instalación en el venv. |
| redis | 8.0.0 | No encontrados | El informe incluye 8.0.0; no acredita instalación en el venv. |
| gunicorn | 26.0.0 | 25.3.0 | Versión distinta de la incluida en el informe. |
| packaging | 26.2 | 26.1 | Versión distinta de la incluida en el informe. |
| reportlab | 4.5.1 | 4.4.10 | Versión distinta de la incluida en el informe. |
| sentry-sdk | 2.60.0 | 2.58.0 | Versión distinta de la incluida en el informe. |
| tzdata | 2026.2 | 2025.3 | Versión distinta de la incluida en el informe. |

**Metadatos adicionales del venv fuera de los 40 pins (34 distribuciones):** bcrypt 5.0.0; boolean-py 5.0; build 1.5.0; cachecontrol 0.14.4; click 8.4.1; colorama 0.4.6; cyclonedx-python-lib 11.7.0; defusedxml 0.7.1; filelock 3.29.0; invoke 3.0.3; license-expression 30.4.4; markdown-it-py 4.2.0; mdurl 0.1.2; msgpack 1.1.2; packageurl-python 0.17.6; paramiko 5.0.0; pip 24.3.1; pip-api 0.0.34; pip-audit 2.10.0; pip-requirements-parser 32.0.1; pip-tools 7.5.3; platformdirs 4.9.6; psycopg2-binary 2.9.11; py-serializable 2.1.0; pygments 2.20.0; pynacl 1.6.2; pyparsing 3.3.2; pyproject-hooks 1.2.0; rich 15.0.0; setuptools 82.0.1; sortedcontainers 2.4.0; tomli 2.4.1; tomli-w 1.2.0; wheel 0.47.0. Solo se leyeron Name/Version: la presencia de herramientas no implica ejecución ni auditoría nueva. No se atribuyen al runtime de la app o a producción por estar instaladas.

### pnpm: paquetes señalados

Resumen original: **8 bajos / 39 moderados / 38 altos / 0 críticos**. Hay **85 registros e IDs numéricos internos distintos, 78 referencias GHSA distintas y 85 combinaciones paquete/versión/GHSA**; un GHSA puede figurar para distintos paquetes o versiones. Se conserva también el recuento de 85 combinaciones por ID interno, sin confundir ambas clases de identificador. No se suma el resumen como vulnerabilidades únicas. Todas las versiones base de esta tabla coinciden con lock y metadatos frontend locales.

| Paquete | Versiones registradas/locales | Registros | Alcance identificable | Referencia de corrección ya registrada, ejemplos |
|---|---|---:|---|---|
| @babel/core | 7.29.0 | 1 | Transitivo; rutas de finding vacías | >=7.29.6 |
| @vitest/mocker | 4.1.8 | 2 | Herramienta de tests/transitivo | >=4.1.11, >=4.1.12 |
| axios | 1.16.0 | 20 | Dependencia directa runtime; no se probó qué ramas Node/browser aplican | >=1.18.0, >=1.20.0 |
| baseline-browser-mapping | 2.10.29 | 1 | Transitivo; atribución por ruta pendiente | >=2.11.0 |
| brace-expansion | 1.1.14 y 5.0.6 | 12 | Transitivo, dos líneas de versión | >=1.1.16 y >=5.0.7, entre otras por advisory |
| browserslist | 4.28.2 | 2 | Transitivo; atribución por ruta pendiente | >=4.28.7 |
| follow-redirects | 1.16.0 | 2 | Transitivo; uso efectivo no demostrado | >=1.16.1 |
| form-data | 4.0.5 | 1 | Transitivo; uso efectivo no demostrado | >=4.0.6 |
| js-yaml | 4.1.1 | 4 | Transitivo; atribución por ruta pendiente | >=4.2.0 a >=4.3.2 según advisory |
| nanoid | 3.3.12 | 2 | Transitivo; atribución por ruta pendiente | >=3.3.16, >=3.3.18 |
| postcss | 8.5.14 | 2 | Transitivo; atribución por ruta pendiente | >=8.5.18, >=8.5.23 |
| react-router | 7.15.0 | 6 | Transitivo de dependencia runtime; rutas de finding no acreditadas | >=7.15.1, >=7.18.0, >=7.18.2 |
| source-map-js | 1.2.1 | 1 | Transitivo; atribución por ruta pendiente | >=1.2.2 |
| undici | 7.27.2 | 21 | Transitivo; atribución por ruta pendiente | >=7.28.0, >=7.29.0, >=7.29.1 |
| vite | 8.0.12 | 7 | Directa dev/build, no servidor runtime acreditado | >=8.0.16, >=8.1.6 |
| vitest | 4.1.8 | 1 | Directa dev/test | >=4.1.11 |

Los 31 directos se inventarían en `package.json` (rangos) y en el importer del lock (pins), contrastados con `package.json` instalados, sin ejecutar paquetes:

- **Runtime, 15:** @fullcalendar/{core,daygrid,interaction,react,timegrid} 6.1.20; @sentry/react 10.52.0; axios 1.16.0; framer-motion 12.38.0; lucide-react 1.14.0; react y react-dom 19.2.6; react-day-picker 9.14.0; react-router-dom 7.15.0; recharts 2.15.4; sonner 2.0.7.
- **Dev/build/test, 16:** @eslint/js 9.39.4; @sentry/vite-plugin 5.3.0; @testing-library/jest-dom 6.9.1; @testing-library/react 16.3.2; @testing-library/user-event 14.6.1; @types/react 19.2.14; @types/react-dom 19.2.3; @vitejs/plugin-react 6.0.1; eslint 9.39.4; eslint-plugin-react 7.37.5; eslint-plugin-react-hooks 7.1.1; eslint-plugin-react-refresh 0.5.2; globals 17.6.0; jsdom 29.1.1; vite 8.0.12; vitest 4.1.8.

Dockerfiles declaran Python 3.13, Node 20 para build, pnpm 9 y nginx 1.27; Compose declara Postgres 16, Redis 7 y Caddy 2. Son etiquetas declaradas, sin versión/digest desplegado observado. No se revisaron advisories de imágenes o del SO.

### CI

Gitleaks sigue **bloqueante** en la configuración local: captura exit y falla el job. pip-audit/pnpm audit tienen `continue-on-error: true`, alcance advisory. La evidencia previa de Gitleaks es histórica bajo su política existente; no confirma rotación ni certifica el checkout actual. No se leyeron/exportaron fingerprints ni se cambiaron gates, excepciones o archivos CI.

## 6. Accesos y superficie: declarada frente a activa

- F17 prescribe SSH sin root/password login y con claves, permisos restrictivos y firewall para SSH/web. Es una **receta**, no evidencia de aplicación. Includes/overrides, configuración efectiva observable, restricciones de usuarios/grupos, forwarding, sudo, grupos Docker y permisos remotos no son verificables en esta ejecución.
- Compose local publica solo en Caddy **80/TCP, 443/TCP y 443/UDP** sin bind de host explícito. No hay publicaciones para Postgres/Redis/backend/frontend/worker/sender. Backend declara bind 8000 dentro del contenedor. Caddy tiene listener de salud interno 8081 sin publicación; su listener no equivale a bind de loopback. La red llamada `internal` usa driver bridge y **no declara `internal: true`**: su nombre no acredita aislamiento de egress.
- Caddy declara proxy a API/hooks y frontend, TLS/headers y `admin off` para su API administrativa. Esto no prueba listeners, carga de configuración, firewall Docker/UFW/nftables ni accesibilidad pública. No se hicieron requests.
- Firewall del proveedor y estado de la cuenta están fuera de lectura del agente. Escucha local, publicación de contenedor y exposición pública son tres afirmaciones diferentes; ninguna fue contrastada remotamente.

## 7. O14 — backups, restore y observabilidad

### Lo que acredita el código local

F11 contempla dump custom → validación de TOC → manifest → cifrado age → copias daily y monthly → retención local → deadman. En modo producción exige offsite; el upload exige cifrado y la copia del manifest. El manifest se genera **antes** del upload y no contiene un recibo de upload: su mera existencia no acreditaría esa etapa. `pg_restore --list` comprueba lectura de catálogo, no restore íntegro.

F12 propone un backup diario a las 21:00 en la zona histórica documentada, retención local de 14 días, disk-alert horario y drill **manual mensual**, umbral documental de seguimiento **>35 días**. El scheduler efectivo y posibles duplicados cron/timer se desconocen. RPO 24h y RTO 1–2h son objetivos documentales, **no mediciones**.

F13 acredita documentalmente el restore offsite del **20-06-2026**: descarga, descifrado, checksum vs manifest, restore temporal y auditorías anchor/payment ledger. No acredita recuperabilidad hoy. La antigüedad del recibo supera 35 días, pero no demuestra que no haya habido otros drills.

El drill existente delega en `pg-restore.sh`, que crea/restaura otra DB en el contenedor Postgres del stack seleccionado y ejecuta backend contra ese stack. Rechaza el nombre de DB live; **no constituye aislamiento completo**. No se ejecutó. El fetch del manifest offsite es best-effort y la verificación en restore es opcional si falta o no aporta el campo; ver H04. El módulo también menciona `audit_billing_schema`, pero el drill solo invoca anchor/payment ledger; ver H05.

### Alertas: evidencia de diseño, no de entrega

- Backup llama al deadman al final cuando hay URL; fallo de ping solo registra error y no convierte automáticamente el final en fallo. En producción un upload fallido suprime ese ping. Sin conocer valores efectivos no se afirma activación.
- Worker tiene ajustes de deadman para planner y sender y llamada periódica; sin URL retorna, y excepciones de red se ignoran. No hay evidencia actual de recepción.
- Sentry se inicializa condicionalmente y configura `before_send`/`send_default_pii=False`. La documentación de junio relata una prueba recibida; no es una prueba de alertas actuales ni se auditó exhaustivamente el scrub.
- Monitor externo está descrito en el runbook; no se consultó su cuenta ni se probó el endpoint. El estado «ACTIVO» del documento no acredita el estado de hoy.
- Disk-alert usa umbral por defecto 80%; sin `ALERT_WEBHOOK` solo loguea. La plantilla no acredita wiring efectivo ni entrega. No se enviaron eventos o pings.

## 8. B3 y cierre

`HybridPermission` usa permisos DB si existen y, si no, el diccionario estático asociado al rol, con evento `RBAC_FALLBACK_ALLOWED` cuando permite. No se cambió. El gate documental exige **7 días consecutivos sin fallback permitido, al menos 500 requests y al menos un request por endpoint crítico**. No se sustituye ninguno de esos requisitos por silencio en logs, y no se iguala recuento de decisiones RBAC a requests sin deduplicación y cobertura.

No hubo acceso al VPS, pruebas de credenciales, escaneos nuevos, consultas de advisories/proveedores, tests/builds, comandos Django, backups nuevos o restores. No se leyó ni solicitó la clave privada age; no se modificaron código/configuración/infraestructura, no hubo reinicios/reloads ni deploy. Solo se añadieron estos documentos y lectores temporales locales fuera del repo. No se reabrieron B9/D29, deudas aceptadas, GA4/Formspree, media B2 u otros órdenes.

La aceptación de este **diagnóstico** conserva `PENDIENTE_USUARIO` y `NO_VERIFICABLE_EN_ESTE_ALCANCE`; no cierra remediaciones. Los estados son independientes de la prioridad de seguimiento. La ausencia de recibos no se clasifica como vulnerabilidad crítica.

### Verificación documental del cierre original

- Cinco entregables nuevos; matriz CSV válida con **66 filas e IDs únicos**, todas con criterio, estado, fuente, fecha, revisión/entorno, prioridad, limitación y siguiente acción.
- Cobertura: mapa 6, O13 26, accesos 8, O01 9, O14 13 y B3 4. Estados: **17 EVIDENCIA_CONFORME, 6 DESVIACION_CONFIRMADA, 17 PENDIENTE_USUARIO, 24 NO_VERIFICABLE_EN_ESTE_ALCANCE y 2 NO_APLICA**. Los recuentos son de criterios documentales, no de vulnerabilidades.
- Verificadas las 18 referencias lógicas y la existencia de los destinos de 40 enlaces relativos; no se adjuntan fuentes crudas. Los enlaces a documentos ajenos inicialmente no rastreados dependen de que estos también se conserven al compartir el expediente.
- Comprobadas estructura y formas de contenido privado en los cinco documentos nuevos, además de revisión de su redacción: sin direcciones/IP de infraestructura, rutas privadas absolutas, claves, asignaciones de credenciales, fingerprints o logs crudos. Esta comprobación documental no es un nuevo escaneo de secretos del repositorio ni certifica fuentes externas.
- `git diff --quiet` y `git diff --cached --quiet` sin diferencias rastreadas. El estado conserva los cuatro documentos ajenos y añade únicamente el expediente no rastreado. No se hizo stage, commit o push.
- Huecos conservados: todo el estado remoto y su ventana de registros, confirmaciones de rotación, advisories actuales, objetos/retención de proveedor, alertas entregadas, restore reciente y gate B3. Se enumeran con criterios de cierre en los pendientes del usuario.

### Aplicación de la revisión del 28-10-2026

- Corregidos F07/D02, resumen, tablas Python y H02 para separar lock, Python global y venv. El inventario global anterior sigue siendo evidencia de aquel entorno, no del backend ni de producción. D02 acredita la diferenciación de inventarios tras esta corrección, no conformidad de versiones con el lock.
- Precisado pnpm como **85 IDs numéricos internos y 78 GHSA**; sin cambio de los recuentos del informe histórico ni nueva consulta de advisories.
- **U01/U02 y P01 quedan aplazados hasta nueva instrucción**, igual que P08 y las partes remotas de P09. No se programa conexión, reactivación o consulta al proveedor y no son requisito para aceptar este diagnóstico local.
- El análisis/diseño local de P03 y de P05/P06/P07/P10 no depende de recuperar el VPS; su implementación o pruebas activas siguen sin estar autorizadas. El restore offsite continúa reservado al usuario para después, no se usa como sustituto del acceso remoto.
- Una futura lectura remota registrará **una nueva ventana** y distinguirá el hueco de cobertura original; no desplazará retrospectivamente este intervalo.
- Comprobación documental posterior a la corrección: se conservan los cinco entregables y el documento de revisión sin editar; matriz con 66 IDs únicos y los mismos estados/recuentos. Verificados los destinos de 41 enlaces de los cinco entregables, sin certificar todos sus anchors; comprobadas coherencia de cifras por entorno y formas de contenido privado. No se introdujeron remediaciones, instalaciones, pruebas activas o cambios fuera del expediente.
