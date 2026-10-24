# Cierre técnico adicional de Inbox, 22-10-2026

[Resultados estructurados](RESULTS.json) y [manifiesto de entrega](MANIFEST.json).
El manifiesto cubre este expediente público, documentos preparados y archivos de
configuración/seguimiento modificados; excluye runtime privado y no se incluye
a sí mismo. Los recibos históricos permanecen en sus expedientes originales.

Alcance autorizado: puntos 1, 2, 3, 5 y 6; Meta/recepción (4) queda a cargo del
usuario y despliegue/activación (7) no se ejecuta. El usuario confirmó que B2 real
también queda pendiente y pidió preparar los documentos legales.

| Punto | Resultado actual |
|---|---|
| 1. M2/M3/M4 | **PASS local**, con backup previo; preview/producción no se tocaron. |
| 2. B2 | **APLAZADO POR EL USUARIO**; configuración y validación futura preparadas. |
| 3. Privacidad/DPA/ARCO | **PREPARADO PARA REVISIÓN**; sin publicación, firma, aceptación ni promoción legal. |
| 4. Meta/recepción | **EXCLUIDO**, pendiente del usuario. |
| 5. Seguridad | **PASS de la verificación nueva**, historial y seis archivos de corrección; FAIL r12 preservado. |
| 6. B9 | **FAIL en BASE**: p95 claim 11,57 s > 10 s; cuatro perfiles NOT_EXECUTED. Auditorías advisory realizadas; sin aceptación integral. |
| 7. Despliegue/activación | **NO EJECUTADO**, decisión separada. |

## Migraciones locales

[Recibo](migrations-local.json) y [estado previo](migrations-local-before.json).
Base `veterinaria_saas`, PostgreSQL 18.3 local. M2 channels0016, M3 agent0029 y M4
channels0017 aplicadas con doce prerrequisitos de agent/channels. Se comprobó la
FK nullable de reply, las tablas nuevas y la conservación del conteo de mensajes
(0 → 0). Media permanece desactivada. No se revirtió ninguna migración.
El [check Django posterior](local-django-check.json) pasó sin incidencias.

Backup custom previo privado: `runtime/local-before.dump`, 1.375.618 bytes,
SHA256 `2d92b16466b9497ff2292ac9276dc04fb73d8ad5624e83609742baa4a562b1bb`.
`pg_restore --list` verificó su inventario; no se afirma un simulacro de restore.
Los guards iniciales por prerrequisitos pendientes y pg_dump de versión anterior
se resolvieron antes de mutar datos; se usó pg_dump 18 para el servidor 18.

## B2 y privacidad

[Expediente de revisión](../../compliance/inbox-privacy-review-2026-10-22/README.md):
aviso Astro completo, parche para la landing, ficha DPA/tratamiento internacional,
pasos de publicación y reconsentimiento, y configuración B2 propuesta. El
[procedimiento ARCO](../../compliance/arco.md) detalla bloqueo anticipado, fencing,
purga de versiones y reaplicación después de restaurar. La sintaxis Astro pasó
sin diagnósticos; no sustituye el build de la landing ni aprobación del texto.

No hay credenciales B2 dedicadas ni DPA aplicable aceptado. La región está por
definir. El addendum EEA/EU localizado no acredita por sí solo cobertura del
tratamiento mexicano. Lifecycle nativo ejecuta por lotes y no prueba purga física
exacta al día 180: resolver plazo efectivo y operación antes de activar.

La consulta web pública mostró un aviso anterior; la descarga directa posterior
falló en TLS. Se debe verificar la publicación viva antes de promover una versión
legal. Se archivaron fuentes oficiales y sus hashes de forma privada, sin
desactivar TLS ni presentar el borrador como vigente.

## Seguridad

[Clasificación](security-classification.json), [política](security-policy.json),
[verificación histórica](security-verification.json) y
[correcciones B9](security-correction-verification.json).

Los 3156 hallazgos históricos se clasificaron por contexto: 2606 hashes de archivo,
422 UUID de operación de tests, 119 UUID de leases de tests, cinco identificadores
de directorios de diagnóstico, dos fixtures locales de firma y dos identificadores
de deduplicación entrante. Se agregaron exclusivamente sus fingerprints exactos
commit/archivo/regla/línea a `.gitleaksignore`. No se cambiaron reglas TOML ni se
excluyeron carpetas, valores generales o todos los casos de una regla.

Gitleaks 8.18.4 descargado del release oficial y checksum verificado: 457 commits,
0 hallazgos pendientes; HEAD y refs idénticos antes/después. El control con valor
sintético nuevo en una ruta previamente afectada fue detectado. Los seis archivos
de corrección del candidato B9 también pasaron. Esta evidencia **no certifica todos
los archivos sin commit del checkout actual** ni reescribe el FAIL histórico r12.

## B9

[Decisión de continuación](B9-RESUMPTION.md),
[referencias originales validadas](b9-retained-reference-validation.json),
[restauración del candidato](b9-candidate-restoration.json) y
[sello de evaluación](b9-evaluation-seal.json).

Se recuperó el candidato histórico f5f18d7 con 3332 hashes exactos. Se preservan
3331 IDs backend (3319 PASS y 12 SKIP identificados), 355 PASS frontend y los demás
gates válidos; sin repetir suites generales. El Inbox actual tiene evidencia
separada en fase 3 y no se presenta como el candidato histórico de B9.

Entorno Windows privado, Python 3.13.2, 34 pins originales, PostgreSQL 16.15 durable,
Node 20.20.2, pnpm 9.15.9 y pip-audit 2.10.1. Se conserva reserva de RAM 2 GiB,
disco 1 GiB y discontinuidad máxima del reloj 1 s, con observación previa 120 s,
vigilia del hilo propio y monitoreo por segundo. Fixtures, carga, concurrencia,
tiempos y gates del módulo original no cambian.

Durante preparación, el wrapper RTK heredó un pipe del servidor y no terminó
después de pg_ctl. Se identificaron y liberaron exclusivamente wrapper/proceso
obsoleto propios, preservando la instancia privada; luego se verificaron servidor,
intérprete y reloj. No había comenzado ningún perfil. El incidente no se atribuye
al producto y sus scripts/recibo se conservan. No se cambiaron energía ni W32Time.

[Resultado final B9](B9-RESULTS.md): una ejecución BASE, p95 claim 11,572640 s
frente a 10 s; safety/outbox pasan los gates heredados. Guard de recursos/reloj
válido y 15932 archivos sellados sin diferencias. Cuatro perfiles NOT_EXECUTED,
sin reintento ni otra campaña. Cleanup PASS, servidor privado detenido.
El evaluador original agrega métricas entre clínicas; el desglose por organización
queda identificado como requisito adicional pendiente del reporte de aceptación.
Esta ejecución terminó con decisión documentada, sin conceder aceptación ni
declarar un cierre administrativo aprobado por el usuario.

Auditorías realizadas, **advisory** según el contrato: pip-audit reportó 162
avisos conocidos en 11 paquetes; pnpm reportó 85 avisos (8 bajos, 39 moderados,
38 altos, 0 críticos en su propio resumen). No se extrapola la severidad de pnpm
a Python. Se conservan los informes completos; estos resultados no significan
dependencias libres de vulnerabilidades. No se actualizaron locks dentro del
candidato congelado ni se cambió su clasificación para aprobar B9. Su revisión
y remediación sigue siendo deuda de dependencias antes del release que la requiera.

## Límites

No commit, push, despliegue, publicación legal, reconsentimiento de usuarios reales
ni activación. No pruebas reales Meta/B2/recepción. MED-06 saliente opcional sigue
pendiente. E4/D29, SSE, nuevos schedulers y tuning no se reabren.
