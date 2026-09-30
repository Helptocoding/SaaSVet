# B9E — matriz de inyección integral

IDs fijos antes de ejecutar el corpus seleccionado. Las referencias exactas a test viven en `profile-beta-1-corpus-v1.json`; un resultado B9A–D histórico sirve de procedencia, pero solo una ejecución exacta en este candidato cuenta como regresión B9E. La aserción negativa exigida se indica junto a la evidencia positiva.

| ID | Cruce | Evidencia positiva y negativa requerida | Estado en este candidato |
| --- | --- | --- | --- |
| B9E-FI-01 | Crash worker tras admisión B9B y recovery B9C | Mismo TurnWork recuperable, nueva lease; budget anterior permanece; sin publicación stale ni cupo extra | PENDING_RUN |
| B9E-FI-02 | Timeout provider, budget y capacidad | Timeout admitido no se reembolsa; capacity se libera solo al estado B3 correspondiente; sin provider call sobre cupo agotado | PENDING_RUN |
| B9E-FI-03 | Meta aceptó, sender murió antes de guardar | Outbound pasa a `UNCERTAIN` al expirar lease; sin retry ciego ni delivery inventado | PENDING_RUN |
| B9E-FI-04 | Worker tardío después de lease | Nuevo witness conserva autoridad; viejo no publica, no ejecuta dominio ni consume como nuevo dueño | PENDING_RUN |
| B9E-FI-05 | Definición/autorización stale antes de B8A | Consentimiento histórico no alcanza; reason code de scope; cero efecto/receipt de éxito | PENDING_RUN |
| B9E-FI-06 | Revocación de gate B9D antes del efecto | Snapshot READY viejo no autoriza; cero efecto nuevo, ledger anterior conciliable | PENDING_RUN |
| B9E-FI-07 | Takeover durante LLM | Epoch nuevo cerca salida tardía; cero publicación/effect nuevo del worker anterior | PENDING_RUN |
| B9E-FI-08 | Duplicado inbound HTTP en dos procesos | Un Message inbound y un TurnWork; no doble provider call/efecto | PENDING_RUN |
| B9E-FI-09 | Confirmación duplicada | Una AuthorizationEvidence/efecto/receipt de operación; segundo inbound no amplía permiso | PENDING_RUN |
| B9E-FI-10 | Retry tras SQL failure en recibo/efecto | Rollback atómico, luego un único efecto y un único receipt; no éxito huérfano | PENDING_RUN |

Estos FI son un conjunto acotado entre fronteras, no prometen exactly-once en Meta ni cancelación física de sockets ya admitidos. El resultado HTTP externo tardío solo puede modificar su evidencia de entrega bajo la admisión previa, nunca adquirir autoridad conversacional o de negocio nueva.

Resultado final 2026-09-30: los diez IDs B9E-FI-01–10 tienen su test exacto `ok`
en [`b9e-corpus-final.json`](b9e-corpus-final.json); su categoría final es
`IMPLEMENTED_AND_PROVEN` en la frontera acotada descrita. La columna anterior
conserva el estado previo. Ninguno sustituye el gate temporal fallido.
