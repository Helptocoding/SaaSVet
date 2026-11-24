/**
 * Ficha del integrante (ADR p67): datos, pendientes, citas por atender con
 * reasignación en bloque, ausencias (registrar y cancelar) e historial. Se usan
 * los módulos reales `api/staff` y `api/appointments`; solo se sustituye el
 * cliente HTTP. El selector de fecha se reemplaza por un campo de texto: su
 * calendario ya tiene sus propias pruebas.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const del = vi.fn();
vi.mock("../api/client", () => ({
    default: {
        get: (...a) => get(...a),
        post: (...a) => post(...a),
        patch: vi.fn(),
        delete: (...a) => del(...a),
    },
}));
let granted = new Set();
const can = (code) => granted.has(code);
const canAny = (codes) => codes.some((code) => granted.has(code));
const ADMIN = { id: 1, role: "ADMIN", organization_timezone: "UTC" };
vi.mock("../auth/authContext", () => ({
    useAuth: () => ({ user: ADMIN, initializing: false, can, canAny }),
}));
const confirmMock = vi.fn(() => Promise.resolve(true));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => (...a) => confirmMock(...a) }));
vi.mock("sonner", () => ({
    toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), info: vi.fn(), promise: vi.fn() }),
}));
vi.mock("../components/DateField", () => ({
    default: ({ id, value, onChange, disabled }) => (
        <input id={id} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
    ),
}));

import { toast } from "sonner";
import StaffMember from "./staffMember";

const ACCESS = { status: "active", last_login: null, temp_password_expires_at: null };
const VET = {
    id: 3, public_id: "vet-uuid", username: "ana", email: "ana@vet.mx",
    first_name: "Ana", last_name: "Galeno", role: "VET", attends_patients: true,
    specialty: "Cirugía", license_number: "1234567", is_active: true, access: ACCESS,
};
const OTHER_VET = { ...VET, id: 4, public_id: "luis-uuid", username: "luis", first_name: "Luis", last_name: "Pérez" };
const ASSISTANT = { ...VET, id: 5, public_id: "rosa-uuid", first_name: "Rosa", last_name: "Mora", role: "ASSISTANT", attends_patients: false };

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

let responses;
const MANAGER = ["staff.list", "staff.update", "staff.manage_absences", "appointment.update"];

function renderPage(path = "/staff/vet-uuid") {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path="/staff/:publicId" element={<StaffMember />} />
                <Route path="/staff" element={<p>Equipo</p>} />
                <Route path="/" element={<p>Inicio</p>} />
            </Routes>
        </MemoryRouter>,
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    granted = new Set(MANAGER);
    responses = {
        profile: VET,
        impact: { upcoming_appointments: 2, open_medical_records: 0, open_cash_session: false },
        appointments: [A1, A2],
        absences: [ABSENCE],
        history: [{ kind: "created", kind_label: "Alta", created_at: "2026-11-20T10:00:00Z", actor_name: "Ada Admin", changes: { role: "VET" } }],
        staff: [VET, OTHER_VET, ASSISTANT],
    };
    get.mockImplementation((url) => {
        if (url.endsWith("/profile/")) {
            return responses.profile instanceof Error ? Promise.reject(responses.profile) : Promise.resolve({ data: responses.profile });
        }
        const data = url.endsWith("/impact/") ? responses.impact
            : url.endsWith("/appointments/") ? responses.appointments
            : url === "staff/absences/" ? responses.absences
            : url.endsWith("/history/") ? responses.history
            : responses.staff;
        return Promise.resolve({ data });
    });
    del.mockResolvedValue({ data: { ...ABSENCE } });
    confirmMock.mockImplementation(() => Promise.resolve(true));
});

describe("Ficha del integrante (ADR p67)", () => {
    it("reúne datos, pendientes, citas, ausencias e historial", async () => {
        renderPage();
        expect(await screen.findByRole("heading", { name: "Ana Galeno" })).toBeInTheDocument();
        expect(screen.getByText(/Atiende pacientes · 2 citas por atender · 0 consultas abiertas/)).toBeInTheDocument();
        expect(screen.getByText("ana@vet.mx")).toBeInTheDocument();
        const citas = screen.getByRole("list", { name: "Citas por atender" });
        expect(within(citas).getAllByRole("listitem")).toHaveLength(2);
        expect(within(citas).getByText(/Luna/)).toBeInTheDocument();
        const ausencias = screen.getByRole("list", { name: "Ausencias" });
        expect(within(ausencias).getByText(/^Vacaciones ·/)).toBeInTheDocument();
        expect(within(ausencias).getByText("Registró Ada Admin")).toBeInTheDocument();
        expect(screen.getByText("Alta como veterinario")).toBeInTheDocument();
        expect(get).toHaveBeenCalledWith("staff/absences/", { params: { member: "vet-uuid" } });
    });

    it("reasigna todas las citas a otro veterinario y muestra las que no se movieron", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockResolvedValueOnce({ data: {
            moved: ["a1"],
            skipped: [{ public_id: "a2", code: "slot_taken", message: "El veterinario destino ya tiene una cita en ese horario." }],
        } });
        renderPage();
        await user.click(await screen.findByRole("button", { name: "Reasignar citas" }));
        const dialog = screen.getByRole("dialog", { name: "Reasignar citas de Ana Galeno" });
        const select = within(dialog).getByLabelText("Las atenderá");
        // Solo otros que atienden pacientes: ni ella misma ni la asistente.
        expect(within(select).getAllByRole("option").map((o) => o.textContent))
            .toEqual(["Selecciona un veterinario", "Luis Pérez"]);
        await user.selectOptions(select, "luis-uuid");
        await user.click(within(dialog).getByRole("button", { name: "Reasignar 2 citas" }));
        await waitFor(() => expect(post).toHaveBeenCalledWith("appointments/reassign/", {
            source_public_id: "vet-uuid",
            target_public_id: "luis-uuid",
            appointments: [
                { public_id: "a1", expected_state: A1.expected_state },
                { public_id: "a2", expected_state: A2.expected_state },
            ],
        }));
        expect(await within(dialog).findByText("Se reasignaron 1 de 2.")).toBeInTheDocument();
        expect(within(dialog).getByText("El veterinario destino ya tiene una cita en ese horario.")).toBeInTheDocument();
        expect(toast.success).toHaveBeenCalledWith("1 cita reasignada");
    });

    it("no envía la reasignación sin elegir destino", async () => {
        const user = userEvent.setup({ delay: null });
        renderPage();
        await user.click(await screen.findByRole("button", { name: "Reasignar citas" }));
        await user.click(screen.getByRole("button", { name: "Reasignar 2 citas" }));
        expect(post).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith("Elige quién atenderá las citas");
    });

    it("registra una ausencia y ofrece reasignar las citas de esos días", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockResolvedValueOnce({ data: { absence: { ...ABSENCE, public_id: "abs-2" }, affected_appointments: [A1] } });
        renderPage();
        await screen.findByRole("heading", { name: "Ana Galeno" });
        await user.type(screen.getByLabelText("Primer día"), "2026-12-01");
        await user.type(screen.getByLabelText("Último día"), "2026-12-01");
        await user.selectOptions(screen.getByLabelText("Tipo"), "training");
        await user.click(screen.getByRole("button", { name: "Registrar ausencia" }));
        await waitFor(() => expect(post).toHaveBeenCalledWith("staff/vet-uuid/absences/", {
            start_date: "2026-12-01", end_date: "2026-12-01", kind: "training",
        }));
        expect(toast.success).toHaveBeenCalledWith("Ausencia registrada");
        const dialog = await screen.findByRole("dialog", { name: "Reasignar citas de Ana Galeno" });
        expect(within(dialog).getByRole("button", { name: "Reasignar 1 cita" })).toBeInTheDocument();
    });

    it("valida las fechas antes de enviar", async () => {
        const user = userEvent.setup({ delay: null });
        renderPage();
        await screen.findByRole("heading", { name: "Ana Galeno" });
        await user.type(screen.getByLabelText("Primer día"), "2026-12-05");
        await user.type(screen.getByLabelText("Último día"), "2026-12-01");
        await user.click(screen.getByRole("button", { name: "Registrar ausencia" }));
        expect(screen.getByText("El último día no puede ser anterior al primero")).toBeInTheDocument();
        expect(post).not.toHaveBeenCalled();
    });

    it("muestra en su campo un error del servidor y el cruce como aviso", async () => {
        const user = userEvent.setup({ delay: null });
        post.mockRejectedValueOnce({ response: { status: 409, data: {
            code: "absence_overlap", message: "Ya hay una ausencia registrada que se cruza con esas fechas." } } });
        renderPage();
        await screen.findByRole("heading", { name: "Ana Galeno" });
        await user.type(screen.getByLabelText("Primer día"), "2026-12-11");
        await user.type(screen.getByLabelText("Último día"), "2026-12-11");
        await user.click(screen.getByRole("button", { name: "Registrar ausencia" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
            "Ya hay una ausencia registrada que se cruza con esas fechas.",
        ));
    });

    it("cancela una ausencia tras confirmar", async () => {
        const user = userEvent.setup({ delay: null });
        renderPage();
        await user.click(await screen.findByRole("button", { name: /Cancelar ausencia del/ }));
        await waitFor(() => expect(del).toHaveBeenCalledWith("staff/absences/abs-1/"));
        expect(confirmMock.mock.calls[0][0]).toMatchObject({ title: "Cancelar ausencia", dangerMode: true });
        expect(toast.success).toHaveBeenCalledWith("Ausencia cancelada");
    });

    it("sin permisos de ausencias ni de citas no ofrece esas acciones", async () => {
        granted = new Set(["staff.list", "staff.update"]);
        renderPage();
        await screen.findByRole("heading", { name: "Ana Galeno" });
        expect(screen.queryByRole("button", { name: "Registrar ausencia" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /Cancelar ausencia del/ })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Reasignar citas" })).not.toBeInTheDocument();
    });

    it("de un inactivo se pueden reasignar citas pero no registrar ausencias", async () => {
        responses.profile = { ...VET, is_active: false };
        renderPage();
        expect(await screen.findByText("Inactivo")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Reasignar citas" })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Registrar ausencia" })).not.toBeInTheDocument();
    });

    it("quien no gestiona personal vuelve al inicio", async () => {
        granted = new Set(["staff.list"]);
        renderPage();
        expect(await screen.findByText("Inicio")).toBeInTheDocument();
        expect(get).not.toHaveBeenCalled();
    });

    it("un integrante que no existe en la clínica se dice claro", async () => {
        responses.profile = Object.assign(new Error("404"), { response: { status: 404, data: { code: "not_found" } } });
        renderPage("/staff/otro-uuid");
        expect(await screen.findByText("No encontramos a este integrante en tu clínica.")).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "← Equipo" })).toHaveAttribute("href", "/staff");
    });
});
