# Desviaciones demostradas

Fuentes Fxx e intervalo en [README](README.md). **Todas las observaciones técnicas siguientes son locales**, revisión `8886604ff77bd86649c12dee695a4742a3fe44f5`, leídas el 28-10-2026. Prioridad ordena trabajo futuro; no es una severidad de vulnerabilidad. No se demostró explotación, acceso indebido ni compromiso del VPS.

## H01 — La clave Fernet independiente no está conectada a settings

- **Estado:** `DESVIACION_CONFIRMADA`. **Prioridad:** alta, antes de cualquier rotación. Matriz S07/S22.
- **Criterio:** el mecanismo anunciado debe poder consumir una clave independiente cuando se configure por entorno.
- **Evidencia:** F04, `crypto.py:21–26`, obtiene un atributo de settings, no lee directamente env. F05, AST del módulo completo: no asignación `AGENT_TOKEN_ENC_KEY`, sin importaciones `*` ni llamadas exec/eval. Los archivos de entorno/plantillas inspeccionados tampoco contienen ese nombre.
- **Efecto probado estáticamente:** usando ese módulo de settings sin override, `_fernet()` deriva la clave de `SECRET_KEY`. Agregar solo el nombre a env no habilita la rama independiente. No se inspeccionó el módulo/override remoto ni tokens persistidos.
- **Impacto acotado:** una futura rotación de la clave de derivación puede dejar ilegibles tokens existentes; `decrypt_secret()` devuelve cadena vacía ante `InvalidToken`/`ValueError`. No implica que actualmente estén corruptos ni que una clave expuesta siga vigente.
- **Recomendación mínima posterior:** primero aclarar configuración efectiva y dependencias con el operador; después proponer el wiring explícito y una transición/reprovisión controlada, coordinada con JWT. No agregar una clave nueva y cambiar de rama a ciegas.

## H02 — Persisten pins del corte de auditoría anterior

- **Estado:** `DESVIACION_CONFIRMADA` respecto a la deuda registrada, no certificación de CVEs actuales. **Prioridad:** alta para triaje; ejecución posterior según aplicabilidad.
- **Evidencia corregida el 28-10-2026 a las 19:07:12.105141Z:** F07/F08/F10. Los 11 paquetes Python con 162 registros históricos conservan sus versiones en el **lock**, y coincidían en el **Python global** leído originalmente. En el **venv del proyecto**, solo siete coinciden con esas versiones; difieren Django (6.0.3 frente a 6.0.5), certifi (2026.2.25 frente a 2026.5.20), PyJWT (2.12.1 frente a 2.13.0) y urllib3 (2.6.3 frente a 2.7.0). El total histórico sigue siendo 124 combinaciones paquete/versión/ID y 124 grupos por alias; no es un total de avisos del venv. Del conjunto de 40 pins, hay 29 coincidencias, nueve versiones distintas y dos nombres sin metadatos encontrados en el venv. El detalle completo se conserva en README §5.
- **Frontend, evidencia original separada:** los 16 paquetes de pnpm conservan las versiones señaladas en lock/metadatos frontend locales. El recibo tiene 85 registros/IDs numéricos internos, **78 GHSA distintos** y 85 combinaciones paquete/versión/GHSA; no se confunde GHSA con ID interno.
- **Alcance:** continuidad de pins asociados a avisos históricos y divergencias de inventario demostradas por entorno; no prueba explotación, exposición de funciones, intérprete de un proceso activo ni instalación remota. **No se trasladan los avisos o fixes de las cuatro versiones distintas al venv sin evidencia de aplicabilidad.** El informe Python no incluye seis paquetes del lock actual; los findings pnpm no aportan rutas utilizables. No se suman ecosistemas ni se presenta un total de vulnerabilidades únicas actuales.
- **Recomendación mínima posterior:** seleccionar explícitamente el entorno objetivo, clasificar cada advisory contra su versión instalada/runtime/dev/uso real y proponer cambios mínimos compatibles con validación aislada. El análisis local puede prepararse con estos metadatos sin P01; no sincronizar el venv con el lock a ciegas. Consultar vigencia de advisories o ejecutar pruebas/escaneos requeriría otro encargo. Mantener auditorías advisory y Gitleaks bloqueante.

## H03 — Contradicción sobre automatización del restore drill

- **Estado:** `DESVIACION_CONFIRMADA`. **Prioridad:** media. Matriz R04.
- **Evidencia:** F14 `modules/backup.md:27,93–103` y F13 `restore-drill.sh:7–21` describen cron local/mensual. F12 `cron-jobs.md:24–26,152–192`, `crontab.example:110–125` y F13 `RUNBOOK-RESTORE.md:16–19` fijan manual offsite mensual y ausencia de cron de restore.
- **Efecto:** el operador recibe instrucciones incompatibles sobre la política; no se demuestra duplicado ni ausencia de cron activo porque no se leyó el VPS.
- **Recomendación mínima posterior:** alinear únicamente la documentación/comentarios con la decisión de drill manual, previa confirmación del responsable. No instalar o editar cron para resolver una contradicción documental.

## H04 — La comprobación de integridad del manifest es condicional

- **Estado:** `DESVIACION_CONFIRMADA` frente al contrato descrito de validación del backup. **Prioridad:** media, antes del próximo drill.
- **Evidencia:** F14 `modules/backup.md:41–43` describe checksum en restore. F13 `restore-drill.sh:95–97` tolera fallo de fetch del manifest; `pg-restore.sh:99–116` solo comprueba integridad si existe manifest y se extrae un campo válido. El resto del restore no exige haber pasado por esa comprobación.
- **Efecto probado en fuente:** la ruta estática puede continuar sin checksum contra manifest y terminar con el veredicto del drill si pasan los otros pasos. No se probó un archivo alterado ni se afirma que el restore histórico omitiera el checksum: su documentación dice que lo verificó.
- **Recomendación mínima posterior:** para la prueba reservada al usuario exigir manifest y comprobación explícita de integridad como criterio de aceptación; en un cambio posterior decidir si hacer obligatoria esa precondición y reflejar fielmente cualquier excepción local. No se modificó el script.

## H05 — La documentación atribuye una auditoría que el drill no ejecuta

- **Estado:** `DESVIACION_CONFIRMADA`. **Prioridad:** media. Matriz R07.
- **Evidencia:** F14 `modules/backup.md:105–114` atribuye al drill `audit_billing_schema`, anchor y payment ledger. F13 `restore-drill.sh:172–184` invoca solo `audit_anchor_integrity` y `audit_payment_ledger_integrity`, además de sus consultas de invariantes previas.
- **Efecto:** el resultado del script por sí solo no acredita convergencia de esquema físico/modelo de Billing. No se ha encontrado ni inferido divergencia de esquema en una DB.
- **Recomendación mínima posterior:** distinguir auditorías realmente ejecutadas y previstas; el usuario debe incluir la auditoría de esquema en su prueba aislada y conservar resultado saneado. Cualquier cambio al drill será una tarea posterior separada.

## H06 — Las negaciones de plantillas quedan anuladas por reglas posteriores

- **Estado:** `DESVIACION_CONFIRMADA`. **Prioridad:** baja. Matriz S02.
- **Evidencia:** F03 `.gitignore:11–12` exceptúa las plantillas; `.gitignore:45` vuelve a ignorar `.env.*`. `git check-ignore -v --no-index` selecciona esa regla para las tres plantillas actuales. `git ls-files` confirma que ya están rastreadas.
- **Efecto:** discrepancia con la descripción del plan histórico sobre excepciones efectivas; nuevas plantillas pueden quedar ignoradas por defecto. Los cambios en las plantillas ya rastreadas siguen siendo visibles a Git. **No es exposición de secretos ni pérdida del seguimiento actual.**
- **Recomendación mínima posterior:** si se modifica la política de ignore, colocar excepciones específicas después del patrón amplio y verificar únicamente nombres/rastreo. No se editó `.gitignore`.

## Lo que no se convierte en hallazgo confirmado

- VPS sin inspección: no se afirma suspensión técnica, borrado, puertos públicos, configuración SSH insegura, fallo de backup o ausencia de monitoreo.
- Rotaciones sin confirmar: no se declara que un secreto histórico siga autenticando. El estado es `PENDIENTE_USUARIO`.
- Recibo DR de junio: antigüedad documental y hueco de evidencia, no prueba de 130 días sin restores ni pérdida de datos.
- ACL locales heredadas: se conoce su estructura; no se acreditó que un principal no autorizado acceda. Revisión de necesidad/pertenencia queda pendiente.
- B3 sin logs actuales: gate no acreditado; no se certifica incumplimiento por tráfico de pruebas local ni se retira fallback.
