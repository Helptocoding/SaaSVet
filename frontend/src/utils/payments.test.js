import { describe, it, expect } from "vitest";
import { buildPaymentLines, paymentLinesValid, PAYMENT_METHODS } from "./payments";

// Reglas de dinero (ADR p30 rev): toda factura se cobra por el TOTAL EXACTO.
// No hay pagos parciales en cobros nuevos. El sobrepago en efectivo es "cambio":
// se muestra en UI pero NUNCA se persiste (se registra solo el total).
// Estas pruebas blindan esa regla — si alguien cambia la matemática del cobro,
// fallan antes del merge.

describe("buildPaymentLines — líneas a enviar al backend (ADR p30)", () => {
  it("pago exacto con un método → una línea normalizada a 2 decimales", () => {
    expect(buildPaymentLines([{ method: "cash", amount: "100" }], 100)).toEqual([
      { method: "cash", amount: "100.00" },
    ]);
  });

  it("múltiples métodos que suman el total → se conservan todas las líneas", () => {
    expect(
      buildPaymentLines([{ method: "cash", amount: "60" }, { method: "card", amount: "40" }], 100)
    ).toEqual([
      { method: "cash", amount: "60.00" },
      { method: "card", amount: "40.00" },
    ]);
  });

  it("sobrepago en efectivo → registra SOLO el total (el cambio no se persiste)", () => {
    expect(buildPaymentLines([{ method: "cash", amount: "150" }], 100)).toEqual([
      { method: "cash", amount: "100.00" },
    ]);
  });

  it("sobrepago con varias líneas → colapsa al total con el método de la primera línea", () => {
    expect(
      buildPaymentLines([{ method: "cash", amount: "80" }, { method: "card", amount: "80" }], 100)
    ).toEqual([{ method: "cash", amount: "100.00" }]);
  });

  it("líneas en cero se descartan (no se mandan al backend)", () => {
    expect(
      buildPaymentLines([{ method: "cash", amount: "100" }, { method: "card", amount: "0" }], 100)
    ).toEqual([{ method: "cash", amount: "100.00" }]);
  });

  it("normaliza montos string con un decimal a dos decimales", () => {
    expect(buildPaymentLines([{ method: "transfer", amount: "50.5" }], 50.5)).toEqual([
      { method: "transfer", amount: "50.50" },
    ]);
  });

  it("redondea a 2 decimales sin disparar la rama de sobrepago por ruido flotante", () => {
    // 33.333 redondea a 33.33 = target → NO es sobrepago, se conserva la línea.
    expect(buildPaymentLines([{ method: "cash", amount: "33.333" }], 33.33)).toEqual([
      { method: "cash", amount: "33.33" },
    ]);
  });
});

describe("paymentLinesValid — habilita/bloquea el botón de cobrar", () => {
  it("total exacto sin parciales → válido", () => {
    expect(paymentLinesValid([{ method: "cash", amount: "100" }], 100, false)).toBe(true);
  });

  it("pago insuficiente sin permitir parcial → inválido (ADR p30: sin parciales)", () => {
    expect(paymentLinesValid([{ method: "cash", amount: "50" }], 100, false)).toBe(false);
  });

  it("pago insuficiente permitiendo parcial → válido (refund parcial / casos futuros)", () => {
    expect(paymentLinesValid([{ method: "cash", amount: "50" }], 100, true)).toBe(true);
  });

  it("sobrepago sin permitir cambio → inválido", () => {
    expect(paymentLinesValid([{ method: "cash", amount: "150" }], 100, false, false)).toBe(false);
  });

  it("sobrepago permitiendo cambio (efectivo) → válido", () => {
    expect(paymentLinesValid([{ method: "cash", amount: "150" }], 100, false, true)).toBe(true);
  });

  it("todas las líneas en cero → inválido (no hay monto positivo)", () => {
    expect(paymentLinesValid([{ method: "cash", amount: "0" }], 100, false)).toBe(false);
  });

  it("array de líneas vacío → inválido", () => {
    expect(paymentLinesValid([], 100, false)).toBe(false);
  });

  it("cualquier monto negativo → inválido", () => {
    expect(paymentLinesValid([{ method: "cash", amount: "-10" }], 100, true)).toBe(false);
  });

  it("monto negativo se bloquea ANTES que la rama de cambio (invariante de dinero)", () => {
    // El guard de negativo corre antes que allowChange: una línea negativa nunca
    // pasa, ni siquiera con cambio habilitado (ej. [+200, -100] sumando 100).
    expect(
      paymentLinesValid([{ method: "cash", amount: "200" }, { method: "card", amount: "-100" }], 100, false, true)
    ).toBe(false);
  });

  it("split de varios métodos que suma exacto → válido", () => {
    expect(
      paymentLinesValid([{ method: "cash", amount: "60" }, { method: "card", amount: "40" }], 100, false)
    ).toBe(true);
  });

  it("líneas positivas + ceros que suman exacto → válido (los ceros se ignoran)", () => {
    expect(
      paymentLinesValid([{ method: "cash", amount: "100" }, { method: "card", amount: "0" }], 100, false)
    ).toBe(true);
  });
});

describe("PAYMENT_METHODS — catálogo (espejo del backend)", () => {
  it("expone los 4 métodos contables conocidos", () => {
    expect(PAYMENT_METHODS.map((m) => m.value)).toEqual(["cash", "card", "transfer", "other"]);
  });
});
