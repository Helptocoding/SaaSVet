# Orden 6 — expediente y prompts por entrega

Contrato: [plan acordado](../../plan-remediacion-orden-6-2026-11-11.md). Estado: **preparado, pendiente de ejecución**. Este expediente no acredita remediación hasta que [MATRIZ](MATRIZ.md) y [EVIDENCIA](EVIDENCIA.md) lo digan.

## Cómo usarlo

Ejecuta una entrega por sesión de Claude Sonnet, en orden, con una sesión limpia para cada una (`/clear`). Pega esto, cambiando el archivo:

```text
Lee y ejecuta docs/remediaciones/orden-6/prompts/E00-linea-base.md
```

Entre entregas, revisa el commit con la [lista del plan, §8](../../plan-remediacion-orden-6-2026-11-11.md). Si el reporte dice `BLOQUEADA`, resuelve la causa antes de continuar.

## Entregas

| # | Prompt | Contenido |
|---|---|---|
| E00 | [línea base](prompts/E00-linea-base.md) | Rama, documentos, cluster aislado, pruebas de referencia |
| E01 | [B2](prompts/E01-b2-items-receta.md) | Base común de los serializers de ítems de receta |
| E02 | [C2](prompts/E02-c2-invoice-solo-lectura.md) | Serializers de Invoice de solo lectura |
| E03 | [B5](prompts/E03-b5-bootstrap-superuser.md) | Comando `bootstrap_superuser` |
| E04 | [B6](prompts/E04-b6-seed-prune.md) | `seed_permissions --prune` |
| E05 | [D2](prompts/E05-d2-vista-legacy-org.md) | Retirar `/api/organizations/<pk>/` |
| E06 | [cierre](prompts/E06-cierre.md) | A1+B4, B3, C1, C7 en docs; corrida amplia; cierre |

E01 corrige un 500 real del endpoint `/items/` de recetas. E03 cambia cómo se crea el superusuario de plataforma: conviene leer el runbook resultante antes del próximo despliegue.

Reglas compartidas: [00-REGLAS-COMUNES](prompts/00-REGLAS-COMUNES.md).
