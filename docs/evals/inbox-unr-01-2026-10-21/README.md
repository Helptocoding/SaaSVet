# WA-UNR-01 — lectura por empleado y hilo (2026-10-21)

Implementación local verificada: **35 pruebas únicas PASS** (24 nuevas y 11
regresiones afectadas), incluidas **dos carreras PostgreSQL reales**.

## Alcance

- Modelo InboxReadState con unicidad por clínica/usuario/contacto/cuenta,
  auditoría, FKs protegidas y last_read_message nullable SET_NULL.
- Migración M3 agent.0029_inbox_read_state: aditiva, sin backfill.
- GET threads añade unread_count por caller: solo inbound operacional visible
  del episodio vigente, con id posterior al marcador. Archivados = 0.
- POST read valida el hilo, tipo/visibilidad del mensaje y permiso agentinbox.view.
  Responde marcador persistido y contador; permite destinos de otra sesión.
- Upsert transaccional con bloqueo de fila y recuperación de carrera de creación;
  un marcador antiguo o repetido no cambia el estado ni updated_at.
- Consulta agregada por página, sin N+1 ni materializar mensajes/read-states.

No cambia frontend, acuses del cliente en WhatsApp, estado de mensajes,
claims ni TurnWork. UNR-02 integrará contador, divisor y marcado automático
únicamente con foco y visibilidad. El contrato anterior de lista se conserva
salvo el nuevo campo unread_count; la fixture congelada PERF-01 no se modifica.

## Validación dirigida

run_backend_tests.py selecciona solo el nuevo módulo (24 tests) y los dos módulos
afectados de rendimiento (4) y paginación (7): 35 casos. Incluye dos carreras
PostgreSQL con conexiones separadas y una barrera que fuerza la doble ausencia
inicial del estado; la fila final debe ser única y conservar el id máximo.

La regresión de payload compara todos los campos previos con la fixture original;
extrae únicamente unread_count y valida que sea entero. Los casos nuevos prueban
su semántica, la independencia multiusuario y el aislamiento por contacto/cuenta
y clínica. El chequeo de rendimiento conserva el presupuesto previo (<=4 queries)
y exige igual cantidad al pasar de 7 a 37 hilos. Se verifica una sola agregación
de conteos y cero instancias Message/InboxReadState cargadas en la lista.

migration-check.json registra makemigrations --check --dry-run PASS.
La migración se aplica solo en la base temporal del runner, cuyo nombre único
comienza con test_inbox_unr01_; se comprueba su eliminación al terminar.
No se ha migrado la base de trabajo ni desplegado/activado el subsistema.

No se ejecutan suites generales, builds frontend ni otra campaña B9. Recepción,
acuses Meta reales y seguridad r12 FAIL conservan sus gates existentes.


## Resultado y correcciones conservadas

- Primera corrida: 35 tests, 32 casos válidos y tres métodos con siete aserciones
  fallidas. Dos métodos detectaron un error de producto en el formato de respuesta:
  el handler global convertía los dicts de excepción en validation_error.
  Se usan NotFound con detail y una APIException de dominio con default_code,
  respetando el normalizador global, sin modificarlo.
- El otro método contaba como unread la agregación preexistente del número de
  sesiones dentro de la cabecera. Se corrigió solo la clasificación SQL del test,
  manteniendo una única agregación unread y cero instancias cargadas.
- Repetición dirigida: solo esos tres métodos, **3/3 PASS**. Composición final:
  **35 casos únicos PASS = 32 conservados + 3 corregidos**; no se suman dos veces.
- AST y hashes prueban que la consulta de conteos y las condiciones/escrituras
  monótonas no cambiaron; en el servicio solo cambió cómo se construyen los errores.
  En los tests solo cambió el método de clasificación SQL. Así se conservan los
  PASS de concurrencia, semántica, permisos, paginación y rendimiento.
- Ambas bases temporales eliminadas; system check sin issues en ambas corridas.
  Makemigrations --check --dry-run PASS. Sintaxis y diff-check PASS.
  La base de trabajo continúa pendiente de aplicar M3 al incorporar este código.

Recibos: [primera corrida](backend.json), [log inicial](backend.log),
[repetición](backend-followup.json), [log final](backend-followup.log),
[composición por test](backend-composite.json), [checks finales](final-checks.json),
[migración sin drift](migration-check.json), [validez conservada](retained-validation.json)
y [hashes finales](source-sha256.json). El [diff de formato](error-format-fix.diff)
y la fuente inicial del servicio quedan preservados.
verify_results.py recompone y valida estos resultados sin ejecutar pruebas nuevas.
