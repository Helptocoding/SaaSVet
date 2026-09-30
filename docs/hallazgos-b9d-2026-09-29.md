# Hallazgos y límites — B9D

Baseline: `4f6d199dc4f8b38e5d48582f9ee289bf8dcfdb17`. Este seguimiento no reemplaza
la auditoría original ni los informes de discrepancia conservados.

| Hallazgo/área | Aporte B9D | Pendiente |
| --- | --- | --- |
| H16/H19 | Gate de alcance org/capability con evidencia y cinco WRITE bajo B8A | B9E: perfil, CI/eval candidato y aceptación integral; ninguna clausura global |
| H03/H04 / safety y circuito humano | Referencia obligatoria a revisión veterinaria y simulacro Inbox | Validación humana real del protocolo/corpus; no certificación del software |
| H17 / privacidad | Referencia a política/mecanismo aplicable con autoridad y revisión | P-A/P-B y revisión operacional real, sin sistema legal nuevo |
| H01/H18 / consentimiento y permiso | Composición con B7/B8 sin sustituir evidencia causal ni permiso vigente | Sin cierre universal; identidad débil y ampliación de alcance siguen condicionadas |
| Autocertificación | Sin writer, endpoint o capability de aprobación; manifest de código | Revisión de release y custodia de registros externos |
| Retirada | Cierre en B8A y fecha nueva que excluye operaciones antiguas | Pausa/drain/corte de todos los writers; versiones mixtas no soportadas |
| Identidad/cobertura | Evidencia de riesgo de teléfono y owner/cobertura requerida | Riesgo de identidad débil y ausencia humana; observación/retirada operacional |
| Alcance READ | Lista explicita la autonomía aprobable; rutas previas conservadas | Promoción READ exige gate operacional, sin claim de contención automática de toda consulta ni supervisión humana de cada READ por el código |

Un `AgentSettings.enabled=True` heredado conserva las READ permitidas por B0 y
por su política/identidad existente aunque el nuevo release esté vacío: B9D no
introduce un guard READ en `run_tool`. Antes de cualquier promoción B9E debe
inspeccionar esa configuración y aprobar de forma explícita el alcance READ del
release y la clínica; el estado productivo declarado sigue sin activación real.
Este límite impide presentar la lista en código como un bloqueo runtime de toda
consulta. El gate nuevo protege exclusivamente los efectos WRITE autónomos.

La validación es estructural: un SHA, referencia o PASS declarado no prueba la
verdad de un documento. No hay verificación criptográfica ni consulta automática
de Git/registro externo. La autoridad revisa candidato, referencias y alcance al
aprobar. No se puede usar un fixture para satisfacer esa obligación.

Un corte de release no deshace efectos committed ni cancela sockets remotos.
`enabled` sigue siendo disponibilidad en el worker, no revocación atómica del
efecto. Conserva fences, consentimiento, datos y presupuesto; nunca resetearlos
para forzar un verde. Riesgos de otra carga, deriva LLM y proveedor permanecen.

No se reescribe el plan canónico ni se abre producción. Ver
[acta](implementacion-b9d-agente-whatsapp-2026-09-29.md) para la evidencia de pruebas.
