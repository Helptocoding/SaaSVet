# Orden 3 — candidato local de privacidad web y proveedores

**Corte:** 30-10-2026 · **Texto de aviso/cookies y regla de retención:** aprobación expresa recibida en esta conversación («lo acepto todo»). **Estado del conjunto:** `PENDIENTE_DE_APROBACION_Y_OPERACION_EXTERNA`.

**Seguimiento 15-11:** el estado no cambia. Este expediente entró a `develop` con el merge `7b6ed82` (04-11). En `LandingSaaS`, los cambios del candidato siguen sin commit en `feature/migration-astro` (seis archivos modificados según `git status` del 15-11), y no se publicó nada.

Este expediente ejecuta el alcance local autorizado en [`plan-remediacion-orden-3-2026-10-30.md`](../../plan-remediacion-orden-3-2026-10-30.md). No declara publicado el aviso, aceptados contratos, purgados registros ni verificados servicios externos.

## Resultado del candidato

- **Landing:** `C:/Users/LAP/Desktop/LandingSaaS`, rama inicial `feature/migration-astro`, HEAD inicial `55c9c72867677be894f301727d964dd023564269`. Cambios locales delimitados en GA4, banner, formulario, shell sin JavaScript, borradores aviso/cookies y un script Playwright acotado. No commit ni publicación.
- **SaaslyVet:** `C:/Users/LAP/Desktop/VeterinariaSaaS`, rama inicial `codex/e4-capacity-scheduling`, HEAD inicial `8886604ff77bd86649c12dee695a4742a3fe44f5`. Este expediente es nuevo; los cambios existentes de órdenes anteriores y `docs/remediaciones/orden-2/` se preservan.
- **Criterios locales acreditados:** el build estático completa; consentimiento inicial/negativa/preferencia inválida/persistencia/tablas, carga única sintética, formulario con validación nativa/AJAX simulado y textos renderizados pasan los casos listados en [EVIDENCIA.md](EVIDENCIA.md). Retención: solo reglas comprobadas con fechas sintéticas.
- **Cierre parcial pendiente:** el test no carga el runtime real de Google. La retirada con runtime externo ya cargado queda `NO ACREDITADA`; los mocks solo prueban el contrato local. El build no certifica cuentas, ajustes, contratos o operación.

## Lectura rápida

1. [DECISIONES.md](DECISIONES.md) — contrato aplicado y aprobación textual registrada.
2. [MATRIZ.md](MATRIZ.md) — los 13 IDs: implementado local, parcial, aplazado y dependencias externas.
3. [EVIDENCIA.md](EVIDENCIA.md) — revisiones iniciales, comandos, builds, navegador, reloj sintético y límites.
4. [RETENCION-PROSPECTOS.md](RETENCION-PROSPECTOS.md) — procedimiento manual y límite de 180 días.
5. [PROVEEDORES.md](PROVEEDORES.md) — fichas saneadas; secretos y evidencia contractual privada permanecen fuera.
6. [PUBLICACION-Y-ROLLBACK.md](PUBLICACION-Y-ROLLBACK.md) — material candidato, aprobación, publicación y retorno controlado.

## Siguiente decisión del usuario

La aprobación textual de aviso, cookies y regla de retención ya fue recibida; no se requiere volver a preguntar esa decisión. Antes de publicar, completar evidencia de cuentas, regiones, ajustes e instrumentos aplicables, comprobar el cese de GA con runtime real y asignar una fecha efectiva. Después, decidir publicación HTTPS y evaluar materialidad para sincronización legal humana; no promover versión ni ejecutar seeds automáticamente.

La eliminación real en Formspree, buzón, exportaciones y demás cuentas queda reservada al usuario. O02/O03/O04/O07/O08/O15/G06 permanecen aplazados y O12 no incluye endpoints.
