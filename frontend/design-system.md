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

**Familias:**
- Display/body: `var(--font-body)` = `'Plus Jakarta Sans', 'Helvetica Neue', Helvetica, Arial, sans-serif`
- Mono (datos clínicos, valores numéricos): `var(--font-mono)` = `'IBM Plex Mono', 'Courier New', monospace`
- Login display: `Space Grotesk` (solo en login.css)

**Pesos permitidos:** `400` · `500` · `600` · `700`. Nada de 300, 450, 550, 650, 750, 800…
(los vigila `src/test/designTokensRatchet.test.js`, §8).

**Tamaño mínimo:** 11px. Nada de 9, 9.5, 10 ni 10.5px: no se leen en una pantalla de recepción.

**Escala (única):** 11 · 11.5 · 12 · 12.5 · 13 · 13.5 · 14 · 16 · 20 · 24 · 28 px. Un tamaño
fuera de la escala se redondea al escalón más cercano. 24 px es el «número en panel» (totales,
cifras en tarjetas compactas); 28 px, el número de indicador y el héroe del Dashboard.

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
| Número en panel | — | 24px | 700 | totales y cifras de tarjetas compactas |

**Letter-spacing:** títulos `-0.01em`; eyebrows/uppercase `0.05em`. No usar valores >0.1em (era el look editorial de Analytics).

---

## 2. Color (tokens de `tokens.css`)

Valores vigentes (2026-11-22). La paleta crema anterior (`#f5f1e8`, primario `#1a4434`) ya no existe.

**Marca (verde bosque):**
`--c-primary #0f624b` · `--c-primary-hover #0d4d3b` · `--c-primary-dark #0b3d30` · `--c-primary-light #e4efeb` · `--c-primary-ring rgba(15,98,75,.18)`

**Accent (coral):** `--c-accent #d67b5c` · `--c-accent-hover #c4674a` · `--c-accent-light #fdf0eb`

**Texto:** `--c-text #171817` · `--c-text-2 #454744` · `--c-text-3 #737570` · `--c-text-4 #9a9c97`

**Superficies:** `--c-bg #f5f5f3` · `--c-surface #ffffff` · `--c-surface-2 #f8f8f6` · `--c-subtle #ecece8` · `--c-hover #e7e7e3`

**Bordes:** `--c-border #deded9` · `--c-border-2 #c5c6c0`

**Semánticos** (text/bg/border): `success` · `danger` · `warning` · `info` · `purple` — usar siempre el trío del token, nunca hex sueltos.

**Header de tabla:** `--ink #171817`.

**Regla de uso (D6, plan UX 2026-11-21): el color marca lo que pide una acción.**
- Con color: lo que alguien tiene que atender (agotado, bajo stock, pendiente de cobro, urgencia,
  error) y el CTA primario.
- Sin color (neutro, `badge-default`, texto `--c-text-2`/`-3`): lo normal ("Normal", "Activo"),
  las categorías y los indicadores que solo cuentan.
- Una vista no debería mostrar más de un acento semántico por bloque. Si todo tiene color, nada
  destaca.
- El color nunca es la única señal: va con texto o ícono.

**Login:** usa sus propias variables `--lp-*`, definidas en `login.css`. El antiguo bloque «LOGIN
REDESIGN» de `tokens.css` (`--accent`, `--text-*`, `--border`…) se retiró en el plan UX F4.3; de
él quedan la escala `--space-*` y el alias `--font-dm-serif` (Analítica).

**Variables definidas:** toda `var(--x)` tiene que estar definida en algún CSS o estilo en línea
(lo vigila `designTokensRatchet.test.js`). Una variable sin definir no falla: la propiedad cae a
su valor inicial en silencio. No usar respaldos `var(--x, #hex)`: esconden ese error.

🚫 **Prohibidos:** teal en cualquier forma (`rgba(45,212,191,*)`, `#99f6e4`, `#087f83`, `#1D9E75`).
Cualquier `#xxxxxx` fuera de `tokens.css`. Paletas propias por página (`const PAL = {…}`).

---

## 3. Espaciado

**Escala:** 2 · 4 · 6 · 8 · 10 · 12 · 14 · 16 · 20 · 24 · 32 · 40 · 48 · 56 · 64 px
(de 2 en 2 hasta 16, después saltos de 4 y 8). `1px` solo para filetes.

| Uso | Valor |
|---|---|
| Padding interno de card | 20–24px |
| Gap entre cards | 24px |
| Gap entre inputs (form) | 16px |
| Separación entre secciones | 32px |
| Gap interno de botón | 6–8px |
| Gap entre botones contiguos | 8px (16px si uno es destructivo) |

No usar `3 · 5 · 7 · 9 · 11 · 13 · 15 · 18 · 22 · 26 · 28 · 30 · 36…`. Redondear al escalón más cercano.

**El espacio agrupa (ley de proximidad).** Lo que va junto se separa poco (4–12px); lo que es otra
cosa, mucho (24–32px). Una etiqueta o aviso va pegado a lo que explica, nunca al otro lado de la
pantalla.

---

## 4. Radios y sombras

**Radios:** `--r-sm 4` · `--r-md 6` · `--r-lg 8` · `--r-xl 10` · `--r-full 9999`.

| Elemento | Radio |
|---|---|
| Botón / input | `--r-md` |
| Card / tabla | `--r-lg` |
| Modal | `--r-xl` |
| Pill / badge | `--r-full` |

No usar `3 · 7 · 9 · 10 · 20px` crudos.

**Sombras:** `--shadow-xs` y `--shadow-sm` valen `none` (las superficies se separan con borde);
`--shadow-md` (hover, popovers) y `--shadow-modal`.
Card reposo = `--shadow-sm`; hover = `--shadow-md`; modal = `--shadow-modal`.
🚫 No usar `rgba(0,0,0,*)` en sombras.

**Transiciones:** `--t (150ms)` · `--t2 (200ms)`. No hardcodear `0.2s`, `120ms`, etc.

---

## 5. Componentes (contratos)

### Botón — `.btn` + variante + tamaño
- **Tamaños:** `.btn-xs` 26px · `.btn-sm` 30px · `.btn-md` 36px · `.btn-lg` 40px. weight 600, radio `--r-md`, gap 6px.
- **Variantes:** `.btn-primary` (verde, texto #fff) · `.btn-secondary` (surface + `--c-border-2` + shadow-xs) · `.btn-ghost` · `.btn-danger` · `.btn-warning` · `.btn-info` · `.btn-purple` · `.btn-success` (confirmar/factura) · `.btn-attention` (iniciar o continuar atención).
- **CTA primario de página = siempre `.btn.btn-primary`.** No crear botones primarios propios (`.btnPrime` = deuda legacy, no replicar).
- **Rótulos en minúscula de oración** con ícono, no con «+»: «Nueva cita», «Nueva mascota», «Nuevo producto». No «+ Nueva Mascota».
- **Tamaño de objetivo (ley de Fitts):** 36px mínimo para la acción principal de una fila o
  tarjeta en escritorio; 44px en pantallas ≤560px (táctil). `btn-xs` (26px) solo para acciones
  secundarias dentro de densidad alta, nunca como única vía para abrir un registro: en ese caso
  la fila o tarjeta entera es clicable.
- **Destructivas separadas:** archivar, borrar o cancelar nunca van pegadas a la acción frecuente
  con el mismo peso. Se separan al menos 16px (o con un divisor) y usan `btn-ghost` / `btn-danger`.
- **Icon-button canónico:** 30×30px, radio `--r-md`, `.btn.btn-icon.btn-ghost` o `.btn.btn-icon.btn-secondary`. Los iconos sin texto deben llevar `aria-label`.
- **CTA de avance:** añade `.btn-arrow` y envuelve el icono final en `.btn-trailing-icon`; al hover se desplaza 3px. Reserva la flecha para navegar, continuar o enviar a otro paso; no para guardar, eliminar o cancelar.
- Acción "éxito" (Cobrar/Pagar): hoy se logra con override inline a `--c-success-text`. Deuda conocida; centralizar en `.btn-success` cuando se aborde.

### Input — `.input` / `.select-input` / `.textarea-input`
- altura **38px**, padding `0 12px`, font 13.5px, border `1.5px var(--c-border)`, radio `--r-md`.
- **Foco (obligatorio):** `border-color var(--c-primary)` + `box-shadow 0 0 0 3px var(--c-primary-ring)`. Siempre anillo, no solo border.
- Label: `.form-label`. Grupo: `.form-group` (margin-bottom 16px).
- `SearchSelect`, `Field` y buscadores deben consumir `.input`, no estilos inline.
- Para formularios largos: `.form-card` → `.form-section` → `.form-grid` / `.form-field`; la geometría de cada flujo puede variar, pero no el aspecto de los controles.

### Búsqueda — `.searchBar`
- Campo compartido con icono `Search` a la izquierda, altura mínima **40px**, radio `--r-md` y foco con el anillo `--c-primary-ring`.
- Usa `input type="search"`; si el campo permite vaciar su valor, añade el botón `.search-clear` con etiqueta accesible.
- Las listas de resultados pueden conservar su propio comportamiento, pero no redefinir el contenedor, icono, foco ni botón de limpiar.
- Si se limita la cantidad inicial de sugerencias, muestra `Mostrando X de Y` y un botón `Ver más`; nunca ocultes coincidencias sin señalarlas.

### Card — `.card`
- bg `--c-surface`, border `1px var(--c-border)`, radio `--r-lg`, padding `20px 22px`, `--shadow-sm`.
- Hover: añadir `.card-hover` (→ `--shadow-md` + `--c-border-2`).
- Variante acento (timeline/historial): border-left 3px coloreado, resto igual. No usar `#e8e8e4` ni radio 12px crudo.

### Tabla — `.table-wrap` + `.table`
- Header: fondo `--c-surface-2`, th 11.5px/600 `--c-text-2`, padding `11px 16px`, letter-spacing 0.01em, borde inferior `--c-border`.
- Body: td 13.5px `--c-text`, padding `12px 16px`, fondo `--c-surface` sin cebra, hover `--c-hover`.
- Radio header `--r-lg`. Footer `.table-footer`.
- **Fila que abre un registro:** `tr.table-row-clickable` con `onClick` en la fila; el botón de la
  última columna se conserva para teclado y detiene la propagación.
- **Columna ordenable:** componente compartido `components/SortHeader.jsx` (`th.th-sortable`
  + `.th-inner` + `.sort-arrow` en `global.css`). No crear sorting por módulo.
- 🚫 No crear `.tableCompact` ni tablas por módulo. Una sola tabla.
  (`.tableCompact` de Cobros eliminado 2026-06-11 — migrado a `.table-wrap`/`.table`.)

### Badge — `.badge` + color
- altura 20px, padding `0 8px`, font 11px/600, radio `--r-full`.
- Colores: `.badge-success/danger/warning/info/purple/default/primary`.

### Indicador (tarjeta de métrica) — `components/StatTiles`
- **Fuente única**: `StatSection` + `StatTile` (+ `StatSectionSkeleton`). La usan
  Inventario, Dashboard y Mascotas. 🚫 No crear tarjetas de métrica por página ni
  volver a `.stat-card` con `borderTop` y colores inline.
- Sin rótulo sobre la rejilla: el `eyebrow` es opcional y por defecto no se muestra (el antiguo
  «Linear Insights» era un nombre interno en inglés, D2). La sección conserva su `aria-label`.
- Estructura adaptada de ReUI `statistic-card-2` (MIT): título + icono, valor 28px/700
  `tabular-nums` + insignia opcional, y pie separado por una línea con un dato real o
  qué cuenta el número (no se muestran deltas sin histórico). Sin formas decorativas.
  El valor baja hasta 22px en tarjetas angostas (`clamp` con `cqi`), sin desbordar.
- **Tono sutil** (`tone`): fondo claro + borde + texto del mismo trío semántico, que
  fija `--stat-bg` / `--stat-border` / `--stat-fg` (solo tokens): `ink` y `forest`
  (neutro; `forest` con el número en verde), `primary` (`--c-primary-light`),
  `attention` (`--c-warning-*`), `danger` (`--c-danger-*`) y `calm` (indicador de
  alerta en cero: neutro, sin color de alarma).
- Rejilla por defecto `auto-fit` (mín. 150px). Una página la cambia fijando
  `--stat-grid-cols` en `gridClassName` (Inventario: 4 + «Valor del stock» más ancho);
  un contenedor que ya separa con `gap` fija `--stat-section-gap: 0` (Dashboard).
- Accionable (`onClick`) → `<button>` con `aria-pressed` y `aria-label` «título: valor»;
  activo = borde del color del texto. `live` antepone al pie un punto que late (dato en
  vivo; se apaga con movimiento reducido). 🚫 No usar fondos sólidos oscuros.

### Modal — `.modal-overlay` + `.modal`
- Tamaños: `.modal-sm 400` · `.modal-md 520` · `.modal-lg 640`.
- radio `--r-xl`, `--shadow-modal`. Header `h3` 16px/700. `.modal-body` padding `20px 24px`. `.modal-footer` gap 8px.
- El marco es compartido; el tamaño (`sm/md/lg`) y la distribución interior son contextuales. Para acciones verticales usa `.modal-footer-stacked`.

### Filtros y resultados
- Para filtros mutuamente excluyentes de la misma vista usa `SegmentedControl` / `.segmented-control`; los `.tabs` quedan reservados para navegación entre secciones.
- Los autocompletados usan `.result-popover` y `.result-popover-item`, siempre con estados de foco/selección visibles.

### Menú de acciones de fila — `components/ActionMenu`
- Las acciones secundarias de una fila (restablecer, desactivar…) van en `ActionMenu` (botón ⋯
  `btn-ghost btn-icon` + `role="menu"` en portal); la acción frecuente queda visible a su lado.
- Mismo lenguaje que `.result-popover` (superficie, borde, `--r-lg`, `--shadow-md`). Opción
  destructiva con texto `--c-danger-text`, nunca sola como botón rojo en cada fila.
- 🚫 No crear menús desplegables por página.

### Header de página — `.page-header`
- `.page-title` (20/700) + `.page-subtitle` (13). Acciones a la derecha con `.btn`.
- **Orden de acciones (D7, ley de Jakob):** de izquierda a derecha, ayuda (`btn-ghost`: «Cómo
  funciona», «Ver ejemplo») → secundarias (`btn-secondary`) → **primaria al final**
  (`btn-primary`). El CTA principal vive siempre en el header, nunca en la fila de filtros.
- **Un solo H1 por página con `.page-title`.** Nada de `.ptitle`, `styles.pageTitle` ni tamaños
  inline. La barra superior del shell no repite el H1 (D8): no lleva título. Las rutas anidadas
  (ficha de mascota) ponen su «‹ Volver a…» junto al H1, dentro de la página; una miga en la
  barra lo repetiría.

### Navegación — `Sidebar`
- Agrupada (D9): Inicio · Atención (Citas, Mascotas, Historial clínico, Recetas) · Ventas
  (Punto de venta, Cobros, Caja) · Operación (Inventario, WhatsApp) · Admin.
- Permisos con `can()`, nunca por `user.role`.
- ≤560px: menú desplegable con texto desde la barra superior (D11); 560–900px: riel de íconos.

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
- **Tamaños de display fuera de la escala:** el título del paso del asistente de primer uso
  (40px, `FirstRunAssistant`) y el «404» de `notFound.jsx` (56px).
- **Analytics** (`analytics.module.css`) usa un lenguaje editorial aislado (serif, brutalist, paleta propia). Decisión pendiente de ADR: alinear vs. mantener aislado. Mientras tanto, **sus tokens locales no salen de esa página**.

- **Login** (`styles/login.css`) usa su propio set de variables y Space Grotesk. El botón
  principal del login es verde de marca, como el resto de la app (D12).
- **Ilustraciones SVG** del tutorial de inventario (`features/inventory/tutorial/`) llevan sus
  colores dentro del dibujo.
- **Gráficas (recharts)** del Dashboard: necesitan colores ya resueltos; los leen de los tokens en
  tiempo de ejecución (`readCssVar`) con un respaldo literal.
- **Logos de terceros** (`components/icons/GoogleIcon.jsx`): colores de marca ajenos.

Cualquier nueva excepción se documenta aquí antes de implementarla.

---

## 8. Trinquete (gate de regresión)

`src/test/designTokensRatchet.test.js` cuenta en `src`, sin las excepciones del §7:

- hex fuera de `tokens.css`;
- `font-weight` fuera de 400/500/600/700;
- `font-size` menor a 11px;
- `font-size` fuera de la escala del §1;
- espaciados (`padding`, `margin`, `gap`) fuera de la escala del §3.

Cada conteo tiene una línea base en el propio test. **Si sube, falla. Si baja, también falla
hasta que se baje la línea base en el mismo cambio**: así lo ganado no se pierde. La meta es 0
(plan UX 2026-11-21, F4.5).

---

_Última actualización: 2026-11-22 (plan UX 2026-11-21: D1–D13). Cambiar valores aquí ANTES de cambiarlos en el código._
