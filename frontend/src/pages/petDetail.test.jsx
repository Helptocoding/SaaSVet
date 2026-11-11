import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import PetDetail from "./petDetail";

vi.mock("../api/pets", () => ({
    getPet: vi.fn().mockResolvedValue({
        name: "Luna",
        species: "Perro",
        birth_date: "2020-01-01",
        owner_name: "Ana",
        public_id: "abc",
    }),
}));
vi.mock("../api/medicalRecords", () => ({
    getMedicalRecords: vi.fn().mockResolvedValue([]),
    getMedicalRecord: vi.fn(),
}));
vi.mock("../api/client", () => ({
    default: {
        get: vi.fn().mockResolvedValue({
            data: [
                { id: 1, date: "2026-11-01", status: "confirmed" },
                { id: 2, date: "2026-11-02", status: "in_progress" },
                { id: 3, date: "2026-11-03", status: "no_show" },
            ],
        }),
    },
}));
vi.mock("../auth/authContext", () => ({
    useAuth: () => ({ token: "t", user: { id: 1 }, initializing: false }),
}));
vi.mock("../components/ImportedDataSection", () => ({ default: () => null }));

describe("petDetail — estados de cita", () => {
    it("muestra etiqueta para confirmed, in_progress y no_show", async () => {
        render(
            <MemoryRouter initialEntries={["/pets/abc"]}>
                <Routes>
                    <Route path="/pets/:id" element={<PetDetail />} />
                </Routes>
            </MemoryRouter>
        );
        const tab = await screen.findByRole("button", { name: /^Citas/ });
        await userEvent.click(tab);
        expect(screen.getByText("Confirmada")).toBeInTheDocument();
        expect(screen.getByText("En consulta")).toBeInTheDocument();
        expect(screen.getByText("No se presentó")).toBeInTheDocument();
    });
});
