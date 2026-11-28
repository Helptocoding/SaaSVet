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
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// El calendario se sustituye, pero se guardan sus props para ver qué recibe.
const calendarState = vi.hoisted(() => ({ props: null }));
vi.mock("@fullcalendar/react", () => ({
    default: (props) => { calendarState.props = props; return <div data-testid="calendar" />; },
}));
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
    getAgendaConfig: vi.fn(() => Promise.resolve(agendaState.config)),
}));
const agendaState = vi.hoisted(() => ({ config: null }));
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
const confirmMock = vi.hoisted(() => vi.fn(() => Promise.resolve(true)));
vi.mock("../components/useConfirm", () => ({ useConfirm: () => confirmMock }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), promise: vi.fn() }) }));

import Appointments from "./appointments";
import apiClient from "../api/client";
import { createAppointmentWithPatient, updateAppointment } from "../api/appointments";
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
    agendaState.config = null;
    calendarState.props = null;
    confirmMock.mockImplementation(() => Promise.resolve(true));
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

// ADR p70 D7, plan F2.2/F2.3: la agenda pinta el horario y los cierres de la clínica
// (`GET /appointments/agenda-config/`, bajo `appointment.list`), advierte con
// confirmación fuera de horario y calcula la hora de fin con la duración habitual.
describe("Citas: horario de la clínica en la agenda", { timeout: 20000 }, () => {
    const iso = (offset) => {
        const d = new Date();
        d.setDate(d.getDate() + offset);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    };
    const tomorrow = iso(1);
    // Todos los días 9–18: el resultado no depende de qué día sea mañana.
    const WEEK = [1, 2, 3, 4, 5, 6, 7].map((weekday) => ({
        weekday, is_closed: false, opens_at: "09:00:00", closes_at: "18:00:00",
        has_break: false, break_start: null, break_end: null,
    }));
    const CLOSURE = { public_id: "cl-1", start_date: iso(5), end_date: iso(5), reason: "Inventario" };
    const CONFIG = {
        schedule: WEEK,
        closures: [CLOSURE],
        settings: { default_appointment_duration_minutes: 45, show_status_change_history: true, allow_anonymous_walkin: false },
    };
    const APPT = {
        id: 50, public_id: "appt-uuid", status: "scheduled", date: tomorrow, start_time: "10:00",
        end_time: "10:30", pet: 7, pet_name: "Luna", pet_public_id: "pet-uuid", veterinarian: 3,
        veterinarian_name: "Eva Galeno", reason: "Vacuna", category: "vaccination",
    };

    beforeEach(() => { agendaState.config = CONFIG; });

    it("el calendario muestra el horario, una hora de margen y los cierres de fondo", async () => {
        renderAgenda();
        await waitFor(() => expect(calendarState.props?.businessHours).toHaveLength(7), { timeout: 10000 });
        expect(calendarState.props.slotMinTime).toBe("08:00:00");
        expect(calendarState.props.slotMaxTime).toBe("19:00:00");
        expect(calendarState.props.events).toContainEqual(expect.objectContaining({
            display: "background", title: "Cerrado: Inventario", start: `${CLOSURE.start_date}T00:00:00`,
        }));
    });

    it("sin la configuración de la agenda, el calendario conserva 07:00–20:00", async () => {
        agendaState.config = null;
        renderAgenda();
        await screen.findByRole("button", { name: /nueva cita/i }, { timeout: 10000 });
        expect(calendarState.props.slotMinTime).toBe("07:00:00");
        expect(calendarState.props.slotMaxTime).toBe("20:00:00");
        expect(calendarState.props.businessHours).toBe(false);
    });

    it("una cita nueva termina según la duración habitual", async () => {
        const user = userEvent.setup({ delay: null });
        renderAgenda();
        await waitFor(() => expect(calendarState.props?.businessHours).toHaveLength(7), { timeout: 10000 });
        await user.click(screen.getByRole("button", { name: /nueva cita/i }));
        const modal = within(document.querySelector(".appointment-create-modal"));
        await user.click(modal.getByRole("button", { name: /No encuentro la mascota/ }));
        await user.type(modal.getByPlaceholderText("Ej: Juan Pérez"), "Ana López");
        await user.type(modal.getByPlaceholderText("10 dígitos"), "5512345678");
        await user.type(modal.getByPlaceholderText("Ej: Firulais"), "Kira");
        await user.selectOptions(document.querySelector(".appointment-create-modal #new-appt-vet"), "3");
        await user.type(document.querySelector(".appointment-create-modal #new-appt-reason"), "Revisión");
        await user.click(modal.getByRole("button", { name: "Guardar cita" }));
        await waitFor(() => expect(createAppointmentWithPatient).toHaveBeenCalledWith(
            expect.objectContaining({ start_time: "09:00", end_time: "09:45" })));
        expect(confirmMock).not.toHaveBeenCalled();
    });

    const openEdit = async () => {
        const user = userEvent.setup({ delay: null });
        apiClient.get.mockResolvedValue({ data: APPT });
        render(
            <MemoryRouter initialEntries={[`/appointments?appointment=${APPT.public_id}`]}>
                <Appointments />
            </MemoryRouter>,
        );
        await user.click(await screen.findByRole("button", { name: "Editar" }, { timeout: 10000 }));
        return user;
    };

    it("mover fuera del horario pide confirmación; si no se confirma, no se guarda", async () => {
        confirmMock.mockImplementation(() => Promise.resolve(false));
        const user = await openEdit();
        fireEvent.change(screen.getByLabelText("HORA INICIO *"), { target: { value: "07:00" } });
        fireEvent.change(screen.getByLabelText(/HORA FIN/), { target: { value: "07:30" } });
        await user.click(screen.getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
            message: expect.stringContaining("fuera del horario de la clínica (9:00–18:00)"),
            confirmText: "Moverla de todos modos",
        })));
        expect(updateAppointment).not.toHaveBeenCalled();
    });

    it("confirmado, se guarda igual: no se bloquea (D7)", async () => {
        const user = await openEdit();
        fireEvent.change(screen.getByLabelText("FECHA *"), { target: { value: CLOSURE.start_date } });
        await user.click(screen.getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
            message: expect.stringContaining("cerrada ese día (Inventario)"),
        })));
        await waitFor(() => expect(updateAppointment).toHaveBeenCalled());
    });

    it("editar sin mover la cita no pregunta", async () => {
        const user = await openEdit();
        await user.type(screen.getByLabelText("NOTAS"), " extra");
        await user.click(screen.getByRole("button", { name: "Guardar cambios" }));
        await waitFor(() => expect(updateAppointment).toHaveBeenCalled());
        expect(confirmMock).not.toHaveBeenCalled();
    });

    it("arrastrar a un horario cerrado y no confirmar deshace el movimiento", async () => {
        confirmMock.mockImplementation(() => Promise.resolve(false));
        renderAgenda();
        await waitFor(() => expect(calendarState.props?.businessHours).toHaveLength(7), { timeout: 10000 });
        const revert = vi.fn();
        await calendarState.props.eventDrop({
            oldEvent: { extendedProps: { appointment: APPT } },
            event: { start: new Date(`${tomorrow}T20:00:00`), end: new Date(`${tomorrow}T20:30:00`) },
            revert,
        });
        expect(confirmMock).toHaveBeenCalled();
        expect(revert).toHaveBeenCalled();
        expect(updateAppointment).not.toHaveBeenCalled();
    });

    it("pulsar un cierre de fondo no abre nada", async () => {
        renderAgenda();
        await waitFor(() => expect(calendarState.props?.businessHours).toHaveLength(7), { timeout: 10000 });
        calendarState.props.eventClick({ event: { extendedProps: { closure: CLOSURE } } });
        expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
    });

    const hourButtons = (modal) => modal.getAllByRole("button", { pressed: false })
        .concat(modal.getAllByRole("button", { pressed: true }))
        .map((button) => button.textContent)
        .filter((text) => /^\d{2}:00$/.test(text))
        .sort();

    it("los botones de hora siguen el horario del día y empiezan en la apertura", async () => {
        const user = userEvent.setup({ delay: null });
        agendaState.config = {
            ...CONFIG,
            schedule: WEEK.map((item) => ({ ...item, opens_at: "10:00:00", closes_at: "14:00:00" })),
        };
        renderAgenda();
        await waitFor(() => expect(calendarState.props?.businessHours).toHaveLength(7), { timeout: 10000 });
        await user.click(screen.getByRole("button", { name: /nueva cita/i }));
        const modal = within(document.querySelector(".appointment-create-modal"));
        expect(hourButtons(modal)).toEqual(["10:00", "11:00", "12:00", "13:00"]);
        expect(modal.getByRole("button", { name: "10:00", pressed: true })).toBeInTheDocument();
    });

    it("sin la configuración de la agenda, 7:00–19:00 y la hora inicial 9:00", async () => {
        const user = userEvent.setup({ delay: null });
        agendaState.config = null;
        renderAgenda();
        await user.click(await screen.findByRole("button", { name: /nueva cita/i }, { timeout: 10000 }));
        const modal = within(document.querySelector(".appointment-create-modal"));
        expect(hourButtons(modal)).toHaveLength(13);
        expect(modal.getByRole("button", { name: "09:00", pressed: true })).toBeInTheDocument();
    });

    const fillQuickPatient = async (user, modal) => {
        await user.click(modal.getByRole("button", { name: /No encuentro la mascota/ }));
        await user.type(modal.getByPlaceholderText("Ej: Juan Pérez"), "Ana López");
        await user.type(modal.getByPlaceholderText("10 dígitos"), "5512345678");
        await user.type(modal.getByPlaceholderText("Ej: Firulais"), "Kira");
        await user.selectOptions(document.querySelector(".appointment-create-modal #new-appt-vet"), "3");
        await user.type(document.querySelector(".appointment-create-modal #new-appt-reason"), "Revisión");
    };

    it("un clic en la casilla de las 10:30 empieza a las 10:30", async () => {
        const user = userEvent.setup({ delay: null });
        renderAgenda();
        await waitFor(() => expect(calendarState.props?.businessHours).toHaveLength(7), { timeout: 10000 });
        act(() => calendarState.props.dateClick({ date: new Date(`${tomorrow}T10:30:00`), allDay: false }));
        const modal = within(document.querySelector(".appointment-create-modal"));
        expect(modal.getByRole("button", { name: "10:30", pressed: true })).toBeInTheDocument();
        expect(modal.getByRole("button", { name: "10:00", pressed: false })).toBeInTheDocument();
        await fillQuickPatient(user, modal);
        await user.click(modal.getByRole("button", { name: "Guardar cita" }));
        await waitFor(() => expect(createAppointmentWithPatient).toHaveBeenCalledWith(
            expect.objectContaining({ date: tomorrow, start_time: "10:30", end_time: "11:15" })));
    });

    it("elegir otra hora después de la media hora vuelve a la hora en punto", async () => {
        const user = userEvent.setup({ delay: null });
        renderAgenda();
        await waitFor(() => expect(calendarState.props?.businessHours).toHaveLength(7), { timeout: 10000 });
        act(() => calendarState.props.dateClick({ date: new Date(`${tomorrow}T10:30:00`), allDay: false }));
        const modal = within(document.querySelector(".appointment-create-modal"));
        await user.click(modal.getByRole("button", { name: "11:00" }));
        expect(modal.getByRole("button", { name: "11:00", pressed: true })).toBeInTheDocument();
        await fillQuickPatient(user, modal);
        await user.click(modal.getByRole("button", { name: "Guardar cita" }));
        await waitFor(() => expect(createAppointmentWithPatient).toHaveBeenCalledWith(
            expect.objectContaining({ start_time: "11:00", end_time: "11:45" })));
    });
});
