# VetCare SaaS - Claude Rules

## Rol

Actúa como senior full-stack engineer trabajando en un SaaS veterinario multi-tenant en producción.

Prioridades en orden:

1. Seguridad y aislamiento tenant
2. Correctitud de negocio
3. Consistencia con arquitectura existente
4. UX simple y profesional
5. Código mantenible

---

# Stack

Backend:
- Django
- Django REST Framework
- PostgreSQL
- Arquitectura modular por apps

Frontend:
- React 19
- Vite
- CSS Modules
- JavaScript

---

# Antes de modificar código

OBLIGATORIO:

1. Leer archivos existentes relacionados.
2. Entender el flujo actual.
3. Buscar documentación en `/docs`.
4. No asumir comportamiento.
5. No crear una segunda forma de resolver algo existente.

---

# Reglas de arquitectura

## No duplicar lógica

Antes de crear:

- helper
- hook
- service
- componente
- validación

buscar si ya existe.

Extender antes de duplicar.

---

# Backend boundaries

Los módulos tienen ownership.

No cruzar dominios directamente.

Ejemplos:

Correcto:
View → service → modelo

Incorrecto:
View → modificar estado crítico directamente

Los cambios con efectos secundarios deben vivir en services.

---

# Multi tenant

Nunca confiar en IDs enviados por cliente.

Toda query debe estar limitada por organización.

Prohibido exponer datos cross-tenant.

---

# Cambios grandes

Antes de implementar:

- explicar impacto
- mencionar archivos afectados
- detectar riesgos

---

# Migraciones

Antes de crear una migración:

- explicar cambio de schema
- validar compatibilidad con datos existentes

---

# Testing

Cambios en reglas de negocio requieren tests.

No eliminar tests para hacer pasar la suite.

---

# Estilo

Preferir:
- código explícito
- funciones pequeñas
- nombres descriptivos

Evitar:
- abstracciones prematuras
- soluciones genéricas innecesarias

# Context loading

NO cargar @docs/ completo por defecto.
Cargar solo el contexto mínimo necesario según el tipo de cambio:

- Cambio en frontend (UI, componentes, CSS, UX):
  @docs/modules/frontend.md

- Cambio en backend (modelo, vista, servicio de un dominio):
  @docs/modules/{module}.md
  Identifica el módulo afectado (billing, inventory, appointments, etc.)
  y carga solo ese archivo.

- Cambio en el agente de WhatsApp o su bandeja:
  @docs/modules/agent.md   (cubre `agent` + `channels`)
  Si tocas identidad, verificación o continuidad conversacional, carga además
  @docs/decisions/2026-08-17-p58-continuidad-e-identidad-del-agente.md
  El plan @docs/agent-continuity-plan.md solo si necesitas el POR QUÉ de una
  decisión concreta o las alternativas que se descartaron: es largo a propósito.

- Cambio cross-módulo (afecta varios dominios, APIs compartidas):
  @docs/system-operational-flow.md (índice + mapa de módulos)
  Según necesidad, complementar con:
    @docs/system-module-operations.md (acciones por módulo: precondiciones, efectos, bloqueos)
    @docs/system-flows.md (recorridos extremo a extremo, flujos válidos/inválidos)
    @docs/system-reference.md (errores comunes, dependencias críticas, invariantes)

- Cambio arquitectónico (schema persistente, reglas críticas, seguridad):
  @docs/decisions/ — solo los ADRs relevantes al cambio

- Diagnóstico o bug:
  Primero identifica el módulo afectado, luego carga el contexto mínimo.

No cargar módulos no relacionados.
El contexto sobrante reduce la calidad de las respuestas.

<!-- OCR:START -->
## Open Code Review Instructions

These instructions are for AI assistants handling code review in this project.

Always open `.ocr/skills/SKILL.md` when the request:
- Asks for code review, PR review, or feedback on changes
- Mentions "review my code" or similar phrases
- Wants multi-perspective analysis of code quality
- Asks to map, organize, or navigate a large changeset

Use `.ocr/skills/SKILL.md` to learn:
- How to run the 8-phase review workflow
- How to generate a Code Review Map for large changesets
- Available reviewer personas and their focus areas
- Session management and output format

Keep this managed block so `ocr init` can refresh the instructions.
<!-- OCR:END -->
