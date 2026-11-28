/**
 * Historial de cambios de Configuración (ADR p70 D9): lista, vacío, error con
 * reintento y paginación.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getConfigHistory = vi.fn();

vi.mock("../../api/organizations", () => ({ getConfigHistory: (...a) => getConfigHistory(...a) }));
vi.mock("../../auth/authContext", () => ({
    useAuth: () => ({ user: { organization_timezone: "America/Mexico_City" } }),
}));

import HistorySection from "./HistorySection";

const event = (n) => ({
    kind: "clinic_updated",
    kind_label: "Datos de la clínica",
    occurred_at: "2026-11-27T18:00:00Z",
    actor_name: "Ana Pérez",
    subject: {},
    changes: { display_name: [`Antes ${n}`, `Después ${n}`] },
});

beforeEach(() => {
    vi.clearAllMocks();
});

describe("HistorySection", () => {
    it("muestra cada cambio con quién y qué", async () => {
        getConfigHistory.mockResolvedValue({ count: 1, results: [event(1)] });
        render(<HistorySection />);
        expect(await screen.findByText("Editó los datos de la clínica")).toBeInTheDocument();
        expect(screen.getByText(/Ana Pérez/)).toBeInTheDocument();
        expect(screen.getByText("Nombre comercial: Antes 1 → Después 1")).toBeInTheDocument();
    });

    it("sin cambios explica qué aparecerá", async () => {
        getConfigHistory.mockResolvedValue({ count: 0, results: [] });
        render(<HistorySection />);
        expect(await screen.findByText("Todavía no hay cambios registrados")).toBeInTheDocument();
    });

    it("un autor ya eliminado no deja el renglón vacío", async () => {
        getConfigHistory.mockResolvedValue({ count: 1, results: [{ ...event(1), actor_name: null }] });
        render(<HistorySection />);
        expect(await screen.findByText(/Alguien que ya no está en el equipo/)).toBeInTheDocument();
    });

    it("si falla, permite reintentar", async () => {
        const user = userEvent.setup({ delay: null });
        getConfigHistory
            .mockRejectedValueOnce({ response: { status: 500, data: {} } })
            .mockResolvedValueOnce({ count: 1, results: [event(1)] });
        render(<HistorySection />);
        await user.click(await screen.findByRole("button", { name: "Reintentar" }));
        expect(await screen.findByText("Editó los datos de la clínica")).toBeInTheDocument();
        expect(getConfigHistory).toHaveBeenCalledTimes(2);
    });

    it("pagina de 25 en 25", async () => {
        const user = userEvent.setup({ delay: null });
        getConfigHistory.mockImplementation(({ page }) => Promise.resolve({
            count: 30, results: [event(page)],
        }));
        render(<HistorySection />);
        await screen.findByText("Nombre comercial: Antes 1 → Después 1");
        await user.click(screen.getByRole("button", { name: "Página siguiente" }));
        await waitFor(() => expect(getConfigHistory).toHaveBeenLastCalledWith({ page: 2 }));
        expect(await screen.findByText("Nombre comercial: Antes 2 → Después 2")).toBeInTheDocument();
    });
});
