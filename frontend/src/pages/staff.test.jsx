/**
 * Equipo: cédula profesional (M01, orden 7), plan Equipo (F4–F6: permisos por
 * capacidad, fila propia, identidad A1, reactivación A2, nombres D4) y Fase 1
 * de profesionalización (estado de acceso, alta con contraseña generada, tabla
 * de cinco columnas con menú de acciones, descripción de roles, acciones en
 * curso y guarda de ruta). Se usa el módulo real `api/staff`; solo se sustituye
 * el cliente HTTP.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
const canAny = (codes) => codes.some((code) => granted.has(code));
// Objeto estable: la página recarga Equipo cuando cambia `user` (useEffect).
const ADMIN = { role: "ADMIN", organization_timezone: "UTC" };
let currentUser = ADMIN;
const refreshUser = vi.fn();
vi.mock("../auth/authContext", () => ({
    useAuth: () => ({ user: currentUser, initializing: false, can, canAny, refreshUser }),
}));
const confirmMock = vi.fn(() => Promise.resolve(true));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => (...a) => confirmMock(...a) }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }) }));

import { toast } from "sonner";
import Staff from "./staff";
import { getStaff } from "../api/staff";

const ACTIVE_ACCESS = { status: "active", last_login: null, temp_password_expires_at: null };
const VET = {
    id: 3, public_id: "vet-uuid", username: "ana", email: "ana@vet.mx",
    first_name: "Ana", last_name: "Galeno", role: "VET", attends_patients: true,
    specialty: "Cirugía", license_number: "1234567", is_active: true,
    access: ACTIVE_ACCESS,
};

const NO_IMPACT = { upcoming_appointments: 0, open_medical_records: 0, open_cash_session: false };
let impact = NO_IMPACT;
let historyRows = [];

let activeRows = [VET];
let inactiveRows = [];

function renderStaff() {
    return render(
        <MemoryRouter initialEntries={["/staff"]}>
            <Routes>
                <Route path="/staff" element={<Staff />} />
                <Route path="/" element={<p>Inicio</p>} />
                <Route path="/cash" element={<p>Caja</p>} />
            </Routes>
        </MemoryRouter>,
    );
}

const openRowMenu = async (user, name = "Ana Galeno") => {
    await user.click(screen.getByRole("button", { name: `Más acciones para ${name}` }));
    return screen.getByRole("menu");
};

beforeEach(() => {
    vi.clearAllMocks();
    granted = new Set(["staff.list", "staff.create", "staff.update", "staff.destroy"]);
    currentUser = ADMIN;
    activeRows = [VET];
    inactiveRows = [];
    impact = NO_IMPACT;
    historyRows = [];
    get.mockImplementation((url) => Promise.resolve({
        data: url.endsWith("/impact/") ? impact
            : url.endsWith("/history/") ? historyRows
            : url.includes("archived=true") ? inactiveRows : activeRows,
    }));
    post.mockResolvedValue({ data: VET });
    patch.mockResolvedValue({ data: VET });
    del.mockResolvedValue({ data: null });
    confirmMock.mockImplementation(() => Promise.resolve(true));
});

describe("Equipo: cédula profesional", () => {
    it("muestra la cédula en la tabla", async () => {
        renderStaff();
        expect(await screen.findByText("1234567")).toBeInTheDocument();
    });

    it("editar envía PATCH sobre el public_id con la cédula normalizada", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
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

    it("no guarda a un veterinario sin cédula y lo dice en el campo", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /editar/i }));
        await user.clear(screen.getByLabelText(/cédula profesional/i));
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        expect(patch).not.toHaveBeenCalled();
        // Fase 1: la validación del cliente se muestra en su campo, no en un toast.
        expect(screen.getByText("La cédula profesional es obligatoria para veterinarios")).toBeInTheDocument();
        expect(toast.error).not.toHaveBeenCalled();
    });

    it("el alta de un veterinario exige cédula con formato válido", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockResolvedValueOnce({ data: { temp_password: "Gen-1", expires_in_seconds: null, member: VET } });
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        await user.type(screen.getByPlaceholderText("usuario123"), "diego");
        await user.type(screen.getByPlaceholderText("Juan"), "Diego");
        await user.type(screen.getByPlaceholderText("correo@ejemplo.com"), "diego@vet.mx");
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
        renderStaff();
        await screen.findByText("1234567");
        expect(screen.queryByRole("button", { name: /editar/i })).not.toBeInTheDocument();
    });

    it("avisa, sin color de alarma general, al veterinario que no puede firmar", async () => {
        activeRows = [{ ...VET, license_number: "" }];
        renderStaff();
        expect(await screen.findByText("Sin cédula: no puede firmar")).toBeInTheDocument();
    });
});

describe("Equipo: permisos por capacidad, ruta y fila propia (F4, Fase 1)", () => {
    it("decide por can() y no por rol", async () => {
        currentUser = { role: "VET", id: 99 };
        renderStaff();
        await screen.findByText("1234567");
        expect(screen.getByRole("button", { name: /agregar miembro/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /editar a ana galeno/i })).toBeInTheDocument();
    });

    it("sin permisos de gestión, /staff redirige al inicio y no pide el equipo", async () => {
        granted = new Set(["staff.list"]);
        renderStaff();
        expect(await screen.findByText("Inicio")).toBeInTheDocument();
        expect(screen.queryByRole("heading", { name: "Equipo" })).not.toBeInTheDocument();
        expect(get).not.toHaveBeenCalled();
    });

    it("con un solo permiso de gestión la página se abre con sus acciones", async () => {
        const user = userEvent.setup({ delay: null });
        granted = new Set(["staff.list", "staff.update"]);
        renderStaff();
        await screen.findByText("1234567");
        expect(screen.getByRole("button", { name: /editar a ana galeno/i })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /agregar miembro/i })).not.toBeInTheDocument();
        // ADR p66: el menú solo ofrece el historial; sin permisos para lo demás.
        const menu = await openRowMenu(user);
        expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Historial"]);
    });

    it("la fila propia muestra «Tú» y Editar, y su menú solo el historial", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        granted.add("staff.change_role");
        currentUser = { role: "ADMIN", id: VET.id };
        renderStaff();
        const row = (await screen.findByText("1234567")).closest("tr");
        expect(within(row).getByText("Tú")).toBeInTheDocument();
        expect(within(row).getByRole("button", { name: /editar/i })).toBeInTheDocument();
        const menu = await openRowMenu(user);
        expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Historial"]);
    });

    it("una cuenta protegida de la demo no muestra acciones", async () => {
        granted.add("staff.reset_password");
        activeRows = [{ ...VET, demo_protected: true }];
        renderStaff();
        const row = (await screen.findByText("1234567")).closest("tr");
        expect(within(row).queryByRole("button")).not.toBeInTheDocument();
    });

    it("desactivar vive en el menú, usa la confirmación nueva y no el icono de basura", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await screen.findByText("1234567");
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Desactivar acceso" }));
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
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        await user.type(screen.getByPlaceholderText("usuario123"), "ana");
        await user.type(screen.getByPlaceholderText("Juan"), "Ana");
        await user.type(screen.getByPlaceholderText("correo@ejemplo.com"), "otra@vet.mx");
        await user.click(screen.getByRole("radio", { name: /^Asistente/ }));
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        expect(await screen.findByText("Ese usuario ya existe.")).toBeInTheDocument();
        expect(screen.getByText("Nuevo Miembro")).toBeInTheDocument();
        expect(post.mock.calls[0][1]).toMatchObject({ role: "ASSISTANT" });
    });

    it("el modal temporal calcula las horas desde expires_in_seconds", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        post.mockResolvedValueOnce({ data: { temp_password: "Tmp-123", expires_in_seconds: 7200 } });
        renderStaff();
        await screen.findByText("1234567");
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Restablecer contraseña" }));
        const dialog = await screen.findByRole("dialog", { name: "Contraseña temporal generada" });
        expect(within(dialog).getByText("Tmp-123")).toBeInTheDocument();
        expect(within(dialog).getByText("2 horas para iniciar sesión")).toBeInTheDocument();
        expect(post.mock.calls[0][0]).toBe("staff/vet-uuid/reset-password/");
    });
});

describe("Equipo: alta con contraseña generada (Fase 1)", () => {
    const fill = async (user) => {
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        await user.type(screen.getByPlaceholderText("usuario123"), "diego");
        await user.type(screen.getByPlaceholderText("Juan"), "Diego");
        await user.type(screen.getByPlaceholderText("correo@ejemplo.com"), "diego@vet.mx");
        await user.type(screen.getByLabelText(/cédula profesional/i), "2468024");
    };

    it("no pide contraseña y explica que la genera el sistema", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        expect(screen.queryByLabelText(/contraseña/i)).not.toBeInTheDocument();
        expect(screen.getByText(/el sistema generará una al guardar/)).toBeInTheDocument();
        expect(screen.queryByText(/6 caracteres/)).not.toBeInTheDocument();
    });

    it("no envía contraseña y muestra las credenciales generadas una sola vez", async () => {
        const user = userEvent.setup({ delay: null });
        const created = {
            ...VET, id: 9, public_id: "diego-uuid", username: "diego", email: "diego@vet.mx",
            first_name: "Diego", last_name: "", license_number: "2468024",
            access: { status: "pending_first_login", last_login: null, temp_password_expires_at: null },
        };
        post.mockResolvedValueOnce({
            data: { temp_password: "Gen-Pass-xyz", expires_in_seconds: null, must_change_on_first_login: true, member: created },
        });
        renderStaff();
        await screen.findByText("1234567");
        await fill(user);
        await user.click(screen.getByRole("button", { name: /guardar/i }));

        await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
        expect(post.mock.calls[0][1]).not.toHaveProperty("password");
        const dialog = await screen.findByRole("dialog", { name: "Integrante creado" });
        expect(within(dialog).getByText("Gen-Pass-xyz")).toBeInTheDocument();
        expect(within(dialog).getByText("diego@vet.mx")).toBeInTheDocument();
        expect(within(dialog).getByText("Hasta su primer ingreso")).toBeInTheDocument();
        expect(screen.queryByText("Nuevo Miembro")).not.toBeInTheDocument();

        await user.click(within(dialog).getByRole("button", { name: "Listo" }));
        expect(screen.queryByText("Gen-Pass-xyz")).not.toBeInTheDocument();
    });

    it("muestra la descripción real de cada rol al elegirlo", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        const roles = screen.getAllByRole("radio");
        expect(roles).toHaveLength(3);
        expect(screen.getByRole("radio", { name: /^Veterinario/ })).toBeChecked();
        expect(screen.getByRole("radio", { name: /^Asistente.*Consulta expedientes sin modificarlos/ })).toBeInTheDocument();
        expect(screen.getByRole("radio", { name: /^Administrador.*equipo/ })).toBeInTheDocument();
    });
});

describe("Equipo: estado de acceso y resumen (Fase 1)", () => {
    const NOW = new Date("2026-11-23T18:00:00Z");
    const row = (overrides) => ({ ...VET, ...overrides });

    beforeEach(() => {
        vi.useFakeTimers({ toFake: ["Date"] });
        vi.setSystemTime(NOW);
    });
    afterEach(() => vi.useRealTimers());

    it("traduce cada estado del backend a un texto corto", async () => {
        activeRows = [
            row({ id: 1, public_id: "a", first_name: "Activa", access: { status: "active", last_login: "2026-11-23T15:00:00Z", temp_password_expires_at: null } }),
            row({ id: 2, public_id: "b", first_name: "Nueva", access: { status: "pending_first_login", last_login: null, temp_password_expires_at: null } }),
            row({ id: 4, public_id: "c", first_name: "Temporal", access: { status: "temp_password_active", last_login: null, temp_password_expires_at: "2026-11-23T23:00:00Z" } }),
            row({ id: 5, public_id: "d", first_name: "Vencida", access: { status: "temp_password_expired", last_login: null, temp_password_expires_at: "2026-11-23T16:00:00Z" } }),
            row({ id: 6, public_id: "e", first_name: "Cambio", access: { status: "password_change_pending", last_login: "2026-11-20T10:00:00Z", temp_password_expires_at: null } }),
        ];
        renderStaff();
        await screen.findByText("Activa Galeno");
        const cell = (name) => screen.getByText(`${name} Galeno`).closest("tr");
        expect(within(cell("Activa")).getByText("Activo")).toBeInTheDocument();
        expect(within(cell("Activa")).getByText("Último acceso: hace 3 h")).toBeInTheDocument();
        expect(within(cell("Nueva")).getByText("Pendiente de primer ingreso")).toBeInTheDocument();
        expect(within(cell("Nueva")).getByText("Sin accesos registrados")).toBeInTheDocument();
        expect(within(cell("Temporal")).getByText("Contraseña temporal")).toBeInTheDocument();
        expect(within(cell("Temporal")).getByText("Vence en 5 h")).toBeInTheDocument();
        expect(within(cell("Vencida")).getByText("Contraseña temporal vencida")).toBeInTheDocument();
        expect(within(cell("Vencida")).getByText("Venció hace 2 h")).toBeInTheDocument();
        expect(within(cell("Cambio")).getByText("Debe cambiar su contraseña")).toBeInTheDocument();
        expect(within(cell("Cambio")).getByText("Último acceso: 20 nov")).toBeInTheDocument();
    });

    it("resume activos, inactivos y accesos pendientes con datos reales", async () => {
        granted.add("staff.reactivate");
        activeRows = [
            row({ id: 1, public_id: "a" }),
            row({ id: 2, public_id: "b", first_name: "Nueva", access: { status: "pending_first_login", last_login: null, temp_password_expires_at: null } }),
        ];
        inactiveRows = [row({ id: 7, public_id: "z", first_name: "Luis", is_active: false, access: { status: "inactive", last_login: null, temp_password_expires_at: null } })];
        renderStaff();
        expect(await screen.findByText("2 activos · 1 inactivo · 1 con acceso pendiente")).toBeInTheDocument();
    });

    it("las celdas llevan su rótulo para la vista apilada en pantallas angostas", async () => {
        renderStaff();
        const tr = (await screen.findByText("1234567")).closest("tr");
        const labels = [...tr.querySelectorAll("td[data-label]")].map((td) => td.dataset.label);
        expect(labels).toEqual(["Rol", "Datos profesionales", "Acceso"]);
        expect(screen.getAllByRole("columnheader").map((th) => th.textContent || th.getAttribute("aria-label")))
            .toEqual(["Integrante", "Rol", "Datos profesionales", "Acceso", "Acciones"]);
    });
});

describe("Equipo: acciones en curso (Fase 1)", () => {
    it("mientras se restablece, ninguna otra acción de fila se puede lanzar", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        let finish;
        post.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
        renderStaff();
        await screen.findByText("1234567");
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Restablecer contraseña" }));

        const trigger = await screen.findByRole("button", { name: "Más acciones para Ana Galeno" });
        await waitFor(() => expect(trigger).toBeDisabled());
        expect(trigger).toHaveAttribute("aria-busy", "true");
        expect(screen.getByRole("button", { name: /editar a ana galeno/i })).toBeDisabled();

        finish({ data: { temp_password: "Tmp-1", expires_in_seconds: 86400 } });
        await screen.findByRole("dialog", { name: "Contraseña temporal generada" });
        expect(screen.getByRole("button", { name: "Más acciones para Ana Galeno" })).not.toBeDisabled();
        expect(post).toHaveBeenCalledTimes(1);
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
    ["José", true, "José"],
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
        renderStaff();
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

    it("muestra el rol y su alcance sin ofrecer cambiarlo", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /editar/i }));
        expect(screen.getByText(/Atiende consultas, emite recetas y registra vacunas/)).toBeInTheDocument();
        expect(screen.queryByRole("radio")).not.toBeInTheDocument();
        expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    });

    it("el error del PATCH con sobre aparece en su campo", async () => {
        const user = userEvent.setup({ delay: null });
        patch.mockRejectedValueOnce({
            response: { status: 400, data: { code: "validation_error", errors: { email: ["Este correo no está disponible."] } } },
        });
        renderStaff();
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
        renderStaff();
        await screen.findByText("1234567");
        for (const [value, accepted, stored] of NAME_EXAMPLES) {
            patch.mockClear();
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
                // Fase 1: el error queda en el campo, no en un toast.
                expect(screen.getByText(
                    "El nombre solo puede contener letras, espacios, guiones y apóstrofos.",
                )).toBeInTheDocument();
                await user.click(screen.getByRole("button", { name: /cancelar/i }));
            }
        }
    }, 30000); // 16 casos con escritura real: holgura para la suite completa
});

describe("Equipo: inactivos y reactivación (F6)", () => {
    const FORMER = {
        ...VET, id: 7, public_id: "former-uuid", username: "luis", first_name: "Luis",
        last_name: "Pardo", role: "ASSISTANT", license_number: "", specialty: "", is_active: false,
        access: { status: "inactive", last_login: null, temp_password_expires_at: null },
    };

    it("sin staff.reactivate no hay segmento Inactivos", async () => {
        renderStaff();
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
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: "Inactivos" }));
        expect(screen.getByText("Inactivo")).toBeInTheDocument();
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
        renderStaff();
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
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: "Inactivos" }));
        await user.click(screen.getByRole("button", { name: "Reactivar acceso de Luis Pardo" }));
        expect(confirmMock.mock.calls[0][0].message).toMatch(/No tiene cédula profesional registrada/);
    });

    it("sin inactivos muestra un estado vacío", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reactivate");
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: "Inactivos" }));
        expect(screen.getByText("No hay integrantes inactivos")).toBeInTheDocument();
    });

    it("getStaff() sin argumentos no envía parámetros (regresión de Citas)", async () => {
        await getStaff();
        expect(get).toHaveBeenLastCalledWith("staff/");
    });
});

describe("Equipo: rol, función clínica, impacto e historial (ADR p66)", () => {
    const ASSISTANT = {
        ...VET, id: 8, public_id: "asst-uuid", username: "rosa", email: "rosa@vet.mx",
        first_name: "Rosa", last_name: "Mora", role: "ASSISTANT", attends_patients: false,
        specialty: "", license_number: "",
    };

    it("cambia el rol desde el menú y conserva la función clínica al pasar a ADMIN", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.change_role");
        post.mockResolvedValueOnce({ data: { ...VET, role: "ADMIN" } });
        renderStaff();
        await screen.findByText("1234567");
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Cambiar rol" }));
        const dialog = await screen.findByRole("dialog", { name: "Cambiar rol de Ana Galeno" });
        expect(within(dialog).getByRole("button", { name: "Cambiar rol" })).toBeDisabled();
        await user.click(within(dialog).getByRole("radio", { name: /^Administrador/ }));
        expect(within(dialog).getByRole("checkbox", { name: /atiende pacientes/i })).toBeChecked();
        await user.click(within(dialog).getByRole("button", { name: "Cambiar rol" }));
        await waitFor(() => expect(post).toHaveBeenCalledWith(
            "staff/vet-uuid/role/", { role: "ADMIN", attends_patients: true },
        ));
        expect(toast.success).toHaveBeenCalledWith("Rol actualizado");
    });

    it("no deja dar un rol que atiende a quien no tiene cédula", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.change_role");
        activeRows = [VET, ASSISTANT];
        renderStaff();
        await screen.findByText("Rosa Mora");
        const menu = await openRowMenu(user, "Rosa Mora");
        await user.click(within(menu).getByRole("menuitem", { name: "Cambiar rol" }));
        const dialog = await screen.findByRole("dialog", { name: "Cambiar rol de Rosa Mora" });
        await user.click(within(dialog).getByRole("radio", { name: /^Veterinario/ }));
        expect(within(dialog).getByText(/No tiene cédula profesional registrada/)).toBeInTheDocument();
        expect(within(dialog).getByRole("button", { name: "Cambiar rol" })).toBeDisabled();
    });

    it("avisa de sus citas al quitarle la función clínica", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.change_role");
        impact = { upcoming_appointments: 3, open_medical_records: 1, open_cash_session: false };
        renderStaff();
        await screen.findByText("1234567");
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Cambiar rol" }));
        const dialog = await screen.findByRole("dialog", { name: "Cambiar rol de Ana Galeno" });
        await user.click(within(dialog).getByRole("radio", { name: /^Asistente/ }));
        expect(await within(dialog).findByText(
            "Tiene 3 citas próximas y 1 consulta abierta a su nombre: seguirán asignadas, no se reasignan solas.",
        )).toBeInTheDocument();
    });

    it("sin staff.change_role no ofrece cambiar el rol", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await screen.findByText("1234567");
        const menu = await openRowMenu(user);
        expect(within(menu).queryByRole("menuitem", { name: "Cambiar rol" })).not.toBeInTheDocument();
    });

    it("una caja abierta bloquea la desactivación y lleva a Caja", async () => {
        const user = userEvent.setup({ delay: null });
        impact = { ...NO_IMPACT, open_cash_session: true };
        renderStaff();
        await screen.findByText("1234567");
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Desactivar acceso" }));
        await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
            title: "Ana Galeno tiene una caja abierta", confirmText: "Ir a Caja",
        })));
        expect(await screen.findByText("Caja")).toBeInTheDocument();
        expect(del).not.toHaveBeenCalled();
    });

    it("avisa de citas y consultas antes de desactivar, sin bloquear", async () => {
        const user = userEvent.setup({ delay: null });
        impact = { upcoming_appointments: 2, open_medical_records: 0, open_cash_session: false };
        renderStaff();
        await screen.findByText("1234567");
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Desactivar acceso" }));
        await waitFor(() => expect(del).toHaveBeenCalledWith("staff/vet-uuid/"));
        expect(confirmMock.mock.calls[0][0].message).toMatch(
            /^Tiene 2 citas próximas a su nombre: seguirán asignadas, no se reasignan solas\. Dejará de poder entrar/,
        );
    });

    it("muestra el historial con frases y sin datos personales", async () => {
        const user = userEvent.setup({ delay: null });
        historyRows = [
            { kind: "role_changed", kind_label: "Cambio de rol", created_at: "2026-11-24T15:00:00Z", actor_name: "Ada Admin",
              changes: { role: { from: "VET", to: "ADMIN" } } },
            { kind: "created", kind_label: "Alta", created_at: "2026-11-20T10:00:00Z", actor_name: "Ada Admin",
              changes: { role: "VET", attends_patients: true } },
        ];
        renderStaff();
        await screen.findByText("1234567");
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Historial" }));
        const dialog = await screen.findByRole("dialog", { name: "Historial de Ana Galeno" });
        expect(await within(dialog).findByText("Cambió el rol de veterinario a administrador")).toBeInTheDocument();
        expect(within(dialog).getByText("Alta como veterinario")).toBeInTheDocument();
        expect(within(dialog).getAllByText(/Ada Admin/)).toHaveLength(2);
        expect(get).toHaveBeenCalledWith("staff/vet-uuid/history/");
    });

    it("el alta de un ADMIN que atiende exige cédula y la envía marcada", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockResolvedValueOnce({ data: { temp_password: "Gen-2", expires_in_seconds: null, member: VET } });
        renderStaff();
        await screen.findByText("1234567");
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        await user.type(screen.getByPlaceholderText("usuario123"), "duena");
        await user.type(screen.getByPlaceholderText("Juan"), "Dueña");
        await user.type(screen.getByPlaceholderText("correo@ejemplo.com"), "duena@vet.mx");
        await user.click(screen.getByRole("radio", { name: /^Administrador/ }));
        await user.click(screen.getByRole("checkbox", { name: /atiende pacientes/i }));
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(screen.getByText("La cédula profesional es obligatoria para quien atiende pacientes")).toBeInTheDocument();
        await user.type(screen.getByRole("textbox", { name: /cédula profesional/i }), "2468024");
        await user.click(screen.getByRole("button", { name: /guardar/i }));
        await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
        expect(post.mock.calls[0][1]).toMatchObject({ role: "ADMIN", attends_patients: true, license_number: "2468024" });
    });

    it("un ADMIN que atiende se distingue en la tabla y su falta de cédula se avisa", async () => {
        activeRows = [{ ...VET, role: "ADMIN", attends_patients: true, license_number: "" }];
        renderStaff();
        expect(await screen.findByText(/· Atiende pacientes/)).toBeInTheDocument();
        expect(screen.getByText("Sin cédula: no puede firmar")).toBeInTheDocument();
    });
});
