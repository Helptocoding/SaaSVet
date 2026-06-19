/**
 * SetupChecklist — activación del primer uso.
 * Derivado de estado real (props), sin flags. Se oculta al completar; CTAs por
 * paso pendiente; "Importar Excel" gateado por permiso import.create.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

const navigate = vi.fn();
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));

let canImpl = () => true;
vi.mock("../../auth/authContext", () => ({
  useAuth: () => ({ can: (...a) => canImpl(...a) }),
}));

import SetupChecklist from "./SetupChecklist";

const ALL_FALSE = {
  has_patients: false,
  has_services: false,
  has_appointments: false,
  has_consultations: false,
  completed: false,
};

beforeEach(() => {
  navigate.mockReset();
  canImpl = () => true;
});

describe("SetupChecklist", () => {
  it("no renderiza sin activación", () => {
    const { container } = render(<SetupChecklist activation={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("no renderiza cuando la activación está completa", () => {
    const { container } = render(
      <SetupChecklist
        activation={{
          has_patients: true,
          has_services: true,
          has_appointments: true,
          has_consultations: true,
          completed: true,
        }}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("muestra el progreso real y el CTA de un paso pendiente", () => {
    render(<SetupChecklist activation={{ ...ALL_FALSE, has_patients: true }} />);
    expect(screen.getByText(/1 de 4/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /ir a configuración/i })
    ).toBeInTheDocument();
  });

  it("el CTA navega a la ruta del paso", async () => {
    const user = userEvent.setup();
    render(<SetupChecklist activation={ALL_FALSE} />);
    await user.click(screen.getByRole("button", { name: /agregar paciente/i }));
    expect(navigate).toHaveBeenCalledWith("/pets");
  });

  it("oculta 'Importar Excel' sin permiso import.create (deja 'Agregar paciente')", () => {
    canImpl = (p) => p !== "import.create";
    render(<SetupChecklist activation={ALL_FALSE} />);
    expect(screen.queryByRole("button", { name: /importar excel/i })).toBeNull();
    expect(
      screen.getByRole("button", { name: /agregar paciente/i })
    ).toBeInTheDocument();
  });

  it("no renderiza para un usuario sin capability de setup (VET/ASISTENTE)", () => {
    // El checklist es setup de clínica: sin service.create no se muestra.
    canImpl = (p) => p !== "service.create";
    const { container } = render(<SetupChecklist activation={ALL_FALSE} />);
    expect(container).toBeEmptyDOMElement();
  });
});
