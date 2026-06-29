import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { LoginForm } from "./LoginForm";

// ADR p48 (Fase 0): el backend resuelve login por correo O username, así que el
// campo de identidad debe etiquetarse "Correo o usuario", NO "Correo electrónico".
// El bug que originó el ADR: el campo decía "Correo electrónico" pero el valor se
// envía como `username` → una clínica que escribía su correo recibía 401.
//
// `useLoginForm` toca auth context, router y red — fuera del alcance de un test
// de presentación. Se mockea a un stub estable para aislar el render de LoginForm.
vi.mock("../hooks/useLoginForm", () => ({
  useLoginForm: () => ({
    username: "",
    setUsername: () => {},
    password: "",
    setPassword: () => {},
    remember: true,
    setRemember: () => {},
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
