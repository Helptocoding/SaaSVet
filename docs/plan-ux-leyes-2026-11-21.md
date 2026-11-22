# Plan de implementación — Correcciones UX (Fitts, Jakob, Proximidad, Hick, jerarquía, color, espacio)

**Fecha:** 2026-11-21
**Revisión:** 2
**Estado:** D1–D13 APROBADAS por el usuario (2026-11-22, todas según la recomendación).
F0, F1, F2 y F3 IMPLEMENTADAS (rama feat/ux-leyes). Siguiente: F4. Registro en §7.
**Origen:** auditoría UX del 2026-11-21, hecha sobre la app local con la cuenta demo-admin:
13 pantallas capturadas a 1440 px y 390 px, mediciones del DOM con Playwright y búsqueda en
`frontend/src`. Capturas y métricas fuera del repositorio (scratchpad de la sesión).

Todas las rutas son relativas a `frontend/src` salvo que se indique otra raíz.

---

## 0. Resumen

Las fases están ordenadas por importancia y complejidad. Cada una se puede entregar y revisar
por separado, y ninguna toca el backend.

| Fase | Qué resuelve | Importancia | Complejidad | Esfuerzo |
|---|---|---|---|---|
| F0 | Doc del design system al día + trinquete contra regresiones + auditar lo que faltó | Habilitadora | Baja | S |
| F1 | Errores visibles y arreglos de 1–2 archivos | Alta | Baja | S–M |
| F2 | Consistencia entre pantallas y control del color | Alta | Media | M–L |
| F3 | Jerarquía y estructura: barra superior, menú, Dashboard, tipografía, espaciado | Media-alta | Media-alta | L |
| F4 | Móvil y consolidación de tokens | Media | Alta | L |

S = horas · M = 1–2 días · L = 3+ días.

---

## 1. Hallazgos que motivan el plan (con evidencia)

| # | Ley | Hallazgo | Dónde |
|---|---|---|---|
| H1 | Jakob | Calendario en inglés ("Sun Mon", "9a/12p"); semana inicia en domingo y la agenda del Dashboard en lunes | `pages/appointments.jsx:1319` (FullCalendar sin `locale`), `getWeekStart` en el mismo archivo |
| H2 | Jerarquía | Rótulo "Linear Insights" visible en Mascotas, Inventario y Dashboard | `components/StatTiles.jsx:28,85` (valor por defecto de `eyebrow`) |
| H3 | Fitts | Botón "?" fijo abajo a la derecha (`z-index 1000`) tapa la última columna de acciones; dice "?" pero abre "Reportar un problema" | `components/FeedbackButton.jsx:57`, montado en `App.jsx:104` |
| H4 | Jakob | "¿Olvidaste tu contraseña?" es un enlace muerto (`preventDefault`). No hay autoservicio: el reset lo hace un ADMIN (ADR p21) | `components/LoginForm.jsx` |
| H5 | Color | 295 hex distintos fuera de `tokens.css`. La agenda tiene paleta propia (`PAL`, `CATEGORY_PALETTE`, color por veterinario) y dos bloques `<style>` con `--monday-teal:#087f83` (teal prohibido, design-system §0.6) | `pages/appointments.jsx:43-50, 929, 1084, 1172-1312` |
| H6 | Color | ≥5 verdes en pantalla: `--c-primary`, `--c-success-text`, `--accent` (login), teal de agenda | `styles/tokens.css`, agenda, `FeedbackButton.jsx` |
| H7 | Color / jerarquía | Inventario: 27 fondos y 12 colores de texto en una vista; badge verde "Normal" en cada fila; categorías coloreadas | `pages/inventory.jsx` |
| H8 | Fitts | Destructivas junto a frecuentes con el mismo peso: "Editar \| Archivar" + "Archivar cliente" en cada tarjeta de mascota; lápiz junto a papelera en Inventario | `pages/pets.jsx:1160-1162, 279`; `pages/inventory.jsx` |
| H9 | Fitts | Cobros: la única forma de abrir un cobro es un ícono de ojo en el borde derecho | `pages/billing.jsx` |
| H10 | Fitts | Navegación ‹ Hoy › de la agenda a 26×30 px con estilos inline, en el lado opuesto al selector de vista | `pages/appointments.jsx:103, 1319` |
| H11 | Jakob | El botón primario cambia de lugar: en medio (Citas), al final (Inventario), en la fila de filtros (Cobros "+ Cobro") | headers de cada página |
| H12 | Jakob | Filtros con 4 estilos: `<select>` sin `.select-input` (Citas), `.select-input` (Mascotas, Cobros), chips (WhatsApp, Inventario), segmentado. Búsqueda de Citas sin ícono | `pages/appointments.jsx`, `pages/inbox` |
| H13 | Proximidad | La barra superior repite el H1 en cada página y queda vacía en Caja, WhatsApp y Analítica (`PAGE_TITLES` incompleto) | `components/Layout.jsx:8-22` |
| H14 | Proximidad | "No se permiten fechas pasadas" a ~900 px de lo que explica (es paso del recorrido: `data-tour="agenda-past-dates"`) | `pages/appointments.jsx:954` |
| H15 | Hick | Menú de 12 entradas sin agrupar (solo "Admin"); el dinero ocupa 3 entradas | `components/Sidebar.jsx` |
| H16 | Hick | Inventario: ~18 decisiones antes de la tabla; "Ver ejemplo" al nivel de "Nuevo producto". Recetas: 6 filtros con 0 recetas. POS: "Sin resultados" al enfocar sin escribir | `pages/inventory.jsx`, `pages/prescriptions.jsx`, `components/pos/ProductSearch.jsx:75-80` |
| H17 | Jerarquía | Dashboard: el bloque más ancho es "Ingresos del día $0"; la agenda empieza a ~630 px; "En consulta" aparece dos veces | `pages/dashboard/index.jsx:183-215`, `DashboardTopBar.jsx` |
| H18 | Jerarquía | H1 de 20, ~26 y ~28 px según la página; Historial clínico sin H1; 28 tamaños de fuente y 13 pesos en el código (DS: 4 pesos); 75 usos de 9–10 px | config, inbox, inventory (`.ptitle`), cash (inline), agenda |
| H19 | Espacio | ~51 % de los padding/margin/gap fuera de la escala base-4 (10, 14, 6, 18, 9, 7…). `--space-8` vale 36 px y el doc dice 32 | todo `src` |
| H20 | Móvil | Inventario: los botones del encabezado se salen a 390 px (`.pacts` sin `flex-wrap`). Menú de 12 íconos sin texto. Los indicadores llenan la primera pantalla (Mascotas: 11 pantallas para 25 mascotas) | `pages/inventory.module.css:31`, `components/AppShell.module.css:224-254` |
| H21 | Doc | `design-system.md` describe otra paleta (crema, primario `#1a4434`) y un set de tokens que ya no existe. `tokens.css` tiene un segundo set "LOGIN REDESIGN" usado fuera del login | `frontend/design-system.md`, `styles/tokens.css:112-148` |
| H22 | Regla frontend | `Sidebar.jsx:52` decide con `user?.role === "ADMIN"`. `components/Header.jsx` está muerto (sin importadores), con hex y chequeo de rol | `components/Sidebar.jsx`, `components/Header.jsx` |

**Agregados en F0.1 (rev. 2)** — ficha de mascota, historial clínico y modales:

| # | Ley | Hallazgo | Dónde |
|---|---|---|---|
| H23 | Fitts | El «?» también tapaba «Editar» en el pie del panel de mascota (resuelto en F1.3) | `pages/pets.jsx` (panel) |
| H24 | Proximidad / Fitts | Modal «Nueva cita»: fecha y hora dos veces (subtítulo y chip), formulario vertical de 7 bloques, botones de hora de ~24 px de alto, enlace «No encuentro la mascota →» de 11 px | `pages/appointments.jsx` (modal de cita) |
| H25 | Jerarquía / color | Historial clínico: etiquetas de signos vitales pequeñas y grises («Ultimos» sin acento); la tarjeta de consulta usa borde y badge azul para «Consulta general» (color sin acción); «+ Nueva Consulta» en otro verde y en mayúsculas | `pages/medicalRecords/*` |
| H26 | Fitts | Confirmado H9: en Cobros, pulsar el nombre de la mascota no hace nada | `pages/billing.jsx` |

**Fuera del alcance UX, para decisión aparte:** el buscador del Punto de Venta muestra
`Stock {p.stock}` de `Presentation.stock`, que la documentación de Billing declara campo legado
y no autoridad de disponibilidad (`components/pos/ProductSearch.jsx`).

---

## 2. Decisiones que necesito aprobar

| # | Decisión | Recomendación | Alternativa |
|---|---|---|---|
| D1 | Inicio de semana y formato de hora del calendario | **Lunes y 24 h ("09:00")**, como el Dashboard y la vista de lista | Domingo y 12 h ("9:00 a. m.") |
| D2 | Rótulo de los indicadores | **Quitarlo** (`eyebrow` por defecto `null`); el `aria-label` de la sección se conserva | Texto en español ("Resumen") |
| D3 | Botón de reporte de problemas | **Ícono en la barra superior**, junto a la campana, con nombre "Reportar un problema" (también en `DashboardTopBar`) | Dejar el botón flotante y reservar espacio inferior en `.content` |
| D4 | "¿Olvidaste tu contraseña?" | **Mostrar la instrucción en línea**: "Pide al administrador de tu clínica que la restablezca desde Equipo." Sin backend | Quitar el enlace |
| D5 | Color en la agenda | **Una sola dimensión: categoría**, con tríos semánticos existentes (urgencia = danger, cirugía = purple, vacunación = info, resto = neutro). Se quita el color por veterinario; el filtro por veterinario ya existe | Color por veterinario con 4 tonos de token |
| D6 | Regla general de color | **Color solo para estados que piden acción.** Lo normal y las categorías van en neutro | Mantener categorías coloreadas |
| D7 | Orden del encabezado de página | **Primario siempre al final** (extremo derecho). Ayuda ("Cómo funciona", "Ver ejemplo") como `btn-ghost` | — |
| D8 | Barra superior | **Sin título en páginas de primer nivel** (el H1 ya lo dice). En rutas anidadas, miga: "Mascotas › Bella" | Completar `PAGE_TITLES` y mantener el duplicado |
| D9 | Grupos del menú | **Inicio · Atención** (Citas, Mascotas, Historial clínico, Recetas) **· Ventas** (Punto de venta, Cobros, Caja) **· Operación** (Inventario, WhatsApp) **· Admin** | Otro reparto |
| D10 | Dashboard | **Agenda del día primero.** Los ingresos pasan a un indicador (solo con `dashboard.financial.view`) y se quita el duplicado de "En consulta" | Solo bajar la tarjeta de ingresos |
| D11 | Navegación en móvil (≤560 px) | **Menú lateral desplegable con texto**, abierto desde la barra superior. El riel de íconos se queda para tabletas (560–900 px) | Barra inferior con 4 accesos + "Más" |
| D12 | Botón de login | **Verde de marca** (`--c-primary`), como el resto de la app | Mantener negro |
| D13 | "Archivar cliente" | **Sale de la tarjeta de mascota** y queda en la ficha de la mascota, junto a los datos del cliente | Dejarlo en un menú "Más" de la tarjeta |

---

## 3. Fases

Reglas para todas las fases:

- Sin cambios de backend ni de API. Si un punto lo requiere, se saca a un plan propio.
- Se conservan `data-tour` (recorrido de la agenda) y los nombres accesibles que usan las
  pruebas (`pets.test.jsx`, `pets.edit.test.jsx`, `inventory.*.test.jsx`).
- Cada punto termina con `pnpm test`, `pnpm lint`, `pnpm build` y capturas antes/después a
  1440 y 390 px con el script de la auditoría.
- Sin commits hasta que se pidan; propongo un commit por punto o por grupo pequeño.

### F0 — Preparación (habilitadora · baja)

**F0.1 Completar la auditoría.** Capturar ficha de mascota, consulta y los modales de nueva
cita, cobro y producto con un solo login reutilizado (`storage_state` de Playwright) para no
chocar con el límite de intentos. Los hallazgos nuevos se agregan a la tabla del §1 como rev. 2.

**F0.2 Poner al día `frontend/design-system.md`** (el contrato dice: cambiar el doc antes que el
código):
- Paleta, radios y sombras reales de `tokens.css` (neutro + `--c-primary #0f624b`, `--r-xl 10px`,
  sombras `none` en reposo).
- Convenciones aprobadas: D6 (color), D7 (orden del encabezado) y objetivos mínimos (36 px en
  escritorio, 44 px táctil en ≤560 px).
- Escala tipográfica y de espaciado finales que usarán F3 y F4.

**F0.3 Trinquete contra regresiones.** `src/test/designTokensRatchet.test.js`, con el patrón
de `src/test/noConsoleTokenLeak.test.js`. Recorre `src` y cuenta:
- hex fuera de `tokens.css`;
- `font-weight` fuera de {400, 500, 600, 700};
- `font-size` menor a 11 px;
- valores de espaciado fuera de la escala.

Falla si algún conteo **sube** respecto a la línea base guardada en el propio test. Cada fase
baja la línea base. Excepciones documentadas: `pages/analytics/` (fuera del piloto), ilustraciones
SVG del tutorial de inventario y `styles/login.css`.

Verificación: `pnpm test`.

### F1 — Errores visibles y arreglos rápidos (alta · baja)

Cada punto toca 1–2 archivos.

| # | Cambio | Archivos | Hallazgo |
|---|---|---|---|
| F1.1 | Calendario en español (D1): `locale={esLocale}` desde `@fullcalendar/core/locales/es` (ya instalado), `firstDay`, `eventTimeFormat`/`slotLabelFormat` a 24 h; `getWeekStart`, vista semana y mini calendario con el mismo inicio; pie "De domingo a sábado" de Mascotas y su rango | `pages/appointments.jsx`, `pages/pets.jsx` | H1 |
| F1.2 | Quitar "Linear Insights" (D2): `eyebrow` por defecto `null` en `StatSection` y `StatSectionSkeleton`; ajustar la prueba | `components/StatTiles.jsx`, `StatTiles.test.jsx` | H2 |
| F1.3 | Reporte de problemas a la barra superior (D3): botón ícono con `aria-label`, CSS module, sin inline ni `--accent`; el modal usa `.modal-overlay` / `.modal` en vez de su modal propio | `components/FeedbackButton.jsx`, `Layout.jsx`, `dashboard/DashboardTopBar.jsx`, `App.jsx` | H3, H6 |
| F1.4 | "¿Olvidaste tu contraseña?" muestra la instrucción en línea (D4); prueba nueva en `LoginForm.test.jsx` | `components/LoginForm.jsx` | H4 |
| F1.5 | Encabezado de Inventario que no se sale en móvil: `flex-wrap` en `.pacts` | `pages/inventory.module.css:31` | H20 |
| F1.6 | POS: con la búsqueda vacía no se abre "Sin resultados" | `components/pos/ProductSearch.jsx` | H16 |
| F1.7 | Recetas: sin recetas no se muestran filtros (quedan el aviso y el estado vacío) | `pages/prescriptions.jsx` | H16 |
| F1.8 | "No se permiten fechas pasadas" junto a la navegación del calendario; el paso del recorrido sigue apuntando a `data-tour="agenda-past-dates"` | `pages/appointments.jsx:954`, verificar `features/appointments/tour/agendaSteps.js:87` | H14 |
| F1.9 | Borrar `components/Header.jsx` (código muerto) | — | H22 |
| F1.10 | Menú: `isAdmin` → `can("organization.update")` para Configuración (regla del frontend); prueba pequeña de `Sidebar` | `components/Sidebar.jsx` | H22 |
| F1.11 | Solo si D8 se aplaza: completar `PAGE_TITLES` con `/cash`, `/inbox`, `/analytics` | `components/Layout.jsx` | H13 |

Docs: `docs/modules/frontend.md` (§StatTiles: quitar el valor por defecto de `eyebrow`).

### F2 — Consistencia y color (alta · media)

| # | Cambio | Archivos | Hallazgo |
|---|---|---|---|
| F2.1 | **Agenda sin paleta propia** (D5). Los dos `<style>` (~140 líneas) pasan a `features/appointments/agenda.module.css`, con `:global(.fc-…)` para las clases de FullCalendar. `--monday-teal` y los hex → tokens. `PAL`/`CATEGORY_PALETTE` → tríos semánticos; se quita `vetPalette`. `calNavBtn`/`miniNavBtn`/`lblStyle` → clases, con ‹ Hoy › a 32 px mínimo | `pages/appointments.jsx`, CSS nuevo | H5, H6, H10 |
| F2.2 | **Botón primario al final** (D7). Citas: "Cómo funciona" y "Atención sin cita" antes, "Nueva cita" al final (también en `AppointmentsSkeleton`). Inventario: "Ver ejemplo" → ghost. Cobros: "+ Cobro" sube al `page-header` junto a `CajaBar`. Rótulos en minúscula con `Icon.Plus` ("Nueva mascota", "Agregar miembro") | `appointments.jsx`, `features/appointments/AppointmentsSkeleton.jsx`, `inventory.jsx`, `billing.jsx`, `pets.jsx`, `staff.jsx` | H11, H16 |
| F2.3 | **Destructivas separadas** (Fitts). Tarjeta de mascota: "Editar" visible y "Archivar" como `btn-ghost`, separado al menos 16 px; "Archivar cliente" sale de la tarjeta (D13). Inventario: la papelera se separa con divisor y margen | `pets.jsx`, `petDetail.jsx`, `inventory.jsx` | H8 |
| F2.4 | **Cobros: fila completa clicable**, con cursor; el botón del ojo se queda para teclado | `billing.jsx` | H9 |
| F2.5 | **Menos ruido de color** (D6). Inventario: estado "Normal" en texto neutro (solo bajo y agotado con color); categorías con `badge-default`. Indicadores sin acción ("Total mascotas", "Medicamentos") con tono `ink`. No se toca el chip crítico del Dashboard (contrato en `frontend.md` §Reglas Fase 1) | `inventory.jsx`, `pets.jsx`, `dashboard/index.jsx` | H7 |
| F2.6 | **Un solo H1**: `.page-title` en Configuración (`styles.pageTitle`), WhatsApp (`h1` sin clase), Inventario (`.ptitle`), Caja (inline) y la agenda (anular el override del `<style>`). Historial clínico: H1 "Historial clínico" cuando no hay mascota elegida | `pages/config/index.jsx`, `pages/inbox/index.jsx`, `inventory.jsx`, `cash.jsx`, `medicalRecords/index.jsx` | H18 |
| F2.7 | **Filtros con un solo aspecto.** Citas usa `.select-input` y `.searchBar`. Chips de WhatsApp → `SegmentedControl` cuando son excluyentes; si combinan (AND), se mantienen chips con el estilo de los de Inventario | `appointments.jsx`, `pages/inbox/*` | H12 |
| F2.8 | **Caja** con `.table-wrap`/`.table` y el mismo contenedor que las demás páginas (23 estilos inline) | `cash.jsx` | H18, H19 |
| F2.9 | **Modal «Nueva cita»**: fecha y hora una sola vez; campos en dos columnas donde quepa (mascota + veterinario, motivo + categoría); botones de hora de 36 px; «No encuentro la mascota» como `btn-ghost btn-sm` | `pages/appointments.jsx` | H24 |
| F2.10 | **Historial clínico**: signos vitales con etiqueta legible (12 px, `--c-text-2`) y «Últimos»; categoría de consulta en neutro (D6); «Nueva consulta» con `btn-primary` estándar | `pages/medicalRecords/*` | H25 |

Docs: `frontend/design-system.md` (§5 Botón: orden del encabezado; §2 Color: regla D6).
Riesgo principal: F2.1 es el archivo más grande (`appointments.jsx`, 91 estilos inline). Va en
su propio commit, probando el recorrido completo de la agenda y las vistas mes, semana, día y
lista.

### F3 — Jerarquía y estructura (media-alta · media-alta)

Cambian contratos documentados en `docs/modules/frontend.md`; el doc se actualiza en el mismo cambio.

| # | Cambio | Archivos | Hallazgo |
|---|---|---|---|
| F3.1 | **Barra superior sin duplicado** (D8): sin título en primer nivel; miga en rutas anidadas (`/pets/:id` → "Mascotas › {nombre}"). Se conservan el "Volver al Dashboard" del onboarding, la campana, el reporte (F1.3) y el avatar | `components/Layout.jsx`, `AppShell.module.css`, `petDetail.jsx` | H13 |
| F3.2 | **Menú agrupado** (D9) con `navSection`; en el riel de íconos los grupos se separan con espacio | `components/Sidebar.jsx`, `AppShell.module.css` | H15 |
| F3.3 | **Dashboard** (D10): agenda del día como primer bloque de la columna principal; ingresos como `StatTile` (solo con `dashboard.financial.view`) en lugar de la tarjeta ancha; se quita el duplicado de "En consulta". `FirstRunAssistant` no cambia. Actualizar `frontend.md` §Dashboard (composición) | `pages/dashboard/index.jsx`, `DashboardTopBar.jsx`, `dashboard.css` | H17 |
| F3.4 | **Tipografía a la escala**: pesos 300/450/550/650/680/740/750/760/800 → 400/500/600/700; tamaños de 9–10 px → 11 px; los 28 tamaños → la escala de F0.2. Mecánico, por módulo, bajando el trinquete | todo `src` salvo excepciones | H18 |
| F3.5 | **Espaciado a la escala**: valores fuera de la escala → escalón más cercano, por módulo, con capturas antes/después | todo `src` salvo excepciones | H19 |

### F4 — Móvil y deuda de tokens (media · alta)

| # | Cambio | Archivos | Hallazgo |
|---|---|---|---|
| F4.1 | **Navegación móvil** (D11): en ≤560 px, menú desplegable con texto desde la barra superior, con foco atrapado y cierre con Escape; riel de íconos entre 560 y 900 px | `Sidebar.jsx`, `Layout.jsx`, `AppShell.module.css` | H20 |
| F4.2 | **Densidad móvil**: indicadores a 2 columnas compactas en ≤560 px; tarjetas de mascota más bajas; objetivos táctiles de 44 px en ≤560 px (`btn-xs`, `btn-sm`, `btn-icon` vía media query global) | `components/StatTiles.module.css`, `styles/global.css`, `pets.jsx` | H20 |
| F4.3 | **Un solo set de tokens**: el set "LOGIN REDESIGN" pasa a estar acotado en `login.css`. Fuera del login se migra a los tokens canónicos (`MultiPresentationAnimation.module.css` 25 usos, `consultationForm.module.css` 19, `dashboard.css` 3). Hex sueltos de `consultationForm.module.css` (66), `medicalRecords.module.css` (29) y `config.module.css` (12) → tokens. Se corrige `--space-8` | `styles/tokens.css`, `styles/login.css`, archivos citados | H6, H19, H21 |
| F4.4 | **Botón de login verde** (D12) | `styles/login.css` | H6 |
| F4.5 | **Trinquete a su meta**: 0 fuera de las excepciones documentadas | `src/test/designTokensRatchet.test.js` | — |

---

## 4. Riesgos

- **Recorrido de la agenda.** Depende de `data-tour` y de la estructura del encabezado y del
  calendario (F1.8, F2.1, F2.2). Se recorre completo tras cada cambio de la agenda.
- **Pruebas por nombre accesible.** Las de Mascotas e Inventario buscan botones por texto. Se
  conservan los nombres; si un rótulo cambia (F2.2), la prueba se ajusta en el mismo cambio,
  nunca se borra.
- **Cambios visuales amplios sin pruebas visuales automáticas** (F3.4, F3.5, F4.3). Se mitiga
  con capturas antes/después por módulo, revisión de una persona y el trinquete.
- **FullCalendar en un CSS module.** Sus clases son globales y necesitan `:global(...)`; si no,
  la agenda pierde estilos en silencio.
- **Semana desde el lunes** (D1). Cambia qué cuenta "Citas esta semana" en Mascotas. Es un
  rango que calcula el frontend; no cambia el backend.
- **Contratos documentados que cambian.** `frontend.md` (§Dashboard, §StatTiles) y
  `design-system.md`. Se actualizan en el mismo cambio que el código.

## 5. Fuera de alcance

- Analítica (excluida del piloto) y el lenguaje visual del héroe del login.
- Recuperación de contraseña por correo: requiere backend y ADR propios (hoy aplica ADR p21).
- Pruebas con usuarios reales. Recomendadas después de F3 (skill `ux-researcher-designer`).

## 6. Orden sugerido

F0 → F1 completo → F2.1 sola → resto de F2 → F3.1–F3.3 → F3.4–F3.5 por módulo → F4.

---

## 7. Registro de implementación

### 2026-11-22 — F0 y F1 (sin commit)

Verificación: `vitest` 914/914 (85 archivos), `eslint` 0 errores (15 avisos
`exhaustive-deps` previos), `vite build` correcto, capturas antes/después a 1440 y 390 px.
Las pruebas de WhatsApp (`pages/inbox/index.test.jsx`) rozan su límite de 5 s y fallan por
tiempo cuando la suite corre en paralelo con los servidores de desarrollo encendidos; con
`--maxWorkers=2` pasan. No es de este cambio, pero conviene subirles el límite.

**F0**
- F0.1: auditadas ficha de mascota, historial clínico y modales de cita y producto
  (H23–H26, F2.9, F2.10). Las capturas usan un solo login y guardan la sesión rotada entre
  contextos (el refresh rota).
- F0.2: `frontend/design-system.md` con la paleta real, la regla de color (D6), la escala de
  letra y de espaciado, tamaños de objetivo, orden del encabezado (D7), barra superior (D8),
  menú (D9) y el trinquete (§8).
- F0.3: `src/test/designTokensRatchet.test.js`. Línea base inicial 548 hex · 45 pesos ·
  84 letras <11 px · 391 espaciados; tras F1: **523 · 45 · 84 · 388**.

**F1**
- F1.1: calendario con `locale` español, semana desde el lunes y 24 h; `getWeekStart`, mini
  calendario y «Citas esta semana» de Mascotas desde el lunes; sin «hs».
- F1.2: `StatSection` sin rótulo por defecto; doc y pruebas.
- F1.3: «Reportar un problema» en la barra superior (Layout y Dashboard), con el modal del
  design system montado en `document.body` (dentro de la barra sticky salía cortado), Escape
  y pruebas. Íconos nuevos `ReportProblem` y `Paperclip`.
- F1.4: «¿Olvidaste tu contraseña?» muestra a quién pedir el restablecimiento; pruebas.
- F1.5: botones del encabezado de Inventario que bajan de línea en móvil.
- F1.6: el buscador del Punto de Venta no abre «Sin resultados» sin texto.
- F1.7: Recetas sin filtros cuando no hay recetas; pruebas.
- F1.8: «No se permiten fechas pasadas» junto a ‹ Hoy ›; el paso del recorrido sigue
  apuntando a `data-tour="agenda-past-dates"`.
- F1.9: borrado `components/Header.jsx` (sin importadores).
- F1.10: Configuración en el menú por `can("organization.update")`; el operador de
  plataforma sigue por rol porque `*.*` no lo distingue. Pruebas.
- F1.11: no aplica (D8 aprobada; se resuelve en F3.1).

### 2026-11-22 — Mensajes del login (fuera de fase, pedido del usuario)

`hooks/useLoginForm.js` → `loginErrorMessage(err)`: distingue sin respuesta (red, backend
apagado o CORS), 401, 403 por contraseña temporal vencida, 403 por clínica desactivada, 429
(límite de 5 intentos / 15 min) y 5xx. Antes todo lo que no era 401 decía «Error de conexión.
Verifica tu internet». Origen: en local, el frontend del usuario arrancó en el 5174 porque un
Vite de las capturas ocupaba el 5173, y el backend solo admite el 5173 por CORS. Pruebas en
`hooks/useLoginForm.test.js`.

### 2026-11-22 — F2 (sin commit)

Verificación: `vitest` 924/924 (87 archivos), `eslint` 0 errores, `vite build` correcto,
capturas a 1440 px de agenda (mes, semana, día, lista, modal, recorrido), Inventario, Cobros,
Mascotas, ficha, Historial clínico, Caja y Configuración. Trinquete: **364 · 29 · 67 · 340**.

- F2.1: los dos `<style>` de la agenda (141 líneas) pasan a `features/appointments/agenda.css`
  solo con tokens. **Desvío del plan:** archivo global con prefijos propios (`agenda-`,
  `appointment-`, `day-`, `week-`) en vez de CSS module; convertir ~60 clases de un archivo de
  1.300 líneas multiplicaba el riesgo. Se verificó que ninguna otra pantalla usa esos nombres.
  Se retiran la paleta `PAL`, `CATEGORY_PALETTE`, el color por veterinario y `--monday-teal`;
  el tono sale de la categoría (urgencia, cirugía, vacunación; el resto neutro). ‹ Hoy › a
  32 px con clases. CSS muerto `week-*` eliminado. Token nuevo `--c-on-primary`.
- F2.2: orden ayuda → secundarias → primaria en Citas, Inventario («Ver ejemplo» ghost),
  Cobros («Nuevo cobro» al encabezado) y Punto de Venta; rótulos «Nueva mascota»,
  «Agregar miembro», «Nueva consulta», «Nueva cita» con ícono.
- F2.3: «Archivar» en ghost y separado 16 px de «Editar» (tarjeta y tabla de Mascotas);
  papelera de Inventario separada del lápiz. «Archivar cliente» pasa a la ficha (D13) con
  confirmación; pruebas en `pages/petDetail.archive.test.jsx`.
- F2.4: filas de Cobros clicables (`tr.table-row-clickable`); «Venta de mostrador» cuando no
  hay mascota.
- F2.5: Inventario sin color por categoría (había un teal `#0d9488` en el ícono de alimento),
  «Normal» neutro; indicadores sin acción en tono `ink`.
- F2.6: `.page-title` en Configuración, WhatsApp, Inventario y Caja; H1 «Historial clínico»
  sin mascota elegida. Configuración usa los tokens (tenía otra paleta con dos verdes) y deja
  de sangrar sobre el padding. Se quita la etiqueta decorativa «Control de stock».
- F2.7: filtros de Citas con `.searchBar` y `.select-input`. **WhatsApp no se toca:** sus
  chips están fijados por el contrato WA-FIL-01 (`aria-pressed`, 44 px, segmentos AND).
- F2.8: Caja sin contenedor propio y con `.table-wrap`/`.table` (usaba `table-compact`, que no
  existe).
- F2.9: modal de cita con fecha y hora una sola vez, campos en dos columnas y botones de hora
  de 36 px.
- F2.10: signos vitales legibles («Últimos», 11,5–12 px, tokens); tipo de consulta con el
  mismo criterio de color que la agenda; «Nueva consulta» sin el verde viejo `#1a4434`.

### 2026-11-22 — F3

Verificación: `vitest` 926/926 (87 archivos), `eslint` 0 errores, `vite build` correcto,
capturas a 1440 y 390 px. Trinquete: **362 hex · 0 pesos · 0 letras <11 px · 2 tamaños fuera
de escala (excepciones documentadas) · 4 espaciados** (valores > 64 px de layout grande).

- F3.1: la barra superior ya no lleva título. **Desvío del plan:** sin miga en rutas
  anidadas: la ficha de mascota ya tiene su «‹ Volver a mascotas» junto al H1 y una miga en la
  barra lo repetiría. `PAGE_TITLES` y `.topbarTitle` eliminados.
- F3.2: menú en grupos Atención · Ventas · Operación · Admin (`role="group"` con nombre; en el
  riel de íconos se separan con un filete). Rótulos en minúscula de oración («Historial
  clínico», «Punto de venta»). Pruebas en `components/Sidebar.test.jsx`.
- F3.3: Dashboard con la agenda del día primero, después los indicadores; «Ingresos del día»
  es un indicador con su variación contra ayer; sale «En consulta» (lo muestra «Ahora»).
  `DashboardTopBar` sin la tarjeta ancha ni la mini gráfica. `frontend.md` §Dashboard
  actualizado.
- F3.4: pesos y tamaños con un script reproducible (mismas exclusiones que el trinquete):
  300/450/550/650/680/740/750/760/800 → 400–700; < 11 px → 11; 14.5→14, 15/17/18→16,
  19→20, 22/23/26→24, 30/32→28. **Escala ampliada con 24 px** («número en panel»): convertir
  esas cifras a 20 o 28 movía demasiado los totales. Trinquete con métrica nueva `fontScale`.
- F3.5: espaciados con el mismo método: escalón más cercano, en empate el múltiplo de 4
  (307 líneas en 41 archivos, casi todas de 1–2 px). Valores > 64 px sin tocar (4).
