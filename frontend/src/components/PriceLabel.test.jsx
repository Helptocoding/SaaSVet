import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PriceLabel from "./PriceLabel";

describe("PriceLabel (ADR p70 D4)", () => {
    it("rotula el precio capturado como sin IVA y muestra el total que entrega el backend", () => {
        render(<PriceLabel base="500.00" withTax="580.00" />);
        expect(screen.getByText("$500.00")).toBeInTheDocument();
        expect(screen.getByText("sin IVA")).toBeInTheDocument();
        expect(screen.getByText("$580.00")).toBeInTheDocument();
        expect(screen.getByText("con IVA")).toBeInTheDocument();
    });

    it("sin precio con IVA del backend no lo calcula: solo muestra el base", () => {
        render(<PriceLabel base="500.00" />);
        expect(screen.getByText("$500.00")).toBeInTheDocument();
        expect(screen.getByText("sin IVA")).toBeInTheDocument();
        expect(screen.queryByText("con IVA")).not.toBeInTheDocument();
        expect(screen.queryByText("$580.00")).not.toBeInTheDocument();
    });
});
