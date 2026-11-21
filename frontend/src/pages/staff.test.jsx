/**
 * Equipo: cédula profesional (M01, orden 7) y plan Equipo (F4–F6): permisos por
 * capacidad, fila propia, identidad (A1), reactivación (A2) y validación de
 * nombres (D4). Se usa el módulo real `api/staff`; solo se sustituye el cliente
 * HTTP.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const del = vi.fn();
vi.mock("../api/client", () => ({
    default: {
        get: (...a) => get(...a),
        post: (...a) => post(...a),
        patch: (...a) => patch(...a),
        delete: (...a) => del(...a),
    },
}));
let granted = new Set(["staff.list", "staff.create", "staff.update", "staff.destroy"]);
const can = (code) => granted.has(code);
// Objeto estable: la página recarga Equipo cuando cambia `user` (useEffect).
const ADMIN = { role: "ADMIN" };
let currentUser = ADMIN;
const refreshUser = vi.fn();
vi.mock("../auth/authContext", () => ({
    useAuth: () => ({ user: currentUser, initializing: false, can, refreshUser }),
}));
const confirmMock = vi.fn(() => Promise.resolve(true));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => (...a) => confirmMock(...a) }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }) }));

import { toast } from "sonner";
import Staff from "./staff";
import { getStaff } from "../api/staff";

const VET = {
    id: 3, public_id: "vet-uuid", username: "ana", email: "ana@vet.mx",
    first_name: "Ana", last_name: "Galeno", role: "VET",
    specialty: "Cirugía", license_number: "1234567", is_active: true,
};

let activeRows = [VET];
let inactiveRows = [];

beforeEach(() => {
    vi.clearAllMocks();
    granted = new Set(["staff.list", "staff.create", "staff.update", "staff.destroy"]);
    currentUser = ADMIN;
    activeRows = [VET];
    inactiveRows = [];
    get.mockImplementation((url) => Promise.resolve({
        data: url.includes("archived=true") ? inactiveRows : activeRows,
    }));
    post.mockResolvedValue({ data: VET });
    patch.mockResolvedValue({ data: VET });
    del.mockResolvedValue({ data: null });
    confirmMock.mockImplementation(() => Promise.resolve(true));
});

describe("Equipo: cédula profesional", () => {
    it("muestra la cédula en la tabla", async () => {
        render(<Staff />);
        expect(await screen.findByText("1234567")).toBeInTheDocument();
    });

    it("editar envía PATCH sobre el public_id con la cédula normalizada", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /editar/i }));
        const license = screen.getByLabelText(/cédula profesional/i);
        await user.clear(license);
        await user.type(license, " 7654321 ");
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
        // Plan Equipo (F5): solo viajan los campos que cambiaron; antes la
        // especialidad viajaba siempre aunque no cambiara.
        expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", {
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
        // Plan Equipo (F4): el placeholder dice 8 caracteres (antes, 6) y las
        // validaciones del cliente se muestran en su campo, no en un toast.
        await user.type(screen.getByPlaceholderText("Mínimo 8 caracteres"), "Segura123");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(screen.getByText("La cédula profesional es obligatoria para veterinarios")).toBeInTheDocument();

        const license = screen.getByLabelText(/cédula profesional/i);
        await user.type(license, "12a45");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(screen.getByText("La cédula profesional debe tener solo dígitos, entre 5 y 10")).toBeInTheDocument();

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

describe("Equipo: permisos por capacidad y fila propia (F4)", () => {
    it("decide por can() y no por rol", async () => {
        currentUser = { role: "VET", id: 99 };
        render(<Staff />);
        await screen.findByText("1234567");
        expect(screen.getByRole("button", { name: /agregar miembro/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /editar a ana galeno/i })).toBeInTheDocument();
    });

    it("un ADMIN sin permisos de gestión no ve acciones", async () => {
        granted = new Set(["staff.list"]);
        render(<Staff />);
        await screen.findByText("1234567");
        expect(screen.queryByRole("button", { name: /agregar miembro/i })).not.toBeInTheDocument();
        expect(screen.queryByRole("columnheader", { name: "Acciones" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /editar|desactivar|restablecer/i })).not.toBeInTheDocument();
    });

    it("la fila propia muestra «Tú» y Editar, pero no Restablecer ni Desactivar", async () => {
        granted.add("staff.reset_password");
        currentUser = { role: "ADMIN", id: VET.id };
        render(<Staff />);
        const row = (await screen.findByText("1234567")).closest("tr");
        expect(within(row).getByText("Tú")).toBeInTheDocument();
        expect(within(row).getByRole("button", { name: /editar/i })).toBeInTheDocument();
        expect(within(row).queryByRole("button", { name: /restablecer/i })).not.toBeInTheDocument();
        expect(within(row).queryByRole("button", { name: /desactivar/i })).not.toBeInTheDocument();
    });

    it("una cuenta protegida de la demo no muestra acciones", async () => {
        granted.add("staff.reset_password");
        activeRows = [{ ...VET, demo_protected: true }];
        render(<Staff />);
        const row = (await screen.findByText("1234567")).closest("tr");
        expect(within(row).queryByRole("button")).not.toBeInTheDocument();
    });

    it("desactivar usa la confirmación nueva y no el icono de basura", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: "Desactivar acceso de Ana Galeno" }));
        expect(confirmMock).toHaveBeenCalledWith({
            title: "Desactivar acceso de Ana Galeno",
            message: "Dejará de poder entrar y se cerrarán sus sesiones. Sus citas, consultas y registros se conservan. Revisa en Citas si tiene citas próximas asignadas. Podrás reactivarlo desde Inactivos.",
            confirmText: "Desactivar acceso",
            dangerMode: true,
        });
        await waitFor(() => expect(del).toHaveBeenCalledWith("staff/vet-uuid/"));
        expect(document.querySelector(".lucide-trash2, .lucide-trash-2")).toBeNull();
    });

    it("el error del alta sin sobre aparece en su campo y el modal sigue abierto", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockRejectedValueOnce({ response: { status: 400, data: { username: ["Ese usuario ya existe."] } } });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        await user.type(screen.getByPlaceholderText("usuario123"), "ana");
        await user.type(screen.getByPlaceholderText("Juan"), "Ana");
        await user.type(screen.getByPlaceholderText("correo@ejemplo.com"), "otra@vet.mx");
        await user.type(screen.getByPlaceholderText("Mínimo 8 caracteres"), "Segura123");
        await user.selectOptions(screen.getByLabelText("ROL *"), "ASSISTANT");
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        expect(await screen.findByText("Ese usuario ya existe.")).toBeInTheDocument();
        expect(screen.getByText("Nuevo Miembro")).toBeInTheDocument();
    });

    it("el texto de la contraseña pide 8 caracteres y ninguno menciona 6", async () => {
        const user = userEvent.setup({ delay: null });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        expect(screen.getByText(/Al menos 8 caracteres, una mayúscula y un número/)).toBeInTheDocument();
        expect(screen.queryByText(/6 caracteres/)).not.toBeInTheDocument();
    });

    it("el modal temporal calcula las horas desde expires_in_seconds", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        post.mockResolvedValueOnce({ data: { temp_password: "Tmp-123", expires_in_seconds: 7200 } });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /restablecer la contraseña de ana galeno/i }));
        const dialog = await screen.findByRole("dialog", { name: "Contraseña temporal generada" });
        expect(within(dialog).getByText("Tmp-123")).toBeInTheDocument();
        expect(within(dialog).getByText("2 horas para iniciar sesión")).toBeInTheDocument();
    });
});

// Tabla de ejemplos de nombres (D4). Copia literal de
// backend/apps/users/tests/test_staff_profile_edit.py (NAME_EXAMPLES).
const NAME_EXAMPLES = [
    ["María José", true, "María José"],
    ["Argüelles", true, "Argüelles"],
    ["María-José", true, "María-José"],
    ["O'Brien", true, "O'Brien"],
    ["D’Angelo", true, "D’Angelo"],
    ["de la Cruz", true, "de la Cruz"],
    ["Zoë", true, "Zoë"],
    ["Łukasz", true, "Łukasz"],
    ["José", true, "José"],
    ["  Ana  ", true, "Ana"],
    ["Ana  Luz", true, "Ana  Luz"],
    ["Juan2", false, null],
    ["Ana 😀", false, null],
    ["Аna", false, null],
    ["Ana_Luz", false, null],
    ["Ma. José", false, null],
];

describe("Equipo: edición de identidad (F5)", () => {
    it("envía solo lo que cambió, avisa del correo y refresca la sesión propia", async () => {
        const user = userEvent.setup({ delay: null });
        currentUser = { role: "ADMIN", id: VET.id };
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /editar/i }));
        expect(screen.getByRole("button", { name: /guardar/i })).toBeDisabled();

        const email = screen.getByLabelText(/correo electrónico/i);
        await user.clear(email);
        await user.type(email, "ana.nueva@vet.mx");
        expect(screen.getByText(/Es su acceso al sistema/)).toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", { email: "ana.nueva@vet.mx" }));
        await waitFor(() => expect(refreshUser).toHaveBeenCalled());
    });

    it("el error del PATCH con sobre aparece en su campo", async () => {
        const user = userEvent.setup({ delay: null });
        patch.mockRejectedValueOnce({
            response: { status: 400, data: { code: "validation_error", errors: { email: ["Este correo no está disponible."] } } },
        });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /editar/i }));
        const email = screen.getByLabelText(/correo electrónico/i);
        await user.clear(email);
        await user.type(email, "ocupado@vet.mx");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        expect(await screen.findByText("Este correo no está disponible.")).toBeInTheDocument();
        expect(screen.getByText("Editar miembro")).toBeInTheDocument();
    });

    it("valida los nombres igual que el backend", async () => {
        const user = userEvent.setup({ delay: null });
        activeRows = [{ ...VET, first_name: "Zed" }];
        render(<Staff />);
        await screen.findByText("1234567");
        for (const [value, accepted, stored] of NAME_EXAMPLES) {
            patch.mockClear();
            toast.error.mockClear();
            await user.click(screen.getByRole("button", { name: /editar/i }));
            const first = screen.getByLabelText(/^nombre/i);
            await user.clear(first);
            await user.type(first, value);
            await user.click(screen.getByRole("button", { name: /guardar/i }));
            if (accepted) {
                await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", { first_name: stored }));
                await waitFor(() => expect(screen.queryByText("Editar miembro")).not.toBeInTheDocument());
            } else {
                expect(patch, value).not.toHaveBeenCalled();
                expect(toast.error).toHaveBeenCalledWith(
                    "El nombre solo puede contener letras, espacios, guiones y apóstrofos.",
                );
                await user.click(screen.getByRole("button", { name: /cancelar/i }));
            }
        }
    }, 30000); // 16 casos con escritura real: holgura para la suite completa
});

describe("Equipo: inactivos y reactivación (F6)", () => {
    const FORMER = {
        ...VET, id: 7, public_id: "former-uuid", username: "luis", first_name: "Luis",
        last_name: "Pardo", role: "ASSISTANT", license_number: "", specialty: "", is_active: false,
    };

    it("sin staff.reactivate no hay segmento Inactivos", async () => {
        render(<Staff />);
        await screen.findByText("1234567");
        expect(screen.queryByRole("button", { name: "Inactivos" })).not.toBeInTheDocument();
        expect(get).toHaveBeenCalledTimes(1);
    });

    it("reactiva, muestra la temporal y recarga ambas listas", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reactivate");
        inactiveRows = [FORMER];
        post.mockResolvedValueOnce({
            data: { temp_password: "Tmp-9", expires_in_seconds: 86400, member: { ...FORMER, is_active: true } },
        });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: "Inactivos" }));
        await user.click(screen.getByRole("button", { name: "Reactivar acceso de Luis Pardo" }));

        expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
            title: "Reactivar acceso de Luis Pardo",
            message: "Conservará su rol (Asistente) y su historial. Se generará una contraseña temporal válida por 24 h que deberá cambiar al entrar.",
            confirmText: "Reactivar acceso",
        }));
        await waitFor(() => expect(post.mock.calls[0][0]).toBe("staff/former-uuid/reactivate/"));
        const dialog = await screen.findByRole("dialog", { name: "Contraseña temporal generada" });
        expect(within(dialog).getByText("Tmp-9")).toBeInTheDocument();
        expect(within(dialog).getByText("24 horas para iniciar sesión")).toBeInTheDocument();
        await waitFor(() => expect(get.mock.calls.filter(([u]) => u.includes("archived=true")).length).toBe(2));
    });

    it("409 already_active indica restablecer y recarga", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reactivate");
        inactiveRows = [FORMER];
        const message = "Ya está activo. Si no recibiste la contraseña temporal, usa Restablecer contraseña.";
        post.mockRejectedValueOnce({ response: { status: 409, data: { code: "already_active", message } } });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: "Inactivos" }));
        await user.click(screen.getByRole("button", { name: "Reactivar acceso de Luis Pardo" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message));
        await waitFor(() => expect(get.mock.calls.filter(([u]) => u.includes("archived=true")).length).toBe(2));
    });

    it("advierte al reactivar a un veterinario sin cédula", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reactivate");
        inactiveRows = [{ ...FORMER, role: "VET" }];
        post.mockResolvedValueOnce({ data: { temp_password: "x", expires_in_seconds: 86400 } });
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: "Inactivos" }));
        await user.click(screen.getByRole("button", { name: "Reactivar acceso de Luis Pardo" }));
        expect(confirmMock.mock.calls[0][0].message).toMatch(/No tiene cédula profesional registrada/);
    });

    it("sin inactivos muestra un estado vacío", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reactivate");
        render(<Staff />);
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: "Inactivos" }));
        expect(screen.getByText("No hay integrantes inactivos")).toBeInTheDocument();
    });

    it("getStaff() sin argumentos no envía parámetros (regresión de Citas)", async () => {
        await getStaff();
        expect(get).toHaveBeenLastCalledWith("staff/");
    });
});
