# WA-TAB-01 — pendientes en título de pestaña

Estado: **implementada y verificada localmente**. `useInboxTitle` presenta
`(N) SaaslyVet` cuando la pestaña está oculta o sin foco, con N igual a los hilos
con `has_unanswered` del último poll. Restaura el título al volver al foco,
desaparecer pendientes o salir de Inbox. No añade consultas, sonido ni
Notification API. No sustituye el unread por usuario pendiente de UNR-01/02.

| Check | Evidencia |
|---|---|
| Pruebas nuevas | **7/7 PASS**, `vitest.json` / `frontend.log`: seis del hook y una integración con carga de lista. Conteo de tres, cero, cambios de poll sin prefijos acumulados, foco/visibilidad, desmontaje/listeners, StrictMode y ausencia de requests adicionales. 38 casos no afectados excluidos. |
| Build | PASS, `build-run.json` / `build.log`; sin upload a Sentry. Advertencia existente de tamaño de chunk. |
| Lint | Dos errores previos de polling advisory; hook y tests sin errores nuevos. `lint.json`. |

`source-sha256.json` fija el corte de código. No se repitieron pruebas de render,
copiado, agrupación o backend: el cambio sólo sincroniza título y listeners, sin
modificar sus rutas. La evidencia de CMP/GRP/CPY se conserva. No hubo browser
adicional para TAB-01; el criterio de cálculo/eventos se verifica en jsdom según
el plan. Las capturas Chromium previas acreditan únicamente sus propios cortes.

Sin commit, push, despliegue ni activación. No se abrió campaña B9; el FAIL de
seguridad r12 y los gates operativos/Meta reales siguen vigentes.
