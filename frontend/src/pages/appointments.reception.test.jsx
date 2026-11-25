/**
 * Citas: crear, gestionar y atender se deciden por capacidad, no por rol (Fase 1
 * Equipo, §7; con ADR p69 los permisos son además por persona).
 *
 * Antes `canCreate = user.role !== "ASSISTANT"` dejaba a la recepción en
 * «Modo lectura» aunque el RBAC le concede `appointment.create` (ADR p63) y el
 * backend acepta sus citas (apps/appointments/tests/test_reception_scheduling.py).
 * La agenda real se renderiza; solo se sustituyen el calendario de FullCalendar
 * (no corre en jsdom), las llamadas HTTP y la sesión.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@fullcalendar/react", () => ({ default: () => <div data-testid="calendar" /> }));
vi.mock("@fullcalendar/daygrid", () => ({ default: {} }));
vi.mock("@fullcalendar/timegrid", () => ({ default: {} }));
vi.mock("@fullcalendar/interaction", () => ({ default: {} }));
vi.mock("@fullcalendar/core/locales/es", () => ({ default: {} }));

vi.mock("../api/appointments", () => ({
    getAppointments: vi.fn(() => Promise.resolve([])),
    createAppointment: vi.fn(),
    updateAppointment: vi.fn(),
    updateAppointmentStatus: vi.fn(),
    walkInAppointment: vi.fn(),
    getAppointmentHistory: vi.fn(() => Promise.resolve([])),
    assignPatient: vi.fn(),
    createAppointmentWithPatient: vi.fn(),
}));
vi.mock("../api/organizations", () => ({ getOrgSettings: vi.fn(() => Promise.resolve({})) }));
const absenceState = vi.hoisted(() => ({ rows: [] }));
vi.mock("../api/staff", () => ({
    getAbsences: vi.fn(() => Promise.resolve(absenceState.rows)),
    getStaff: vi.fn(() => Promise.resolve([
        { id: 3, public_id: "vet-uuid", first_name: "Eva", last_name: "Galeno", role: "VET", attends_patients: true },
        { id: 4, public_id: "owner-uuid", first_name: "Dora", last_name: "Dueña", role: "ADMIN", attends_patients: true },
        { id: 5, public_id: "office-uuid", first_name: "Olga", last_name: "Oficina", role: "ADMIN", attends_patients: false },
        { id: 6, public_id: "rec-uuid", first_name: "Rita", last_name: "Recepción", role: "ASSISTANT", attends_patients: false },
    ])),
}));
vi.mock("../api/lookups", () => ({ searchPets: vi.fn(() => Promise.resolve({ items: [], hasMore: false })) }));
vi.mock("../api/client", () => ({ default: { get: vi.fn(() => Promise.resolve({ data: {} })) } }));

let granted = new Set();
let currentUser = { id: 10, role: "ASSISTANT" };
vi.mock("../auth/authContext", () => ({
    useAuth: () => ({
        token: "t", initializing: false, user: currentUser,
        can: (code) => granted.has(code),
    }),
}));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => vi.fn(() => Promise.resolve(true)) }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }) }));

import Appointments from "./appointments";
import apiClient from "../api/client";
import { AGENDA_TOUR_KEY } from "../features/appointments/tour/agendaSteps";

// Permisos reales de ASSISTANT para la agenda (apps/core/permissions_codes.py).
const ASSISTANT_GRANTS = [
    "appointment.list", "appointment.retrieve", "appointment.create",
    "appointment.update", "appointment.destroy",
];

const renderAgenda = () => render(
    <MemoryRouter initialEntries={["/appointments"]}>
        <Appointments />
    </MemoryRouter>,
);

beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem(AGENDA_TOUR_KEY, "true"); // sin recorrido automático
    currentUser = { id: 10, role: "ASSISTANT" };
    granted = new Set(ASSISTANT_GRANTS);
    absenceState.rows = [];
});

// La agenda completa es pesada de montar en jsdom: la primera prueba paga el
// arranque en frío del módulo y bajo carga supera los 5 s por defecto.
describe("Citas: recepción puede agendar", { timeout: 20000 }, () => {
    it("una recepcionista con appointment.create ve cómo crear citas", async () => {
        renderAgenda();
        expect(await screen.findByRole("button", { name: /nueva cita/i }, { timeout: 10000 })).toBeInTheDocument();
        expect(screen.queryByText(/Modo lectura/)).not.toBeInTheDocument();
    });

    it("sin appointment.create queda en modo lectura, sea cual sea el rol", async () => {
        currentUser = { id: 11, role: "VET" };
        granted = new Set(["appointment.list", "appointment.retrieve"]);
        renderAgenda();
        expect(await screen.findByText("Modo lectura — sin permiso para crear citas")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /nueva cita/i })).not.toBeInTheDocument();
    });

    // Antes se ocultaba por rol (`canEdit` = ADMIN o VET) aunque el endpoint solo exige
    // `appointment.create` a quien registra (el veterinario asignado necesita
    // `appointment.create_walkin`, y eso lo valida el backend).
    it("recepción registra atención sin cita: lo decide `appointment.create`", async () => {
        renderAgenda();
        await screen.findByRole("button", { name: /nueva cita/i });
        expect(screen.getByRole("button", { name: "Atención sin cita" })).toBeInTheDocument();
    });

    it("sin appointment.create no hay atención sin cita, aunque el rol sea VET", async () => {
        currentUser = { id: 11, role: "VET" };
        granted = new Set(["appointment.list", "appointment.retrieve", "appointment.create_walkin"]);
        renderAgenda();
        await screen.findByText("Modo lectura — sin permiso para crear citas");
        expect(screen.queryByRole("button", { name: "Atención sin cita" })).not.toBeInTheDocument();
    });

    it("lista como veterinarios a quienes atienden pacientes, no por rol (ADR p66)", async () => {
        renderAgenda();
        await screen.findByRole("button", { name: /nueva cita/i });
        const vets = screen.getByText("Veterinarios").parentElement;
        expect(within(vets).getByRole("button", { name: "Eva Galeno" })).toBeInTheDocument();
        expect(within(vets).getByRole("button", { name: "Dora Dueña" })).toBeInTheDocument();
        expect(within(vets).queryByRole("button", { name: "Olga Oficina" })).not.toBeInTheDocument();
        expect(within(vets).queryByRole("button", { name: "Rita Recepción" })).not.toBeInTheDocument();
    });

    it("marca como ausente a quien tiene ausencia ese día (ADR p67)", async () => {
        const now = new Date();
        const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
        absenceState.rows = [{ public_id: "abs-1", member: 3, member_public_id: "vet-uuid", start_date: today, end_date: today }];
        currentUser = { id: 20, role: "ADMIN" };
        granted = new Set([...ASSISTANT_GRANTS, "appointment.create_walkin"]);
        const user = userEvent.setup({ delay: null });
        renderAgenda();
        await user.click(await screen.findByRole("button", { name: "Atención sin cita" }));
        expect(await screen.findByRole("option", { name: "Eva Galeno · ausente" })).toBeInTheDocument();
        expect(screen.getAllByRole("option", { name: "Dora Dueña" }).length).toBeGreaterThan(0);
    });

    it("un veterinario conserva la creación y la atención sin cita", async () => {
        currentUser = { id: 3, role: "VET" };
        granted = new Set([...ASSISTANT_GRANTS, "appointment.create_walkin"]);
        renderAgenda();
        expect(await screen.findByRole("button", { name: /nueva cita/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Atención sin cita" })).toBeInTheDocument();
    });
});

// Acciones del detalle de una cita: cada una pide el permiso de su endpoint, no un rol.
describe("Citas: acciones del detalle por permiso", { timeout: 20000 }, () => {
    const tomorrow = (() => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    })();
    const APPT = {
        id: 50, public_id: "appt-uuid", status: "scheduled", date: tomorrow, start_time: "10:00",
        end_time: "10:30", pet: 7, pet_name: "Luna", pet_public_id: "pet-uuid", veterinarian: 3,
        veterinarian_name: "Eva Galeno", reason: "Vacuna", category: "vaccination",
    };

    const openDetail = async (appointment = APPT) => {
        apiClient.get.mockResolvedValue({ data: appointment });
        render(
            <MemoryRouter initialEntries={[`/appointments?appointment=${appointment.public_id}`]}>
                <Appointments />
            </MemoryRouter>,
        );
        return screen.findByRole("button", { name: "Cerrar" }, { timeout: 10000 });
    };

    it("recepción gestiona la cita pero no abre la consulta", async () => {
        await openDetail();
        expect(screen.getByRole("button", { name: "Editar" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Confirmar" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /Atender ahora/ })).not.toBeInTheDocument();
    });

    it("quien puede crear consultas atiende", async () => {
        currentUser = { id: 3, role: "VET" };
        granted = new Set([...ASSISTANT_GRANTS, "medicalrecord.create"]);
        await openDetail();
        expect(screen.getByRole("button", { name: /Atender ahora/ })).toBeInTheDocument();
    });

    it("sin appointment.update solo se consulta, aunque el rol sea VET (ADR p69)", async () => {
        currentUser = { id: 3, role: "VET" };
        granted = new Set(["appointment.list", "appointment.retrieve", "appointment.create", "medicalrecord.create"]);
        await openDetail();
        expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /Atender ahora/ })).not.toBeInTheDocument();
    });
});
