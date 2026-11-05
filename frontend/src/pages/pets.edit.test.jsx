/**
 * Edición de mascotas: la pantalla envía PATCH con el public_id, usando el módulo
 * real `api/pets`. Solo se sustituye el cliente HTTP. El cuerpo es el mismo que
 * acepta `backend/apps/patients/tests/test_partial_update_permission.py`.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const patch = vi.fn();
vi.mock("../api/client", () => ({ default: { get: (...a) => get(...a), patch: (...a) => patch(...a) } }));
vi.mock("../api/medicalRecords", () => ({ getMedicalRecords: vi.fn(() => Promise.resolve([])) }));
vi.mock("../api/appointments", () => ({ getAppointments: vi.fn(() => Promise.resolve([])) }));
vi.mock("../api/statusBreakdown", () => ({ getStatusBreakdown: vi.fn(() => Promise.resolve({ totals: {} })) }));
// Permisos de un VET relevantes para esta pantalla.
const VET = new Set(["patient.list", "patient.retrieve", "patient.update", "owner.update"]);
const can = (code) => VET.has(code);
vi.mock("../auth/authContext", () => ({ useAuth: () => ({ token: "tok", initializing: false, can }) }));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock("react-router-dom", () => ({
    useNavigate: () => vi.fn(),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
    useLocation: () => ({ state: null, pathname: "/pets", search: "" }),
}));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }) }));

import { toast } from "sonner";
import Pets from "./pets";

const PET = {
    public_id: "pet-uuid",
    id: 7,
    name: "Luna",
    species: "canino",
    breed: "",
    birth_date: "2020-01-01",
    sex: "unknown",
    color: "",
    is_active: true,
    owner: { name: "Ana", phone: "5512345678" },
};

beforeEach(() => {
    vi.clearAllMocks();
    get.mockImplementation((url) => Promise.resolve({
        data: url === "pets/stats/"
            ? { total: 1, caninos: 1, felinos: 0 }
            : { count: 1, next: null, previous: null, results: [PET] },
    }));
    patch.mockResolvedValue({ data: PET });
});

async function editAndSave() {
    const user = userEvent.setup({ delay: null });
    render(<Pets />);
    await screen.findByText("Luna");
    await user.click(screen.getByRole("button", { name: /editar/i }));
    const name = await screen.findByDisplayValue("Luna");
    await user.clear(name);
    await user.type(name, "Luna Editada");
    await user.click(screen.getByRole("button", { name: /guardar/i }));
}

describe("Mascotas: editar", () => {
    it("un VET guarda con PATCH sobre el public_id", async () => {
        await editAndSave();

        await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
        const [url, body] = patch.mock.calls[0];
        expect(url).toBe("pets/pet-uuid/");
        expect(body).toEqual({
            name: "Luna Editada",
            species: "canino",
            breed: "",
            birth_date: "2020-01-01",
            sex: "unknown",
            color: "",
            owner: { name: "Ana", phone: "5512345678" },
        });
        await waitFor(() => expect(toast.success).toHaveBeenCalled());
    }, 15000);

    it("un 403 no se presenta como guardado", async () => {
        patch.mockRejectedValue({ response: { status: 403, data: { code: "permission_denied", message: "Sin permiso" } } });

        await editAndSave();

        await waitFor(() => expect(patch).toHaveBeenCalled());
        await screen.findByRole("button", { name: /guardar cambios/i });
        expect(toast.success).not.toHaveBeenCalled();
    }, 15000);
});
