# Orden 7 — expediente y prompts por entrega

Contrato: [plan acordado](../../plan-remediacion-orden-7-2026-11-12.md). Estado: **integrado en `develop` por el [PR #6](https://github.com/Helptocoding/SaaSVet/pull/6) (`ea21232`), con CI en verde el 12-11; sin despliegue**. Este expediente no acredita remediación hasta que [MATRIZ](MATRIZ.md) y [EVIDENCIA](EVIDENCIA.md) lo digan.

## Cómo usarlo

Ejecuta una entrega por sesión de Claude Sonnet, en orden, con una sesión limpia para cada una (`/clear`). Pega esto, cambiando el archivo:

```text
Lee y ejecuta docs/remediaciones/orden-7/prompts/E00-linea-base.md
```

Entre entregas, revisa el commit con la [lista del plan, §8](../../plan-remediacion-orden-7-2026-11-12.md). Si el reporte dice `BLOQUEADA`, resuelve la causa antes de continuar.

## Entregas

| # | Prompt | Contenido |
|---|---|---|
| E00 | [línea base](prompts/E00-linea-base.md) | Rama, documentos, cluster aislado, pruebas de referencia de backend y frontend |
| E01 | [M03](prompts/E01-m03-peso.md) | `VitalSigns` como única fuente del peso |
| E02 | [M01, Equipo](prompts/E02-m01-cedula-equipo.md) | `User.license_number`, alta y PATCH de Equipo, permiso `staff.update` |
| E03 | [M01, firma](prompts/E03-m01-firma.md) | Cédula obligatoria para quien firma, snapshot al cierre, PDF, demo |
| E04 | [M01, frontend](prompts/E04-m01-frontend-equipo.md) | Captura de la cédula en la pantalla de Equipo |
| E05 | [cierre](prompts/E05-cierre.md) | ADR p64, addendum p63, documentos operativos, corrida amplia, cierre |

E03 cambia el comportamiento visible: desde ahí, nadie sin cédula puede cerrar una consulta que firma ni emitir una receta. Tras desplegar, un ADMIN tiene que capturar las cédulas en Equipo antes de que la clínica opere.

Reglas compartidas: [00-REGLAS-COMUNES](prompts/00-REGLAS-COMUNES.md).
