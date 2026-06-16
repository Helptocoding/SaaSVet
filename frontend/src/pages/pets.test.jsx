/**
 * Mascotas — la lista NO depende de recibir todas las filas: consume el envelope
 * paginado del backend ({count, results}), navega páginas server-side y manda la
 * búsqueda a la API (debounced). Protege el rediseño de escalabilidad.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ── Mocks de side-effects y dependencias externas (no lógica de negocio) ──
const getPets = vi.fn();
const getPetStats = vi.fn();
vi.mock("../api/pets", () => ({
    getPets: (...a) => getPets(...a),
    getPetStats: (...a) => getPetStats(...a),
    createPet: vi.fn(),
    updatePet: vi.fn(),
    deletePet: vi.fn(),
}));
vi.mock("../api/medicalRecords", () => ({ getMedicalRecords: vi.fn(() => Promise.resolve([])) }));
vi.mock("../api/appointments", () => ({ getAppointments: vi.fn(() => Promise.resolve([])) }));
vi.mock("../api/statusBreakdown", () => ({ getStatusBreakdown: vi.fn(() => Promise.resolve({ totals: {} })) }));
vi.mock("../auth/authContext", () => ({ useAuth: () => ({ token: "tok", initializing: false }) }));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }));
vi.mock("sonner", () => ({
    toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }),
}));

import Pets from "./pets";

const PAGE_SIZE = 25;

const makeRows = (page, n) =>
    Array.from({ length: n }, (_, i) => ({
        public_id: `pid-${page}-${i}`,
        id: page * 100 + i,
        name: `Mascota ${page}-${i}`,
        species: "canino",
        breed: "",
        birth_date: null,
        sex: "unknown",
        color: "",
        owner: { name: "Dueño X", phone: "5551234567" },
    }));

const envelope = (page, count) => {
    const rows = page === 1 ? makeRows(1, 25) : makeRows(2, Math.min(25, count - 25));
    return {
        count,
        next: page * PAGE_SIZE < count ? "http://x/?page=" + (page + 1) : null,
        previous: page > 1 ? "http://x/?page=" + (page - 1) : null,
        results: rows,
    };
};

beforeEach(() => {
    getPets.mockReset();
    getPetStats.mockReset();
    getPets.mockImplementation((params = {}) => Promise.resolve(envelope(params.page || 1, 60)));
    getPetStats.mockResolvedValue({ total: 60, caninos: 60, felinos: 0 });
});

describe("Mascotas — lista paginada server-side", () => {
    it("renderiza desde el envelope paginado y pide la página 1 (no toda la lista)", async () => {
        render(<Pets />);

        await screen.findByText("Mascota 1-0");
        // Pidió paginación explícita, no un volcado completo.
        expect(getPets).toHaveBeenCalledWith(
            expect.objectContaining({ page: 1, page_size: PAGE_SIZE })
        );
        // Stats (toda la clínica) alimentan el subtítulo + cards, no el length local.
        expect(getPetStats).toHaveBeenCalled();
        expect(screen.getByText(/60 registradas/)).toBeInTheDocument();
        expect(screen.getByText(/Mostrando 1–25 de 60/)).toBeInTheDocument();
    });

    it("cambia de página llamando a la API con page=2", async () => {
        const user = userEvent.setup();
        render(<Pets />);
        await screen.findByText("Mascota 1-0");

        await user.click(screen.getByRole("button", { name: /siguiente/i }));

        await waitFor(() =>
            expect(getPets).toHaveBeenCalledWith(expect.objectContaining({ page: 2 }))
        );
        await screen.findByText("Mascota 2-0");
    });

    it("la búsqueda se envía al backend (debounced), no se filtra en memoria", async () => {
        const user = userEvent.setup();
        render(<Pets />);
        await screen.findByText("Mascota 1-0");

        await user.type(screen.getByPlaceholderText(/Nombre, raza, especie/), "max");

        await waitFor(
            () =>
                expect(getPets).toHaveBeenCalledWith(
                    expect.objectContaining({ search: "max", page: 1 })
                ),
            { timeout: 1500 }
        );
    });
});
