# Design System — VeterinariaSaaS Frontend

> **Fuente única de verdad visual.** Este documento congela el sistema de diseño.
> Toda UI nueva o modificada DEBE ajustarse a estos contratos.
> Fuente real de los valores: `src/styles/tokens.css` + `src/styles/global.css`.

---

## 0. Contrato para agentes de IA (Claude / Gemini / Copilot / futuros)

Lee esta sección ANTES de escribir o modificar cualquier `.css`, `.jsx` o estilo.

**Reglas no negociables:**

1. **Un solo set de tokens.** Usa las variables de `tokens.css`. No definas variables nuevas de color/espaciado/radio/sombra en componentes. No crees un segundo set paralelo.
2. **Cero hex crudo.** Nunca `#1a4434`, `#888`, `#eee`. Usa el token (`var(--c-primary)`, `var(--c-text-3)`, `var(--c-border)`). El único lugar con hex es `tokens.css`.
3. **Reutiliza las clases globales.** Botón → `.btn`. Card → `.card`. Input → `.input`. Tabla → `.table`. Badge → `.badge`. Modal → `.modal`. No reimplementes un botón/card/input propio.
4. **Nada de estilos inline temáticos.** `style={{}}` solo para valores dinámicos (posición calculada, ancho %, color de dato). Color/spacing/radio/sombra fijos → clase + token.
5. **Un H1 por página**, con `.page-title` (20px/700). No inventes tamaños de título por módulo.
6. **TEAL PROHIBIDO.** `rgba(45,212,191,*)` y `#99f6e4` son restos de una marca anterior. La marca es verde bosque (`--c-primary`). No introduzcas teal.
7. Si un valor no existe como token, **no lo hardcodees**: propónlo como token nuevo en `tokens.css` y documéntalo aquí.

Si vas a desviarte de un contrato, primero edita este documento explicando la excepción.

---

## 1. Tipografía

**Familia:** `var(--font-body)` = `'Helvetica Neue', Helvetica, Arial, sans-serif`. Una sola familia en todo el producto.

**Pesos permitidos:** `400` · `500` · `600` · `700`. (No usar 450, 800.)

**Escala (única):**

| Rol | Token/clase | font-size | weight | Notas |
|---|---|---|---|---|
| Hero (solo Dashboard landing) | `.ptitle` (dashboard) | 28px | 700 | Excepción documentada §7 |
| **H1 página** | `.page-title` | **20px** | **700** | line-height 1.3 |
| H2 sección | `.dash-section-title`, modal `h3` | 16px | 700 | |
| H3 / título de card | — | 14px | 600 | |
| Body | (default) | 13.5px | 400 | |
| Body fuerte | — | 13.5px | 600 | |
| Label de campo | `.form-label` | 12.5px | 600 | letter-spacing 0.01em |
| Caption / meta | `.page-subtitle` | 13px | 400/500 | |
| Micro / eyebrow | — | 11px | 600 | UPPERCASE, letter-spacing 0.05em |
| Badge | `.badge` | 11px | 600 | |
| Número métrico | — | 28px | 700 | `font-variant-numeric: tabular-nums` |

**Letter-spacing:** títulos `-0.01em`; eyebrows/uppercase `0.05em`. No usar valores >0.1em (era el look editorial de Analytics).

---

## 2. Color (tokens de `tokens.css`)

**Marca (verde bosque):**
`--c-primary #1a4434` · `--c-primary-hover #16382a` · `--c-primary-dark #0f2a1f` · `--c-primary-light #c6d9c0` · `--c-primary-ring rgba(26,68,52,.14)`

**Accent (coral):** `--c-accent #d67b5c` · `--c-accent-hover #c4674a` · `--c-accent-light #fdf0eb`

**Texto:** `--c-text #1a1a1a` · `--c-text-2 #3a3a3a` · `--c-text-3 #8a8a7f` · `--c-text-4 #b0aba0`

**Superficies:** `--c-bg #f5f1e8` · `--c-surface #fbf8f1` · `--c-subtle #ede7d7` · `--c-hover #e8e2d4`

**Bordes:** `--c-border #d9d2be` · `--c-border-2 #c8bfa8`

**Semánticos** (text/bg/border): `success` · `danger` · `warning` · `info` · `purple` — usar siempre el trío del token, nunca hex sueltos.

**Header de tabla:** `--ink #1a1a1a`.

🚫 **Prohibidos:** `rgba(45,212,191,*)`, `#99f6e4` (teal legacy). Cualquier `#xxxxxx` fuera de `tokens.css`.

---

## 3. Espaciado

Escala base-4 (`--space-*`): **4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 · 56**.

| Uso | Valor |
|---|---|
| Padding interno de card | 20–24px |
| Gap entre cards | 24px |
| Gap entre inputs (form) | 16px |
| Separación entre secciones | 32px |
| Gap interno de botón | 6–8px |

No usar `7 · 9 · 11 · 13 · 18 · 22 · 26` (arbitrarios). Redondear al escalón más cercano.

---

## 4. Radios y sombras

**Radios:** `--r-sm 4` · `--r-md 6` · `--r-lg 8` · `--r-xl 12` · `--r-full 9999`.

| Elemento | Radio |
|---|---|
| Botón / input | `--r-md` |
| Card / tabla | `--r-lg` |
| Modal | `--r-xl` |
| Pill / badge | `--r-full` |

No usar `3 · 7 · 9 · 10 · 20px` crudos.

**Sombras (verde-tinte, ya tokenizadas):** `--shadow-xs` · `--shadow-sm` · `--shadow-md` · `--shadow-modal`.
Card reposo = `--shadow-sm`; hover = `--shadow-md`; modal = `--shadow-modal`.
🚫 No usar `rgba(0,0,0,*)` en sombras.

**Transiciones:** `--t (150ms)` · `--t2 (200ms)`. No hardcodear `0.2s`, `120ms`, etc.

---

## 5. Componentes (contratos)

### Botón — `.btn` + variante + tamaño
- **Tamaños:** `.btn-xs` 26px · `.btn-sm` 30px · `.btn-md` 36px · `.btn-lg` 40px. weight 600, radio `--r-md`, gap 6px.
- **Variantes:** `.btn-primary` (verde, texto #fff) · `.btn-secondary` (surface + `--c-border-2` + shadow-xs) · `.btn-ghost` · `.btn-danger` · `.btn-warning` · `.btn-info` · `.btn-purple`.
- **CTA primario de página = siempre `.btn.btn-primary`.** No crear botones primarios propios (`.btnPrime` = deuda legacy, no replicar).
- **Icon-button canónico:** 30×30px, radio `--r-md`, `.btn.btn-ghost` o `.btn-secondary`. (Variantes ad-hoc `.ab*`/`.actionBtn`/`.detailBtn` = legacy, no añadir más.)
- Acción "éxito" (Cobrar/Pagar): hoy se logra con override inline a `--c-success-text`. Deuda conocida; centralizar en `.btn-success` cuando se aborde.

### Input — `.input` / `.select-input` / `.textarea-input`
- altura **38px**, padding `0 12px`, font 13.5px, border `1.5px var(--c-border)`, radio `--r-md`.
- **Foco (obligatorio):** `border-color var(--c-primary)` + `box-shadow 0 0 0 3px var(--c-primary-ring)`. Siempre anillo, no solo border.
- Label: `.form-label`. Grupo: `.form-group` (margin-bottom 16px).
- `SearchSelect`, `Field` y buscadores deben consumir `.input`, no estilos inline.

### Card — `.card`
- bg `--c-surface`, border `1px var(--c-border)`, radio `--r-lg`, padding `20px 22px`, `--shadow-sm`.
- Hover: añadir `.card-hover` (→ `--shadow-md` + `--c-border-2`).
- Variante acento (timeline/historial): border-left 3px coloreado, resto igual. No usar `#e8e8e4` ni radio 12px crudo.

### Tabla — `.table-wrap` + `.table`
- Header: fondo `--ink`, th 11.5px/700 UPPERCASE #fff, padding `14px 16px`, letter-spacing 0.05em.
- Body: td 13.5px `--c-text`, padding `12px 16px`, zebra `--c-subtle`/`--c-surface`, hover `--c-hover`.
- Radio header `--r-lg`. Footer `.table-footer`.
- **Columna ordenable:** componente compartido `components/SortHeader.jsx` (`th.th-sortable`
  + `.th-inner` + `.sort-arrow` en `global.css`). No crear sorting por módulo.
  (Inventario conserva su SortHeader local en module CSS — deuda contenida, migrar
  junto con la unificación de su tabla, no piecemeal.)
- 🚫 No crear `.tableCompact` ni tablas por módulo. Una sola tabla.
  (`.tableCompact` de Cobros eliminado 2026-06-11 — migrado a `.table-wrap`/`.table`.)

### Badge — `.badge` + color
- altura 20px, padding `0 8px`, font 11px/600, radio `--r-full`.
- Colores: `.badge-success/danger/warning/info/purple/default/primary`.

### Modal — `.modal-overlay` + `.modal`
- Tamaños: `.modal-sm 400` · `.modal-md 520` · `.modal-lg 640`.
- radio `--r-xl`, `--shadow-modal`. Header `h3` 16px/700. `.modal-body` padding `20px 24px`. `.modal-footer` gap 8px.

### Header de página — `.page-header`
- `.page-title` (20/700) + `.page-subtitle` (13). Acciones a la derecha con `.btn`.

---

## 6. Anti-patrones detectados (no repetir)

| ❌ Anti-patrón | ✅ Correcto |
|---|---|
| Título de página con tamaño/peso por módulo | `.page-title` 20/700 |
| `#1a4434`, `#888`, `#eee` en CSS/JSX | `var(--c-primary)`, `var(--c-text-3)`, `var(--c-border)` |
| `rgba(45,212,191,*)`, `#99f6e4` (teal) | `var(--c-primary*)` |
| Botón propio (`.btnPrime`, `.detailBtn`) | `.btn .btn-primary` / `.btn-secondary` |
| Segunda tabla (`.tableCompact`) | `.table` |
| `style={{ padding, color, border }}` fijos | clase + token |
| Set de tokens paralelo (`--radius-*`, `--space-*` duplicados) | un solo set en `tokens.css` |
| Sombra `rgba(0,0,0,.1)` | `--shadow-sm/md` |
| `transition: all 0.2s` | `var(--t)` / `var(--t2)` |

---

## 7. Excepciones conscientes (no son bugs)

- **Dashboard landing** usa hero title 28px/700 (`.ptitle`) — contexto de portada, no página de lista.
- **Analytics** (`analytics.module.css`) usa un lenguaje editorial aislado (serif, brutalist, paleta propia). Decisión pendiente de ADR: alinear vs. mantener aislado. Mientras tanto, **sus tokens locales no salen de esa página**.

Cualquier nueva excepción se documenta aquí antes de implementarla.

---

_Última actualización: 2026-05-30. Cambiar valores aquí ANTES de cambiarlos en el código._
