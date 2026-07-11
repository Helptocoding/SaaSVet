import { render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { describe, it, expect } from "vitest";
import { generalProtocol } from "./generalProtocol";

// Host que reproduce el contrato del container (ConsultationForm): value + onChange
// con patch. La sección es controlada.
function Host({ initial }) {
  const [value, setValue] = useState(initial ?? generalProtocol.initDraft(null));
  const Section = generalProtocol.Section;
  return <Section value={value} onChange={(patch) => setValue((p) => ({ ...p, ...patch }))} />;
}

describe("generalProtocol contrato", () => {
  it("label y validate no bloqueante", () => {
    expect(generalProtocol.label).toBeTruthy();
    expect(generalProtocol.validate()).toEqual({});
  });

  it("initDraft por defecto y rehidratación desde consultation_draft", () => {
    const fresh = generalProtocol.initDraft(null);
    expect(fresh).toMatchObject({ chief_complaint: "", exam: {} });

    const record = { consultation_draft: { general: { chief_complaint: "Tos", exam: {} } } };
    expect(generalProtocol.initDraft(record).chief_complaint).toBe("Tos");
  });
});

describe("GeneralSection", () => {
  it("captura el motivo principal", () => {
    render(<Host />);
    const motivo = screen.getByPlaceholderText(/Vómito desde ayer/i);
    fireEvent.change(motivo, { target: { value: "Cojera" } });
    expect(motivo).toHaveValue("Cojera");
  });

  it("exploración: marcar un sistema como alterado revela el campo de hallazgo", () => {
    render(<Host />);
    // Sin alterados, no hay campo de hallazgo.
    expect(screen.queryByPlaceholderText(/Hallazgo/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Cardiovascular/i }));
    const hallazgo = screen.getByPlaceholderText(/Hallazgo/i);
    expect(hallazgo).toBeInTheDocument();

    fireEvent.change(hallazgo, { target: { value: "Soplo grado II" } });
    expect(hallazgo).toHaveValue("Soplo grado II");

    // Volver a normal oculta el campo.
    fireEvent.click(screen.getByRole("button", { name: /Cardiovascular/i }));
    expect(screen.queryByPlaceholderText(/Hallazgo/i)).toBeNull();
  });
});
