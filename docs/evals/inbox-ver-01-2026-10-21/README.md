# WA-VER-01 — distintivo de verificación

Estado: **implementada y verificada localmente** (2026-10-21). Lista y cabecera
muestran `Verificado` para `staff_verified`/`confirmed_in_chat`, `Teléfono coincide`
para `phone_match` y nada para `unknown`, valores ausentes o desconocidos.
El tooltip explica el origen y aclara que coincidencia de teléfono no verifica
identidad. Se muestran los niveles enviados por la API, sin conceder permisos,
revalidar identidad ni inferir autorización para operaciones.

El nivel del transcript prevalece sobre la sesión legacy, incluso si es unknown.
Funciona en hilos archivados y el siguiente poll retira una verificación revocada.

| Check | Resultado |
|---|---|
| Tests dirigidos | **15 PASS**: siete casos del badge, seis de integración y dos regresiones de selección/acuse. 40 excluidos. `vitest.json`, `frontend.log`. |
| Build y lint | PASS, cero errores/advertencias lint. `build-run.json`, `build.log`, `lint.json`; sin publicación a Sentry, advertencia de chunk grande preexistente. |
| Chromium | PASS con API sintética: ambos badges en lista/cabecera a 1366×768 y 390×844, explicaciones presentes, sin desbordamiento horizontal ni errores de página. `browser.json`, `check_browser.py`, cuatro capturas `badge-*.png`; inspeccionadas escritorio verificado y móvil teléfono coincide. |
| Cleanup | Vite temporal propio y navegador cerrados; puerto 4178 libre. |

`source-sha256.json` identifica el corte. Sin cambios backend ni repetición de
suites generales. No equivale a gates operativos reales; FAIL B9 r12 conservado.
No hubo commit, push, despliegue ni activación.
