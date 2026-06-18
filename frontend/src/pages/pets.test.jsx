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
const createPet = vi.fn();
vi.mock("../api/pets", () => ({
    getPets: (...a) => getPets(...a),
    getPetStats: (...a) => getPetStats(...a),
    createPet: (...a) => createPet(...a),
    getPet: vi.fn(() => Promise.resolve({})),
    updatePet: vi.fn(),
    deletePet: vi.fn(),
}));
vi.mock("../api/medicalRecords", () => ({ getMedicalRecords: vi.fn(() => Promise.resolve([])) }));
vi.mock("../api/appointments", () => ({ getAppointments: vi.fn(() => Promise.resolve([])) }));
vi.mock("../api/statusBreakdown", () => ({ getStatusBreakdown: vi.fn(() => Promise.resolve({ totals: {} })) }));
vi.mock("../auth/authContext", () => ({ useAuth: () => ({ token: "tok", initializing: false, can: () => true }) }));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock("react-router-dom", () => ({
    useNavigate: () => vi.fn(),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));
vi.mock("sonner", () => ({
    toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }),
}));

import { toast } from "sonner";
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
    createPet.mockReset();
    getPets.mockImplementation((params = {}) => Promise.resolve(envelope(params.page || 1, 60)));
    getPetStats.mockResolvedValue({ total: 60, caninos: 60, felinos: 0 });
    createPet.mockResolvedValue({ public_id: "new-pet" });
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

describe("Mascotas — alta con datos mínimos", () => {
    // Regla de producto piloto: nombre mascota + nombre/teléfono dueño bastan.
    // Especie y fecha de nacimiento NO bloquean (se completan después).
    it("guarda con datos mínimos: sin especie ni fecha de nacimiento", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Pets />);
        await screen.findByText("Mascota 1-0");

        await user.click(screen.getByRole("button", { name: /nueva mascota/i }));

        await user.type(screen.getByPlaceholderText("Ej: Max"), "Lola");
        await user.type(screen.getByPlaceholderText("Nombre del cliente"), "Ana Soto");
        await user.type(screen.getByPlaceholderText("10 dígitos"), "8112345678");
        // Especie se deja en "Pendiente" ('') y fecha vacía — no se tocan.

        await user.click(screen.getByRole("button", { name: /registrar mascota/i }));

        await waitFor(() => expect(createPet).toHaveBeenCalled());
        const payload = createPet.mock.calls[0][1];
        expect(payload).toMatchObject({ name: "Lola", species: "", birth_date: null });
        expect(payload.owner).toMatchObject({ name: "Ana Soto", phone: "8112345678" });
        // Datos opcionales vacíos no dispararon error.
        expect(toast.error).not.toHaveBeenCalled();
    }, 15000);

    it("el teléfono del dueño sigue siendo obligatorio", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Pets />);
        await screen.findByText("Mascota 1-0");

        await user.click(screen.getByRole("button", { name: /nueva mascota/i }));
        await user.type(screen.getByPlaceholderText("Ej: Max"), "Lola");
        await user.type(screen.getByPlaceholderText("Nombre del cliente"), "Ana Soto");
        // Sin teléfono.
        await user.click(screen.getByRole("button", { name: /registrar mascota/i }));

        await waitFor(() => expect(toast.error).toHaveBeenCalled());
        expect(createPet).not.toHaveBeenCalled();
    }, 15000);
});

describe("Mascotas — empty state guiado", () => {
  it("sin pacientes muestra título guiado + CTAs importar/agregar", async () => {
    getPets.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    getPetStats.mockResolvedValue({ total: 0, caninos: 0, felinos: 0 });

    render(<Pets />);

    expect(
      await screen.findByText("Todavía no tienes pacientes")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /importar excel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /agregar paciente/i })).toBeInTheDocument();
  });

  it("con pacientes NO muestra el empty state", async () => {
    render(<Pets />);
    await screen.findByText("Mascota 1-0");
    expect(screen.queryByText("Todavía no tienes pacientes")).toBeNull();
  });
});
