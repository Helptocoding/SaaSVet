/**
 * Ficha del integrante en panel lateral (rediseño Equipo 2026-11-25; ADR p67 y
 * p69). Se abre desde Equipo con `?member=<uuid>`; `/staff/:publicId` redirige.
 *
 * Conserva lo que protegía la página de ficha (citas por atender y su
 * reasignación, ausencias, historial, guarda de ruta, 404) y añade el guardado
 * único de datos, rol y permisos. Se usan los módulos reales `api/staff` y
 * `api/appointments`; solo se sustituye el cliente HTTP. El selector de fecha se
 * reemplaza por un campo de texto: su calendario ya tiene sus propias pruebas.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const del = vi.fn();
vi.mock("../../api/client", () => ({
    default: {
        get: (...a) => get(...a),
        post: (...a) => post(...a),
        patch: (...a) => patch(...a),
        delete: (...a) => del(...a),
    },
}));
let granted = new Set();
const can = (code) => granted.has(code);
const canAny = (codes) => codes.some((code) => granted.has(code));
const ADMIN_USER = { id: 1, role: "ADMIN", organization_timezone: "UTC" };
let currentUser = ADMIN_USER;
const refreshUser = vi.fn();
vi.mock("../../auth/authContext", () => ({
    useAuth: () => ({ user: currentUser, initializing: false, can, canAny, refreshUser }),
}));
const confirmMock = vi.fn(() => Promise.resolve(true));
vi.mock("../../components/useConfirm", () => ({ useConfirm: () => (...a) => confirmMock(...a) }));
vi.mock("sonner", () => ({
    toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), info: vi.fn(), promise: vi.fn() }),
}));
vi.mock("../../components/DateField", () => ({
    default: ({ id, value, onChange, disabled }) => (
        <input id={id} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
    ),
}));

import { toast } from "sonner";
import Staff, { StaffMemberRedirect } from "../../pages/staff";

const CATALOG = {
    signing_permission: "prescription.create",
    reserved: ["staff.create", "staff.manage_permissions"],
    roles: {
        ADMIN: ["appointment.list", "billing.refund", "organization.update", "prescription.create", "staff.create", "staff.manage_permissions"],
        VET: ["appointment.list", "prescription.create"],
        ASSISTANT: ["appointment.list"],
    },
    areas: [
        { key: "clinical", label: "Clínica", groups: [
            { key: "prescriptions", label: "Recetas", permissions: [{ code: "prescription.create", label: "Emitir y firmar recetas", reserved: false }] },
        ] },
        { key: "operation", label: "Operación", groups: [
            { key: "appointments", label: "Citas", permissions: [{ code: "appointment.list", label: "Ver la agenda", reserved: false }] },
            { key: "billing", label: "Cobros", permissions: [{ code: "billing.refund", label: "Hacer devoluciones", reserved: false }] },
        ] },
        { key: "administration", label: "Administración", groups: [
            { key: "team", label: "Equipo", permissions: [
                { code: "staff.create", label: "Dar de alta integrantes", reserved: true },
                { code: "staff.manage_permissions", label: "Conceder o quitar permisos", reserved: true },
            ] },
            { key: "clinic_settings", label: "Configuración", permissions: [{ code: "organization.update", label: "Editar datos de la clínica", reserved: false }] },
        ] },
    ],
};

const ACCESS = { status: "active", last_login: "2026-11-24T10:00:00Z", temp_password_expires_at: null };
const NO_OVERRIDES = { granted: [], revoked: [] };
const VET = {
    id: 3, public_id: "vet-uuid", username: "ana", email: "ana@vet.mx",
    first_name: "Ana", last_name: "Galeno", role: "VET", attends_patients: true,
    specialties: ["surgery"], specialty_label: "Cirugía", license_number: "1234567", is_active: true, access: ACCESS,
    permissions: CATALOG.roles.VET, permission_overrides: NO_OVERRIDES,
};
const OTHER_VET = { ...VET, id: 4, public_id: "luis-uuid", username: "luis", first_name: "Luis", last_name: "Pérez" };
const ASSISTANT = {
    ...VET, id: 5, public_id: "rosa-uuid", username: "rosa", email: "rosa@vet.mx", first_name: "Rosa", last_name: "Mora",
    role: "ASSISTANT", attends_patients: false, specialties: [], specialty_label: "", license_number: "",
    permissions: CATALOG.roles.ASSISTANT,
};
const SELF_ADMIN = {
    ...VET, id: 1, public_id: "admin-uuid", username: "ada", email: "ada@vet.mx", first_name: "Ada", last_name: "Admin",
    role: "ADMIN", attends_patients: false, specialties: [], license_number: "", permissions: CATALOG.roles.ADMIN,
};

const appt = (publicId, date, time, pet) => ({
    public_id: publicId, date, start_time: time, end_time: "10:30", status: "scheduled",
    reason: "Vacuna", pet_name: pet, owner_name: "Carla",
    expected_state: { status: "scheduled", date, start_time: time },
});
const A1 = appt("a1", "2026-12-01", "10:00", "Luna");
const A2 = appt("a2", "2026-12-02", "11:00", "Max");
const ABSENCE = {
    public_id: "abs-1", member: 3, member_public_id: "vet-uuid", member_name: "Ana Galeno",
    start_date: "2026-12-10", end_date: "2026-12-12", kind: "vacation", kind_label: "Vacaciones",
    created_at: "2026-11-24T10:00:00Z", created_by_name: "Ada Admin",
};

const MANAGER = [
    "staff.list", "staff.update", "staff.change_role", "staff.manage_permissions", "staff.manage_absences",
    "staff.reset_password", "staff.destroy", "staff.reactivate", "appointment.update",
];
let responses;

function Where() {
    const location = useLocation();
    return <p data-testid="where">{location.pathname}{location.search}</p>;
}

function renderDrawer(path = "/staff?member=vet-uuid") {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path="/staff" element={<><Staff /><Where /></>} />
                <Route path="/staff/:publicId" element={<StaffMemberRedirect />} />
                <Route path="/" element={<p>Inicio</p>} />
            </Routes>
        </MemoryRouter>,
    );
}

const drawer = () => screen.getByRole("dialog", { name: /Ana Galeno|Rosa Mora|Ada Admin|Ficha no disponible/ });
const openDrawer = async (name = "Ana Galeno") => {
    // La primera ficha de la suite carga muchos módulos: margen bajo carga paralela.
    await screen.findByRole("heading", { name: new RegExp(name) }, { timeout: 4000 });
    return screen.getByRole("dialog", { name: new RegExp(name) });
};
const openArea = async (user, dialog, area) => {
    await user.click(within(dialog).getByRole("button", { name: new RegExp(`^${area}`) }));
};
const showTab = async (user, dialog, name) => {
    await user.click(within(dialog).getByRole("tab", { name: new RegExp(`^${name}`) }));
};
const openAbsenceForm = async (user, dialog) => {
    await showTab(user, dialog, "Agenda");
    await user.click(within(dialog).getByRole("button", { name: "Nueva ausencia" }));
};

beforeEach(() => {
    vi.clearAllMocks();
    granted = new Set(MANAGER);
    currentUser = ADMIN_USER;
    responses = {
        profiles: { "vet-uuid": VET, "rosa-uuid": ASSISTANT, "admin-uuid": SELF_ADMIN },
        impact: { upcoming_appointments: 2, open_medical_records: 1, open_cash_session: false },
        appointments: [A1, A2],
        absences: [ABSENCE],
        history: [{ kind: "created", kind_label: "Alta", created_at: "2026-11-20T10:00:00Z", actor_name: "Ada Admin", changes: { role: "VET" } }],
        staff: [SELF_ADMIN, VET, OTHER_VET, ASSISTANT],
        inactive: [],
    };
    get.mockImplementation((url) => {
        const profile = url.match(/^staff\/([^/]+)\/profile\/$/);
        if (profile) {
            const found = responses.profiles[profile[1]];
            return found instanceof Error || !found
                ? Promise.reject(found || Object.assign(new Error("404"), { response: { status: 404, data: { code: "not_found" } } }))
                : Promise.resolve({ data: found });
        }
        const data = url === "staff/permission-catalog/" ? CATALOG
            : url.endsWith("/impact/") ? responses.impact
            : url.endsWith("/appointments/") ? responses.appointments
            : url === "staff/absences/" ? responses.absences
            : url.endsWith("/history/") ? responses.history
            : url.includes("archived=true") ? responses.inactive
            : responses.staff;
        return Promise.resolve({ data });
    });
    patch.mockImplementation((url, body) => Promise.resolve({ data: { ...VET, ...body } }));
    del.mockResolvedValue({ data: { ...ABSENCE } });
    confirmMock.mockImplementation(() => Promise.resolve(true));
});

describe("Ficha lateral: lo operativo (ADR p67)", () => {
    it("reúne rol, datos, acceso, citas, ausencias e historial en pestañas", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        expect(within(dialog).getAllByRole("tab").map((tab) => tab.textContent))
            .toEqual(["Perfil", "Permisos", "Agenda 2", "Historial"]);
        expect(within(dialog).getByRole("tab", { name: "Perfil" })).toHaveAttribute("aria-selected", "true");
        expect(within(dialog).queryByText("ana@vet.mx")).not.toBeInTheDocument(); // el correo vive en Datos, no en el encabezado
        expect(within(dialog).getByLabelText("CORREO ELECTRÓNICO *")).toHaveValue("ana@vet.mx");
        // Lo de otras pestañas no se ve hasta abrirlas.
        expect(within(dialog).queryByRole("list", { name: "Citas por atender" })).not.toBeInTheDocument();
        await showTab(user, dialog, "Agenda");
        expect(within(dialog).getByLabelText("CORREO ELECTRÓNICO *")).not.toBeVisible();
        const citas = within(dialog).getByRole("list", { name: "Citas por atender" });
        expect(within(citas).getAllByRole("listitem")).toHaveLength(2);
        expect(within(citas).getByText(/Luna/)).toBeInTheDocument();
        expect(within(dialog).getByText("Además tiene 1 consulta abierta.")).toBeInTheDocument();
        const ausencias = within(dialog).getByRole("list", { name: "Ausencias" });
        expect(within(ausencias).getByText(/^Vacaciones ·/)).toBeInTheDocument();
        expect(within(ausencias).getByText("Registró Ada Admin")).toBeInTheDocument();
        await showTab(user, dialog, "Historial");
        const historial = within(dialog).getByRole("list", { name: "Historial" });
        expect(within(historial).getByText("Alta como veterinario")).toBeInTheDocument();
        expect(get).toHaveBeenCalledWith("staff/absences/", { params: { member: "vet-uuid" } });
    });

    it("/staff/:publicId abre la ficha sobre Equipo", async () => {
        renderDrawer("/staff/vet-uuid");
        await openDrawer();
        expect(screen.getByTestId("where")).toHaveTextContent("/staff?member=vet-uuid");
    });

    it("reasigna todas las citas a otro veterinario y muestra las que no se movieron", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockResolvedValueOnce({ data: {
            moved: ["a1"],
            skipped: [{ public_id: "a2", code: "slot_taken", message: "El veterinario destino ya tiene una cita en ese horario." }],
        } });
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Agenda");
        await user.click(within(dialog).getByRole("button", { name: "Reasignar citas" }));
        const reassign = screen.getByRole("dialog", { name: "Reasignar citas de Ana Galeno" });
        const select = within(reassign).getByLabelText("Las atenderá");
        // Solo otros que atienden pacientes: ni ella misma ni la asistente.
        expect(within(select).getAllByRole("option").map((o) => o.textContent))
            .toEqual(["Selecciona un veterinario", "Luis Pérez"]);
        await user.selectOptions(select, "luis-uuid");
        await user.click(within(reassign).getByRole("button", { name: "Reasignar 2 citas" }));
        await waitFor(() => expect(post).toHaveBeenCalledWith("appointments/reassign/", {
            source_public_id: "vet-uuid",
            target_public_id: "luis-uuid",
            appointments: [
                { public_id: "a1", expected_state: A1.expected_state },
                { public_id: "a2", expected_state: A2.expected_state },
            ],
        }));
        expect(await within(reassign).findByText("Se reasignaron 1 de 2.")).toBeInTheDocument();
        expect(within(reassign).getByText("El veterinario destino ya tiene una cita en ese horario.")).toBeInTheDocument();
        expect(toast.success).toHaveBeenCalledWith("1 cita reasignada");
    });

    it("no envía la reasignación sin elegir destino", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Agenda");
        await user.click(within(dialog).getByRole("button", { name: "Reasignar citas" }));
        await user.click(screen.getByRole("button", { name: "Reasignar 2 citas" }));
        expect(post).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith("Elige quién atenderá las citas");
    });

    it("registra una ausencia y ofrece reasignar las citas de esos días", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockResolvedValueOnce({ data: { absence: { ...ABSENCE, public_id: "abs-2" }, affected_appointments: [A1] } });
        renderDrawer();
        const dialog = await openDrawer();
        await openAbsenceForm(user, dialog);
        await user.type(within(dialog).getByLabelText("Primer día"), "2026-12-01");
        await user.type(within(dialog).getByLabelText("Último día"), "2026-12-01");
        await user.selectOptions(within(dialog).getByLabelText("Tipo"), "training");
        await user.click(within(dialog).getByRole("button", { name: "Registrar ausencia" }));
        await waitFor(() => expect(post).toHaveBeenCalledWith("staff/vet-uuid/absences/", {
            start_date: "2026-12-01", end_date: "2026-12-01", kind: "training",
        }));
        expect(toast.success).toHaveBeenCalledWith("Ausencia registrada");
        const reassign = await screen.findByRole("dialog", { name: "Reasignar citas de Ana Galeno" });
        expect(within(reassign).getByRole("button", { name: "Reasignar 1 cita" })).toBeInTheDocument();
    });

    it("valida las fechas de la ausencia antes de enviar", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        await openAbsenceForm(user, dialog);
        await user.type(within(dialog).getByLabelText("Primer día"), "2026-12-05");
        await user.type(within(dialog).getByLabelText("Último día"), "2026-12-01");
        await user.click(within(dialog).getByRole("button", { name: "Registrar ausencia" }));
        expect(within(dialog).getByText("El último día no puede ser anterior al primero")).toBeInTheDocument();
        expect(post).not.toHaveBeenCalled();
    });

    it("el cruce de ausencias del servidor llega como aviso", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockRejectedValueOnce({ response: { status: 409, data: {
            code: "absence_overlap", message: "Ya hay una ausencia registrada que se cruza con esas fechas." } } });
        renderDrawer();
        const dialog = await openDrawer();
        await openAbsenceForm(user, dialog);
        await user.type(within(dialog).getByLabelText("Primer día"), "2026-12-11");
        await user.type(within(dialog).getByLabelText("Último día"), "2026-12-11");
        await user.click(within(dialog).getByRole("button", { name: "Registrar ausencia" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
            "Ya hay una ausencia registrada que se cruza con esas fechas.",
        ));
    });

    it("cancela una ausencia tras confirmar", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Agenda");
        await user.click(within(dialog).getByRole("button", { name: /Cancelar ausencia del/ }));
        await waitFor(() => expect(del).toHaveBeenCalledWith("staff/absences/abs-1/"));
        expect(confirmMock.mock.calls[0][0]).toMatchObject({ title: "Cancelar ausencia", dangerMode: true });
        expect(toast.success).toHaveBeenCalledWith("Ausencia cancelada");
    });

    it("sin permisos de ausencias ni de citas no ofrece esas acciones", async () => {
        const user = userEvent.setup({ delay: null });
        granted = new Set(["staff.list", "staff.update"]);
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Agenda");
        expect(within(dialog).queryByRole("button", { name: "Nueva ausencia" })).not.toBeInTheDocument();
        expect(within(dialog).queryByRole("button", { name: "Registrar ausencia" })).not.toBeInTheDocument();
        expect(within(dialog).queryByRole("button", { name: /Cancelar ausencia del/ })).not.toBeInTheDocument();
        expect(within(dialog).queryByRole("button", { name: "Reasignar citas" })).not.toBeInTheDocument();
    });

    it("de un desactivado se pueden reasignar citas pero no registrar ausencias ni editar", async () => {
        const user = userEvent.setup({ delay: null });
        responses.profiles["vet-uuid"] = { ...VET, is_active: false, access: { ...ACCESS, status: "inactive" } };
        renderDrawer();
        const dialog = await openDrawer();
        expect(within(dialog).getAllByText("Desactivado").length).toBeGreaterThan(0);
        await showTab(user, dialog, "Agenda");
        expect(within(dialog).getByRole("button", { name: "Reasignar citas" })).toBeInTheDocument();
        expect(within(dialog).queryByRole("button", { name: "Nueva ausencia" })).not.toBeInTheDocument();
        expect(within(dialog).queryByRole("button", { name: "Guardar cambios" })).not.toBeInTheDocument();
        expect(within(dialog).getByRole("button", { name: "Reactivar acceso" })).toBeInTheDocument();
    });

    it("quien no gestiona personal vuelve al inicio y no se pide nada", async () => {
        granted = new Set(["staff.list"]);
        renderDrawer();
        expect(await screen.findByText("Inicio")).toBeInTheDocument();
        expect(get).not.toHaveBeenCalled();
    });

    it("un integrante que no existe en la clínica se dice claro y la ficha se cierra", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer("/staff?member=otro-uuid");
        expect(await screen.findByText("No encontramos a este integrante en tu clínica.")).toBeInTheDocument();
        await user.click(within(drawer()).getByRole("button", { name: "Cerrar ficha" }));
        expect(screen.getByTestId("where")).toHaveTextContent(/^\/staff$/);
    });
});

describe("Ficha lateral: guardar datos y rol", () => {
    it("guarda solo lo que cambió en un PATCH, con la cédula normalizada", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        const license = within(dialog).getByLabelText(/CÉDULA PROFESIONAL/);
        await user.clear(license);
        await user.type(license, " 7654321 ");
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", { license_number: "7654321" }));
        expect(toast.success).toHaveBeenCalledWith("Cambios guardados");
    });

    it("sin cambios no se puede guardar, y cerrar con cambios pide confirmación", async () => {
        const user = userEvent.setup({ delay: null });
        confirmMock.mockImplementationOnce(() => Promise.resolve(false));
        renderDrawer();
        const dialog = await openDrawer();
        expect(within(dialog).getByRole("button", { name: "Guardar cambios" })).toBeDisabled();
        await user.type(within(dialog).getByLabelText("NOMBRE *"), "x");
        await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));
        expect(confirmMock.mock.calls[0][0]).toMatchObject({ title: "¿Descartar los cambios?" });
        expect(screen.getByRole("dialog", { name: /Ana Galeno/ })).toBeInTheDocument();
    });

    it("Escape cierra la ficha sin cambios", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        await openDrawer();
        await user.keyboard("{Escape}");
        await waitFor(() => expect(screen.queryByRole("dialog", { name: /Ana Galeno/ })).not.toBeInTheDocument());
        expect(screen.getByTestId("where")).toHaveTextContent(/^\/staff$/);
    });

    it("un error del servidor aparece en su campo", async () => {
        const user = userEvent.setup({ delay: null });
        patch.mockRejectedValueOnce({ response: { status: 400, data: {
            code: "validation_error", errors: { email: ["No se pudo usar ese correo."] } } } });
        renderDrawer();
        const dialog = await openDrawer();
        const email = within(dialog).getByLabelText("CORREO ELECTRÓNICO *");
        await user.clear(email);
        await user.type(email, "otra@vet.mx");
        expect(within(dialog).getByText(/entrará con el correo nuevo/)).toBeInTheDocument();
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        expect(await within(dialog).findByText("No se pudo usar ese correo.")).toBeInTheDocument();
    });

    it("pasar a veterinario a quien no tiene cédula no se envía y lo dice en el campo", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer("/staff?member=rosa-uuid");
        const dialog = await openDrawer("Rosa Mora");
        await user.click(within(dialog).getByRole("radio", { name: /Veterinario/ }));
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        expect(within(dialog).getByText("La cédula profesional es obligatoria para veterinarios")).toBeInTheDocument();
        expect(patch).not.toHaveBeenCalled();
    });

    it("cambia rol y datos en un solo PATCH", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer("/staff?member=rosa-uuid");
        const dialog = await openDrawer("Rosa Mora");
        await user.click(within(dialog).getByRole("radio", { name: /Veterinario/ }));
        await user.type(within(dialog).getByLabelText(/CÉDULA PROFESIONAL/), "7654321");
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/rosa-uuid/", {
            license_number: "7654321", role: "VET",
        }));
    });

    it("al quitarle la función clínica avisa de sus citas", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        await user.click(within(dialog).getByRole("radio", { name: /Asistente/ }));
        expect(within(dialog).getByText(/Tiene 2 citas próximas y 1 consulta abierta a su nombre/)).toBeInTheDocument();
    });

    it("no se cambia el propio rol ni el del único administrador", async () => {
        currentUser = { ...ADMIN_USER };
        renderDrawer("/staff?member=admin-uuid");
        const dialog = await openDrawer("Ada Admin");
        expect(within(dialog).getByRole("radio", { name: /Veterinario/ })).toBeDisabled();
        expect(within(dialog).getByText("No puedes cambiar tu propio rol.")).toBeInTheDocument();
    });

    it("sin staff.change_role el rol se ve pero no se cambia", async () => {
        granted = new Set(["staff.list", "staff.update"]);
        renderDrawer();
        const dialog = await openDrawer();
        expect(within(dialog).getByRole("radio", { name: /Veterinario/ })).toBeChecked();
        expect(within(dialog).getByRole("radio", { name: /Asistente/ })).toBeDisabled();
    });

    it("«Completar cédula» lleva al campo", async () => {
        const user = userEvent.setup({ delay: null });
        responses.profiles["vet-uuid"] = { ...VET, license_number: "" };
        renderDrawer();
        const dialog = await openDrawer();
        expect(within(dialog).getByText("No puede firmar recetas: falta su cédula profesional.")).toBeInTheDocument();
        await user.click(within(dialog).getByRole("button", { name: "Completar cédula" }));
        expect(within(dialog).getByLabelText(/CÉDULA PROFESIONAL/)).toHaveFocus();
    });

    it("una invitación vencida se reenvía desde la ficha y muestra la temporal", async () => {
        const user = userEvent.setup({ delay: null });
        responses.profiles["vet-uuid"] = {
            ...VET, access: { status: "temp_password_expired", last_login: null, temp_password_expires_at: "2026-11-22T10:00:00Z" },
        };
        post.mockResolvedValueOnce({ data: { temp_password: "Temp-123", expires_in_seconds: 86400 } });
        renderDrawer();
        const dialog = await openDrawer();
        await user.click(within(dialog).getAllByRole("button", { name: "Reenviar invitación" })[0]);
        await waitFor(() => expect(post).toHaveBeenCalledWith("staff/vet-uuid/reset-password/", {}, expect.anything()));
        expect(await screen.findByRole("dialog", { name: "Contraseña temporal generada" })).toBeInTheDocument();
        expect(confirmMock.mock.calls[0][0]).toMatchObject({ title: "Reenviar invitación" });
    });

    it("desactiva desde el pie de la ficha", async () => {
        const user = userEvent.setup({ delay: null });
        responses.impact = { upcoming_appointments: 0, open_medical_records: 0, open_cash_session: false };
        renderDrawer();
        const dialog = await openDrawer();
        await user.click(within(dialog).getByRole("button", { name: "Desactivar acceso" }));
        await waitFor(() => expect(del).toHaveBeenCalledWith("staff/vet-uuid/"));
        expect(confirmMock.mock.calls.at(-1)[0]).toMatchObject({ title: "Desactivar acceso de Ana Galeno", dangerMode: true });
    });
});

describe("Ficha lateral: permisos por integrante (ADR p69)", () => {
    it("concede un permiso extra y lo envía como lista efectiva", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Permisos");
        expect(within(dialog).getByText("Los permisos de Veterinario, sin ajustes.")).toBeVisible();
        await openArea(user, dialog, "Operación");
        await user.click(within(dialog).getByRole("checkbox", { name: "Hacer devoluciones" }));
        expect(within(dialog).getByText("Extra al rol")).toBeInTheDocument();
        expect(within(dialog).getByText("Permisos de Veterinario con 1 extra.")).toBeInTheDocument();
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", {
            permissions: ["appointment.list", "billing.refund", "prescription.create"],
            // §12: los que veía al abrir la ficha, tal como llegaron.
            expected_permissions: ["appointment.list", "prescription.create"],
        }));
    });

    it("si otro administrador cambió sus permisos, avisa, recarga y no reintenta", async () => {
        const user = userEvent.setup({ delay: null });
        const message = "Sus permisos cambiaron mientras los editabas. Revisa los actuales y vuelve a guardar.";
        patch.mockRejectedValueOnce({ response: { status: 409, data: {
            code: "permissions_changed", message, current: ["appointment.list", "billing.refund", "prescription.create"] } } });
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Permisos");
        await openArea(user, dialog, "Operación");
        await user.click(within(dialog).getByRole("checkbox", { name: "Hacer devoluciones" }));
        responses.profiles["vet-uuid"] = {
            ...VET, permissions: [...CATALOG.roles.VET, "billing.refund"], permission_overrides: { granted: ["billing.refund"], revoked: [] },
        };
        const profileLoads = () => get.mock.calls.filter(([url]) => url === "staff/vet-uuid/profile/").length;
        const before = profileLoads();
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message));
        await waitFor(() => expect(profileLoads()).toBe(before + 1));
        expect(patch).toHaveBeenCalledTimes(1);
        expect(await within(dialog).findByText("Permisos de Veterinario con 1 extra.")).toBeInTheDocument();
        expect(within(dialog).getByRole("button", { name: "Guardar cambios" })).toBeDisabled();
    });

    it("restaurar devuelve los permisos del rol", async () => {
        const user = userEvent.setup({ delay: null });
        responses.profiles["vet-uuid"] = {
            ...VET, permissions: ["prescription.create"], permission_overrides: { granted: [], revoked: ["appointment.list"] },
        };
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Permisos");
        expect(within(dialog).getByText("Permisos de Veterinario con 1 quitado.")).toBeVisible();
        await user.click(within(dialog).getByRole("button", { name: /Restaurar valores del rol/ }));
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", {
            permissions: ["appointment.list", "prescription.create"],
            expected_permissions: ["prescription.create"],
        }));
    });

    it("los permisos reservados no se conceden a otro rol", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Permisos");
        await openArea(user, dialog, "Administración");
        const reserved = within(dialog).getByRole("checkbox", { name: "Dar de alta integrantes" });
        expect(reserved).toBeDisabled();
        expect(reserved).not.toBeChecked();
        expect(reserved).toHaveAccessibleDescription("Solo administradores");
    });

    it("nadie se quita a sí mismo permisos de administración", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer("/staff?member=admin-uuid");
        const dialog = await openDrawer("Ada Admin");
        await showTab(user, dialog, "Permisos");
        await openArea(user, dialog, "Administración");
        const own = within(dialog).getByRole("checkbox", { name: "Editar datos de la clínica" });
        expect(own).toBeDisabled();
        expect(own).toHaveAccessibleDescription("No puedes quitarte permisos de administración");
        await openArea(user, dialog, "Operación");
        expect(within(dialog).getByRole("checkbox", { name: "Hacer devoluciones" })).toBeEnabled();
    });

    it("al cambiar de rol con ajustes pregunta si se conservan y envía la decisión", async () => {
        const user = userEvent.setup({ delay: null });
        responses.profiles["vet-uuid"] = {
            ...VET, permissions: [...CATALOG.roles.VET, "billing.refund"], permission_overrides: { granted: ["billing.refund"], revoked: [] },
        };
        renderDrawer();
        const dialog = await openDrawer();
        await user.click(within(dialog).getByRole("radio", { name: /Asistente/ }));
        expect(within(dialog).getByText(/Tiene permisos ajustados/)).toBeInTheDocument();
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        expect(toast.error).toHaveBeenCalledWith("Elige qué pasa con sus permisos personalizados.");
        expect(patch).not.toHaveBeenCalled();
        await user.click(within(dialog).getByRole("radio", { name: "Conservar ajustes" }));
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", {
            specialties: [], role: "ASSISTANT", keep_custom_permissions: true,
        }));
    });

    it("usar solo los del rol nuevo cambia la vista previa", async () => {
        const user = userEvent.setup({ delay: null });
        responses.profiles["vet-uuid"] = {
            ...VET, permissions: [...CATALOG.roles.VET, "billing.refund"], permission_overrides: { granted: ["billing.refund"], revoked: [] },
        };
        renderDrawer();
        const dialog = await openDrawer();
        await user.click(within(dialog).getByRole("radio", { name: /Asistente/ }));
        await user.click(within(dialog).getByRole("radio", { name: "Usar los de Asistente" }));
        await showTab(user, dialog, "Permisos");
        expect(within(dialog).getByText("Los permisos de Asistente, sin ajustes.")).toBeVisible();
    });

    it("sin staff.manage_permissions los permisos se ven pero no se cambian", async () => {
        const user = userEvent.setup({ delay: null });
        granted = new Set(["staff.list", "staff.update"]);
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Permisos");
        expect(within(dialog).getByText("Solo un administrador puede conceder o quitar permisos.")).toBeVisible();
        await openArea(user, dialog, "Clínica");
        expect(within(dialog).getByRole("checkbox", { name: "Emitir y firmar recetas" })).toBeDisabled();
        expect(within(dialog).queryByRole("button", { name: /Restaurar valores del rol/ })).not.toBeInTheDocument();
    });

    it("el historial nombra los permisos concedidos con el catálogo", async () => {
        const user = userEvent.setup({ delay: null });
        responses.history = [{
            kind: "permissions_changed", kind_label: "Cambio de permisos", created_at: "2026-11-25T10:00:00Z",
            actor_name: "Ada Admin", changes: { granted: ["billing.refund"], revoked: [], restored: [] },
        }];
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Historial");
        expect(within(dialog).getByText("Le concedió hacer devoluciones")).toBeVisible();
    });
});

describe("Ficha lateral: pestañas y menos ruido (2026-11-25)", () => {
    it("las flechas recorren las pestañas y solo la activa está en el orden de tabulación", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        const perfil = within(dialog).getByRole("tab", { name: "Perfil" });
        expect(perfil).toHaveAttribute("tabindex", "0");
        expect(within(dialog).getByRole("tab", { name: "Permisos" })).toHaveAttribute("tabindex", "-1");
        perfil.focus();
        await user.keyboard("{ArrowRight}");
        const permisos = within(dialog).getByRole("tab", { name: "Permisos" });
        expect(permisos).toHaveFocus();
        expect(permisos).toHaveAttribute("aria-selected", "true");
        await user.keyboard("{End}");
        expect(within(dialog).getByRole("tab", { name: "Historial" })).toHaveFocus();
        await user.keyboard("{ArrowRight}");
        expect(within(dialog).getByRole("tab", { name: "Perfil" })).toHaveFocus();
        expect(within(dialog).getByRole("tabpanel", { name: "Perfil" })).toBeVisible();
    });

    it("marca la pestaña con cambios sin guardar", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        expect(within(dialog).queryByRole("tab", { name: /cambios sin guardar/ })).not.toBeInTheDocument();
        await user.type(within(dialog).getByLabelText("NOMBRE *"), "x");
        expect(within(dialog).getByRole("tab", { name: "Perfil, con cambios sin guardar" })).toBeInTheDocument();
        await showTab(user, dialog, "Permisos");
        await openArea(user, dialog, "Operación");
        await user.click(within(dialog).getByRole("checkbox", { name: "Hacer devoluciones" }));
        expect(within(dialog).getByRole("tab", { name: "Permisos, con cambios sin guardar" })).toBeInTheDocument();
    });

    it("un error de un dato del perfil vuelve a esa pestaña al guardar desde otra", async () => {
        const user = userEvent.setup({ delay: null });
        patch.mockRejectedValueOnce({ response: { status: 400, data: {
            code: "validation_error", errors: { email: ["No se pudo usar ese correo."] } } } });
        renderDrawer();
        const dialog = await openDrawer();
        const email = within(dialog).getByLabelText("CORREO ELECTRÓNICO *");
        await user.clear(email);
        await user.type(email, "otra@vet.mx");
        await showTab(user, dialog, "Historial");
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        expect(await within(dialog).findByText("No se pudo usar ese correo.")).toBeVisible();
        expect(within(dialog).getByRole("tab", { name: /^Perfil/ })).toHaveAttribute("aria-selected", "true");
    });

    it("el alcance del rol solo aparece al elegir otro", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer("/staff?member=rosa-uuid");
        const dialog = await openDrawer("Rosa Mora");
        expect(within(dialog).queryByText(/No cobra ni administra/)).not.toBeInTheDocument();
        await user.click(within(dialog).getByRole("radio", { name: /Veterinario/ }));
        expect(within(dialog).getByText(/No cobra ni administra/)).toBeInTheDocument();
    });

    it("las especialidades se ven en una línea y el catálogo se abre al pedirlo", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        expect(within(dialog).getByText("Cirugía", { selector: "span" })).toBeInTheDocument();
        expect(within(dialog).queryByRole("checkbox", { name: "Dermatología" })).not.toBeInTheDocument();
        await user.click(within(dialog).getByRole("button", { name: "Cambiar especialidades" }));
        await user.click(within(dialog).getByRole("checkbox", { name: "Dermatología" }));
        await user.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(patch).toHaveBeenCalledWith("staff/vet-uuid/", {
            specialties: ["surgery", "dermatology"],
        }));
    });

    it("el formulario de ausencia se abre con «Nueva ausencia» y se cierra sin enviar", async () => {
        const user = userEvent.setup({ delay: null });
        renderDrawer();
        const dialog = await openDrawer();
        await showTab(user, dialog, "Agenda");
        expect(within(dialog).queryByLabelText("Primer día")).not.toBeInTheDocument();
        await user.click(within(dialog).getByRole("button", { name: "Nueva ausencia" }));
        await user.type(within(dialog).getByLabelText("Primer día"), "2026-12-01");
        await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));
        expect(within(dialog).queryByLabelText("Primer día")).not.toBeInTheDocument();
        expect(post).not.toHaveBeenCalled();
    });
});
