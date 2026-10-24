# WA-CMP-01 — composer con altura automática y contador

Fecha de ejecución: 2026-10-20 (America/Mexico_City).
Estado: **WA-CMP-01 IMPLEMENTADO / VERIFICADO LOCALMENTE**.

Alcance: siguiente tarea recomendada por el cierre del plan original, después de
contrastar la tabla de `docs/CIERRE-INBOX-WHATSAPP.md` con las fuentes actuales.
No es aceptación integral de Inbox ni campaña B9.

El textarea crece entre 40 y 120 px y permite scroll interno al exceder el tope.
El contador aparece después de 3600 caracteres; desde 3800 usa advertencia y
conserva el máximo de 4000. Borrar, enviar o cambiar de hilo reajusta la altura.
El código de envío y sus claves no se modifican.

Validación ejecutada:

- [Vitest](vitest.json): **30/30 PASS**, cuatro casos nuevos CMP-01 y 26
  regresiones del mismo archivo Inbox. Se repitió ese archivo por compartir
  textarea, borrador, envío optimista y montaje por selección; no se alteraron
  las aserciones existentes. Comando en `frontend`:
  `rtk proxy pnpm exec vitest run src/pages/inbox/index.test.jsx --reporter=default --reporter=json --outputFile=../docs/evals/inbox-cmp-01-2026-10-20/vitest.json`.
- [Build](build.json) **PASS**, salida en [build.log](build.log). Upload de Sentry
  deshabilitado para esta compilación local. Advertencia de tamaño de bundle
  conservada; no se amplía esta tarea a optimizarlo.
- [Lint dirigido](lint.json), advisory: **2 errores existentes**
  `react-hooks/set-state-in-effect` en los efectos de `loadList`/`loadThread`,
  ambos fuera del cambio (documentados también en el corte histórico del plan).
  Tests sin errores. No se presenta como lint PASS.
- [Chromium](browser.json) **PASS** con frontend real y API sintética interceptada:
  1366×768 y 390×844. Altura inicial **40 px**, pegado de 2000 caracteres
  limitado a **120 px** con scroll interno, sin overflow horizontal; contador
  desde >3600, color de advertencia desde 3800 y reset tras enviar. Cero errores
  de página. Capturas: [escritorio](composer-desktop-3800.png),
  [móvil](composer-mobile-3800.png). [Script reproducible](check_browser.py).
- `rtk git diff --check` de los archivos afectados: **PASS**.
- [Recibo final](result.json): hashes SHA-256 de las tres fuentes verificadas;
  Chromium cerrado y puerto temporal 4178 sin listener. El helper dejó un Vite
  hijo en Windows: se verificaron PID/comando y se cerró sólo ese proceso.

No se ejecutaron suites backend ni generales frontend. Los 30 resultados son
evidencia dirigida de este checkout; no reemplazan ni se suman a la aceptación
integral histórica r12. Los datos del navegador son sintéticos y ninguna llamada
se envía al backend real o a Meta.

Incidencias de preparación: el sandbox de Windows no pudo iniciar su auxiliar
(`helper_read_acl_helper_spawn_failed` / `Acceso denegado`); las lecturas/comandos
se ejecutaron después por la vía de escalación autorizada. RTK 0.48.0 verificado.
Una lectura Python falló por consola cp1252 y se resolvió con `-X utf8`.
`rtk grep` no encontró el binario grep; fallback `rtk proxy rg`.
La creación de esta carpeta mediante apply_patch falló; se creó por la vía
autorizada y se continuó sin modificar el alcance de la validación.
Estos incidentes no son fallos del producto ni resultados de tests.

El [primer intento visual](browser-attempt1.json) falló por interceptar también
`/src/api/` (módulos JavaScript de Vite). Se conservan su captura/HTML y el
timeout; se corrigió sólo el harness para interceptar paths que empiezan en
`/api/`. El segundo intento aprobó sin cambiar producto ni aserciones. No fue
necesario repetir Vitest ni build por esta corrección del harness.

El gate real Meta, la prueba operativa de recepción, media y el FAIL de seguridad
r12 mantienen su estado. Sin commit, push, despliegue ni activación.
