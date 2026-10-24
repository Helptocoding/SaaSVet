# Fase 3 completa — ejecución autorizada el 22-10-2026

Solicitud: «implementa todo lo de fase 3». Completar RPL-07 y MED-01..05 en esta
ejecución, conservando RPL-01..06 y la evidencia válida. MED-06 es opcional y se
mantiene fuera del cierre obligatorio descrito al usuario. La nueva solicitud
autoriza agrupar la fase; no ejecutar solo una WA y pedir otro «continúa».

## Estado final: implementación y validación local completadas

- RPL-07: contexto nativo tras admisión B4 y matriz final verificados.
- MED-01: MessageMedia/storage local-B2, M4 temporal y dependencias verificados.
- MED-02: captura atómica, raw/caption, dedup/carreras y contrato B1 verificados.
- MED-03: transferencia acotada, claims/retries/leases, purga/reconciliación,
  versiones B2 simuladas, scavenger e integración worker/job verificados.
- MED-04: streaming privado y matriz de permisos/clínica/errores verificados.
- MED-05: controles, captions/previews, blobs, N+1 y deltas verificados.
- Final: 170 backend y 257 frontend únicos PASS; build/lint/drift y Chromium
  escritorio/móvil PASS. Documentación y evidencia compuesta completadas.

## Restricciones preservadas

Sin tocar bases habitual/preview: migraciones solo en PostgreSQL temporal.
Sin commit, push, despliegue, activación ni requests reales Meta/B2. No leer ni
imprimir secretos. INBOX_MEDIA_ENABLED default false; B2 se habilita únicamente
tras gates externos de almacenamiento/privacidad/ARCO/DPA, que no se inventan.
Recepción/Meta reales siguen pospuestos por el usuario. B9 FAIL sigue vigente.
No nuevos scheduler/SSE/planner/tools. No repetir PASS salvo cambios afectados.
Usar RTK en todo shell y grafo para descubrimiento. No subagentes autorizados.

## Archivos principales nuevos/modificados

backend/apps/channels/{models.py,providers.py,replies.py,events.py,views.py,
media_storage.py,media_policy.py,media_ingest.py,media_transfer.py,media_worker.py}
backend/apps/agent/{sender.py,services.py,serializers.py,views.py,urls.py,
inbox_sync.py,inbox_media.py,management/commands/run_agent_worker.py}
backend/apps/channels/management/commands/maintain_inbox_media.py
backend/config/settings.py

El checkout contiene muchos cambios previos legítimos; no limpiar ni reordenar
otros archivos. Los manifiestos anteriores quedan sellados e intactos.


Cierre: 170 pruebas PostgreSQL y 257 frontend únicas PASS. Ver README.md, summary.json y cases.json.
Los gates reales descritos siguen pendientes; no se acreditan por simulación.
