import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge from "./StatusBadge";

describe("StatusBadge", () => {
    it.each([
        ["scheduled", "Programada", "badge-info"],
        ["confirmed", "Confirmada", "badge-purple"],
        ["in_progress", "En consulta", "badge-warning"],
        ["done", "Completada", "badge-success"],
        ["canceled", "Cancelada", "badge-danger"],
        ["no_show", "No se presentó", "badge-default"],
    ])("muestra %s como %s", (status, label, cls) => {
        render(<StatusBadge status={status} />);
        const el = screen.getByText(label);
        expect(el).toHaveClass("badge", cls);
    });

    it("estado desconocido muestra el valor crudo con badge-default", () => {
        render(<StatusBadge status="algo_raro" />);
        expect(screen.getByText("algo_raro")).toHaveClass("badge-default");
    });
});
