/**
 * Citas: «puede crear» se decide por capacidad, no por rol (Fase 1 Equipo, §7).
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

    it("no habilita otras capacidades: la atención sin cita sigue oculta para recepción", async () => {
        renderAgenda();
        await screen.findByRole("button", { name: /nueva cita/i });
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
