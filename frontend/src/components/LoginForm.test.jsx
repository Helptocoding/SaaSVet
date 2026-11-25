import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { LoginForm } from "./LoginForm";

// ADR p48 (Fase 0): el backend resuelve login por correo O username, así que el
// campo de identidad debe etiquetarse "Correo o usuario", NO "Correo electrónico".
// El bug que originó el ADR: el campo decía "Correo electrónico" pero el valor se
// envía como `username` → una clínica que escribía su correo recibía 401.
//
// `useLoginForm` toca auth context, router y red — fuera del alcance de un test
// de presentación. Se mockea a un stub estable para aislar el render de LoginForm.
const { setRememberMock } = vi.hoisted(() => ({ setRememberMock: vi.fn() }));

vi.mock("../hooks/useLoginForm", () => ({
  useLoginForm: () => ({
    username: "",
    setUsername: () => {},
    password: "",
    setPassword: () => {},
    remember: true,
    setRemember: setRememberMock,
    loading: false,
    handleSubmit: () => {},
  }),
}));

describe("LoginForm — identidad de login (ADR p48)", () => {
  it("etiqueta el campo de identidad como 'Correo o usuario'", () => {
    render(<LoginForm />);
    expect(screen.getByLabelText("Correo o usuario")).toBeInTheDocument();
  });

  it("ya NO etiqueta el campo solo como 'Correo electrónico'", () => {
    render(<LoginForm />);
    expect(screen.queryByLabelText("Correo electrónico")).toBeNull();
  });

  it("el placeholder admite correo o usuario", () => {
    render(<LoginForm />);
    const input = screen.getByTestId("input-username");
    expect(input.getAttribute("placeholder")).toMatch(/usuario/i);
  });
});

// Plan UX D4: no hay recuperación por correo (ADR p21). El enlace ya no es un
// enlace muerto: explica a quién pedirle el restablecimiento.
describe("LoginForm — ¿Olvidaste tu contraseña?", () => {
  it("muestra a quién pedir el restablecimiento y lo vuelve a ocultar", () => {
    render(<LoginForm />);
    const trigger = screen.getByRole("button", { name: "¿Olvidaste tu contraseña?" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/administrador de tu clínica/)).toBeNull();

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/administrador de tu clínica/)).toBeInTheDocument();

    fireEvent.click(trigger);
    expect(screen.queryByText(/administrador de tu clínica/)).toBeNull();
  });

  it("no envía el formulario al pulsarlo", () => {
    render(<LoginForm />);
    const trigger = screen.getByRole("button", { name: "¿Olvidaste tu contraseña?" });
    expect(trigger).toHaveAttribute("type", "button");
  });
});

describe("LoginForm — Recordarme", () => {
  beforeEach(() => setRememberMock.mockClear());

  it("el checkbox propaga su estado al hook", () => {
    render(<LoginForm />);
    const checkbox = screen.getByTestId("remember-checkbox");

    expect(checkbox).toBeChecked();
    fireEvent.click(checkbox);
    expect(setRememberMock).toHaveBeenCalledWith(false);
  });
});
