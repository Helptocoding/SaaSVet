import { describe, it, expect } from "vitest";
import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PaymentLinesEditor from "./PaymentLinesEditor";

// PaymentLinesEditor conecta la interacción humana (escribir montos, agregar/quitar
// métodos) con la regla de dinero (total exacto / cambio no persistido, ADR p30 rev).
// El componente es CONTROLADO: el padre posee `lines` + `setLines`. Un host con
// useState reproduce ese contrato para observar el comportamiento real (footer, inputs)
// tras la interacción — sin espiar estado interno ni mockear payments.js.

function Host({ total = 500, allowPartial = false, allowChange = false, initial, disabled = false }) {
  const [lines, setLines] = useState(initial ?? [{ method: "cash", amount: "" }]);
  return (
    <PaymentLinesEditor
      total={total}
      allowPartial={allowPartial}
      allowChange={allowChange}
      lines={lines}
      setLines={setLines}
      disabled={disabled}
    />
  );
}

// Helpers de query — solo contrato observable (roles + texto visible).
const methodSelects = () => screen.getAllByRole("combobox");
const amountInputs = () => screen.getAllByRole("spinbutton"); // input type=number → spinbutton
const addButton = () => screen.getByRole("button", { name: /otro método/i });
// Botones de basura: sin nombre accesible (solo icono) → se identifican por exclusión.
const removeButtons = () =>
  screen.getAllByRole("button").filter((b) => !/otro método/i.test(b.textContent || ""));

describe("PaymentLinesEditor — render inicial", () => {
  it("muestra una línea con los 4 métodos de pago del catálogo (payments.js real)", () => {
    render(<Host total={500} />);
    expect(methodSelects()).toHaveLength(1);
    expect(amountInputs()).toHaveLength(1);

    const opts = within(methodSelects()[0]).getAllByRole("option");
    expect(opts.map((o) => o.textContent)).toEqual([
      "Efectivo",
      "Tarjeta",
      "Transferencia",
      "Otro",
    ]);
  });

  it("estado inicial: monto vacío, total y faltante reflejan el pendiente", () => {
    render(<Host total={500} />);
    expect(amountInputs()[0]).toHaveValue(null); // input number vacío
    expect(screen.getByText(/Total \$500\.00 · Ingresado \$0\.00/)).toBeInTheDocument();
    expect(screen.getByText("Falta $500.00")).toBeInTheDocument();
  });

  it("con una sola línea no hay control de eliminar accesible (no se queda sin métodos)", () => {
    // El trash se oculta (visibility:hidden) + se deshabilita cuando hay 1 línea,
    // por lo que queda fuera del árbol de accesibilidad: el usuario no puede borrar
    // el único método de pago.
    render(<Host total={500} />);
    expect(removeButtons()).toHaveLength(0);
  });
});

describe("PaymentLinesEditor — captura de cantidad", () => {
  it("escribir un monto actualiza el input y recalcula el footer", async () => {
    const user = userEvent.setup();
    render(<Host total={500} />);
    await user.type(amountInputs()[0], "300");

    expect(amountInputs()[0]).toHaveValue(300);
    expect(screen.getByText(/Ingresado \$300\.00/)).toBeInTheDocument();
    expect(screen.getByText("Falta $200.00")).toBeInTheDocument();
  });

  it("cambiar el valor recalcula (borrar y reescribir)", async () => {
    const user = userEvent.setup();
    render(<Host total={500} />);
    await user.type(amountInputs()[0], "300");
    await user.clear(amountInputs()[0]);
    await user.type(amountInputs()[0], "450");

    expect(screen.getByText("Falta $50.00")).toBeInTheDocument();
  });

  it("cambiar el método de pago se refleja en el select", async () => {
    const user = userEvent.setup();
    render(<Host total={500} />);
    await user.selectOptions(methodSelects()[0], "transfer");
    expect(methodSelects()[0]).toHaveValue("transfer");
  });
});

describe("PaymentLinesEditor — pago exacto", () => {
  it("500 en efectivo sobre total 500 → 'Exacto', sin faltante ni cambio", async () => {
    const user = userEvent.setup();
    render(<Host total={500} allowPartial={false} />);
    await user.type(amountInputs()[0], "500");

    expect(screen.getByText("Exacto")).toBeInTheDocument();
    expect(screen.queryByText(/Falta/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Cambio/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Excede/)).not.toBeInTheDocument();
  });
});

describe("PaymentLinesEditor — sobrepago (regla existente, sin inventar)", () => {
  it("600 efectivo / total 500 con allowChange → 'Cambio $100.00' + aviso de no-registro", async () => {
    const user = userEvent.setup();
    render(<Host total={500} allowChange={true} />);
    await user.type(amountInputs()[0], "600");

    expect(screen.getByText("Cambio $100.00")).toBeInTheDocument();
    expect(
      screen.getByText(/Se cobra el total \$500\.00; el cambio \$100\.00 no se registra\./)
    ).toBeInTheDocument();
  });

  it("600 efectivo / total 500 SIN allowChange → 'Excede $100.00', sin aviso de cambio", async () => {
    const user = userEvent.setup();
    render(<Host total={500} allowChange={false} />);
    await user.type(amountInputs()[0], "600");

    expect(screen.getByText("Excede $100.00")).toBeInTheDocument();
    expect(screen.queryByText(/no se registra/)).not.toBeInTheDocument();
  });
});

describe("PaymentLinesEditor — múltiples métodos (split)", () => {
  it("300 efectivo + 200 tarjeta sobre total 500 → suma exacta, ambas líneas respetadas", async () => {
    const user = userEvent.setup();
    render(
      <Host
        total={500}
        initial={[
          { method: "cash", amount: "" },
          { method: "card", amount: "" },
        ]}
      />
    );
    const inputs = amountInputs();
    expect(inputs).toHaveLength(2);

    await user.type(inputs[0], "300");
    await user.type(inputs[1], "200");

    expect(methodSelects()[0]).toHaveValue("cash");
    expect(methodSelects()[1]).toHaveValue("card");
    expect(amountInputs()[0]).toHaveValue(300);
    expect(amountInputs()[1]).toHaveValue(200);
    expect(screen.getByText(/Ingresado \$500\.00/)).toBeInTheDocument();
    expect(screen.getByText("Exacto")).toBeInTheDocument();
  });

  it("split con centavos que sufre drift flotante → 'Exacto' (protege la normalización .toFixed(2))", () => {
    // 199.99 + 300.01 = 500.0000000000001 en float. Si se quitara la normalización
    // Number(...toFixed(2)) del cálculo del footer, remaining sería ~-1e-13 → "Excede".
    // Este caso ancla esa redondeo y blinda la deuda de duplicación con payments.js.
    render(
      <Host
        total={500}
        initial={[
          { method: "cash", amount: "199.99" },
          { method: "card", amount: "300.01" },
        ]}
      />
    );
    expect(screen.getByText("Exacto")).toBeInTheDocument();
    expect(screen.queryByText(/Excede/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Falta/)).not.toBeInTheDocument();
  });
});

describe("PaymentLinesEditor — agregar / eliminar líneas", () => {
  it("agregar un método añade una fila", async () => {
    const user = userEvent.setup();
    render(<Host total={500} />);
    expect(amountInputs()).toHaveLength(1);

    await user.click(addButton());
    expect(amountInputs()).toHaveLength(2);
    // 2ª línea por defecto = método 'card' (Tarjeta)
    expect(methodSelects()[1]).toHaveValue("card");
  });

  it("al agregar tras un pago parcial, la nueva línea precarga el faltante (comportamiento existente)", async () => {
    const user = userEvent.setup();
    render(<Host total={500} />);
    await user.type(amountInputs()[0], "300");
    await user.click(addButton());

    // remaining = 200 → la nueva línea precarga 200.00
    expect(amountInputs()[1]).toHaveValue(200);
    expect(screen.getByText("Exacto")).toBeInTheDocument();
  });

  it("eliminar una línea vuelve a una sola fila", async () => {
    const user = userEvent.setup();
    render(<Host total={500} />);
    await user.click(addButton());
    expect(amountInputs()).toHaveLength(2);

    // con 2 líneas, los botones eliminar están habilitados
    const remove = removeButtons();
    expect(remove[0]).toBeEnabled();
    await user.click(remove[0]);
    expect(amountInputs()).toHaveLength(1);
  });
});

describe("PaymentLinesEditor — valores inválidos (comportamiento existente, sin cambiar validación)", () => {
  it("monto vacío cuenta como 0 (faltante = total)", () => {
    render(<Host total={500} initial={[{ method: "cash", amount: "" }]} />);
    expect(screen.getByText("Falta $500.00")).toBeInTheDocument();
  });

  it("monto cero → faltante = total", () => {
    render(<Host total={500} initial={[{ method: "cash", amount: "0" }]} />);
    expect(screen.getByText("Falta $500.00")).toBeInTheDocument();
  });

  it("texto no numérico no entra al input number (queda vacío, no rompe el cálculo)", async () => {
    const user = userEvent.setup();
    render(<Host total={500} />);
    await user.type(amountInputs()[0], "abc");

    expect(amountInputs()[0]).toHaveValue(null);
    expect(screen.getByText("Falta $500.00")).toBeInTheDocument();
  });

  it("monto negativo fluye al cálculo del editor (el gate de validez vive en payments.js, no aquí)", () => {
    // El editor solo muestra; paymentLinesValid (B1) rechaza negativos antes de cobrar.
    render(<Host total={500} initial={[{ method: "cash", amount: "-50" }]} />);
    expect(screen.getByText(/Ingresado \$-50\.00/)).toBeInTheDocument();
    expect(screen.getByText("Falta $550.00")).toBeInTheDocument();
  });
});

describe("PaymentLinesEditor — disabled", () => {
  it("con disabled, los controles quedan inhabilitados", () => {
    render(<Host total={500} disabled={true} />);
    expect(methodSelects()[0]).toBeDisabled();
    expect(amountInputs()[0]).toBeDisabled();
    expect(addButton()).toBeDisabled();
  });
});
