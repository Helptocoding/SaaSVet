# Orden 5 — expediente y prompts por entrega

Contrato: [plan acordado](../../plan-remediacion-orden-5-2026-11-09.md). Estado: **preparado, sin ejecutar**. Este expediente no acredita remediación hasta que [MATRIZ](MATRIZ.md) y [EVIDENCIA](EVIDENCIA.md) lo digan.

## Cómo usarlo

Ejecuta una entrega por sesión de Claude Sonnet, en orden, con una sesión limpia para cada una (`/clear`). Pega esto, cambiando el archivo:

```text
Lee y ejecuta docs/remediaciones/orden-5/prompts/E00-linea-base.md
```

Entre entregas, revisa el commit con la [lista del plan, §9](../../plan-remediacion-orden-5-2026-11-09.md). Si el reporte dice `BLOQUEADA`, resuelve la causa antes de continuar.

## Entregas

| # | Prompt | Contenido | Errores de lint al terminar |
|---|---|---|---|
| E00 | [línea base](prompts/E00-linea-base.md) | Rama, documentos, excluir `standalone` | 61 |
| E01 | [C6 y F04](prompts/E01-c6-f04.md) | Docstring y término «Usuario» | 61 |
| E02 | [C4 y C5](prompts/E02-c4-c5-pagos.md) | Matemática de pagos y accesibilidad | 61 |
| E03 | [`allowPartial`](prompts/E03-retirar-allow-partial.md) | Retiro de pago parcial | 61 |
| E04 | [C3](prompts/E04-c3-providers.md) | Separar providers | 59 |
| E05 | [F01 auth y hooks](prompts/E05-f01-auth-hooks.md) | Supresiones justificadas | 50 |
| E06 | [F01 componentes](prompts/E06-f01-componentes.md) | Dashboard, tours, modales | 34 |
| E07 | [F01 páginas I](prompts/E07-f01-paginas-1.md) | Agenda, inventario, mascota, equipo | 18 |
| E08 | [F01 páginas II](prompts/E08-f01-paginas-2.md) | Config, analítica, importador, consulta | 0 |
| E09 | [F03 badges](prompts/E09-f03-badges.md) | Estados de cita | 0 |
| E10 | [F03 tabla](prompts/E10-f03-tabla-inventario.md) | Tabla de Inventario y `SortHeader` | 0 |
| E11 | [F02 billing](prompts/E11-f02-billing.md) | Extraer subcomponentes y probarlos | 0 |
| E12 | [cierre](prompts/E12-cierre-gate.md) | Gate de CI, docs y cierre | 0 |

Las entregas [E10](prompts/E10-f03-tabla-inventario.md) y [E06](prompts/E06-f01-componentes.md) cambian o pueden cambiar la apariencia: conviene mirar Inventario y las gráficas del dashboard al revisarlas.

Reglas compartidas: [00-REGLAS-COMUNES](prompts/00-REGLAS-COMUNES.md).
