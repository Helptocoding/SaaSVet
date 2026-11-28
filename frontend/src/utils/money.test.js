import { describe, expect, it } from "vitest";
import { formatMoney, formatTaxRate } from "./money";

const nbsp = (text) => text.replace(/[\u00a0\u202f]/g, " ");

describe("formatMoney (ADR p70 D4)", () => {
    it("da formato de pesos con dos decimales y separador de miles", () => {
        expect(nbsp(formatMoney("580"))).toBe("$580.00");
        expect(nbsp(formatMoney(1234.5))).toBe("$1,234.50");
    });

    it("trata vacío o inválido como cero, sin lanzar", () => {
        expect(nbsp(formatMoney(null))).toBe("$0.00");
        expect(nbsp(formatMoney("abc"))).toBe("$0.00");
    });
});

describe("formatTaxRate", () => {
    it("rotula la tasa como porcentaje", () => {
        expect(formatTaxRate("0.1600")).toBe("16 %");
        expect(formatTaxRate("0.0800")).toBe("8 %");
        expect(formatTaxRate("0.0000")).toBe("0 %");
    });

    it("sin tasa no inventa un valor", () => {
        expect(formatTaxRate(null)).toBeNull();
        expect(formatTaxRate(undefined)).toBeNull();
        expect(formatTaxRate("")).toBeNull();
    });
});
