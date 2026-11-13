/**
 * Equipo: cédula profesional (M01, orden 7). Alta de VET con cédula obligatoria
 * y edición por PATCH /staff/<public_id>/ con solo especialidad y cédula. Se usa
 * el módulo real `api/staff`; solo se sustituye el cliente HTTP.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
vi.mock("../api/client", () => ({
    default: { get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a) },
}));
let granted = new Set(["staff.list", "staff.create", "staff.update", "staff.destroy"]);
const can = (code) => granted.has(code);
// Objeto estable: la página recarga Equipo cuando cambia `user` (useEffect).
const ADMIN = { role: "ADMIN" };
vi.mock("../auth/authContext", () => ({
    useAuth: () => ({ user: ADMIN, initializing: false, can }),
}));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }) }));

import { toast } from "sonner";
import Staff from "./staff";

const VET = {
    id: 3, public_id: "vet-uuid", username: "ana", email: "ana@vet.mx",
    first_name: "Ana", last_name: "Galeno", role: "VET",
    specialty: "Cirugía", license_number: "1234567", is_active: true,
};

beforeEach(() => {
    vi.clearAllMocks();
    granted = new Set(["staff.list", "staff.create", "staff.update", "staff.destroy"]);
    get.mockResolvedValue({ data: [VET] });
    post.mockResolvedValue({ data: VET });
    patch.mockResolvedValue({ data: VET });
});

describe("Equipo: cédula profesional", () => {
    it("muestra la cédula en la tabla", async () => {
        render(<Staff />);
        expect(await screen.findByText("1234567")).toBeInTheDocument();
    });

    it("editar envía PATCH con solo especialidad y cédula sobre el public_id", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /editar/i }));
        const license = screen.getByLabelText(/cédula profesional/i);
        await user.clear(license);
        await user.type(license, " 7654321 ");
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
        expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", {
            specialty: "Cirugía",
            license_number: "7654321",
        });
    });

    it("no guarda a un veterinario sin cédula", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /editar/i }));
        await user.clear(screen.getByLabelText(/cédula profesional/i));
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        expect(patch).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith("La cédula profesional es obligatoria para veterinarios");
    });

    it("el alta de un veterinario exige cédula con formato válido", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        await user.type(screen.getByPlaceholderText("usuario123"), "diego");
        await user.type(screen.getByPlaceholderText("Juan"), "Diego");
        await user.type(screen.getByPlaceholderText("correo@ejemplo.com"), "diego@vet.mx");
        await user.type(screen.getByPlaceholderText("Mínimo 6 caracteres"), "Segura123");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenLastCalledWith("La cédula profesional es obligatoria para veterinarios");

        const license = screen.getByLabelText(/cédula profesional/i);
        await user.type(license, "12a45");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenLastCalledWith("La cédula profesional debe tener solo dígitos, entre 5 y 10");

        await user.clear(license);
        await user.type(license, "2468024");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
        expect(post.mock.calls[0][0]).toBe("staff/create/");
        expect(post.mock.calls[0][1]).toMatchObject({ role: "VET", license_number: "2468024" });
    });

    it("sin staff.update no ofrece editar", async () => {
        granted.delete("staff.update");
        render(<Staff />);
        await screen.findByText("1234567");
        expect(screen.queryByRole("button", { name: /editar/i })).not.toBeInTheDocument();
    });
});
