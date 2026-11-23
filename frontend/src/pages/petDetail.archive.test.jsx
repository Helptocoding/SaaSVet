// Plan UX D13: «Archivar cliente» salió de cada tarjeta de mascota (una acción
// destructiva repetida 25 veces por página) y vive en la ficha, junto a los
// datos del cliente, con confirmación.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const archiveOwner = vi.fn();
const confirmMock = vi.fn();
let perms = new Set(["owner.destroy"]);

vi.mock("../api/pets", () => ({
    getPet: vi.fn().mockResolvedValue({
        name: "Luna",
        species: "Perro",
        birth_date: "2020-01-01",
        public_id: "abc",
        is_active: true,
        owner: { public_id: "own-1", name: "Ana", phone: "5512345678", is_generic: false },
    }),
    archiveOwner: (...a) => archiveOwner(...a),
}));
vi.mock("../api/medicalRecords", () => ({
    getMedicalRecords: vi.fn().mockResolvedValue([]),
    getMedicalRecord: vi.fn(),
}));
vi.mock("../api/client", () => ({ default: { get: vi.fn().mockResolvedValue({ data: [] }) } }));
vi.mock("../auth/authContext", () => ({
    useAuth: () => ({ token: "t", user: { id: 1 }, initializing: false, can: (c) => perms.has(c) }),
}));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => confirmMock }));
vi.mock("../components/ImportedDataSection", () => ({ default: () => null }));
vi.mock("sonner", () => ({
    toast: Object.assign(vi.fn(), { promise: (p) => p, error: vi.fn(), success: vi.fn() }),
}));

import PetDetail from "./petDetail";

const renderDetail = () => render(
    <MemoryRouter initialEntries={["/pets/abc"]}>
        <Routes>
            <Route path="/pets/:id" element={<PetDetail />} />
            <Route path="/pets" element={<p>Lista de mascotas</p>} />
        </Routes>
    </MemoryRouter>
);

beforeEach(() => {
    archiveOwner.mockReset().mockResolvedValue({ is_active: false });
    confirmMock.mockReset().mockResolvedValue(true);
    perms = new Set(["owner.destroy"]);
});

describe("petDetail — archivar cliente (D13)", () => {
    it("confirma, archiva al cliente y vuelve a la lista", async () => {
        renderDetail();
        await userEvent.click(await screen.findByRole("button", { name: "Archivar cliente" }));
        expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ dangerMode: true }));
        await waitFor(() => expect(archiveOwner).toHaveBeenCalledWith("own-1"));
        expect(await screen.findByText("Lista de mascotas")).toBeInTheDocument();
    });

    it("si no se confirma no archiva", async () => {
        confirmMock.mockResolvedValue(false);
        renderDetail();
        await userEvent.click(await screen.findByRole("button", { name: "Archivar cliente" }));
        expect(archiveOwner).not.toHaveBeenCalled();
    });

    it("sin el permiso no aparece", async () => {
        perms = new Set();
        renderDetail();
        await screen.findByText("Ana");
        expect(screen.queryByRole("button", { name: "Archivar cliente" })).toBeNull();
    });
});
