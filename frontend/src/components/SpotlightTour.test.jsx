/**
 * SpotlightTour — motor genérico de recorridos (coach-marks). Smoke test del
 * comportamiento observable: paso actual, navegación, cierre. Sin geometría (jsdom
 * devuelve rects en cero; con `target: null` el popover va centrado, suficiente).
 */
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import SpotlightTour from "./SpotlightTour";

const STEPS = [
  { target: null, tag: "Uno", title: "Primer paso", body: "Cuerpo uno" },
  { target: null, tag: "Dos", title: "Segundo paso", body: "Cuerpo dos" },
  { target: null, tag: "Tres", title: "Tercer paso", body: "Cuerpo tres" },
];

function Host({ onSkip = () => {}, onFinish = () => {} }) {
  const [i, setI] = useState(0);
  return (
    <SpotlightTour
      steps={STEPS}
      stepIdx={i}
      onNext={() => setI((n) => n + 1)}
      onPrev={() => setI((n) => n - 1)}
      onSkip={onSkip}
      onFinish={onFinish}
    />
  );
}

describe("SpotlightTour", () => {
  it("muestra el paso actual y no dice 'Tutorial'", () => {
    render(<Host />);
    expect(screen.getByText("Primer paso")).toBeInTheDocument();
    expect(screen.getByText("Cuerpo uno")).toBeInTheDocument();
    expect(screen.queryByText(/tutorial/i)).toBeNull();
  });

  it("'← Anterior' está deshabilitado en el primer paso", () => {
    render(<Host />);
    expect(screen.getByRole("button", { name: /anterior/i })).toBeDisabled();
  });

  it("'Siguiente' avanza de paso", async () => {
    const user = userEvent.setup();
    render(<Host />);
    await user.click(screen.getByRole("button", { name: /siguiente/i }));
    expect(screen.getByText("Segundo paso")).toBeInTheDocument();
    expect(screen.queryByText("Primer paso")).toBeNull();
  });

  it("el último paso muestra 'Entendido ✓' e invoca onFinish", async () => {
    const user = userEvent.setup();
    const onFinish = vi.fn();
    render(<Host onFinish={onFinish} />);
    await user.click(screen.getByRole("button", { name: /siguiente/i }));
    await user.click(screen.getByRole("button", { name: /siguiente/i }));
    const done = screen.getByRole("button", { name: /entendido/i });
    expect(done).toBeInTheDocument();
    await user.click(done);
    expect(onFinish).toHaveBeenCalledTimes(1);
  });

  it("'Saltar' invoca onSkip", async () => {
    const user = userEvent.setup();
    const onSkip = vi.fn();
    render(<Host onSkip={onSkip} />);
    await user.click(screen.getByRole("button", { name: /saltar/i }));
    expect(onSkip).toHaveBeenCalledTimes(1);
  });
});
