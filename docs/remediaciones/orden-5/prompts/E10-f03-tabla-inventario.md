# E10 — F03: tabla de Inventario y `SortHeader` compartido

Primero lee y aplica `docs/remediaciones/orden-5/prompts/00-REGLAS-COMUNES.md`.

## Objetivo

Que Inventario use la tabla global y el `SortHeader` compartido, que además aporta teclado y `aria-sort`.

**Cambio visual esperado y aprobado:** el encabezado pasa de oscuro a claro y desaparece la cebra, igual que en Cobros. `global.css` no se toca.

## Archivos permitidos

- `frontend/src/pages/inventory.jsx`
- `frontend/src/pages/inventory.module.css`
- `frontend/src/pages/inventory.order.test.jsx`
- `frontend/src/components/SortHeader.jsx` (solo su comentario)
- `frontend/design-system.md`
- `docs/modules/frontend.md` (una frase)
- Expediente del orden 5

## Precondición

`inventory.module.css` también lo importan `StockEntryModal.jsx` y `ReceptionsModal.jsx`. Busca en ambos `s.tableWrap`, `s.table`, `s.th`, `s.td`, `s.sortable`, `s.thInner` y `s.sortArrow`. Debe dar 0 resultados. Si hay alguno, detente con `BLOQUEADA`.

## Paso 1. `inventory.jsx`

1. Añade `import SortHeader from "../components/SortHeader";`.
2. Elimina el componente local `const SortHeader = (...) => {...};` y su comentario `// ── SortableHeader ───...`.
3. Cambia las clases de la tabla:

| Antes | Después |
|---|---|
| `<div className={s.tableWrap}>` | `<div className="table-wrap">` |
| `<table className={s.table}>` | `<table className="table">` |
| `<th className={s.th}>Acciones</th>` | `<th>Acciones</th>` |
| `<td className={s.td}>` (todas) | `<td>` |
| `<td className={s.td} style={{ textAlign: "right" }}>` (todas) | `<td style={{ textAlign: "right" }}>` |

Las llamadas `<SortHeader col=... />` no cambian. No toques las clases del contenido de las celdas (`s.prodCell`, `s.stockCell`, etc.).

## Paso 2. `inventory.module.css`

Elimina **solo** estas reglas: `.tableWrap`, `.table`, `.table thead tr`, `.th`, `.th:first-child`, `.th:last-child`, `.th.sortable`, `.th.sortable:hover`, `.thInner`, `.sortArrow`, `.sortArrow.active`, `.table tbody tr:nth-child(even)`, `.table tbody tr:nth-child(odd)`, `.table tbody tr`, `.table tbody tr:hover` y `.td`, junto con sus comentarios `/* ─ Header ─ */` y `/* ─ Body rows ─ */`.

Conserva `/* ─ Columna: Producto ─ */` y todo lo que sigue. No toques `.active` si existe como regla suelta.

## Paso 3. `SortHeader.jsx`

Elimina del docblock las líneas que empiezan con `Nota: Inventario conserva su SortHeader local` y su continuación. No cambies código.

## Paso 4. `frontend/design-system.md`

En la sección `### Tabla — \`.table-wrap\` + \`.table\``:

Sustituye las dos primeras viñetas (Header y Body) por:

```markdown
- Header: fondo `--c-surface-2`, th 11.5px/600 `--c-text-2`, padding `11px 16px`, letter-spacing 0.01em, borde inferior `--c-border`.
- Body: td 13.5px `--c-text`, padding `12px 16px`, fondo `--c-surface` sin cebra, hover `--c-hover`.
```

Y elimina el paréntesis `(Inventario conserva su SortHeader local en module CSS — deuda contenida, migrar junto con la unificación de su tabla, no piecemeal.)`.

## Paso 5. `docs/modules/frontend.md`

En la sección SortHeader, elimina la frase desde `Deuda contenida: Inventario conserva su SortHeader local` hasta el final de esa frase. Añade `Inventario lo usa desde el orden 5.` tras `Usado en Cobros (Fecha/Total)`.

En Testing, elimina el bullet `**Bug conocido (deuda fase 3 B7):**` y su continuación: el orden 4 ya lo corrigió. En «Pendiente», elimina la línea `B7 (deuda fase 3)`.

## Paso 6. Pruebas

En `inventory.order.test.jsx`, añade dentro del `describe` existente, usando el mismo montaje de datos que el test actual:

```js
it("usa la tabla global y expone el orden de forma accesible", async () => {
    render(<Inventory />);
    await screen.findByText("Producto A");
    const table = screen.getByRole("table");
    expect(table).toHaveClass("table");

    const header = within(table).getByText("Valor en stock").closest("th");
    expect(header).toHaveAttribute("aria-sort", "none");

    fireEvent.click(header);
    expect(header).toHaveAttribute("aria-sort", "ascending");

    fireEvent.keyDown(header, { key: "Enter" });
    expect(header).toHaveAttribute("aria-sort", "descending");
});
```

No cambies el test existente.

## Verificación

```
rtk proxy node_modules/.bin/vitest run src/pages/inventory.order.test.jsx src/pages/inventory.receptions.test.jsx --reporter=dot 2>&1 | tail -15
rtk proxy node_modules/.bin/eslint src/pages/inventory.jsx src/pages/inventory.order.test.jsx src/components/SortHeader.jsx
pnpm run build
```

Busca `s.th\b` y `s.td\b` en `inventory.jsx`: 0 resultados. Recuento total: **0 errores**.

Verificación visual: si dispones de backend y navegador, abre `/inventory` en escritorio y móvil. Si no, decláralo como pendiente. No afirmes haberlo visto.

## Cierre

Commit: `refactor(frontend): move inventory to the shared table and sort header (order 5, F03)`.

Marca F03 como `IMPLEMENTADO_Y_VERIFICADO_LOCALMENTE`. En «Para revisar» indica mirar Inventario en vista tabla.
