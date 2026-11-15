# Orden 8 — expediente y prompts por entrega

Contrato: [plan acordado](../../plan-remediacion-orden-8-2026-11-14.md). Estado: **implementado localmente, pendiente de revisión y subida por el usuario**. Este expediente no acredita remediación hasta que [MATRIZ](MATRIZ.md) y [EVIDENCIA](EVIDENCIA.md) lo digan.

## Cómo usarlo

Ejecuta una entrega por sesión de Claude Sonnet, en orden, con una sesión limpia para cada una (`/clear`). Pega esto, cambiando el archivo:

```text
Lee y ejecuta docs/remediaciones/orden-8/prompts/E00-linea-base.md
```

Entre entregas, revisa el commit con la [lista del plan, §8](../../plan-remediacion-orden-8-2026-11-14.md). Si el reporte dice `BLOQUEADA`, resuelve la causa antes de continuar.

## Entregas

| # | Prompt | Contenido |
|---|---|---|
| E00 | [línea base](prompts/E00-linea-base.md) | Rama, documentos, cluster aislado, pruebas de referencia del agente |
| E01 | [G07](prompts/E01-g07-veredictos.md) | `TurnDecision.verdict` limitado a los cinco veredictos del árbitro |
| E02 | [G09](prompts/E02-g09-disponibilidad.md) | Pruebas de la ocupación por intervalos y documentación al día |
| E03 | [cierre](prompts/E03-cierre.md) | Corrida de cierre, IDs fuera de alcance y expediente |

Ninguna entrega cambia lo que ve el cliente por WhatsApp ni el Inbox. El agente sigue sin activarse.

Reglas compartidas: [00-REGLAS-COMUNES](prompts/00-REGLAS-COMUNES.md).
