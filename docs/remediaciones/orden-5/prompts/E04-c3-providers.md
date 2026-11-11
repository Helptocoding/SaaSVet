# E04 — C3: separar providers de contexto y hook

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Que los archivos que exportan componentes solo exporten componentes (`react-refresh/only-export-components`). Se mueve el Provider, no el hook: así los archivos que importan `useAuth`, incluidos 20 `vi.mock`, no cambian. **No alteres ninguna línea de la lógica de sesión.**

Precedente: `components/useConfirm.js` (contexto y hook) y `components/ConfirmDialog.jsx` (Provider).

## Archivos permitidos

- `frontend/src/auth/authContext.jsx` → renombrado (ver pasos)
- `frontend/src/auth/AuthProvider.jsx` (nuevo por renombrado)
- `frontend/src/auth/authContext.js` (nuevo)
- `frontend/src/auth/authContext.logout.test.jsx`
- `frontend/src/hooks/activationContext.jsx` → renombrado
- `frontend/src/hooks/ActivationProvider.jsx` (nuevo por renombrado)
- `frontend/src/hooks/activationContext.js` (nuevo)
- `frontend/src/App.jsx`
- `docs/modules/frontend.md` (dos referencias)
- Expediente del orden 5

Busca antes `authContext.jsx` y `activationContext.jsx` con extensión dentro de `frontend/src`. Si algún import incluye la extensión, detente con `BLOQUEADA`.

## Paso 1. Auth

Desde la raíz del repositorio: `git mv frontend/src/auth/authContext.jsx frontend/src/auth/AuthProvider.jsx`.

Crea `frontend/src/auth/authContext.js`:

```js
import { createContext, useContext } from "react";

// Contexto y hook de autenticación. Viven aparte de AuthProvider.jsx para que ese
// archivo exporte solo componentes (react-refresh/only-export-components).
export const AuthContext = createContext();

export const useAuth = () => useContext(AuthContext);
```

En `AuthProvider.jsx`:

1. En el import de `react`, quita `createContext` y `useContext`.
2. Añade `import { AuthContext } from "./authContext";`.
3. Elimina `const AuthContext = createContext();`.
4. Elimina la última línea, `export const useAuth = () => useContext(AuthContext);`.

Nada más cambia en ese archivo.

## Paso 2. Activación

`git mv frontend/src/hooks/activationContext.jsx frontend/src/hooks/ActivationProvider.jsx`.

Crea `frontend/src/hooks/activationContext.js`:

```js
import { createContext, useContext } from "react";

// Contexto y hook de activación. El Provider vive en ActivationProvider.jsx.
export const ActivationContext = createContext({
  activation: null,
  loading: true,
  refetch: () => {},
});

export function useActivationContext() {
  return useContext(ActivationContext);
}
```

En `ActivationProvider.jsx`:

1. Del import de `react`, quita `createContext` y `useContext`.
2. Añade `import { ActivationContext } from "./activationContext";`.
3. Elimina el bloque `const ActivationContext = createContext({...});`. Conserva el docblock largo, encima de `ActivationProvider`.
4. Elimina la función `useActivationContext` del final.

## Paso 3. Importadores

| Archivo | Antes | Después |
|---|---|---|
| `App.jsx` | `import { AuthProvider } from "./auth/authContext";` | `import { AuthProvider } from "./auth/AuthProvider";` |
| `App.jsx` | `import { ActivationProvider } from "./hooks/activationContext";` | `import { ActivationProvider } from "./hooks/ActivationProvider";` |
| `auth/authContext.logout.test.jsx` | `import { AuthProvider, useAuth } from "./authContext";` | dos líneas: `import { AuthProvider } from "./AuthProvider";` y `import { useAuth } from "./authContext";` |

Los demás archivos no se tocan.

## Paso 4. Documentación

En `docs/modules/frontend.md`:

- Línea del stack: ``Auth: Context propio (`src/auth/authContext.jsx`)`` → ``Auth: Context propio (`src/auth/AuthProvider.jsx` + `src/auth/authContext.js`)``.
- Título de sección `### authContext.jsx` → `### AuthProvider.jsx`.

No edites los ADR históricos.

## Verificación

```
rtk proxy node_modules/.bin/eslint src/auth src/hooks/ActivationProvider.jsx src/hooks/activationContext.js src/App.jsx
pnpm run build
```

Ejecuta la suite completa, porque cambia el módulo que simulan 20 archivos de prueba.

Recuento total: **59 errores**. Los dos `only-export-components` deben haber desaparecido. `AuthProvider.jsx` conserva sus dos errores previos: se tratan en E05.

## Cierre

Commit: `refactor(frontend): keep auth and activation providers in component-only files (order 5, C3)`.

Marca C3 como `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. Registra en evidencia que el criterio escrito en la deuda fue sustituido por decisión del usuario (plan §1).
