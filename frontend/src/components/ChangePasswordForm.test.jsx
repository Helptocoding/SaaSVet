import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ChangePasswordForm from "./ChangePasswordForm";
import { clearTokens, setTokens } from "../auth/tokenStorage";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  refreshUser: vi.fn(async () => ({ must_change_password: false })),
  changePassword: vi.fn(async () => ({ access: "access-new", refresh: "refresh-new" })),
  navigate: vi.fn(),
}));

vi.mock("../auth/authContext", () => ({
  useAuth: () => ({
    login: mocks.login,
    refreshUser: mocks.refreshUser,
    user: { must_change_password: false },
  }),
}));

vi.mock("../api/users", () => ({ changePassword: mocks.changePassword }));

vi.mock("react-router-dom", () => ({ useNavigate: () => mocks.navigate }));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const fillForm = (container) => {
  const inputs = container.querySelectorAll('input[type="password"]');
  fireEvent.change(inputs[0], { target: { value: "Actual123!" } });
  fireEvent.change(inputs[1], { target: { value: "Nueva123!" } });
  fireEvent.change(inputs[2], { target: { value: "Nueva123!" } });
};

describe("ChangePasswordForm — persistencia de la decisión Recordarme", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearTokens();
  });

  it("conserva remember=false al reemplazar los tokens", async () => {
    setTokens({ access: "access-old", refresh: "refresh-old", remember: false });
    const { container } = render(<ChangePasswordForm />);
    fillForm(container);

    fireEvent.click(screen.getByRole("button", { name: "Cambiar contraseña" }));

    await waitFor(() =>
      expect(mocks.login).toHaveBeenCalledWith("access-new", "refresh-new", false));
    expect(mocks.refreshUser).toHaveBeenCalled();
  });

  it("conserva remember=true al reemplazar los tokens", async () => {
    setTokens({ access: "access-old", refresh: "refresh-old", remember: true });
    const { container } = render(<ChangePasswordForm />);
    fillForm(container);

    fireEvent.click(screen.getByRole("button", { name: "Cambiar contraseña" }));

    await waitFor(() =>
      expect(mocks.login).toHaveBeenCalledWith("access-new", "refresh-new", true));
  });
});
