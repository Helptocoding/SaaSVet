/**
 * FirstRunAssistant — experiencia de primer uso (activación).
 * Overlay de un solo paso derivado del estado REAL (activation/), sin flags.
 * Se prueba comportamiento observable: qué paso se ve, celebración, cierre, gates.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

const navigate = vi.fn();
let locationState = null;
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
  useLocation: () => ({ pathname: "/", state: locationState }),
}));

// framer-motion: passthrough determinista (cualquier motion.* → tag plano, sin
// props de animación). Proxy con caché por tag (identidad estable → sin remounts).
vi.mock("framer-motion", () => {
  const cache = {};
  return {
    motion: new Proxy(
      {},
      {
        get: (_t, tag) => {
          const key = typeof tag === "string" ? tag : "div";
          if (!cache[key]) {
            cache[key] = ({ children, className }) => {
              const Tag = key;
              return <Tag className={className}>{children}</Tag>;
            };
          }
          return cache[key];
        },
      }
    ),
    AnimatePresence: ({ children }) => <>{children}</>,
    useReducedMotion: () => true,
  };
});

let canImpl = () => true;
let userImpl = { organization_name: "Clínica San Pedro" };
vi.mock("../../auth/authContext", () => ({
  useAuth: () => ({ can: (...a) => canImpl(...a), user: userImpl }),
}));

let activationImpl = null;
vi.mock("../../hooks/activationContext", () => ({
  useActivationContext: () => ({ activation: activationImpl }),
}));

import FirstRunAssistant from "./FirstRunAssistant";

const A = (over = {}) => ({
  has_patients: false,
  has_clinic_contact: false,
  has_services: false,
  has_appointments: false,
  has_consultations: false,
  completed: false,
  ...over,
});

// Readiness completa: pacientes + contacto + servicios (sin cita ni consulta).
const READY = { has_patients: true, has_clinic_contact: true, has_services: true, completed: true };

beforeEach(() => {
  navigate.mockReset();
  locationState = null;
  canImpl = () => true;
  userImpl = { organization_name: "Clínica San Pedro" };
  activationImpl = null;
});

describe("FirstRunAssistant", () => {
  it("no renderiza sin activación", () => {
    activationImpl = null;
    const { container } = render(<FirstRunAssistant />);
    expect(container).toBeEmptyDOMElement();
  });

  it("no renderiza cuando la clínica ya estaba activada (completed, sin transición)", () => {
    activationImpl = A({ ...READY, has_appointments: true, has_consultations: true });
    const { container } = render(<FirstRunAssistant />);
    expect(container).toBeEmptyDOMElement();
  });

  it("muestra SOLO el paso actual + saludo con el nombre de la clínica", () => {
    activationImpl = A({ has_patients: true, has_clinic_contact: true }); // siguiente = servicios
    render(<FirstRunAssistant />);
    expect(screen.getByText("Configura tus servicios")).toBeInTheDocument();
    expect(screen.queryByText("Agrega tu primer paciente")).toBeNull();
    expect(screen.queryByText("Agenda tu primera cita")).toBeNull();
    expect(screen.getByText(/Hola, Clínica San Pedro/)).toBeInTheDocument();
  });

  it("nunca verbaliza 'Paso N de N' (solo barra de progreso)", () => {
    activationImpl = A();
    render(<FirstRunAssistant />);
    expect(screen.queryByText(/paso\s*\d\s*de\s*\d/i)).toBeNull();
  });

  it("el CTA primary navega al módulo con fromOnboarding", async () => {
    const user = userEvent.setup();
    activationImpl = A();
    render(<FirstRunAssistant />);
    await user.click(screen.getByRole("button", { name: /agregar paciente/i }));
    expect(navigate).toHaveBeenCalledWith("/pets", { state: { fromOnboarding: true } });
  });

  it("el CTA secundario 'Importar' solo existe en el paso 1", () => {
    // Paso 1 → aparece (única ruta alterna real del onboarding)
    activationImpl = A();
    const { unmount } = render(<FirstRunAssistant />);
    expect(screen.getByRole("button", { name: /importar desde excel/i })).toBeInTheDocument();
    unmount();
    // Paso 2 (datos de clínica) → solo primary
    activationImpl = A({ has_patients: true });
    const second = render(<FirstRunAssistant />);
    expect(screen.queryByRole("button", { name: /importar/i })).toBeNull();
    expect(screen.getByRole("button", { name: /capturar datos de la clínica/i })).toBeInTheDocument();
    second.unmount();
    // Paso 3 (servicios) → solo primary
    activationImpl = A({ has_patients: true, has_clinic_contact: true });
    render(<FirstRunAssistant />);
    expect(screen.queryByRole("button", { name: /importar/i })).toBeNull();
    expect(screen.getByRole("button", { name: /configurar servicios/i })).toBeInTheDocument();
  });

  it("oculta 'Importar' sin permiso import.create (deja 'Agregar paciente')", () => {
    canImpl = (p) => p !== "import.create";
    activationImpl = A();
    render(<FirstRunAssistant />);
    expect(screen.queryByRole("button", { name: /importar/i })).toBeNull();
    expect(screen.getByRole("button", { name: /agregar paciente/i })).toBeInTheDocument();
  });

  it("no renderiza para un usuario sin capability de setup (VET/ASISTENTE)", () => {
    canImpl = (p) => p !== "service.create";
    activationImpl = A();
    const { container } = render(<FirstRunAssistant />);
    expect(container).toBeEmptyDOMElement();
  });

  it("celebra el paso recién completado (signal por router state)", () => {
    locationState = { onboardingStep: "has_patients" };
    activationImpl = A({ has_patients: true });
    render(<FirstRunAssistant />);
    expect(screen.getByText("Primer paciente agregado")).toBeInTheDocument();
  });

  it("no incluye pasos de cita ni consulta (readiness = paciente + contacto + servicio)", () => {
    activationImpl = A({ has_patients: true, has_clinic_contact: true }); // ÚLTIMO = servicios
    render(<FirstRunAssistant />);
    expect(screen.getByText("Configura tus servicios")).toBeInTheDocument();
    expect(screen.queryByText("Agenda tu primera cita")).toBeNull();
    expect(screen.queryByText("Todo preparado")).toBeNull();
  });

  it("al completar readiness muestra el momento de cierre", () => {
    // Falta el servicio → el componente 've' el paso en marcha (latch sawStep).
    activationImpl = A({ has_patients: true, has_clinic_contact: true });
    const { rerender } = render(<FirstRunAssistant />);
    expect(screen.getByText("Configura tus servicios")).toBeInTheDocument();
    // Servicio creado → completed → momento de cierre (sin depender de cita/consulta).
    activationImpl = A(READY);
    rerender(<FirstRunAssistant />);
    expect(screen.getByText("Todo listo.")).toBeInTheDocument();
    expect(screen.getByText(/Clínica San Pedro ya está lista/)).toBeInTheDocument();
  });

  // ── Paso "datos de tu clínica" ────────────────────────────────────────────
  // El teléfono es lo que el asistente de WhatsApp da en su plantilla de urgencia.

  it("pide los datos de la clínica después de pacientes y antes de servicios", () => {
    activationImpl = A({ has_patients: true });
    render(<FirstRunAssistant />);
    expect(screen.getByText("¿Cómo pueden encontrarte tus clientes?")).toBeInTheDocument();
    expect(screen.queryByText("Configura tus servicios")).toBeNull();
  });

  it("el copy habla de llamadas, WhatsApp y emergencias — no de 'completar tus datos'", () => {
    activationImpl = A({ has_patients: true });
    render(<FirstRunAssistant />);
    expect(screen.getByText(/emergencia/i)).toHaveTextContent(/WhatsApp/);
    expect(screen.queryByText(/completa tus datos/i)).toBeNull();
  });

  it("el CTA de clínica lleva a su apartado de /config por ruta", async () => {
    const user = userEvent.setup();
    activationImpl = A({ has_patients: true });
    render(<FirstRunAssistant />);
    await user.click(screen.getByRole("button", { name: /capturar datos de la clínica/i }));
    expect(navigate).toHaveBeenCalledWith("/config/clinic", {
      state: { fromOnboarding: true },
    });
  });

  it("el CTA de servicios abre la sección de servicios, no la de clínica", async () => {
    const user = userEvent.setup();
    activationImpl = A({ has_patients: true, has_clinic_contact: true });
    render(<FirstRunAssistant />);
    await user.click(screen.getByRole("button", { name: /configurar servicios/i }));
    expect(navigate).toHaveBeenCalledWith("/config/services", {
      state: { fromOnboarding: true },
    });
  });

  it("celebra el hito de contacto al volver de /config", () => {
    locationState = { onboardingStep: "has_clinic_contact" };
    activationImpl = A({ has_patients: true, has_clinic_contact: true });
    render(<FirstRunAssistant />);
    expect(screen.getByText("Datos de tu clínica listos")).toBeInTheDocument();
  });

  it("sin teléfono NO cierra el onboarding aunque haya pacientes y servicios", () => {
    activationImpl = A({ has_patients: true, has_services: true }); // completed: false
    render(<FirstRunAssistant />);
    expect(screen.getByText("¿Cómo pueden encontrarte tus clientes?")).toBeInTheDocument();
    expect(screen.queryByText("Todo listo.")).toBeNull();
  });
});
