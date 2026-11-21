/**
 * inventory — lógica derivada pura de inventario (extraída de pages/inventory.jsx, P1-4 B3).
 *
 * Estado del stock, cantidad disponible, valor en $ y stock inicial del wizard.
 * Funciones PURAS (sin React, sin side-effects) para poder testearlas y evitar que un
 * cambio visual en la página rompa silenciosamente un cálculo financiero/operativo.
 *
 * IMPORTANTE — comportamiento congelado (no cambiar sin ADR):
 *  - `stock_quantity` tiene prioridad sobre `presentation.stock`.
 *  - valor = sale_price / conversion_factor × qty (el /cf normaliza a unidad base).
 *  - "bajo stock" de `stockStatus` = regla frontend (min>0 && stock<min). NO es la misma
 *    que `presentation.is_low_stock` (flag del backend, stock<=min, incluye agotados) ni
 *    que la del dashboard (min>0 && stock<=min). La página de Inventario usa SOLO
 *    `stockStatus` para badges, filtros e indicadores.
 */

// Cantidad de stock del producto en unidades base. stock_quantity > presentation.stock > 0.
export const productStockQty = (product) => {
    const pres = product.presentation || {};
    return parseFloat(product.stock_quantity ?? pres.stock ?? 0) || 0;
};

// Valor monetario del stock: precio por unidad base (sale_price / cf) × cantidad.
export const productStockValue = (product) => {
    const pres = product.presentation || {};
    const stock = productStockQty(product);
    const salePrice = parseFloat(pres.sale_price ?? 0) || 0;
    const cf = parseFloat(pres.conversion_factor ?? 1) || 1;
    return (salePrice / cf) * stock;
};

// Estado del stock para la UI: crítico (agotado), bajo (< mínimo) u ok (normal).
// `pct` alimenta la mini-barra; `label` es el texto mostrado.
export const stockStatus = (product) => {
    const pres = product.presentation || {};
    const stock = productStockQty(product);
    const min = parseFloat(product.min_stock ?? pres.min_stock ?? 0) || 0;
    if (stock <= 0) return { pct: 0, state: "crit", label: "Agotado" };
    if (min > 0 && stock < min) return { pct: Math.min((stock / min) * 100, 100), state: "low", label: "Stock bajo" };
    const top = min > 0 ? min * 3 : 100;
    return { pct: Math.max(Math.min((stock / top) * 100, 100), 15), state: "ok", label: "Normal" };
};

// Bajo stock y agotado son alertas de reposición: un producto desactivado ya no se
// repone, así que no cuenta (mismo criterio que el dashboard, `is_active=True`).
const isActiveProduct = (product) => product.is_active !== false;

// Filtro de estado de stock de la página de Inventario. Es la MISMA regla con la que
// se cuentan los indicadores "Bajo stock"/"Sin stock": el número que se pulsa coincide
// con las filas que aparecen. `attention` = bajo stock + agotado (conjuntos disjuntos).
export const matchesStockFilter = (product, filter) => {
    if (!filter) return true;
    const state = stockStatus(product).state;
    if (filter === "ok") return state === "ok";
    if (!isActiveProduct(product)) return false;
    if (filter === "attention") return state === "low" || state === "crit";
    return state === filter;
};

// La tabla ordena con las mismas cantidades que muestra; los empates conservan
// el orden de entrada gracias al sort estable de JavaScript.
export const compareInventoryProducts = (a, b, column, direction) => {
    let va, vb;
    if (column === "name") {
        va = a.name.toLowerCase(); vb = b.name.toLowerCase();
    } else if (column === "stock") {
        va = productStockQty(a); vb = productStockQty(b);
    } else if (column === "price") {
        va = parseFloat((a.presentation || {}).sale_price ?? 0) || 0;
        vb = parseFloat((b.presentation || {}).sale_price ?? 0) || 0;
    } else if (column === "value") {
        va = productStockValue(a); vb = productStockValue(b);
    } else if (column === "cat") {
        va = a.category; vb = b.category;
    } else if (column === "status") {
        const order = { crit: 0, low: 1, ok: 2 };
        va = order[stockStatus(a).state]; vb = order[stockStatus(b).state];
    } else return 0;
    if (va < vb) return direction === "asc" ? -1 : 1;
    if (va > vb) return direction === "asc" ? 1 : -1;
    return 0;
};

// Stock inicial capturado en el wizard de alta:
//  - divide (multi): countQty × dividesCount (ej. 5 cajas × 100 = 500 piezas)
//  - simple: countQty
export const computeInitialStock = (divides, countQty, dividesCount) => {
    const qty = Number(countQty) || 0;
    return divides ? qty * (Number(dividesCount) || 0) : qty;
};

// Redondeo entero para display (no afecta el valor persistido).
export const fmt = (n) => Math.round(parseFloat(n ?? 0) || 0);

// Formato de moneda sin decimales (MXN/locale del navegador por defecto).
export const fmtCur = (n, locale = navigator.language) =>
    (parseFloat(n ?? 0) || 0).toLocaleString(locale, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
