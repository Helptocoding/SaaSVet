# B9 BASE: deuda de latencia aceptada y no bloqueante

Fecha local del usuario: **2026-10-22**. Estado: **ACEPTADA POR EL USUARIO**.

## Decisión

El usuario indicó: «Esto lo dejaremos así, hemos intentado reducirlo y no se ha
podido será una deuda que aceptaremos y que no debe ser un bloqueante».

Se acepta como deuda el incumplimiento medido del gate
`healthy_claim_p95_le_10` en BASE: **11,572640 s** frente al objetivo de **10 s**.
Este valor deja de ser un bloqueo para continuar el cierre o considerar activación.
No se exige volver a reducirlo ni repetir BASE para continuar este plan.

La aceptación es una decisión de producto sobre esa latencia. El resultado
técnico original sigue siendo FAIL, sin alterar el recibo, el límite de 10 s,
los denominadores ni los informes sellados. El estado de seguimiento vigente es
`ACCEPTED_DEBT_NON_BLOCKING`; no se convierte la medición en PASS.

## Alcance

- No iniciar otra campaña B9, tuning ni barridos por este incumplimiento.
- Los cuatro perfiles restantes conservan su estado histórico NOT_EXECUTED;
  esta decisión no inventa sus resultados ni ordena ejecutarlos ahora.
- La brecha del reporte por organización queda documentada en el informe
  anterior; no se reabre automáticamente la aceptación integral para este cierre.
- Siguen aplicando los gates reales de B2, privacidad, publicación legal,
  Meta/recepción y operación que el usuario acaba de exigir. La excepción de
  latencia no los dispensa ni activa el servicio.
- Los avisos de las auditorías de dependencias conservan su clasificación y
  seguimiento propios. No quedan resueltos mediante esta aceptación.

## Evidencia y seguimiento

[Resultado observado](../evals/inbox-readiness-2026-10-22/B9-RESULTS.md),
[recibo BASE](../evals/inbox-readiness-2026-10-22/blocks/profile-base.json) y
[nueva lista de cierre B2/WhatsApp](../compliance/cierre-b2-whatsapp-2026-10-22.md).

No se modifica el scheduler ni el runtime para registrar esta decisión. Una
revisión futura de esta deuda requerirá priorización explícita; no se programa
trabajo adicional ni se presenta la capacidad comercial como certificada.
