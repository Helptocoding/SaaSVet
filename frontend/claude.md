# Required context

Leer siempre antes de cualquier cambio:

@docs/modules/frontend.md

Contiene contratos sobre:

- manejo de errores
- permisos
- formularios
- llamadas API
- patrones UX existentes

# Frontend Rules

React 19 + Vite.

Objetivo:
interfaces SaaS profesionales simples.

---

# Componentes

Antes de crear componente:

buscar uno existente.

Reutilizar:

- modales
- inputs
- confirmaciones
- tablas
- estados loading/error

---

# API

Todas las llamadas pasan por api/.

Nunca llamar axios directamente desde páginas.

---

# Errores

Usar siempre:

apiError()

Nunca mostrar errores raw del backend.

---

# Formularios

Todo submit debe:

1. validar primero
2. activar saving/loading
3. bloquear doble click
4. manejar error
5. restaurar estado

---

# Confirmaciones

Nunca:

window.confirm()

Usar:

useConfirm()

---

# UX

Evitar:

- formularios gigantes verticales
- demasiados pasos innecesarios
- información escondida sin motivo

Preferir:

- layouts horizontales
- agrupación visual
- acciones claras

---

# CSS

Usar:

CSS modules.

No estilos inline salvo casos necesarios.

Mantener tokens globales.

---

# Permisos

Nunca:

user.role === "ADMIN"

Usar:

can(permission)

---

# IDs

Para URLs:

usar public_id.

No usar PK interno.