import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../api/legal", () => ({
    getCurrentLegal: vi.fn(),
    acceptLegal: vi.fn(),
}));
vi.mock("../auth/login", () => ({ getMe: vi.fn() }));
vi.mock("../auth/tokenStorage", () => ({ getItem: vi.fn(() => "tok") }));

const navigate = vi.fn();
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }));

const setUserData = vi.fn();
const logout = vi.fn();
vi.mock("../auth/authContext", () => ({ useAuth: () => ({ setUserData, logout }) }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import AcceptLegal from "./acceptLegal";
import { getCurrentLegal, acceptLegal } from "../api/legal";
import { getMe } from "../auth/login";

const DOCS = [
    { public_id: "p1", doc_type: "terms", version: "2026-06-24", landing_url: "https://x/terminos" },
    { public_id: "p2", doc_type: "privacy", version: "2026-06-24", landing_url: "https://x/aviso" },
];

describe("AcceptLegal", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        getCurrentLegal.mockResolvedValue({ documents: DOCS, acceptance_required: true });
        acceptLegal.mockResolvedValue({ acceptance_required: false });
        getMe.mockResolvedValue({ legal_acceptance_required: false });
    });

    it("requiere marcar TODOS los documentos antes de habilitar continuar, luego acepta", async () => {
        const user = userEvent.setup();
        render(<AcceptLegal />);

        const checkboxes = await screen.findAllByRole("checkbox");
        expect(checkboxes).toHaveLength(2);

        const btn = screen.getByRole("button", { name: /aceptar y continuar/i });
        expect(btn).toBeDisabled();

        await user.click(checkboxes[0]);
        expect(btn).toBeDisabled(); // falta el segundo

        await user.click(checkboxes[1]);
        expect(btn).toBeEnabled();

        await user.click(btn);
        await waitFor(() => expect(acceptLegal).toHaveBeenCalledWith(["p1", "p2"]));
        expect(setUserData).toHaveBeenCalled();
        expect(navigate).toHaveBeenCalledWith("/", { replace: true });
    });

    it("enlaza al texto legal de la landing (no duplica el texto)", async () => {
        render(<AcceptLegal />);
        const links = await screen.findAllByRole("link");
        expect(links.map((a) => a.getAttribute("href"))).toEqual([
            "https://x/terminos",
            "https://x/aviso",
        ]);
    });
});
