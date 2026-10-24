# Resultado de la continuación B9: FAIL en BASE

La ejecución autorizada terminó con **FAIL**. No se concedió aceptación integral,
no se relanzó la campaña y no se repitieron perfiles. Se conserva también el FAIL
original de r12. [Decisión estructurada](RESULTS.json) y
[parada durable](b9-STOP.json).

| Bloque | Resultado |
|---|---|
| Backend/frontend previamente válidos | Referenciados y validados con los validadores originales, sin repetir PASS. |
| Gitleaks historial + seis correcciones | PASS bajo la política de fingerprints históricos exactos documentada. |
| pip-audit | ADVISORY_NONZERO: 162 avisos en 11 paquetes; informe completo en `blocks/pip-audit.json`. |
| pnpm audit | ADVISORY_NONZERO: resumen 8 bajos, 39 moderados, 38 altos, 0 críticos. JSON original en `blocks/pnpm-audit.command.log`. |
| BASE | FAIL: p95 de claim 11,572640 s frente a límite 10 s. |
| BLOCKED_LLM / META_SLOW / DUPLICATE / SATURATION | NOT_EXECUTED por parada obligatoria tras BASE. |
| Cleanup | PASS: PostgreSQL privado detenido, archivos conservados, sin tocar otros servidores. |

## Medición observada

Se ejecutó una sola vez el módulo original, sin smoke: calentamiento 30 s,
medición 300 s y drenaje 20 s, dos planners y un sender. El proceso terminó exit 0
y generó un recibo con `technical_pass=false`; exit 0 del runner no equivale a
aceptación del perfil. [Recibo](blocks/profile-base.json).

| Métrica del evaluador heredado | Muestras | p95 (s) | Máximo (s) | Faltantes | Gate original |
|---|---:|---:|---:|---:|---|
| Claim de clínicas sanas | 60 | 11,572640 | 14,334091 | 0 | FAIL, límite 10 |
| Dispatch de safety | 20 | 2,957768 | 2,957768 | No expuesto separadamente | PASS, límite 5 |
| Dispatch de outbox | 137 | 2,560056 | 6,811526 | 0 | PASS, límite p95 5 |

La ventana contiene 360 mensajes entrantes. El generador completo registró
33/33/330 envíos incluyendo calentamiento, 22 safety y ningún error. Se observó
un máximo de un trabajo activo por clínica. No se amplió la carga ni se cambió
un umbral para obtener estos resultados.

**Limitación identificada del evaluador original:** `healthy_claim` agrega las
dos clínicas sanas y dispatch agrega sus poblaciones correspondientes. El recibo
no contiene el desglose de percentiles por organización exigido para una
aceptación completa. Las cifras anteriores son las del gate heredado; **no se
presentan como SLO por clínica**. Esta brecha de reporte también debe resolverse
antes de conceder aceptación futura. No se alteró el evaluador ni se fabricaron
métricas por organización después de observar el fallo.

## Validez y alcance

Los guards no registraron incidentes invalidantes. Hubo 350 muestras del monitor:
RAM libre mínima 2.699.538.432 bytes (> 2 GiB), disco mínimo 14.333.603.840 bytes
(> 1 GiB), discontinuidad máxima de reloj 0,000310 s (< 1 s). La política de
recursos es la enmienda de 2 GiB autorizada anteriormente; no se afirma cumplir
el piso original de 5 GiB. El sello posterior comprobó **15932 archivos sin
diferencias**. El fallo no se elimina atribuyéndolo a un incidente no observado.

El candidato es el histórico `f5f18d71847a46d66644775cd90d30268f072e3b`, restaurado
con sus 3332 hashes exactos. Esta continuación no certifica el checkout de Inbox
fase 3 ni capacidad comercial, otros escenarios E4/D29 o uso real de proveedores.
Se mantiene la limitación histórica aceptada de evidencia compuesta.

No se determinó una causa raíz productiva mediante esta medición. El siguiente
trabajo de aceptación debe resolver el incumplimiento de latencia y el desglose
por clínica antes de una nueva ejecución explícitamente autorizada y acotada.
No se inicia automáticamente otra campaña, tuning ni un barrido de parámetros.

Las auditorías siguen siendo advisory para B9; sus avisos son deuda abierta y no
una certificación de seguridad de dependencias. Se evaluarán conforme a los
requisitos del release antes de desplegar. Meta/recepción, B2 real y aprobación
legal continúan pendientes; no hubo despliegue ni activación.
