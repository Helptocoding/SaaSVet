# Cierre de evidencia — PASS

El runner inicial conserva 31 tests: 28 PASS, 2 errores de fixture y 1 fallo del harness.
No hubo cambios de producto después de la primera ejecución.

Correcciones dirigidas:
- Hilo único: crear otro contacto/hilo con un mensaje, sin intentar hard delete.
- UNCERTAIN: aportar uncertain_at, conservando message_uncertainty_evidence.
- Materialización: verificar exactamente las 52 filas de destino/ventana y distinguir
  las dos lecturas preexistentes del último mensaje en los metadatos de sesión.

La repetición solo incluye esos tres tests y dos nuevos de permiso (VET view-only
permitido; AGENT sin agentinbox.view rechazado). backend-followup.json: 5/5 PASS, base temporal eliminada.
Composición final: 33 casos únicos PASS (22 nuevos + 11 afectados), verificada
por verify_results.py en backend-composite.json.
Los recibos backend.log/backend.json y los hashes iniciales no se sobrescriben.
