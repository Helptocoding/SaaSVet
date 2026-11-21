import { describe, it, expect } from "vitest";
import {
  productStockQty,
  productStockValue,
  compareInventoryProducts,
  stockStatus,
  matchesStockFilter,
  computeInitialStock,
  fmt,
  fmtCur,
} from "./inventory";

describe("orden de inventario según las columnas mostradas", () => {
  const a = { name: "A", stock_quantity: 12, presentation: { stock: 12, conversion_factor: 12, sale_price: 120 } };
  const b = { name: "B", stock_quantity: 6, presentation: { stock: 6, conversion_factor: 1, sale_price: 50 } };
  const sort = (items, column, dir) => [...items].sort((x, y) => compareInventoryProducts(x, y, column, dir)).map(p => p.name);

  it("ordena valores mostrados incluso con sombra divergente", () => {
    expect([productStockValue(a), productStockValue(b)]).toEqual([120, 300]);
    expect(sort([b, a], "value", "asc")).toEqual(["A", "B"]);
    expect(sort([a, b], "value", "desc")).toEqual(["B", "A"]);
    expect(sort([a, b], "stock", "asc")).toEqual(["B", "A"]);
    expect(sort([b, a], "stock", "desc")).toEqual(["A", "B"]);
  });

  it("con sombras coherentes, cero, datos ausentes y empates mantiene el orden", () => {
    const coherent = { ...a, presentation: { ...a.presentation, stock: 1 } };
    const zero = { name: "C", stock_quantity: 0, presentation: { stock: 99, sale_price: 9 } };
    const missing = { name: "D" };
    expect(sort([b, coherent, zero, missing], "value", "asc")).toEqual(["C", "D", "A", "B"]);
    expect(sort([b, coherent, zero, missing], "value", "desc")).toEqual(["B", "A", "C", "D"]);
    expect(sort([b, coherent, zero, missing], "stock", "asc")).toEqual(["C", "D", "B", "A"]);
  });
});

// Lógica derivada de inventario (extraída de pages/inventory.jsx, P1-4 B3).
// Protege que un cambio visual en la página no rompa el cálculo de stock/valor.
// Estos tests documentan el COMPORTAMIENTO ACTUAL — no introducen reglas nuevas.

describe("productStockQty — cantidad de stock en unidades base", () => {
  it("usa stock_quantity cuando está presente", () => {
    expect(productStockQty({ stock_quantity: 7 })).toBe(7);
  });

  it("cae a presentation.stock si no hay stock_quantity", () => {
    expect(productStockQty({ presentation: { stock: 4 } })).toBe(4);
  });

  it("stock_quantity tiene prioridad sobre presentation.stock", () => {
    expect(productStockQty({ stock_quantity: 5, presentation: { stock: 99 } })).toBe(5);
  });

  it("producto sin datos → 0", () => {
    expect(productStockQty({})).toBe(0);
  });

  it("null/undefined de la API → 0 (no NaN, no crash)", () => {
    expect(productStockQty({ stock_quantity: null, presentation: { stock: null } })).toBe(0);
    expect(productStockQty({ stock_quantity: undefined })).toBe(0);
  });

  it("string numérico de la API se parsea", () => {
    expect(productStockQty({ stock_quantity: "12" })).toBe(12);
  });

  it("stock negativo se conserva (el sistema lo permite en este cálculo)", () => {
    expect(productStockQty({ stock_quantity: -2 })).toBe(-2);
  });
});

describe("productStockValue — valor $ = sale_price / conversion_factor × qty", () => {
  it("cf=1: valor = precio × cantidad", () => {
    expect(
      productStockValue({ stock_quantity: 10, presentation: { sale_price: 50, conversion_factor: 1 } })
    ).toBe(500);
  });

  it("cf>1: normaliza el precio a unidad base antes de multiplicar", () => {
    expect(
      productStockValue({ stock_quantity: 10, presentation: { sale_price: 100, conversion_factor: 2 } })
    ).toBe(500);
  });

  it("sin presentación → 0 (precio 0)", () => {
    expect(productStockValue({ stock_quantity: 10 })).toBe(0);
  });

  it("producto vacío → 0", () => {
    expect(productStockValue({})).toBe(0);
  });

  it("conversion_factor ausente → cf=1 por defecto", () => {
    expect(productStockValue({ stock_quantity: 2, presentation: { sale_price: "25.5" } })).toBe(51);
  });

  it("conversion_factor 0 → se protege a 1 (no divide por cero)", () => {
    expect(
      productStockValue({ stock_quantity: 5, presentation: { sale_price: 10, conversion_factor: 0 } })
    ).toBe(50);
  });
});

describe("stockStatus — estado para la UI (agotado/bajo/normal)", () => {
  it("stock normal sin mínimo → 'Normal' (ok)", () => {
    const r = stockStatus({ presentation: { stock: 50 } });
    expect(r.state).toBe("ok");
    expect(r.label).toBe("Normal");
  });

  it("stock cero → 'Agotado' (crit), pct 0", () => {
    const r = stockStatus({ stock_quantity: 0 });
    expect(r).toEqual({ pct: 0, state: "crit", label: "Agotado" });
  });

  it("stock negativo → 'Agotado' (crit)", () => {
    expect(stockStatus({ stock_quantity: -3 }).state).toBe("crit");
  });

  it("stock por debajo del mínimo → 'Stock bajo' (low) con pct proporcional", () => {
    const r = stockStatus({ stock_quantity: 5, min_stock: 10 });
    expect(r.state).toBe("low");
    expect(r.label).toBe("Stock bajo");
    expect(r.pct).toBe(50);
  });

  it("stock exactamente igual al mínimo → 'Normal' (la regla es estrictamente <)", () => {
    expect(stockStatus({ stock_quantity: 10, min_stock: 10 }).state).toBe("ok");
  });

  it("min_stock puede venir en la presentación", () => {
    expect(stockStatus({ presentation: { stock: 5, min_stock: 10 } }).state).toBe("low");
  });

  it("producto sin configuración completa (vacío) → 'Agotado' (stock 0)", () => {
    expect(stockStatus({}).state).toBe("crit");
  });

  it("presentation null → no crashea, stock 0 → 'Agotado'", () => {
    expect(stockStatus({ presentation: null }).state).toBe("crit");
  });

  it("pct nunca baja de 15 en estado ok (visibilidad mínima de la barra)", () => {
    // stock 3, min 0 → top 100 → 3% → se eleva a 15
    expect(stockStatus({ stock_quantity: 3 }).pct).toBe(15);
  });
});

describe("computeInitialStock — stock inicial del wizard de alta", () => {
  it("modo simple (no divide): devuelve la cantidad contada", () => {
    expect(computeInitialStock(false, "5", "")).toBe(5);
  });

  it("modo multi (divide): cantidad × sub-unidades (5 cajas × 100 = 500)", () => {
    expect(computeInitialStock(true, "5", "100")).toBe(500);
  });

  it("multi sin dividesCount → 0 (5 × 0)", () => {
    expect(computeInitialStock(true, "5", "")).toBe(0);
  });

  it("cantidad vacía → 0", () => {
    expect(computeInitialStock(false, "", "")).toBe(0);
  });

  it("acepta números y decimales", () => {
    expect(computeInitialStock(true, 2.5, 4)).toBe(10);
  });
});

describe("fmt — redondeo entero para display", () => {
  it("redondea al entero más cercano", () => {
    expect(fmt(3.7)).toBe(4);
    expect(fmt(3.2)).toBe(3);
  });

  it("null/undefined/no-numérico → 0", () => {
    expect(fmt(null)).toBe(0);
    expect(fmt(undefined)).toBe(0);
    expect(fmt("abc")).toBe(0);
  });

  it("parsea strings numéricos", () => {
    expect(fmt("5.6")).toBe(6);
  });
});

describe("fmtCur — moneda sin decimales", () => {
  it("formatea miles con separador (locale explícito para estabilidad)", () => {
    expect(fmtCur(1234, "en-US")).toBe("1,234");
    expect(fmtCur(1000000, "en-US")).toBe("1,000,000");
  });

  it("null/0 → '0'", () => {
    expect(fmtCur(0, "en-US")).toBe("0");
    expect(fmtCur(null, "en-US")).toBe("0");
  });

  it("negativos se formatean", () => {
    expect(fmtCur(-50, "en-US")).toBe("-50");
  });
});

describe("matchesStockFilter — misma regla para filtros e indicadores", () => {
  const agotado = { stock_quantity: 0, min_stock: 5 };
  const bajo = { stock_quantity: 2, min_stock: 5 };
  const enMinimo = { stock_quantity: 10, min_stock: 10 };
  const inactivoAgotado = { stock_quantity: 0, min_stock: 5, is_active: false };

  it("sin filtro deja pasar todo, incluidos los inactivos", () => {
    expect([agotado, bajo, enMinimo, inactivoAgotado].every(p => matchesStockFilter(p, ""))).toBe(true);
  });

  it("bajo stock y agotado son disjuntos: el agotado no cuenta como bajo", () => {
    expect(matchesStockFilter(agotado, "low")).toBe(false);
    expect(matchesStockFilter(agotado, "crit")).toBe(true);
    expect(matchesStockFilter(bajo, "low")).toBe(true);
    expect(matchesStockFilter(bajo, "crit")).toBe(false);
  });

  it("'requieren atención' = bajo + agotado; en el mínimo exacto no requiere atención", () => {
    expect(matchesStockFilter(agotado, "attention")).toBe(true);
    expect(matchesStockFilter(bajo, "attention")).toBe(true);
    expect(matchesStockFilter(enMinimo, "attention")).toBe(false);
    expect(matchesStockFilter(enMinimo, "ok")).toBe(true);
  });

  it("un producto desactivado no genera alertas de stock", () => {
    expect(matchesStockFilter(inactivoAgotado, "crit")).toBe(false);
    expect(matchesStockFilter(inactivoAgotado, "attention")).toBe(false);
  });
});
