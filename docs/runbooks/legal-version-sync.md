# Runbook: Sincronizar una versión legal nueva (landing ↔ app)

**Fecha**: 2026-06-24
**Audiencia**: operador / ADMIN_SAAS.

## Contexto (decisión P0)

La landing (`www.saaslyvet.com`) y la app son **repos independientes**, **sin
dependencia en runtime**. El texto legal vive en la landing; la app solo versiona
(`LegalDocument.version`) y registra quién aceptó qué.

Promover una versión a `is_current` en la app es la **decisión humana** que dispara
el re-consentimiento de los usuarios. La fecha "Última actualización" de la landing
es la fuente de verdad del texto; `version` en la app debe **espejearla**.

## Tabla `doc_type` ↔ URL de la landing

| `doc_type` | URL en la landing |
|---|---|
| `terms` | `/terminos` |
| `privacy` | `/aviso-de-privacidad` |
| `cookies` | `/cookies` |

## Pasos cuando cambia un documento legal

### 1. Editar y publicar la LANDING

En el repo de la landing (`/desktop/LandingSaaS`):

- Editar el texto del documento (p.ej. `aviso-de-privacidad.astro`).
- Actualizar la fecha **"Última actualización"**.
- Publicar: **build + deploy** de la landing.

### 2. Decidir si el cambio es MATERIAL

- **Material** (cambia derechos, obligaciones, tratamiento de datos, etc.) →
  **requiere re-consentimiento** → se promueve a `is_current`.
- **Menor** (corrección tipográfica, formato) → **NO** se hace bump, **NO** se
  promueve.

> Solo los cambios **materiales** se promueven a `is_current`.

### 3. Promover la versión nueva en la APP (solo si es material)

En el backend:

```bash
python manage.py seed_legal_documents \
  --doc-type privacy \
  --version 2026-12-01 \
  --effective-date 2026-12-01 \
  --url https://www.saaslyvet.com/aviso-de-privacidad
```

Esto **demota** la versión vigente anterior y **promueve** la nueva a `is_current`.

> `version` debe **espejear** la fecha "Última actualización" de la landing.

### 4. Efecto

- Todos los usuarios cuyo **rol requiere** ese documento verán el
  `LegalAcceptanceGate` de nuevo en su próximo request / navegación y deberán
  **re-aceptar**.
- Las aceptaciones viejas **se conservan** (append-only, traza histórica).

## Nota: ejecutar el comando sin argumentos

Correr `python manage.py seed_legal_documents` **sin argumentos** solo **asegura las
versiones por defecto** — es **idempotente** y **NO** dispara re-consentimiento. Úsalo
para garantizar el estado base (p.ej. en un deploy nuevo), no para promover versiones.

## Verificación

Como un **usuario de prueba** del rol afectado:

```
GET /api/legal/current/
```

Debe mostrar la versión **nueva** con `accepted: false` (y `acceptance_required: true`).
Tras aceptar vía `POST /api/legal/accept/`, el mismo endpoint debe devolver
`accepted: true` y `acceptance_required: false`.

## Refs

- Módulo: [`docs/modules/legal.md`](../modules/legal.md)
- ADR p46 (`docs/decisions/2026-06-24-p46-legal-acceptance-gate.md`)
