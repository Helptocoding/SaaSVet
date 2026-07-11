import { describe, it, expect } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VaccineSection from "./VaccineSection";

// VaccineSection es CONTROLADO: el padre (ConsultationForm) posee el slice
// protocolDraft.vaccine y fusiona cada patch. El host reproduce ese contrato
// (merge de patch) para observar el comportamiento real tras la interacción.
function Host({ initial = {}, history = [], species = "canino" }) {
  const [value, setValue] = useState(initial);
  return (
    <VaccineSection
      value={value}
      onChange={(patch) => setValue((v) => ({ ...v, ...patch }))}
      history={history}
      species={species}
      disabled={false}
      fmtDate={(d) => d}
    />
  );
}

const presetValue = {
  presetId: "rabia",
  vaccine_name: "Rabia",
  application_date: "2026-07-01",
  scheduleBooster: true,
  next_due_date: "2027-07-01",
  _boosterMonths: 12,
  _boosterEdited: false,
};

describe("VaccineSection", () => {
  it("con preset: muestra hint de protocolo y la ayuda contextual", () => {
    render(<Host initial={presetValue} />);
    expect(screen.getByText("Calculado según protocolo")).toBeInTheDocument();
    expect(screen.getByText(/Refuerzo recomendado en 12 meses/)).toBeInTheDocument();
  });

  it("al editar la fecha de refuerzo el hint pasa a 'Personalizado'", () => {
    render(<Host initial={presetValue} />);
    const dateInput = screen.getByDisplayValue("2027-07-01");
    fireEvent.change(dateInput, { target: { value: "2028-01-01" } });
    expect(screen.getByText("Personalizado")).toBeInTheDocument();
    expect(screen.queryByText("Calculado según protocolo")).not.toBeInTheDocument();
  });

  it("apagar 'Programar próximo refuerzo' oculta la fecha de refuerzo", async () => {
    const user = userEvent.setup();
    render(<Host initial={presetValue} />);
    expect(screen.getByDisplayValue("2027-07-01")).toBeInTheDocument();
    await user.click(screen.getByRole("switch"));
    expect(screen.queryByDisplayValue("2027-07-01")).not.toBeInTheDocument();
  });

  it("muestra ayuda histórica no bloqueante si la mascota ya tiene esa vacuna", () => {
    render(
      <Host
        initial={{ vaccine_name: "Rabia", presetId: "rabia" }}
        history={[
          { vaccine_name: "Rabia", application_date: "2025-07-01", applied_by_name: "Dr. Díaz" },
        ]}
      />
    );
    expect(screen.getByText(/Última Rabia: 2025-07-01 · Dr\. Díaz/)).toBeInTheDocument();
  });

  it("seleccionar una vacuna del combobox llena nombre y refuerzo sugerido", async () => {
    const user = userEvent.setup();
    render(<Host initial={{}} />);
    // Combobox de la vacuna (hay un 2º combobox para el producto de inventario, A2).
    await user.click(screen.getByPlaceholderText("Buscar vacuna…"));
    // Opción del catálogo (prefetch al enfocar).
    const option = await screen.findByText("Rabia");
    await user.click(option);
    // Preset con boosterMonths → refuerzo programado + hint de protocolo.
    expect(screen.getByText("Calculado según protocolo")).toBeInTheDocument();
  });
});
