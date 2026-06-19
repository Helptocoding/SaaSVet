/**
 * PrescriptionForm — selector de mascota = EntitySearch (búsqueda server-side,
 * render rico, "ver más"); selector de medicamento = SearchSelect.
 *
 * Guard de regresión: ff68196 migró el picker de mascota a EntitySearch y quitó
 * `import SearchSelect`, pero el picker de medicamento seguía usándolo → abrir el
 * form crasheaba (ReferenceError). Este render prueba que ambos pickers montan.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

const searchPets = vi.fn();
vi.mock("../../api/lookups", () => ({ searchPets: (...a) => searchPets(...a) }));
vi.mock("../../api/inventory", () => ({ getPresentations: vi.fn(() => Promise.resolve([])) }));
vi.mock("sonner", () => ({
    toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
}));

import PrescriptionForm from "./PrescriptionForm";

const pet = {
    id: 42, public_id: "pet-42", name: "Bella", species: "perro",
    owner: { name: "Luis Pérez", phone: "8120000000" }, legacy_id: "102",
};

const baseProps = () => ({
    title: "Nueva Receta",
    initialValue: { medical_record: "", pet: "", notes: "", items: [] },
    pets: [],
    medicalRecordsForPet: [],
    submitLabel: "Crear Receta",
    onPetChange: vi.fn(),
    onSubmit: vi.fn(),
    onCancel: vi.fn(),
});

beforeEach(() => {
    searchPets.mockReset();
    searchPets.mockResolvedValue({ items: [pet], hasMore: false });
});

describe("PrescriptionForm", () => {
    it("monta ambos pickers sin crashear (regresión SearchSelect)", () => {
        render(<PrescriptionForm {...baseProps()} />);
        expect(screen.getByPlaceholderText(/Buscar mascota/i)).toBeInTheDocument();
        expect(screen.getByPlaceholderText(/Buscar medicamento/i)).toBeInTheDocument();
    });

    it("seleccionar mascota fija el PK (body FK) y notifica onPetChange", async () => {
        const user = userEvent.setup();
        const props = baseProps();
        render(<PrescriptionForm {...props} />);

        const input = screen.getByPlaceholderText(/Buscar mascota/i);
        await user.type(input, "Bella");

        // Búsqueda server-side (no lista completa en memoria).
        await waitFor(() => expect(searchPets).toHaveBeenCalled());
        const option = await screen.findByText(/Bella · perro/);
        await user.click(option);

        // form.pet = PK (no public_id) — contrato body FK (ADR p18).
        await waitFor(() => expect(props.onPetChange).toHaveBeenCalledWith(42));
        expect(input).toHaveValue("Bella — Luis Pérez");
    });
});
