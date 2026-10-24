# Continuación B9 acotada, 22-10-2026

Autorización: «realiza los 6 puntos exeto el 4 que ese lo hare yo». Se interpreta
como puntos 1, 2, 3, 5 y 6 de la respuesta anterior: migraciones, B2, privacidad,
seguridad y pendientes B9. El punto 4 Meta/recepción queda excluido; no se ejecuta
el despliegue/activación del punto 7. El usuario confirmó posteriormente que B2
real se aplaza y pidió preparar los documentos de privacidad.

Se corrige el gate de seguridad con 3156 fingerprints históricos exactos
clasificados; no se cambia `.gitleaks.toml`, desactiva una regla ni excluye una
ruta completa. Se conserva el FAIL r12 y se abre una comprobación nueva bajo
esa política explícita. Gitleaks 8.18.4, control negativo, historial HEAD (457
commits, refs estables antes/después) y seis archivos de corrección: PASS.

La continuación de aceptación usa el **candidato histórico f5f18d7**, restaurado
desde el árbol Git con sus 3332 hashes exactos. La exportación inicial produjo
CRLF donde el manifiesto histórico conservaba LF; solo se restauró LF cuando
los bytes resultantes coincidían con el SHA registrado. No hay cambio semántico,
de fixtures, locks ni código productivo. El checkout actual contiene Inbox nuevo
y no se presenta como el mismo candidato. Los PASS históricos de B9 conservan
su limitación de evidencia compuesta; no se repiten las suites aprobadas.

Etapas restantes: auditorías advisory pip-audit/pnpm audit; BASE, BLOCKED_LLM,
META_SLOW, DUPLICATE y SATURATION, secuenciales y una vez por variante. Se conserva
el módulo original `b9e_profile.py`, warmup 30 s, medición 300 s, drenaje 20 s,
carga, concurrencia, debounce, denominadores, observaciones y gates originales.
Sin smoke, barridos, afinación de umbrales ni cambio de carga para buscar verde.

Entorno privado Windows: Python 3.13.2 y 34 pins del lock original, PostgreSQL
16.15 durable (fsync/synchronous_commit/full_page_writes on), Node 20.20.2,
pnpm 9.15.9 y pip-audit 2.10.1. Puerto dedicado 35591 y una base nueva por perfil.
No usa la base local habitual ni claves reales. Las herramientas de auditoría
son privadas y sus dependencias se registran separadamente del producto.

Se conserva el piso/reserva de RAM 2 GiB y disco 1 GiB autorizado previamente,
reloj estable (observación previa de 120 s y guard de discontinuidad 1 s), petición
de vigilia del hilo propio, monitor nativo de recursos a intervalos de 1 s,
sellos de fuentes, dependencias, scripts, configuración y recibos referenciados
antes/después de cada bloque. No se cambia W32Time ni planes de energía.

Una aserción de producto válida produce FAIL y termina la continuación. Un fallo
de entorno/guard produce PENDING y también la termina; los demás perfiles quedan
NOT_EXECUTED. No se reintenta automáticamente ni se relanza otra campaña. El
proceso finaliza su propio PostgreSQL y conserva todos los artefactos.

Incluso un PASS sería `PASS_BAJO_CONDICION_DE_EVIDENCIA_ENMENDADA`, separado de
la validación del Inbox actual y de `PENDING_ACTIVATION_REQUIREMENTS`. No acredita
Meta, B2, recepción, legal, producción ni capacidad comercial.
