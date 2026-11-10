# Reglas comunes del orden 5

Aplican a todas las entregas. Léelas completas antes de tocar nada.

## 1. Contexto

- Repositorio: `C:/Users/LAP/Desktop/VeterinariaSaaS`. Frontend en `frontend/`: React 19, Vite, JavaScript, CSS Modules, Vitest.
- Rama de trabajo: `fix/orden-5-calidad-frontend` (la crea E00). Comprueba `git branch --show-current` antes de empezar.
- Contrato: `docs/plan-remediacion-orden-5-2026-11-09.md`. El prompt de tu entrega trae lo necesario; acude al plan solo ante una duda.
- Este orden es solo de frontend. Las decisiones del plan ya las tomó el usuario: no las reabras ni pidas confirmarlas.

## 2. Método obligatorio

1. Lee cada archivo antes de editarlo.
2. Los números de línea corresponden a `c3f42ba` y se desplazan. Localiza por símbolo o por el texto citado.
3. Haz exactamente los pasos de tu entrega, en orden. No mejores nada que no esté pedido.
4. Tras cada archivo editado, ejecuta lint sobre ese archivo.
5. **Si un texto citado no existe, o el código significa otra cosa que lo que dice el prompt, detente.** No adivines: repórtalo con estado `BLOQUEADA`.
6. Si el mismo error persiste tras dos intentos, detente y repórtalo.
7. Usa el grafo `codebase-memory-mcp` si está disponible. Si falla, usa Grep y Read; no es motivo de bloqueo.

## 3. Prohibido

- Tocar backend, migraciones, bases de datos, Docker o VPS. **Nunca te conectes a `159.69.178.136`.**
- `git push`, PR, merge, rebase o despliegue. `--no-verify` o saltar hooks. `git add .` o `git add -A`.
- Instalar o actualizar dependencias, o modificar `pnpm-lock.yaml`.
- Editar archivos que tu entrega no lista. La única excepción es arreglar un import roto por tu propio cambio, y debes declararlo.
- Borrar pruebas, añadir `.skip` o `.only`, debilitar aserciones o subir timeouts. La única excepción son las aserciones de pago parcial en E03.
- Añadir `eslint-disable` que tu prompt no indique, o sin ` -- motivo`.
- Cambiar los warnings `react-hooks/exhaustive-deps`: no añadas ni quites dependencias salvo orden expresa.
- Bajar reglas de ESLint a warning, o ampliar `ignores` más allá de lo que indica E00.
- Rediseñar, renombrar símbolos no pedidos o reformatear.
- Introducir `window.confirm`, `console.log(err)`, llamadas axios en páginas o `user.role` nuevos.

## 4. Comandos

Ejecútalos desde `frontend/`, siempre en primer plano. El prefijo `rtk proxy` evita que la salida se recorte.

```bash
# Lint de archivos
rtk proxy node_modules/.bin/eslint src/ruta/archivo.jsx

# Recuento total: la última línea indica errores y warnings
rtk proxy node_modules/.bin/eslint . 2>&1 | tail -3

# Exit code considerando solo errores
rtk proxy node_modules/.bin/eslint . --quiet; echo "exit=$?"

# Pruebas dirigidas
rtk proxy node_modules/.bin/vitest run src/ruta --reporter=dot 2>&1 | tail -15

# Suite completa: usa timeout de 600000 ms, tarda unos 7 minutos
rtk proxy node_modules/.bin/vitest run --reporter=dot 2>&1 | tail -30

# Build y smoke de URLs
pnpm run build
pnpm run smoke:urls
```

**Timeouts por carga.** En la suite completa, un fallo `Test timed out in 5000ms` en `src/pages/inbox/*.test.jsx` no es regresión si ese archivo pasa al ejecutarlo solo. Reejecútalo solo y registra ambos resultados. Cualquier otro fallo es real.

## 5. Cierre de cada entrega

1. Ejecuta la verificación de tu prompt y conserva la salida real.
2. Actualiza `docs/remediaciones/orden-5/MATRIZ.md` (tabla de avance; estado del ID solo si la entrega lo cierra) y añade tu sección a `docs/remediaciones/orden-5/EVIDENCIA.md`.
3. Haz el commit con `git add <rutas explícitas>` y el mensaje de tu prompt. Añade al final las líneas de atribución que te indique tu entorno. Sin push.
4. Termina con este reporte y nada más:

```markdown
## Entrega E0X — COMPLETA | BLOQUEADA
Commit: <hash> | ninguno
Archivos: <lista>
Lint total: <errores> errores, <warnings> warnings (esperado: <N> errores)
Pruebas: <comando> → <resultado>
Build: <resultado o "no aplica">
Desviaciones: ninguna | <cuáles y por qué>
Para revisar: <lo que el usuario debe mirar, o "nada">
```

Si quedó `BLOQUEADA`, no hagas commit. Indica el paso, el texto o error exacto y qué hace falta para continuar.
