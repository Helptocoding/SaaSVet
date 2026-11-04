# Orden 1: plan de diagnóstico pasivo de seguridad y recuperación

Fecha de acuerdo: **28 de octubre de 2026**, America/Mexico_City.

Deriva del [plan priorizado](plan-remediacion-priorizado-2026-10-28.md), categoría 1, y del [inventario con fuentes](pendientes-documentados-2026-10-27.md). El [metaprompt de ejecución](metaprompt-diagnostico-orden-1-2026-10-28.md) contiene el encargo para el siguiente agente.

## 1. Resultado esperado

Entregar un diagnóstico verificable del estado **observado** del repositorio y del VPS, con brechas, evidencia, límites y recomendaciones de remediación. El agente no implementará esas recomendaciones.

Al terminar, el usuario debe poder distinguir:

1. Qué controles tienen evidencia actual y qué versión/entorno cubre esa evidencia.
2. Qué problemas de configuración o fallos operativos están demostrados.
3. Qué no puede concluirse mediante inspección pasiva.
4. Qué tendrá que confirmar o ejecutar personalmente.
5. Qué trabajo de remediación conviene encargar después y en qué orden.

No se certificará que el sistema esté libre de vulnerabilidades ni que un backup sea recuperable sin la prueba correspondiente.

## 2. Decisiones del usuario: contrato de ejecución

| Tema | Decisión acordada |
|---|---|
| Datos del VPS | Solo demos o datos de prueba. Tratar archivos/logs/backups como privados igualmente. |
| Entornos | Repositorio local y VPS existente. |
| Objetivo | Solo verificar y entregar diagnóstico; sin remediar. |
| Comprobaciones | Solo inspección de archivos, configuración, metadatos y registros existentes. |
| Ventana | Últimos **90 días respecto del momento de ejecución**. Fechar el intervalo en UTC y America/Mexico_City; registrar zona del host. |
| Acceso remoto | SSH ya configurado. Descubrir alias y verificar identidad del host, usuario y ruta sin modificar configuración. |
| Cuentas externas | Las maneja el usuario. No iniciar sesiones ni consultar B2, hosting, Sentry, Healthchecks, etc. |
| Secretos | Inspeccionar **solo nombres de variables, permisos, propietario y fechas**. Sin mostrar/guardar/comparar valores ni generar fingerprints de secretos. |
| Confirmación de rotaciones | La hará el usuario después. Metadatos no demuestran rotación. |
| Backups cifrados | El usuario hará posteriormente descarga, descifrado y prueba de restauración. El agente no accede a la clave privada age. |
| Accesos VPS | Incluir SSH, sudo, permisos de archivos y servicios expuestos según configuración y metadatos locales. Sin pentest ni intentos de autenticación distintos del SSH autorizado. |
| Reinicios | El usuario los tolera si fueran necesarios, pero la selección posterior de inspección pasiva no justifica reinicios rutinarios. Este plan no los programa: si un dato requiere reiniciar/recargar, registrar la limitación y proponer otro trabajo. |
| Cambios permitidos | Solo artefactos documentales del diagnóstico y temporales locales mínimos necesarios para su lectura. Sin código/configuración/servicios modificados. |

No volver a preguntar por estas decisiones. Preguntar solo por un bloqueo real: varios hosts igualmente plausibles, identidad SSH desconocida/cambiada, ruta ambigua o necesidad de información que el usuario debe confirmar.

## 3. Alcance exacto y exclusiones

### Incluido

- **O13:** situación documental de secretos históricos y metadatos de su custodia actual.
- **O01:** inventario de dependencias, versiones y revisión de informes de auditoría **ya existentes**.
- **O14:** evidencia de backups, mantenimiento y monitoreo existentes, con énfasis en recuperabilidad **acreditada**, antigüedad y huecos.
- Configuración de acceso SSH/sudo, permisos y superficie de servicios del VPS.
- **B3:** solo indicadores existentes de uso del fallback RBAC; no corte ni migración de permisos.
- Concordancia entre código local, revisión desplegada, scripts/runbooks y configuración efectiva que pueda observarse pasivamente.

### Fuera de alcance

- Rotar, generar, comparar o revelar secretos; probar si credenciales históricas autentican.
- Nuevas ejecuciones de `pip-audit`, `pnpm audit`, Gitleaks u otros escáneres, ni consultas a registros de advisories.
- Instalaciones, upgrades, cambios de lockfiles, compilaciones, tests, comandos Django o scripts de validación del proyecto.
- Ejecutar scripts de backup/restore/drill, generar dumps, descargar/descifrar respaldos, crear bases temporales o probar recuperación.
- Requests HTTP de prueba, curl a endpoints/deadman, escaneos de puertos externos, pruebas de login, brute force o explotación.
- Reinicios, reload, cambios de servicios, firewall, SSH, sudo, crons, permisos o usuarios.
- Publicar, desplegar, activar WhatsApp/B2, aceptar contratos, modificar GA4/Formspree o abordar los órdenes 2–9.
- Benchmarks/campañas B9/D29, nuevos monitores/automations y reescritura del historial Git.

GA4/Formspree O11 pertenece a categoría 3 del plan priorizado. Aunque aparece en un bloque global de verificación P0, **no se incluye** en este encargo exclusivo de orden 1.

## 4. Reglas de inspección y manejo de evidencia

### Lectura pasiva

- Usar el grafo MCP para descubrir código; texto para literales/configuración/documentos, o cuando el grafo resulte insuficiente.
- Respetar AGENTS.md y RTK. Usar `rtk proxy` cuando no exista filtro. La ausencia de RTK en el VPS no autoriza instalarlo: usar el wrapper local para SSH y anotar la limitación del host.
- Consultar revisiones Git, estado de archivos, versiones registradas y metadatos de servicios mediante comandos de lectura acotados. No cargar settings Django ni importar código del proyecto para averiguar configuración.
- No ejecutar `.env` mediante `source`, dot-sourcing o equivalente. No ejecutar código encontrado dentro de configuraciones.
- No ejecutar los runbooks como recetas: contienen comandos de instalación, restore y cambios fuera de este alcance.
- Priorizar archivos/logs rotados relevantes; fijar filtros temporales y límites de salida. Si el archivo es grande, procesarlo en el host y devolver únicamente el resumen mínimo saneado.
- Las conexiones SSH y lecturas pueden generar logs técnicos normales. No modificar el estado de la aplicación ni afirmar ausencia absoluta de efectos de auditoría del sistema.

### Secretos y datos privados

- Nunca volcar `.env`, claves privadas, rclone config, cookies, cadenas de conexión, tokens o entorno completo a la herramienta, chat, logs o artefactos.
- Para archivos sensibles, extraer en el equipo de origen **solo nombres de claves y metadatos**; omitir valores, longitudes, prefijos, hashes y coincidencias. Nunca copiar esos archivos al informe.
- No usar `env`/`printenv`, `/proc/*/environ`, `docker inspect` completo, `docker compose config` completo ni argumentos que interpolen credenciales.
- Inspeccionar SSH por alias/referencia de identidad y configuración. No leer el contenido de claves privadas ni exportar el inventario de hosts ajenos al proyecto.
- Redactar logs **antes** de que salgan del host. No guardar copias crudas para redactarlas después. Si el saneamiento no es fiable, registrar evidencia inaccesible y seguir con los demás bloques.
- Informes de dependencias pueden incluir URLs privadas o datos sensibles: extraer únicamente paquete, versión, advisory, rango/solución **ya registrados**, fecha y alcance.
- Identificadores de usuarios/clientes y cuerpos clínicos o conversaciones no son necesarios; usar agregados. Mantener detalles privados de infraestructura fuera de Git.

### SSH y privilegios

- Descubrir un alias configurado a partir de metadatos/documentación local. Si varios corresponden plausiblemente al proyecto, preguntar antes de conectar; no probar todos.
- Usar autenticación existente y validación normal de host key. No deshabilitar StrictHostKeyChecking, aceptar claves desconocidas automáticamente ni editar known_hosts.
- Confirmar host, usuario y raíz de instalación. `/home/deploy/apps/SaaSVet` es una referencia del runbook, no una certeza.
- Usar privilegios ya disponibles solo para lecturas necesarias. No adivinar contraseñas ni solicitar secretos por chat. Si falta acceso, marcar qué evidencia requiere al operador.
- Comprobar configuración de sudo sin cambiarla; no ejecutar acciones privilegiadas como forma de “probar” permisos.

## 5. Fases de trabajo

### Fase 0 — Identificar revisiones, fuentes y límites

1. Leer este plan/metaprompt e instrucciones del repositorio.
2. Registrar fecha/intervalo, commit local y estado del checkout, preservando todos los cambios ajenos.
3. Identificar el alias SSH del proyecto y confirmar host/usuario/ruta según reglas anteriores.
4. Observar revisión desplegada mediante archivos/etiquetas/recibos existentes; no llamar `/api/version/`. Si el artefacto no tiene trazabilidad, declararlo.
5. Registrar alcance de logs disponible y bloqueos de lectura, sin detener los bloques independientes.

**Salida:** ficha de ejecución, mapa de fuentes y cobertura de lectura. Ninguna modificación de infraestructura.

### Fase 1 — Secretos y dependencias de las claves (O13)

1. Revisar `.gitignore`, plantillas y documentación de exposición/rotación. Leer nombres de variables, no valores de blobs históricos.
2. Identificar archivos de configuración activos y examinar owner, permisos y fechas; extraer solo nombres de claves. Diferenciar plantillas de configuración efectiva.
3. Buscar recibos existentes que acrediten fecha/alcance de rotación. El usuario conserva la confirmación final; no deducirla de mtime o longitud de una variable.
4. Revisar estáticamente consumidores de `SECRET_KEY`, configuración JWT y cifrado de tokens WhatsApp, sin cargar la aplicación.
5. Documentar si `AGENT_TOKEN_ENC_KEY` figura como nombre configurado. Eso **no prueba** que tenga valor efectivo ni que sea válido. Dejar esa incertidumbre explícita.
6. Elaborar matriz: nombre del secreto, uso, ubicación lógica, metadatos observables, evidencia de rotación, dependencia y acción futura. Sin valores/fingerprints.

**Criterio de cierre del bloque:** cada secreto documentado tiene estado y evidencia/límite; la rotación no confirmada queda **PENDIENTE_USUARIO**, no PASS ni FAIL de credencial vigente.

### Fase 2 — Accesos y superficie del VPS

1. Inspeccionar la configuración SSH efectiva cuando pueda obtenerse con lectura administrativa confiable: root login, password auth, autenticación por claves, restricciones de usuarios/grupos y forwarding. Registrar diferencias entre archivo y configuración efectiva si hay includes/overrides.
2. Revisar política sudo y grupos relevantes del usuario de operación, sin acciones de escritura ni escalación de prueba.
3. Examinar permisos/owner de raíz de aplicación, configuración sensible, archivos de SSH y rutas de backup. No proponer chmod recursivo genérico.
4. Relacionar puertos en escucha y bind addresses con publicaciones Docker, Caddy y firewall existentes. Usar metadatos locales; no sondas externas.
5. Diferenciar “escucha local”, “publicado por contenedor” y “accesible desde Internet”: lo último no se acredita solo con configuración local si hay firewall del proveedor no inspeccionado.
6. Revisar registros de accesos/eventos de seguridad del periodo de forma agregada. No elevar fallos de login aislados a compromiso confirmado.

**Criterio de cierre:** mapa de accesos/control/superficie, desviaciones demostradas y hechos externos no verificables por el agente.

### Fase 3 — Dependencias e informes existentes (O01)

1. Identificar versiones declaradas/pinneadas en `backend/requirements.txt`, `backend/requirements.lock`, `frontend/package.json` y `frontend/pnpm-lock.yaml`.
2. Cuando existan metadatos instalados/desplegados legibles, distinguirlos de los locks locales. No instalar ni ejecutar paquetes para obtenerlos.
3. Leer los informes existentes de auditorías y su fecha, commit, alcance runtime/dev y árbol de dependencias.
4. El resultado del 22-10 indica 162 avisos Python en 11 paquetes y resumen pnpm 8 bajos/39 moderados/38 altos. No convertirlo en número de vulnerabilidades explotables actuales ni deduplicar por suma de resúmenes.
5. Agrupar hallazgos existentes por paquete/advisory/versión/ruta cuando la evidencia permita. Clasificar: versión aún coincide, versión cambió o no hay evidencia suficiente. La coincidencia de versión no demuestra explotabilidad.
6. Inspeccionar CI: Gitleaks bloqueante y auditorías de dependencias advisory. No alterar gates ni excepciones históricas.
7. Crear cola de recomendaciones futuras mínimas, citando correcciones solo si ya constan en la evidencia disponible; no inventar versiones seguras actuales.

**Criterio de cierre:** inventario y triaje documental con antigüedad/cobertura. Sin auditoría nueva, la vigencia de advisories y ausencia de hallazgos nuevos queda **NO_VERIFICABLE_EN_ESTE_ALCANCE**.

### Fase 4 — Backups, recuperación y observabilidad existentes (O14)

1. Inspeccionar scripts y configuración, sin ejecutarlos. Identificar scheduler efectivo, zonas horarias y posibles cron/timer duplicados o ausentes.
2. Revisar metadatos/manifest y logs de backups de los últimos 90 días. Separar dump creado, validación, cifrado, upload y confirmación de éxito; no asumir upload por exit parcial de otra etapa.
3. Informar último éxito acreditado, edad calculada, fallos y huecos. Separar retención de logs de frecuencia real de backups.
4. Revisar recibos existentes de restauración. La documentación acredita un flujo offsite validado el **20-06-2026**; no equivale a evidencia reciente ni a demostrar que nunca se restauró.
5. Comparar con política documentada: backup diario/RPO 24h, drill offsite manual mensual y umbral documental >35 días. Son objetivos/umbrales existentes; no certificar RPO/RTO medidos mediante lectura de planes.
6. Contrastar módulos/scripts antiguos que mencionan cron de restore con `cron-jobs.md` y `crontab.example`, que conservan la decisión de drill manual. No modificar cron para “corregir” la discrepancia.
7. Revisar evidencia/configuración de deadman, alertas de disco, Sentry y monitor externo. No generar eventos/pings ni abrir cuentas. Configuración presente no prueba recepción real de alertas.
8. Preparar checklist de tarea del usuario: escoger backup offsite, conservar manifest, descargar/descifrar fuera del VPS, restaurar en entorno aislado, verificar integridad y registrar fecha/resultado. No ejecutar ningún paso.

**Criterio de cierre:** diagnóstico de evidencias/antigüedad y huecos. Recuperabilidad actual, existencia real del objeto B2 y custodia/funcionamiento de age quedan pendientes del usuario salvo recibos previos suficientes para afirmar únicamente su resultado histórico.

### Fase 5 — Indicador RBAC y consolidación

1. Revisar configuración/código de `HybridPermission` y agregados existentes de `RBAC_FALLBACK_ALLOWED`/tráfico relevante. No crear usuarios, seeds ni requests de prueba.
2. El gate histórico B3 exige siete días consecutivos sin fallback permitido, ≥500 requests y cobertura crítica. Un log incompleto/filtrado o ausencia de eventos no demuestra todo el gate. Documentar qué partes pueden comprobarse.
3. No eliminar fallback, cambiar User.role ni podar permisos; el cambio pertenece a un trabajo posterior.
4. Conciliar evidencias de todas las fases, separar hallazgos de controles no verificados y priorizar acciones futuras por impacto demostrado.

## 6. Estados y prioridad: dos dimensiones distintas

| Estado | Uso |
|---|---|
| EVIDENCIA_CONFORME | El criterio concreto tiene evidencia suficiente con fecha/versión/entorno. No significa seguridad general. |
| DESVIACION_CONFIRMADA | Una lectura demuestra una configuración o incumplimiento del criterio. Describir condición y alcance, sin inventar impacto explotable. |
| PENDIENTE_USUARIO | Confirmación de rotación, proveedores, descarga/descifrado/restore u otra acción reservada al usuario. |
| NO_VERIFICABLE_EN_ESTE_ALCANCE | Hace falta prueba activa, comparación de valores, fuente externa o acceso no disponible. |
| NO_APLICA | Evidencia y motivo justifican que el criterio no corresponde al entorno. |

La prioridad de seguimiento puede ser inmediata/alta/media/baja. Reservar severidades de vulnerabilidad para efectos de seguridad demostrados; no llamar “vulnerabilidad crítica” a una ausencia de recibo. Si la lectura muestra un secreto potencialmente expuesto, no intentar autenticarlo: avisar sin revelar el valor y recomendar el siguiente paso.

## 7. Entregables del agente

Crear un expediente nuevo bajo `docs/diagnosticos/orden-1/` con nombre fechado y sin sobrescribir ejecuciones anteriores. Solo promover resultados saneados a esa carpeta; ningún log/config/dump crudo.

1. **README.md:** resumen ejecutivo, alcance autorizado, intervalo, entorno/revisiones, resultados y limitaciones.
2. **matriz-evidencias.csv:** ID, categoría, criterio, estado, fuente lógica, fecha de evidencia, revisión/entorno, prioridad de seguimiento, limitación y siguiente acción. Sin datos sensibles de infraestructura o usuarios.
3. **hallazgos.md:** únicamente desviaciones demostradas, qué se observó y recomendación mínima; remediaciones no ejecutadas.
4. **pendientes-usuario.md:** checklist de confirmaciones de rotación, recibos de proveedores y restore posterior, con evidencia esperada para cerrar cada punto.
5. **plan-remediacion-propuesto.md:** acciones posteriores ordenadas, dependencias, validación y reversión conceptual. No es autorización de ejecución.

No copiar nombres privados de host, IP pública, usuarios ajenos al proyecto, rutas de claves o detalles de políticas de acceso a archivos versionados. Usar identificadores lógicos; si el usuario necesita detalle operacional privado, mantenerlo fuera del repo y registrar solo su referencia no sensible.

El reporte final debe declarar expresamente: no se probaron credenciales, no se hicieron escaneos nuevos, no se probó restore, no se cambió producción y no se certifica go-live.

## 8. Condiciones de aceptación del diagnóstico

- Todos los bloques O13/O01/O14, accesos y observación B3 tienen estado, evidencia o limitación explícita.
- Cada conclusión distingue repositorio local de versión/configuración desplegada.
- Los 90 días tienen cobertura documentada; no se inventan registros ausentes.
- No aparecen valores/fingerprints de secretos, contenido clínico, dumps o logs crudos en herramientas/artefactos.
- Los nuevos informes enlazan correctamente fuentes sin sobrescribir recibos históricos.
- No se ejecutaron cambios de servicios/configuración/código ni pruebas activas fuera del acuerdo.
- El usuario recibe una lista separada y ejecutable de sus tareas posteriores.
- Puede cerrarse el **diagnóstico** con PENDIENTE_USUARIO/NO_VERIFICABLE; eso no cierra la remediación, la seguridad ni la recuperabilidad.

## 9. Hechos de partida y fuentes principales

- [Secretos históricos y plan de rotación](security/secret-rotation-plan.md): no inferir vigencia de los valores expuestos ni ejecutar sus recetas.
- `backend/apps/channels/crypto.py::_fernet`: usa `AGENT_TOKEN_ENC_KEY` y, si no hay valor efectivo, deriva la clave de `SECRET_KEY`. La presencia del nombre no resuelve esa condición.
- `backend/config/settings.py`: comprobar consumidores/configuración JWT estáticamente; no importar settings.
- [Resultados de auditorías existentes del 22-10](evals/inbox-readiness-2026-10-22/B9-RESULTS.md) y su carpeta `blocks/`.
- [CI](../.github/workflows/ci.yml), locks y manifiestos: auditorías advisory; Gitleaks bloqueante.
- [Restore](runbooks/RUNBOOK-RESTORE.md), [cron](runbooks/cron-jobs.md), [backup](modules/backup.md), [monitoring](runbooks/monitoring.md), [observability](runbooks/observability.md).
- `scripts/{pg-backup,pg-restore,restore-drill}.sh` y `scripts/crontab.example`: lectura únicamente. El script de drill puede usar el cluster compartido con una base de otro nombre; eso no equivale a aislamiento completo ni autoriza ejecutarlo.
- [Hardening VPS](runbooks/vps-hardening.md) y [pre-launch](runbooks/pre-launch-security.md): usar como criterios de lectura; no ejecutar sus cambios ni su validador activo.
- [Deuda B3](deuda/fase3-prioridad-media.md): preservar el gate y las excepciones anteriores.

Los hechos anteriores son guías de inspección, no reemplazan comprobar qué versión y configuración hay cuando el siguiente agente ejecute el diagnóstico.
