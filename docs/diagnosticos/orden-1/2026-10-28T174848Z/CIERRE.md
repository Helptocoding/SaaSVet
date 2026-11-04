# Cierre del diagnóstico del orden 1 con excepción de alcance

Fecha: **28 de octubre de 2026**, America/Mexico_City.

**Estado: CERRADO_CON_EXCEPCION_DE_ALCANCE.** Se cierra el encargo de **diagnóstico pasivo/documental**, con la parte remota exceptuada por decisión del usuario. No se cierra la implementación de remediaciones.

## Decisión y alcance aceptado

El usuario solicitó dar por cerrado el orden 1 tras incorporar las correcciones de la revisión, dejando fuera la conexión al VPS porque no está accesible por falta de pago. Se registra esa circunstancia como información aportada por el usuario, sin comprobar estado de cuenta, conservación, suspensión o eliminación de infraestructura.

Quedan aceptados para el cierre del diagnóstico:

- Inspección y documentación local conforme al alcance pasivo acordado.
- Corrección del inventario Python: global y venv del proyecto separados. De los 40 pins, el venv registra 29 coincidencias, 9 diferencias y 2 nombres sin metadatos encontrados; no se deduce un fallo del backend por estas ausencias.
- Interpretación corregida de H02: 7 de los 11 paquetes señalados históricamente coinciden en versión en el venv y 4 difieren, sin extrapolar automáticamente avisos o fixes.
- Distinción de pnpm: 85 registros/IDs numéricos internos y 78 GHSA distintos.
- Aplazamiento de U01/U02, P01, P08 y las partes remotas de P09; el análisis local no depende de recuperar el VPS.
- Matriz con 66 criterios, 66 IDs únicos, sin campos vacíos y recuentos de estados consistentes.

La comprobación de cierre contrastó las correcciones reflejadas en los documentos y los conteos de la matriz; no repitió un inventario exhaustivo de paquetes ni las inspecciones sensibles de la ejecución original.

## Excepción remota

La excepción cubre la inspección del VPS y la evidencia que depende de él: revisión desplegada, configuración efectiva SSH/sudo/firewall/servicios, registros remotos, operación de backups/alertas y gate B3 remoto.

- No se intentará conexión, reactivación o consulta al proveedor para completar este encargo.
- No se convierten los puntos remotos en PASS, NO_APLICA o desviaciones confirmadas por el solo hecho de estar exceptuados.
- La falta de acceso no demuestra pérdida de datos, fallo de controles ni seguridad del entorno.
- Retomar la parte remota requiere nueva instrucción del usuario y un expediente/ventana de observación nuevos, conservando el hueco histórico.

## Seguimiento posterior preservado

Las confirmaciones de rotación y la prueba de descarga/descifrado/restore siguen reservadas al usuario, como se acordó originalmente. No son comprobaciones completadas por este cierre ni se incluyen silenciosamente en la excepción del VPS.

Los seis hallazgos documentados y las acciones del [plan de remediación propuesto](plan-remediacion-propuesto.md) siguen abiertos para trabajo posterior. Su existencia es un resultado del diagnóstico, no trabajo de implementación pendiente dentro del encargo que se cierra.

La [matriz](matriz-evidencias.csv) conserva sus estados técnicos:

| Estado | Criterios |
|---|---:|
| EVIDENCIA_CONFORME | 17 |
| DESVIACION_CONFIRMADA | 6 |
| PENDIENTE_USUARIO | 17 |
| NO_VERIFICABLE_EN_ESTE_ALCANCE | 24 |
| NO_APLICA | 2 |
| **Total** | **66** |

El estado de cierre del encargo y el estado de cada criterio son dimensiones distintas. No se alteran recibos históricos ni se presenta el cierre como certificación de seguridad, recuperabilidad o go-live.

## Fuentes y efectos de este cierre

- [README y corrección documental](README.md).
- [Revisión y excepción del VPS](revision-2026-10-28.md).
- [Hallazgos](hallazgos.md).
- [Pendientes del usuario](pendientes-usuario.md).
- [Plan posterior](plan-remediacion-propuesto.md).

Se añadió esta acta y se actualizó el estado del README. No se modificó código, configuración, dependencias o servicios; no hubo remediación, SSH, restore, escáneres nuevos ni commit/push como parte del cierre.
