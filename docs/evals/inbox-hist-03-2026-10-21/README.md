# WA-HIST-03 — transcript centrado (2026-10-21)

Implementación local del endpoint opt-in `around`, verificada en PostgreSQL.
**33 pruebas únicas PASS: 22 nuevas y 11 regresiones afectadas.**

## Contrato

- Hasta 25 anteriores operacionales + destino + 24 siguientes, orden `(created_at, id)`.
- `has_older/has_newer` con centinelas SQL; sin rellenar los extremos.
- Destino oculto incluido con `is_hidden=true`; vecinos bajo el selector habitual.
- IDs ajenos/inexistentes: 404 `not_found`; cursor inválido o `around+before`: 400.
- Metadatos de sesión vigente, identidad y handoff conservados; historial cerrado legible.
- Página normal y `before` conservan su contrato y serialización anteriores.

La fixture contiene 200 mensajes, repartidos entre una sesión cerrada y una
vigente. Los cinco cortes principales exigidos por el plan son:

| Destino (índice desde 0) | Ventana esperada | Filas | has_older | has_newer |
|---|---|---|---|---|
| 0 | 0..24 | 25 | false | true |
| 10, en sesión cerrada | 0..34 | 35 | false | true |
| 100, cambio de sesión | 75..124 | 50 | true | true |
| 190 | 165..199 | 35 | true | false |
| 199 | 174..199 | 26 | true | false |

## Alcance y límites

Solo vista, pruebas y documentación; no hay cambios de modelo ni migraciones.
RPL-06/SRCH consumirán esta consulta; este corte no implementa el salto en la UI.
No se ejecutan suites generales, otra campaña B9, build ni pruebas UI: no cambió
el frontend. Las once regresiones seleccionadas ejercitan la misma vista y su
serialización operacional, paginación, correlación y tenant scoping.

La base de pruebas tiene un nombre aleatorio `test_inbox_hist03_*`, solo en
PostgreSQL local. El runner verifica su eliminación al terminar.
Recepción y acuses reales Meta permanecen pendientes; seguridad B9 r12 conserva FAIL.
Sin despliegue, activación, commit ni publicación.

## Registro de validación

`run_backend_tests.py` ejecutó 31 pruebas dirigidas en PostgreSQL: 28 PASS,
dos errores de fixture y un fallo del harness. Se conservan completos
`backend.log`, `backend.json` e `initial-source-sha256.json`.

Los tres casos se corrigieron solo en los tests:

- Hilo único: se crea otro hilo con un mensaje, en lugar de intentar un hard delete
  bloqueado por la protección existente de `OrganizationalQuerySet`.
- Estado UNCERTAIN: se aporta `uncertain_at`, exigido por la constraint vigente
  `message_uncertainty_evidence`; la constraint no cambia.
- Carga acotada: el límite inicial de 53 incluía por error las dos lecturas
  preexistentes del último mensaje en los metadatos. La aserción final identifica
  exactamente las 52 filas de destino/ventana (incluidos centinelas), separadas de
  esas dos lecturas. No se ensancha la ventana ni se relaja el límite de 50 expuestas.

`run_backend_followup.py` repite solo esos tres casos y añade dos de permisos:
VET con `agentinbox.view` puede consultar; AGENT sin ese permiso obtiene 403.
La repetición terminó **5/5 PASS**. El código de producto permanece idéntico
al de la primera ejecución; las 28 pruebas ya válidas no se repiten.
El resultado compuesto es **33 casos únicos PASS** (28 conservados + 5 finales),
sin ocultar los tres fallos iniciales. Ambas bases temporales fueron eliminadas.

Recibos: [primera corrida](backend.json), [log inicial](backend.log),
[repetición dirigida](backend-followup.json), [log final](backend-followup.log),
[composición por ID de test](backend-composite.json),
[checks finales](final-checks.json) y [hashes de fuentes](source-sha256.json).
`verify_results.py` verifica cobertura exacta, códigos de salida, limpieza de
bases y que la vista de producto no cambió después de la primera corrida.
Sintaxis y formato de los archivos modificados verificados.
