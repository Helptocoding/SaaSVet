/**
 * Equipo (rediseño 2026-11-25, ADR p69). Conserva lo que protegían las fases
 * anteriores — cédula profesional (M01), permisos por capacidad y fila propia
 * (plan Equipo F4–F6), alta con contraseña generada y acciones en curso (Fase 1),
 * rol y función clínica (ADR p66), ficha (ADR p67) y especialidades (ADR p68) —
 * sobre la página nueva: encabezado con conteos, «Requiere atención»,
 * pestañas, búsqueda, filtro por rol, tabla con acceso por área, firma de
 * recetas, estado y último acceso. La edición ocurre en la ficha lateral (sus
 * pruebas viven en features/staff/MemberDrawer.test.jsx). Se usa el módulo real
 * `api/staff`; solo se sustituye el cliente HTTP.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
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
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), info: vi.fn(), promise: vi.fn() }) }));

import { toast } from "sonner";
import Staff from "./staff";
import { getStaff } from "../api/staff";

const CATALOG = {
    signing_permission: "prescription.create",
    reserved: ["staff.create"],
    roles: {
        ADMIN: ["appointment.list", "billing.refund", "prescription.create", "staff.create"],
        VET: ["appointment.list", "prescription.create"],
        ASSISTANT: ["appointment.list"],
    },
    areas: [
        { key: "clinical", label: "Clínica", groups: [
            { key: "prescriptions", label: "Recetas", permissions: [{ code: "prescription.create", label: "Emitir y firmar recetas" }] },
        ] },
        { key: "operation", label: "Operación", groups: [
            { key: "appointments", label: "Citas", permissions: [{ code: "appointment.list", label: "Ver la agenda" }] },
            { key: "billing", label: "Cobros", permissions: [{ code: "billing.refund", label: "Hacer devoluciones" }] },
        ] },
        { key: "administration", label: "Administración", groups: [
            { key: "team", label: "Equipo", permissions: [{ code: "staff.create", label: "Dar de alta integrantes" }] },
        ] },
    ],
};

const ACTIVE_ACCESS = { status: "active", last_login: null, temp_password_expires_at: null };
const VET = {
    id: 3, public_id: "vet-uuid", username: "ana", email: "ana@vet.mx",
    first_name: "Ana", last_name: "Galeno", role: "VET", attends_patients: true,
    specialties: ["surgery"], specialty_label: "Cirugía", license_number: "1234567", is_active: true,
    access: ACTIVE_ACCESS, permissions: CATALOG.roles.VET, permission_overrides: { granted: [], revoked: [] },
};
const ASSISTANT = {
    ...VET, id: 8, public_id: "asst-uuid", username: "rosa", email: "rosa@vet.mx",
    first_name: "Rosa", last_name: "Mora", role: "ASSISTANT", attends_patients: false,
    specialties: [], specialty_label: "", license_number: "", permissions: CATALOG.roles.ASSISTANT,
};

const NO_IMPACT = { upcoming_appointments: 0, open_medical_records: 0, open_cash_session: false };
let impact = NO_IMPACT;
let activeRows = [VET];
let inactiveRows = [];

function Where() {
    const location = useLocation();
    return <p data-testid="where">{location.pathname}{location.search}</p>;
}

function renderStaff() {
    return render(
        <MemoryRouter initialEntries={["/staff"]}>
            <Routes>
                <Route path="/staff" element={<><Staff /><Where /></>} />
                <Route path="/" element={<p>Inicio</p>} />
                <Route path="/cash" element={<p>Caja</p>} />
            </Routes>
        </MemoryRouter>,
    );
}

const rowOf = (name) => screen.getByRole("button", { name }).closest("tr");
const loaded = (name = "Ana Galeno") => screen.findByRole("button", { name }, { timeout: 4000 });
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
    get.mockImplementation((url) => Promise.resolve({
        data: url === "staff/permission-catalog/" ? CATALOG
            : url.endsWith("/impact/") ? impact
            : url.endsWith("/history/") ? []
            : url.endsWith("/appointments/") ? []
            : url === "staff/absences/" ? []
            : url.endsWith("/profile/") ? [...activeRows, ...inactiveRows].find((m) => url.includes(m.public_id)) || VET
            : url.includes("archived=true") ? inactiveRows : activeRows,
    }));
    post.mockResolvedValue({ data: VET });
    patch.mockResolvedValue({ data: VET });
    del.mockResolvedValue({ data: null });
    confirmMock.mockImplementation(() => Promise.resolve(true));
});

describe("Equipo: tabla nueva", () => {
    it("muestra rol con especialidades, áreas, firma, estado y último acceso", async () => {
        renderStaff();
        await loaded();
        const row = rowOf("Ana Galeno");
        expect(within(row).getByText("Veterinario")).toBeInTheDocument();
        expect(within(row).getByText("Cirugía")).toBeInTheDocument();
        expect(within(row).getByRole("button", { name: /^Clínica: Recetas/ })).toBeInTheDocument();
        expect(within(row).getByRole("button", { name: /^Operación: Citas/ })).toBeInTheDocument();
        expect(within(row).queryByRole("button", { name: /^Administración/ })).not.toBeInTheDocument();
        expect(within(row).getByText("Habilitada")).toBeInTheDocument();
        expect(within(row).getByText("Nunca")).toBeInTheDocument();
        // D6: lo normal no lleva color; la cédula se consulta en la ficha.
        expect(within(row).getByText("Activo")).not.toHaveClass("badge");
        expect(within(row).queryByText("1234567")).not.toBeInTheDocument();
        expect(within(row).queryByRole("button", { name: /editar/i })).not.toBeInTheDocument();
    });

    it("clic en la fila abre la ficha; el menú de acciones no la abre", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await loaded();
        await user.click(within(rowOf("Ana Galeno")).getByText("Veterinario"));
        expect(screen.getByTestId("where")).toHaveTextContent("/staff?member=vet-uuid");
        await user.keyboard("{Escape}");
        await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/staff$/));
        await openRowMenu(user);
        expect(screen.getByTestId("where")).toHaveTextContent(/^\/staff$/);
    });

    it("las celdas llevan su rótulo para la vista en tarjetas en pantallas angostas", async () => {
        renderStaff();
        await loaded();
        const labels = [...rowOf("Ana Galeno").querySelectorAll("td[data-label]")].map((td) => td.dataset.label);
        expect(labels).toEqual(["Rol", "Acceso por área", "Firma de recetas", "Estado", "Último acceso"]);
        expect(screen.getAllByRole("columnheader").map((th) => th.textContent || th.getAttribute("aria-label")))
            .toEqual(["Integrante", "Rol", "Acceso por área", "Firma de recetas", "Estado", "Último acceso", "Acciones"]);
    });

    it("el popover de un área lista solo lo que puede hacer y se cierra con Escape", async () => {
        const user = userEvent.setup({ delay: null });
        activeRows = [{ ...VET, permissions: [...CATALOG.roles.VET, "billing.refund"], permission_overrides: { granted: ["billing.refund"], revoked: [] } }];
        renderStaff();
        await loaded();
        const chip = screen.getByRole("button", { name: /^Operación: Citas, cobros/ });
        await user.click(chip);
        const panel = screen.getByRole("dialog", { name: "Operación: permisos de Ana Galeno" });
        expect(within(panel).getByText("Ver la agenda")).toBeInTheDocument();
        expect(within(panel).getByText("Hacer devoluciones")).toBeInTheDocument();
        expect(chip).toHaveAttribute("aria-expanded", "true");
        expect(screen.getByText("Permisos ajustados para esta persona")).toBeInTheDocument();
        // Abrir el detalle de un área no abre la ficha.
        expect(screen.getByTestId("where")).toHaveTextContent(/^\/staff$/);
        await user.keyboard("{Escape}");
        expect(screen.queryByRole("dialog", { name: /Operación: permisos/ })).not.toBeInTheDocument();
        expect(chip).toHaveFocus();
    });

    it("quien tiene todos los permisos dice «Todas las áreas»", async () => {
        activeRows = [{ ...VET, role: "ADMIN", permissions: CATALOG.roles.ADMIN }];
        renderStaff();
        expect(await screen.findByText("Todas las áreas")).toBeInTheDocument();
    });

    it("sin permiso de recetas la firma no aplica", async () => {
        activeRows = [ASSISTANT];
        renderStaff();
        await loaded("Rosa Mora");
        expect(within(rowOf("Rosa Mora")).getByText("No aplica")).toBeInTheDocument();
    });
});

// Lo pendiente se señala donde está (su celda) y en el contador del filtro; no
// hay un bloque aparte que compita con la tabla.
describe("Equipo: lo que requiere atención", () => {
    it("sin cédula: la celda lo dice, lleva al campo y el filtro lo cuenta en aviso", async () => {
        const user = userEvent.setup({ delay: null });
        activeRows = [{ ...VET, license_number: "" }];
        renderStaff();
        await loaded();
        expect(screen.queryByRole("region", { name: /Requiere atención/ })).not.toBeInTheDocument();
        const segment = screen.getByRole("button", { name: "Requieren atención 1" });
        expect(segment.querySelector(".segmented-count-attention")).not.toBeNull();
        await user.click(within(rowOf("Ana Galeno")).getByRole("button", { name: "Falta cédula: completar la de Ana Galeno" }));
        expect(screen.getByTestId("where")).toHaveTextContent("/staff?member=vet-uuid&section=license");
    });

    it("«Completar cédula» encabeza su menú", async () => {
        const user = userEvent.setup({ delay: null });
        activeRows = [{ ...VET, license_number: "" }];
        renderStaff();
        await loaded();
        const menu = await openRowMenu(user);
        expect(within(menu).getAllByRole("menuitem")[0]).toHaveTextContent("Completar cédula");
    });

    it("una invitación vencida se marca en Estado y se reenvía desde su menú", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        activeRows = [{ ...VET, access: { status: "temp_password_expired", last_login: null, temp_password_expires_at: "2026-11-22T10:00:00Z" } }];
        post.mockResolvedValueOnce({ data: { temp_password: "Tmp-5", expires_in_seconds: 86400 } });
        renderStaff();
        await loaded();
        expect(within(rowOf("Ana Galeno")).getByText("Invitación vencida")).toHaveClass("badge-warning");
        const menu = await openRowMenu(user);
        const first = within(menu).getAllByRole("menuitem")[0];
        expect(first).toHaveTextContent("Reenviar invitación");
        await user.click(first);
        await waitFor(() => expect(post.mock.calls[0][0]).toBe("staff/vet-uuid/reset-password/"));
        expect(confirmMock.mock.calls[0][0]).toMatchObject({ title: "Reenviar invitación", dangerMode: false });
        expect(await screen.findByRole("dialog", { name: "Contraseña temporal generada" })).toBeInTheDocument();
    });

    it("sin pendientes el contador no avisa", async () => {
        renderStaff();
        await loaded();
        const segment = screen.getByRole("button", { name: "Requieren atención 0" });
        expect(segment.querySelector(".segmented-count-attention")).toBeNull();
    });

    it("sin staff.update la falta de cédula se informa sin enlace", async () => {
        granted.delete("staff.update");
        activeRows = [{ ...VET, license_number: "" }];
        renderStaff();
        await loaded();
        expect(within(rowOf("Ana Galeno")).getByText("Falta cédula")).toBeInTheDocument();
        expect(within(rowOf("Ana Galeno")).queryByRole("button", { name: /Falta cédula/ })).not.toBeInTheDocument();
    });

    it("un ADMIN que atiende se distingue en la tabla y su falta de cédula se avisa", async () => {
        activeRows = [{ ...VET, role: "ADMIN", attends_patients: true, license_number: "", specialties: [], permissions: CATALOG.roles.ADMIN }];
        renderStaff();
        expect(await screen.findByText("Atiende pacientes")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Falta cédula/ })).toBeInTheDocument();
    });
});

describe("Equipo: pestañas, búsqueda y filtro por rol", () => {
    const PENDING = { ...ASSISTANT, id: 9, public_id: "nuevo-uuid", first_name: "Nico", last_name: "Ruiz", email: "nico@vet.mx", access: { status: "pending_first_login", last_login: null, temp_password_expires_at: null } };

    it("cuenta por pestaña y filtra al elegir una", async () => {
        const user = userEvent.setup({ delay: null });
        activeRows = [VET, ASSISTANT, PENDING];
        renderStaff();
        await loaded();
        const filter = screen.getByRole("group", { name: "Mostrar integrantes" });
        expect(within(filter).getByRole("button", { name: "Todos 3" })).toHaveAttribute("aria-pressed", "true");
        expect(within(filter).getByRole("button", { name: "Activos 2" })).toHaveAttribute("aria-pressed", "false");
        await user.click(within(filter).getByRole("button", { name: "Pendientes 1" }));
        expect(within(filter).getByRole("button", { name: "Pendientes 1" })).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByRole("button", { name: "Nico Ruiz" })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Ana Galeno" })).not.toBeInTheDocument();
        expect(within(rowOf("Nico Ruiz")).getByText("Invitación pendiente")).toBeInTheDocument();
    });

    it("filtro, búsqueda y rol comparten una sola barra", async () => {
        renderStaff();
        await loaded();
        const filter = screen.getByRole("group", { name: "Mostrar integrantes" });
        const toolbar = filter.parentElement;
        expect(within(toolbar).getByRole("searchbox", { name: "Buscar por nombre o correo" })).toBeInTheDocument();
        expect(within(toolbar).getByRole("combobox", { name: "Filtrar por rol" })).toBeInTheDocument();
    });

    it("la búsqueda se limpia con su botón", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await loaded();
        await user.type(screen.getByRole("searchbox"), "zzz");
        await user.click(screen.getByRole("button", { name: "Limpiar búsqueda" }));
        expect(screen.getByRole("searchbox")).toHaveValue("");
        expect(screen.getByRole("button", { name: "Ana Galeno" })).toBeInTheDocument();
    });

    it("busca por nombre o correo sin acentos y filtra por rol", async () => {
        const user = userEvent.setup({ delay: null });
        activeRows = [VET, ASSISTANT];
        renderStaff();
        await loaded();
        await user.type(screen.getByRole("searchbox", { name: "Buscar por nombre o correo" }), "rosa@");
        expect(screen.queryByRole("button", { name: "Ana Galeno" })).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Rosa Mora" })).toBeInTheDocument();
        await user.clear(screen.getByRole("searchbox"));
        await user.selectOptions(screen.getByRole("combobox", { name: "Filtrar por rol" }), "VET");
        expect(screen.getByRole("button", { name: "Ana Galeno" })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Rosa Mora" })).not.toBeInTheDocument();
    });

    it("sin coincidencias ofrece limpiar los filtros", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await loaded();
        await user.type(screen.getByRole("searchbox"), "zzz");
        expect(screen.getByText("Sin coincidencias")).toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: "Limpiar filtros" }));
        expect(screen.getByRole("button", { name: "Ana Galeno" })).toBeInTheDocument();
    });

    it("el encabezado dice el tamaño del equipo; los conteos por estado viven en el filtro", async () => {
        granted.add("staff.reactivate");
        activeRows = [VET, PENDING];
        inactiveRows = [{ ...ASSISTANT, id: 7, public_id: "z", is_active: false, access: { status: "inactive", last_login: null, temp_password_expires_at: null } }];
        renderStaff();
        expect(await screen.findByText("2 integrantes")).toBeInTheDocument();
        const filter = screen.getByRole("group", { name: "Mostrar integrantes" });
        expect(within(filter).getByRole("button", { name: "Pendientes 1" })).toBeInTheDocument();
        expect(within(filter).getByRole("button", { name: "Desactivados 1" })).toBeInTheDocument();
    });
});

describe("Equipo: estado y último acceso", () => {
    const NOW = new Date("2026-11-23T18:00:00Z");
    const row = (overrides) => ({ ...VET, ...overrides });

    beforeEach(() => {
        vi.useFakeTimers({ toFake: ["Date"] });
        vi.setSystemTime(NOW);
    });
    afterEach(() => vi.useRealTimers());

    it("traduce el estado del backend a cuatro estados de cuenta", async () => {
        activeRows = [
            row({ id: 1, public_id: "a", first_name: "Activa", access: { status: "active", last_login: "2026-11-23T15:00:00Z", temp_password_expires_at: null } }),
            row({ id: 2, public_id: "b", first_name: "Nueva", access: { status: "pending_first_login", last_login: null, temp_password_expires_at: null } }),
            row({ id: 4, public_id: "c", first_name: "Temporal", access: { status: "temp_password_active", last_login: null, temp_password_expires_at: "2026-11-23T23:00:00Z" } }),
            row({ id: 5, public_id: "d", first_name: "Vencida", access: { status: "temp_password_expired", last_login: null, temp_password_expires_at: "2026-11-23T16:00:00Z" } }),
            row({ id: 6, public_id: "e", first_name: "Cambio", access: { status: "password_change_pending", last_login: "2026-11-20T10:00:00Z", temp_password_expires_at: null } }),
        ];
        renderStaff();
        await loaded("Activa Galeno");
        const cell = (name) => rowOf(`${name} Galeno`);
        expect(within(cell("Activa")).getByText("Activo")).toBeInTheDocument();
        expect(within(cell("Activa")).getByText("hace 3 h")).toBeInTheDocument();
        expect(within(cell("Nueva")).getByText("Invitación pendiente")).toBeInTheDocument();
        expect(within(cell("Nueva")).getByText("Nunca")).toBeInTheDocument();
        expect(within(cell("Temporal")).getByText("Invitación pendiente")).toBeInTheDocument();
        expect(within(cell("Vencida")).getByText("Invitación vencida")).toBeInTheDocument();
        expect(within(cell("Cambio")).getByText("Invitación pendiente")).toBeInTheDocument();
        expect(within(cell("Cambio")).getByText("hace 3 d")).toBeInTheDocument();
    });

    it("la fila propia dice «Ahora»", async () => {
        currentUser = { role: "ADMIN", id: VET.id };
        renderStaff();
        await loaded();
        expect(within(rowOf("Ana Galeno")).getByText("Ahora")).toBeInTheDocument();
    });
});

describe("Equipo: permisos por capacidad, ruta y fila propia (F4, Fase 1)", () => {
    it("decide por can() y no por rol", async () => {
        const user = userEvent.setup({ delay: null });
        currentUser = { role: "VET", id: 99 };
        renderStaff();
        await loaded();
        expect(screen.getByRole("button", { name: /agregar miembro/i })).toBeInTheDocument();
        const menu = await openRowMenu(user);
        expect(within(menu).getByRole("menuitem", { name: "Desactivar acceso" })).toBeInTheDocument();
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
        await loaded();
        expect(screen.queryByRole("button", { name: /agregar miembro/i })).not.toBeInTheDocument();
        const menu = await openRowMenu(user);
        expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Ver ficha"]);
    });

    it("sin staff.update la ficha se abre solo para consultar", async () => {
        const user = userEvent.setup({ delay: null });
        granted.delete("staff.update");
        renderStaff();
        await loaded();
        await user.click(screen.getByRole("button", { name: "Ana Galeno" }));
        const dialog = await screen.findByRole("dialog", { name: /Ana Galeno/ }, { timeout: 4000 });
        expect(await within(dialog).findByLabelText("NOMBRE *")).toBeDisabled();
    });

    it("la fila propia muestra «Tú» y su menú solo la ficha", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        granted.add("staff.change_role");
        currentUser = { role: "ADMIN", id: VET.id };
        renderStaff();
        await loaded();
        const row = rowOf("Ana Galeno");
        expect(within(row).getByText("Tú")).toBeInTheDocument();
        const menu = await openRowMenu(user);
        expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Ver ficha"]);
    });

    it("una cuenta protegida de la demo solo se consulta", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        activeRows = [{ ...VET, demo_protected: true }];
        renderStaff();
        await loaded();
        const menu = await openRowMenu(user);
        expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Ver ficha"]);
    });

    it("el nombre (vía de teclado) abre la ficha lateral (ADR p67)", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await loaded();
        await user.click(screen.getByRole("button", { name: "Ana Galeno" }));
        expect(screen.getByTestId("where")).toHaveTextContent("/staff?member=vet-uuid");
        expect(await screen.findByRole("dialog", { name: /Ana Galeno/ })).toBeInTheDocument();
    });

    it("«Cambiar rol» abre la ficha en la sección de rol", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.change_role");
        renderStaff();
        await loaded();
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Cambiar rol" }));
        expect(screen.getByTestId("where")).toHaveTextContent("/staff?member=vet-uuid&section=role");
    });

    it("sin staff.change_role no ofrece cambiar el rol", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await loaded();
        const menu = await openRowMenu(user);
        expect(within(menu).queryByRole("menuitem", { name: "Cambiar rol" })).not.toBeInTheDocument();
    });
});

describe("Equipo: desactivar y restablecer", () => {
    it("desactivar vive en el menú, usa la confirmación nueva y no el icono de basura", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        await loaded();
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Desactivar acceso" }));
        expect(confirmMock).toHaveBeenCalledWith({
            title: "Desactivar acceso de Ana Galeno",
            message: "Dejará de poder entrar y se cerrarán sus sesiones. Sus citas, consultas y registros se conservan. Podrás reactivarlo desde Desactivados.",
            confirmText: "Desactivar acceso",
            dangerMode: true,
        });
        await waitFor(() => expect(del).toHaveBeenCalledWith("staff/vet-uuid/"));
        expect(document.querySelector(".lucide-trash2, .lucide-trash-2")).toBeNull();
    });

    it("una caja abierta bloquea la desactivación y lleva a Caja", async () => {
        const user = userEvent.setup({ delay: null });
        impact = { ...NO_IMPACT, open_cash_session: true };
        renderStaff();
        await loaded();
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
        await loaded();
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Desactivar acceso" }));
        await waitFor(() => expect(del).toHaveBeenCalledWith("staff/vet-uuid/"));
        expect(confirmMock.mock.calls[0][0].message).toMatch(
            /^Tiene 2 citas próximas a su nombre: seguirán asignadas; las citas se reasignan desde su ficha\. Dejará de poder entrar/,
        );
        // Sin `appointment.update` no se ofrece reasignar.
        expect(toast.success).toHaveBeenCalledWith("Acceso desactivado", undefined);
    });

    it("tras desactivar a alguien con citas ofrece reasignarlas en su ficha (ADR p67)", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("appointment.update");
        impact = { upcoming_appointments: 2, open_medical_records: 0, open_cash_session: false };
        renderStaff();
        await loaded();
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Desactivar acceso" }));
        await waitFor(() => expect(toast.success).toHaveBeenCalled());
        const [, options] = toast.success.mock.calls[0];
        expect(options.action.label).toBe("Reasignar citas");
        options.action.onClick();
        await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/staff?member=vet-uuid"));
    });

    it("el modal temporal calcula las horas desde expires_in_seconds", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        post.mockResolvedValueOnce({ data: { temp_password: "Tmp-123", expires_in_seconds: 7200 } });
        renderStaff();
        await loaded();
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Restablecer contraseña" }));
        const dialog = await screen.findByRole("dialog", { name: "Contraseña temporal generada" });
        expect(within(dialog).getByText("Tmp-123")).toBeInTheDocument();
        expect(within(dialog).getByText("2 horas para iniciar sesión")).toBeInTheDocument();
        expect(post.mock.calls[0][0]).toBe("staff/vet-uuid/reset-password/");
        expect(confirmMock.mock.calls[0][0]).toMatchObject({ title: "Restablecer contraseña", dangerMode: true });
    });

    it("a quien no ha entrado se le reenvía la invitación desde el menú", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        activeRows = [{ ...VET, access: { status: "pending_first_login", last_login: null, temp_password_expires_at: null } }];
        renderStaff();
        await loaded();
        const menu = await openRowMenu(user);
        expect(within(menu).getByRole("menuitem", { name: "Reenviar invitación" })).toBeInTheDocument();
        expect(within(menu).queryByRole("menuitem", { name: "Restablecer contraseña" })).not.toBeInTheDocument();
    });

    it("mientras se restablece, ninguna otra acción de fila se puede lanzar", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reset_password");
        let finish;
        post.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
        activeRows = [VET, ASSISTANT];
        renderStaff();
        await loaded();
        const menu = await openRowMenu(user);
        await user.click(within(menu).getByRole("menuitem", { name: "Restablecer contraseña" }));

        const trigger = await screen.findByRole("button", { name: "Más acciones para Ana Galeno" });
        await waitFor(() => expect(trigger).toBeDisabled());
        expect(trigger).toHaveAttribute("aria-busy", "true");
        expect(screen.getByRole("button", { name: "Más acciones para Rosa Mora" })).toBeDisabled();

        finish({ data: { temp_password: "Tmp-1", expires_in_seconds: 86400 } });
        await screen.findByRole("dialog", { name: "Contraseña temporal generada" });
        expect(screen.getByRole("button", { name: "Más acciones para Ana Galeno" })).not.toBeDisabled();
        expect(post).toHaveBeenCalledTimes(1);
    });
});

describe("Equipo: alta con contraseña generada (Fase 1)", () => {
    const open = async (user) => {
        await loaded();
        await user.click(screen.getByRole("button", { name: /agregar miembro/i }));
        return screen.getByRole("dialog", { name: "Nuevo miembro" });
    };
    const fill = async (user, dialog) => {
        await user.type(within(dialog).getByPlaceholderText("usuario123"), "diego");
        await user.type(within(dialog).getByPlaceholderText("Juan"), "Diego");
        await user.type(within(dialog).getByPlaceholderText("correo@ejemplo.com"), "diego@vet.mx");
    };

    it("no pide contraseña y explica que la genera el sistema", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        const dialog = await open(user);
        expect(within(dialog).queryByLabelText(/contraseña/i)).not.toBeInTheDocument();
        expect(within(dialog).getByText(/el sistema generará una al guardar/)).toBeInTheDocument();
    });

    it("el alta de un veterinario exige cédula con formato válido", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockResolvedValueOnce({ data: { temp_password: "Gen-1", expires_in_seconds: null, member: VET } });
        renderStaff();
        const dialog = await open(user);
        await fill(user, dialog);
        await user.click(within(dialog).getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(within(dialog).getByText("La cédula profesional es obligatoria para veterinarios")).toBeInTheDocument();

        const license = within(dialog).getByLabelText(/cédula profesional/i);
        await user.type(license, "12a45");
        await user.click(within(dialog).getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(within(dialog).getByText("La cédula profesional debe tener solo dígitos, entre 5 y 10")).toBeInTheDocument();

        await user.clear(license);
        await user.type(license, "2468024");
        await user.click(within(dialog).getByRole("button", { name: /guardar/i }));
        await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
        expect(post.mock.calls[0][0]).toBe("staff/create/");
        expect(post.mock.calls[0][1]).toMatchObject({ role: "VET", license_number: "2468024" });
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
        const form = await open(user);
        await fill(user, form);
        await user.type(within(form).getByLabelText(/cédula profesional/i), "2468024");
        await user.click(within(form).getByRole("button", { name: /guardar/i }));

        await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
        expect(post.mock.calls[0][1]).not.toHaveProperty("password");
        const dialog = await screen.findByRole("dialog", { name: "Integrante creado" });
        expect(within(dialog).getByText("Gen-Pass-xyz")).toBeInTheDocument();
        expect(within(dialog).getByText("diego@vet.mx")).toBeInTheDocument();
        expect(within(dialog).getByText("Hasta su primer ingreso")).toBeInTheDocument();
        expect(screen.queryByRole("dialog", { name: "Nuevo miembro" })).not.toBeInTheDocument();

        await user.click(within(dialog).getByRole("button", { name: "Listo" }));
        expect(screen.queryByText("Gen-Pass-xyz")).not.toBeInTheDocument();
    });

    it("el error del alta sin sobre aparece en su campo y el modal sigue abierto", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockRejectedValueOnce({ response: { status: 400, data: { username: ["Ese usuario ya existe."] } } });
        renderStaff();
        const dialog = await open(user);
        await fill(user, dialog);
        await user.click(within(dialog).getByRole("radio", { name: /^Asistente/ }));
        await user.click(within(dialog).getByRole("button", { name: /guardar/i }));
        expect(await within(dialog).findByText("Ese usuario ya existe.")).toBeInTheDocument();
        expect(screen.getByRole("dialog", { name: "Nuevo miembro" })).toBeInTheDocument();
        expect(post.mock.calls[0][1]).toMatchObject({ role: "ASSISTANT" });
    });

    it("muestra la descripción real de cada rol al elegirlo", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        const dialog = await open(user);
        expect(within(dialog).getAllByRole("radio")).toHaveLength(3);
        expect(within(dialog).getByRole("radio", { name: /^Veterinario/ })).toBeChecked();
        expect(within(dialog).getByRole("radio", { name: /^Asistente.*Consulta expedientes sin modificarlos/ })).toBeInTheDocument();
        expect(within(dialog).getByRole("radio", { name: /^Administrador.*equipo/ })).toBeInTheDocument();
    });

    it("el alta de un ADMIN que atiende exige cédula y la envía marcada", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockResolvedValueOnce({ data: { temp_password: "Gen-2", expires_in_seconds: null, member: VET } });
        renderStaff();
        const dialog = await open(user);
        await user.type(within(dialog).getByPlaceholderText("usuario123"), "duena");
        await user.type(within(dialog).getByPlaceholderText("Juan"), "Dueña");
        await user.type(within(dialog).getByPlaceholderText("correo@ejemplo.com"), "duena@vet.mx");
        await user.click(within(dialog).getByRole("radio", { name: /^Administrador/ }));
        await user.click(within(dialog).getByRole("checkbox", { name: /atiende pacientes/i }));
        await user.click(within(dialog).getByRole("button", { name: /guardar/i }));
        expect(post).not.toHaveBeenCalled();
        expect(within(dialog).getByText("La cédula profesional es obligatoria para quien atiende pacientes")).toBeInTheDocument();
        await user.type(within(dialog).getByRole("textbox", { name: /cédula profesional/i }), "2468024");
        await user.click(within(dialog).getByRole("button", { name: /guardar/i }));
        await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
        expect(post.mock.calls[0][1]).toMatchObject({ role: "ADMIN", attends_patients: true, license_number: "2468024" });
    });

    it("el alta de un veterinario envía los códigos de especialidad elegidos", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockResolvedValueOnce({ data: { temp_password: "Gen-3", expires_in_seconds: null, member: VET } });
        renderStaff();
        const dialog = await open(user);
        await fill(user, dialog);
        await user.type(within(dialog).getByRole("textbox", { name: /cédula profesional/i }), "2468024");
        await user.click(within(dialog).getByRole("checkbox", { name: "Dermatología" }));
        await user.click(within(dialog).getByRole("checkbox", { name: "Medicina general" }));
        await user.click(within(dialog).getByRole("button", { name: /guardar/i }));
        await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
        expect(post.mock.calls[0][1].specialties).toEqual(["general_medicine", "dermatology"]);
    });

    it("un asistente no tiene especialidades", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        const dialog = await open(user);
        await user.click(within(dialog).getByRole("radio", { name: /^Asistente/ }));
        expect(within(dialog).queryByRole("checkbox", { name: "Cirugía" })).not.toBeInTheDocument();
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

describe("Equipo: edición desde la ficha (F5, ADR p68)", () => {
    const openEdit = async (user, name = "Ana Galeno") => {
        await loaded(name);
        await user.click(screen.getByRole("button", { name }));
        await screen.findByRole("heading", { name: new RegExp(name) }, { timeout: 4000 });
        return screen.getByRole("dialog", { name: new RegExp(name) });
    };

    it("envía solo lo que cambió, avisa del correo y refresca la sesión propia", async () => {
        const user = userEvent.setup({ delay: null });
        currentUser = { role: "ADMIN", id: VET.id };
        renderStaff();
        const dialog = await openEdit(user);
        expect(within(dialog).getByRole("button", { name: "Guardar cambios" })).toBeDisabled();
        const email = within(dialog).getByLabelText(/correo electrónico/i);
        await user.clear(email);
        await user.type(email, "ana.nueva@vet.mx");
        expect(within(dialog).getByText(/Es su acceso al sistema/)).toBeInTheDocument();
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", { email: "ana.nueva@vet.mx" }));
        await waitFor(() => expect(refreshUser).toHaveBeenCalled());
    });

    it("no guarda a un veterinario sin cédula y lo dice en el campo", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        const dialog = await openEdit(user);
        await user.clear(within(dialog).getByLabelText(/cédula profesional/i));
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        expect(patch).not.toHaveBeenCalled();
        expect(within(dialog).getByText("La cédula profesional es obligatoria para veterinarios")).toBeInTheDocument();
        expect(toast.error).not.toHaveBeenCalled();
    });

    it("muestra el rol elegido y solo su alcance", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        const dialog = await openEdit(user);
        expect(within(dialog).getByRole("radio", { name: "Veterinario" })).toBeChecked();
        expect(within(dialog).getByText(/Atiende consultas, emite recetas y registra vacunas/)).toBeInTheDocument();
        expect(within(dialog).queryByText(/Consulta expedientes sin modificarlos/)).not.toBeInTheDocument();
    });

    it("editar envía solo la lista nueva de especialidades cuando cambia", async () => {
        const user = userEvent.setup({ delay: null });
        renderStaff();
        const dialog = await openEdit(user);
        expect(within(dialog).getByRole("checkbox", { name: "Cirugía" })).toBeChecked();
        await user.click(within(dialog).getByRole("checkbox", { name: "Oncología" }));
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
        expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", { specialties: ["surgery", "oncology"] });
    });

    it("valida los nombres igual que el backend", async () => {
        const user = userEvent.setup({ delay: null });
        activeRows = [{ ...VET, first_name: "Zed" }];
        renderStaff();
        const dialog = await openEdit(user, "Zed Galeno");
        const first = within(dialog).getByLabelText(/^nombre/i);
        for (const [value, accepted, stored] of NAME_EXAMPLES) {
            patch.mockClear();
            await user.clear(first);
            await user.type(first, value);
            await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
            if (accepted) {
                await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", { first_name: stored }));
            } else {
                expect(patch, value).not.toHaveBeenCalled();
                expect(within(dialog).getByText(
                    "El nombre solo puede contener letras, espacios, guiones y apóstrofos.",
                )).toBeInTheDocument();
            }
        }
    }, 30000); // 16 casos con escritura real: holgura para la suite completa
});

describe("Equipo: desactivados y reactivación (F6)", () => {
    const FORMER = {
        ...VET, id: 7, public_id: "former-uuid", username: "luis", first_name: "Luis",
        last_name: "Pardo", role: "ASSISTANT", license_number: "", specialties: [], specialty_label: "",
        attends_patients: false, is_active: false, permissions: CATALOG.roles.ASSISTANT,
        access: { status: "inactive", last_login: null, temp_password_expires_at: null },
    };

    it("sin staff.reactivate no hay filtro Desactivados ni se piden", async () => {
        renderStaff();
        await loaded();
        expect(screen.queryByRole("button", { name: /^Desactivados/ })).not.toBeInTheDocument();
        expect(get.mock.calls.some(([url]) => url.includes("archived=true"))).toBe(false);
    });

    it("«Todos» no mezcla a los desactivados", async () => {
        granted.add("staff.reactivate");
        inactiveRows = [FORMER];
        renderStaff();
        await loaded();
        expect(screen.queryByRole("button", { name: "Luis Pardo" })).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Desactivados 1" })).toBeInTheDocument();
    });

    it("reactiva, muestra la temporal y recarga ambas listas", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reactivate");
        inactiveRows = [FORMER];
        post.mockResolvedValueOnce({
            data: { temp_password: "Tmp-9", expires_in_seconds: 86400, member: { ...FORMER, is_active: true } },
        });
        renderStaff();
        await loaded();
        await user.click(screen.getByRole("button", { name: /^Desactivados/ }));
        expect(within(rowOf("Luis Pardo")).getByText("Desactivado")).toBeInTheDocument();
        await user.click(screen.getByRole("button", { name: "Reactivar acceso de Luis Pardo" }));

        expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
            title: "Reactivar acceso de Luis Pardo",
            message: "Conservará su rol (Asistente), sus permisos y su historial. Se generará una contraseña temporal válida por 24 h que deberá cambiar al entrar.",
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
        await loaded();
        await user.click(screen.getByRole("button", { name: /^Desactivados/ }));
        await user.click(screen.getByRole("button", { name: "Reactivar acceso de Luis Pardo" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message));
        await waitFor(() => expect(get.mock.calls.filter(([u]) => u.includes("archived=true")).length).toBe(2));
    });

    it("advierte al reactivar a un veterinario sin cédula", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reactivate");
        inactiveRows = [{ ...FORMER, role: "VET", attends_patients: true }];
        post.mockResolvedValueOnce({ data: { temp_password: "x", expires_in_seconds: 86400 } });
        renderStaff();
        await loaded();
        await user.click(screen.getByRole("button", { name: /^Desactivados/ }));
        await user.click(screen.getByRole("button", { name: "Reactivar acceso de Luis Pardo" }));
        expect(confirmMock.mock.calls[0][0].message).toMatch(/No tiene cédula profesional registrada/);
    });

    it("sin desactivados muestra un estado vacío", async () => {
        const user = userEvent.setup({ delay: null });
        granted.add("staff.reactivate");
        renderStaff();
        await loaded();
        await user.click(screen.getByRole("button", { name: /^Desactivados/ }));
        expect(screen.getByText("Sin integrantes en «Desactivados»")).toBeInTheDocument();
    });

    it("getStaff() sin argumentos no envía parámetros (regresión de Citas)", async () => {
        await getStaff();
        expect(get).toHaveBeenLastCalledWith("staff/");
    });
});
