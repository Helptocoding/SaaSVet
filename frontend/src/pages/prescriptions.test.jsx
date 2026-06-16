/**
 * Recetas — la página NO carga la lista completa de mascotas (no escalaba con
 * clínicas importadas de miles de pacientes). Los filtros de especie/sexo/edad
 * salen de los metadatos embebidos en cada receta (pet_species/pet_sex/
 * pet_birth_date) y el selector de mascota se deriva de las recetas cargadas.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getPets = vi.fn();
vi.mock("../api/pets", () => ({ getPets: (...a) => getPets(...a) }));
const getPrescriptions = vi.fn();
vi.mock("../api/prescriptions", () => ({
    getPrescriptions: (...a) => getPrescriptions(...a),
    getPrescription: vi.fn(),
    createPrescription: vi.fn(),
    updatePrescription: vi.fn(),
    deletePrescription: vi.fn(),
    downloadPrescriptionPDF: vi.fn(),
}));
vi.mock("../api/inventory", () => ({ getProducts: vi.fn(() => Promise.resolve([])) }));
vi.mock("../api/medicalRecords", () => ({ getMedicalRecords: vi.fn(() => Promise.resolve([])) }));
vi.mock("../auth/authContext", () => ({
    useAuth: () => ({ token: "tok", user: { role: "ADMIN" }, initializing: false }),
}));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock("../components/prescriptions/PrescriptionForm", () => ({ default: () => null }));
vi.mock("react-router-dom", () => ({
    Link: ({ children }) => <a>{children}</a>,
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));
vi.mock("sonner", () => ({
    toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }),
}));

import Prescriptions from "./prescriptions";

const rows = [
    {
        id: 1, public_id: "rx1", pet_name: "Bella", pet_public_id: "pet1",
        pet_species: "perro", pet_sex: "female", pet_birth_date: "2020-01-01",
        veterinarian_name: "Ana", created_at: "2026-06-01T10:00:00Z",
        items: [{ product_name: "Amoxicilina", quantity: "2", product_unit: "ml" }],
    },
    {
        id: 2, public_id: "rx2", pet_name: "Michi", pet_public_id: "pet2",
        pet_species: "gato", pet_sex: "male", pet_birth_date: "2019-01-01",
        veterinarian_name: "Ana", created_at: "2026-06-02T10:00:00Z",
        items: [{ product_name: "Vitamina", quantity: "1", product_unit: "pz" }],
    },
];

beforeEach(() => {
    getPets.mockReset();
    getPrescriptions.mockReset();
    getPrescriptions.mockResolvedValue(rows);
});

describe("Recetas — sin carga completa de mascotas", () => {
    it("no llama getPets al abrir; los datos vienen de las recetas", async () => {
        render(<Prescriptions />);
        const table = await screen.findByRole("table");
        expect(within(table).getByText("Bella")).toBeInTheDocument();
        expect(getPets).not.toHaveBeenCalled();
        expect(getPrescriptions).toHaveBeenCalled();
    });

    it("el selector de mascota se deriva de las recetas cargadas (no del catálogo)", async () => {
        render(<Prescriptions />);
        await screen.findByRole("table");
        // Solo mascotas CON recetas aparecen como opción.
        expect(screen.getByRole("option", { name: "Bella" })).toBeInTheDocument();
        expect(screen.getByRole("option", { name: "Michi" })).toBeInTheDocument();
    });

    it("filtra por especie desde pet_species embebido (client-side, sin recargar)", async () => {
        const user = userEvent.setup();
        render(<Prescriptions />);
        await screen.findByRole("table");

        await user.click(screen.getByRole("button", { name: /Caninos/i }));

        const table = screen.getByRole("table");
        expect(within(table).getByText("Bella")).toBeInTheDocument();
        expect(within(table).queryByText("Michi")).not.toBeInTheDocument();
        // No hubo segunda llamada al backend por el filtro (es client-side).
        expect(getPrescriptions).toHaveBeenCalledTimes(1);
    });
});
