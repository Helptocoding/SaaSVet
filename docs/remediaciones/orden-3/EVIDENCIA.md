# Evidencia de verificación local

**Corte:** 30-10-2026. Builds, HTTP y browser fueron locales; no se abrió el VPS, base habitual, cuentas de proveedor ni endpoints reales.

**Decisión posterior registrada:** el responsable respondió «lo acepto todo» al resumen de los textos y regla de conservación el 30-10-2026. Se registra como aprobación de ese contenido local, no como fecha efectiva, contrato, configuración externa ni publicación.

## Línea base y preservación

| Repositorio | Revisión/estado inicial | Preservación |
|---|---|---|
| `VeterinariaSaaS` | `codex/e4-capacity-scheduling`, `8886604ff77bd86649c12dee695a4742a3fe44f5`. Ya había muchos cambios tracked y untracked de órdenes anteriores: backend de agentes, citas, pagos, auth, imports, inventario, expediente clínico, pacientes, plataforma, prescripciones, migraciones, tests, frontend, infraestructura y docs. | No se limpió ni modificó ese trabajo. Se añadió solamente `docs/remediaciones/orden-3/` nuevo; no se cambió el expediente existente de orden 2. |
| `LandingSaaS` | `feature/migration-astro`, `55c9c72867677be894f301727d964dd023564269`. Inicialmente solo estaban sin seguimiento `branding/`, `frontend/dev.log`, dos mockups PNG y `nul`; no había cambios tracked reportados. | Se preservaron; no se limpiaron ni se incluyeron como entregables. |

Preflight: `rtk --version` → 0.48.0; `rtk gain` registrado. `AGENTS.md` de VeterinariaSaaS aplicado; `docs/CLAUDE.md` aplicable. LandingSaaS no tenía `AGENTS.md` ni `RTK.md`; se leyó su `CLAUDE.md`, que describe Astro y ausencia de suite declarada. Grafo MCP no estuvo disponible (sin recursos/templates ni herramientas de grafo en esta sesión), y no había índice consultable; fallback: lectura de fuentes Astro/configuración actuales y búsquedas literales, contrastadas con build/HTML/browser.

## Comandos y resultados

- `rtk proxy npm run build` (LandingSaaS/frontend): **PASS**, Astro static, 18 páginas generadas. No existía script de lint/test/typecheck en `package.json`; no se afirmó ejecutar suite de aplicación.
- `rtk proxy cmd /c "set PUBLIC_GA_MEASUREMENT_ID=G-TEST123456&& node_modules\.bin\astro.cmd build"`: **PASS**, build con ID sintético. No se registró un Measurement ID real en archivos de evidencia.
- `rtk proxy cmd /c "set PUBLIC_GA_MEASUREMENT_ID=INVALID&& node_modules\.bin\astro.cmd build"`: **PASS**, rama sin tag para ID inválido. Build final local quedó sin conectar al proveedor.
- Browser: `rtk proxy python C:\Users\LAP\Desktop\VeterinariaSaaS\.agents\skills\webapp-testing\scripts\with_server.py --server "node_modules\.bin\astro.cmd preview --host 127.0.0.1 --port 4317" --port 4317 -- python scripts/orden3-privacy-browser.py --no-ga`: **PASS**, ausencia de tag y reabrir preferencias sin ID.
- Browser con build sintético: mismo comando sin `--no-ga`: **PASS**, consentimiento, formulario, navegación y errores con terceros interceptados. El proceso lo gestionó el helper y se ligó a loopback `127.0.0.1:4317`; el helper lo terminó al final.
- Reloj sintético: `rtk proxy python -c "from datetime import date,timedelta; start=date(2026,1,1); d179=start+timedelta(days=179); d180=start+timedelta(days=180); d181=start+timedelta(days=181); eligible=lambda today,ref,active=False:(not active) and (today-ref).days>=180; assert not eligible(d179,start) and eligible(d180,start) and eligible(d181,start); effective=start+timedelta(days=90); automated=start+timedelta(days=179); assert not eligible(automated,effective) and eligible(effective+timedelta(days=180),effective); assert not eligible(d181,start,active=True); unknown_ref=None; assert unknown_ref is None; revoked_requires_manual_review=True; assert revoked_requires_manual_review; print('PASS synthetic: day179=no, day180=yes, day181=yes; automation no reset; effective contact resets; active=review; unknown=manual; revocation=manual review')"` con fechas exclusivamente ficticias: **PASS**, día 179 no vencido; día 180 y 181 elegibles; correo automático no reinicia; contacto efectivo mueve fecha; activa se manda a revisión; fecha desconocida queda manual; revocación requiere revisión.
- La invocación inicial del helper con `npm run dev` no abrió el puerto en Windows; se cambió a `astro.cmd preview` con loopback. No se detuvieron procesos ajenos ni se usó el `0.0.0.0` declarado por scripts.
- `rtk git diff --check` en ambos repositorios: **PASS** (sin errores de whitespace); los siete documentos de este expediente también pasaron el control local de whitespace.
- Revisión de enlaces Markdown locales del expediente: **20 revisados, 0 rotos**. Fuentes oficiales de Google, Formspree y Cámara de Diputados abiertas; el registro legislativo indica última reforma de 14-11-2025. Un enlace público no prueba aceptación contractual.

## Casos browser cubiertos

- Contextos limpios, viewport 390×844 y estándar; rutas externas interceptadas desde antes de navegar. Ninguna solicitud se permitió llegar a Google/Formspree. Se registraron **11 intentos externos interceptados** en la corrida con GA sintético, incluyendo peticiones de tag bloqueadas y Formspree mockeado; no son llamadas de cuenta.
- Sin ID: no banner automático ni script/solicitudes GA; enlace del footer reabre preferencias; aceptar local no crea tag.
- Valor de almacenamiento inválido: banner visible, analítica inicial desmarcada; rechazo persiste y no carga tag.
- Aceptación/doble evento: una sola inserción/solicitud sintética de `gtag.js`; persistencia; configuración de página sin query y referrer vacío.
- Negativa y retirada en el mismo tab y otra pestaña; bandera local de disable, cookie `_ga` sintética borrada y sin solicitudes posteriores al rechazo; navegación con negativa en `/`, contacto, cookies, aviso, términos, nosotros y blog; preferencias disponibles en todas. `/mockup-dashboard` es una herramienta interna `noindex` que no usa el layout público ni integra analítica/formulario; quedó fuera de la prueba de páginas públicas y no se modificó.
- API de almacenamiento bloqueada: el rechazo no carga GA; tras recarga vuelve a denegar por defecto. No se borran cookies ajenas.
- Formulario: campos required, teléfono vacío ausente del payload, checkbox requerido e independiente de GA, payload limitado a `nombre`, `apellido`, `clinica`, `email`, `consentimiento`; sin `_subject`, `_gotcha` ni PII en URL/referrer GA. Formspree simulado: éxito JSON, 4xx, 5xx, 2xx no-JSON, desconexión, reintento y doble evento de submit; el éxito solo aparece con respuesta 2xx JSON.
- JS desactivado: validación nativa presente, submit deshabilitado y aviso accesible a Contacto; no hubo POST.
- Teclado: foco inicial y Tab entre controles del banner probados. No se guardaron capturas ni recibos con datos de persona.

## Límites que siguen abiertos

1. El route handler bloquea `gtag.js`; por eso la bandera `ga-disable-<ID>`, el retiro de script y la sincronía de pestañas se observan como contrato local, pero **no se probó el runtime de Google ya cargado**. Tampoco se observó red real de Analytics. El cese tras retirada queda `NO ACREDITADO` hasta una prueba compatible con runtime y tráfico de recolección interceptado.
2. La intercepción prueba que el navegador intentó URL sintética y que el código reaccionó; no demuestra funcionamiento de cuenta, endpoint, DPA, retención ni eliminación de Google/Formspree.
3. El test sin JavaScript verifica bloqueo/accesibilidad, no que Formspree aplique validación server-side propia. No se le atribuye tal validación.
4. Cookies con HttpOnly, dominios ajenos/no accesibles y solicitudes ya enviadas/en vuelo no se pueden retirar desde este JavaScript. Nunca se borra una cookie que no sea del namespace de analítica.
5. El reloj es fixture sintético; no se inspeccionaron ni borraron prospectos reales ni se verificó ciclo físico de copias de Formspree/correo.
6. Build y pruebas no sustituyen evidencia contractual/configuración, confirmación de hechos de cuenta, inspección HTTPS pública ni publicación. El `dist/` final local quedó generado con un valor inválido sintético, sin tag GA ni release.

## Fuentes vigentes contrastadas (consulta 30-10-2026)

- Google, [Consent mode overview](https://developers.google.com/tag-platform/security/concepts/consent-mode): distingue modo básico (tag bloqueado hasta consentimiento y sin transferencia previa) de avanzado (puede emitir pings sin cookies). Se eligió el patrón básico.
- Google, [Set up consent mode on websites](https://developers.google.com/tag-platform/security/guides/consent): consentimiento debe actualizarse ante cambios y las etiquetas pueden actuar en respuesta a actualizaciones. Esto respalda exigir verificación real al retirar.
- Google, [Safeguarding your data](https://support.google.com/analytics/answer/6004245): el titular controla configuración, enlaces, retención y eliminación de su propiedad; no acredita la cuenta concreta.
- Formspree, [Privacy Policy](https://formspree.io/legal/privacy-policy/): la información pública describe procesamiento en EE.UU. y otros países y retención por fines del servicio; no identifica cuenta/contrato del usuario ni fija los 180 días de SaaslyVet.
- Formspree, [Exporting Submissions](https://help.formspree.io/articles/form-and-project-settings/exporting-submissions/): exportación del dashboard a CSV/JSON, disponible según el plan. La disponibilidad real debe confirmarse en la cuenta.
- Cámara de Diputados, [registro de la LFPDPPP vigente](https://www.diputados.gob.mx/LeyesBiblio/ref/lfpdppp.htm): publica última reforma de 14-11-2025 y enlaza el texto vigente. El PDF se enlaza desde ese registro. La aprobación jurídica del aviso y cómputo final queda pendiente; el borrador no presenta una conclusión legal certificada.

## Diff final

Revisar en cada repo con `rtk git status --short` y `rtk git diff --` (en LandingSaaS) además de archivos nuevos enumerados en este expediente. Archivos propios de landing: `GoogleAnalytics.astro`, `CookieConsentBanner.astro`, `RegisterModal.astro`, `Base.astro`, `aviso-de-privacidad.astro`, `cookies.astro` y `scripts/orden3-privacy-browser.py`. No se añadieron paquetes ni se alteró lockfile.
