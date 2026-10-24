# WA-ASN-01 — Asignación explícita a compañeros

Implementación local del 21-10-2026. Alcance: asignación de una conversación abierta,
directorio mínimo, selector de cabecera, serialización y auditoría. Sin migración,
commit, push, despliegue ni activación. Recepción/Meta reales pospuestos por el usuario.

## Contrato

`GET /api/inbox/assignable-users/` y `POST /api/inbox/conversations/{uuid}/assign/`
exigen `agentinbox.claim`. El POST recibe `{user_public_id}` y vuelve a comprobar
usuario activo de la misma clínica con permiso DB estricto `agentinbox.send`.
Se excluyen service accounts y ADMIN_SAAS. El directorio usa una consulta de usuarios
con `distinct`, sin N+1, y expone únicamente UUID/nombre.

Conversation comparte el row lock de claim/release/close. Una transferencia real
invalida autoridad anterior con el fence existente, cambia responsable/fecha/estado
y emite el evento de auditoría tras commit. Repetir el mismo objetivo ya activo es
idempotente. Se permite asignarse a sí mismo y tener múltiples casos asignados.
Asignar no inventa acuse del handoff, lectura ni push. Conserva garantías de B4.

La UI carga el directorio al abrir, ofrece selección/confirmación/cancelación y
reintento. Deshabilita doble submit y acciones simultáneas; conserva el borrador.
Aborta GET al cerrar/cambiar y descarta POSTs tardíos al cambiar hilo/sesión o salir.
Un POST recibido puede estar aplicado aunque la vista se haya cerrado.

## Verificación dirigida

El resultado reproducible está en [manifest.json](manifest.json), generado por
`rtk proxy python -X utf8 docs/evals/inbox-asn-01-2026-10-21/verify.py` una sola vez.
Los recibos no se sobrescriben. Evidencia compuesta, sin suites generales ni campaña B9.
Los [checks finales](final-checks.json) conservan hashes del código entregado y el
diff check. Después del manifiesto solo se quitó una línea vacía al final del CSS;
`finalize.py` comprueba exactamente esa diferencia, sin repetir tests por whitespace.

- API: **20 IDs únicos**, incluidos dos órdenes de carrera real assign/claim.
  Las carreras observan `wait_event_type=Lock` en PostgreSQL antes de liberar la
  primera petición: assign primero deja claim en 409; claim primero permite la
  transferencia posterior. Permisos, tenant, inactivos, revocación tras directorio,
  payload, cierre, idempotencia, fence, auditoría/rollback y deltas cubiertos.
- Frontend: **25 IDs únicos**: 19 nuevos y seis regresiones de Tomar/Liberar/acuse.
  Los ocho casos del selector se repitieron tras mover las transiciones de carga
  del effect al evento. No se cuentan dos veces. Build y lint finales en
  [build-final2.json](build-final2.json) y [lint-final2.json](lint-final2.json).
- Navegador CUA con Django real y base sintética separada: asignación a María López,
  cabecera actualizada, borrador conservado y handoff todavía pendiente de acuse.
  Móvil solicitado 390×844: selector x=89..355 dentro de 384 px de documento;
  confirmación al mismo objetivo y borrador conservado.
  [Recibo](browser-check.json), [escritorio](desktop-assigned.jpg),
  [selector móvil](mobile-selector.jpg). No se enviaron mensajes.

## Incidencias conservadas y correcciones acotadas

1. `frontend-new`: 17 PASS y un fallo de fixture: `agent_processing` estaba fuera
   de `conversation`. Se corrigió y repitió solo ese caso en `frontend-turn`.
2. `backend-new`: cuatro PASS; la aserción de transcript delta esperaba el campo
   fuera de `metadata`. Corrección de aserción; `backend-remaining` conservó esos
   cuatro PASS y aprobó otros dos antes del siguiente fallo.
3. `backend-remaining`: el mock compartido de `agent.events` veía tanto el evento
   preexistente de ownership como el de asignación. La prueba ahora exige
   exactamente un `INBOX_CONVERSATION_ASSIGNED` con sus campos exactos, sin
   descartar el evento legítimo anterior. No se cambió producto para este fallo.
4. `lint-final`: `set-state-in-effect` en el componente nuevo. Se movió la carga
   inicial al evento abrir/reintentar; ocho casos del selector, build/lint repetidos.
5. `backend-pending`: 13 PASS y un defecto real de ruta: el resolver legado aceptaba
   el PK `1` con la configuración local. Se restringió exclusivamente la ruta nueva
   al converter UUID. `backend-uuid` comprueba rechazo de IDs numéricos/ajenos y
   asignación válida. Las rutas existentes no cambian.

Las ejecuciones iniciales usaban fail-fast; la última selección pendiente lo quitó
para recoger todos sus resultados juntos y evitar recrear una base por cada fallo.
Sin rebajar aserciones, umbrales ni gates del producto. Cada base temporal tiene
cleanup acreditado en su recibo. Los PASS anteriores de permisos/auditoría/carreras
usan UUID, por lo que conservan aplicabilidad tras restringir la ruta.

## Límites

M3 sigue sin aplicar a la base habitual. La demostración usa una base separada con
datos y cuenta sintéticos, claves JWT propias y ningún emisor/worker. Se habilitó
el permiso send de una veterinaria solo en ese fixture de demostración. No se amplió
el rol VET global. La validación de recepción y Meta sigue pendiente; B9 mantiene
su FAIL histórico de seguridad. Siguiente tarea funcional: WA-RPL-01.
