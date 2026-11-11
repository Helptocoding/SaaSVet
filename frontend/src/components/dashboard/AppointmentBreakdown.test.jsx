import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AppointmentBreakdown from "./AppointmentBreakdown";

const props = {
    statusOrder: ["confirmed", "no_show"],
    totals: { confirmed: 2, no_show: 1 },
    byStatus: { confirmed: { items: [] }, no_show: { items: [] } },
};

const renderIt = (extra = {}) =>
    render(
        <MemoryRouter>
            <AppointmentBreakdown {...props} {...extra} />
        </MemoryRouter>
    );

describe("AppointmentBreakdown", () => {
    it("etiqueta cada grupo con statusLabel", () => {
        renderIt();
        expect(screen.getByText("Confirmada (2)")).toBeInTheDocument();
        expect(screen.getByText("No se presentó (1)")).toBeInTheDocument();
    });

    it("el título del estado seleccionado usa la misma etiqueta", () => {
        renderIt({ selectedStatus: "confirmed" });
        const matches = screen.getAllByText("Confirmada (2)");
        expect(matches.length).toBe(2);
        expect(matches[0]).toHaveClass("card-title");
    });
});
