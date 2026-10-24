import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getUsers = vi.hoisted(() => vi.fn());
vi.mock("../../api/inbox", () => ({ getAssignableUsers: getUsers }));
import ThreadAssignment from "./ThreadAssignment";

const users = [{ public_id: "vet-id", name: "María sintética" }, { public_id: "peer-id", name: "Juan sintético" }];
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
async function flush() { await act(async () => {}); }
async function open() { fireEvent.click(screen.getByRole("button", { name: "Asignar a…" })); await flush(); }
function choose() { fireEvent.change(screen.getByRole("combobox", { name: "Persona asignada" }), { target: { value: "vet-id" } }); }

beforeEach(() => { getUsers.mockReset().mockResolvedValue(users); });

describe("WA-ASN-01 selector", () => {
    it("carga el directorio solo al abrir y envía el UUID elegido", async () => {
        const onAssign = vi.fn().mockResolvedValue(true);
        render(<ThreadAssignment onAssign={onAssign} />);
        expect(getUsers).not.toHaveBeenCalled(); await open();
        expect(screen.getByRole("button", { name: "Asignar", exact: true })).toBeDisabled();
        choose(); fireEvent.submit(screen.getByRole("form", { name: "Asignar conversación" })); await flush();
        expect(onAssign).toHaveBeenCalledExactlyOnceWith("vet-id");
        expect(screen.queryByRole("form")).not.toBeInTheDocument();
    });
    it("permite cancelar sin asignar y aborta el GET", async () => {
        const wait = deferred(); getUsers.mockReturnValue(wait.promise);
        const onAssign = vi.fn(); render(<ThreadAssignment onAssign={onAssign} />); await open();
        expect(screen.getByRole("status")).toHaveTextContent("Cargando equipo");
        const signal = getUsers.mock.calls[0][0].signal;
        fireEvent.click(screen.getByRole("button", { name: "Cancelar asignación" })); await flush();
        expect(signal.aborted).toBe(true); expect(onAssign).not.toHaveBeenCalled();
        await act(async () => wait.resolve(users)); expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    });
    it("muestra vacío sin una acción inválida", async () => {
        getUsers.mockResolvedValue([]); render(<ThreadAssignment onAssign={vi.fn()} />); await open();
        expect(screen.getByText("No hay personas disponibles para responder.")).toBeVisible();
        expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    });
    it("explica fallo de carga y permite reintentar", async () => {
        getUsers.mockRejectedValueOnce(new Error("offline"));
        render(<ThreadAssignment onAssign={vi.fn()} />); await open();
        expect(screen.getByRole("alert")).toBeVisible();
        fireEvent.click(screen.getByRole("button", { name: "Reintentar equipo" })); await flush();
        expect(getUsers).toHaveBeenCalledTimes(2); expect(screen.getByRole("combobox")).toBeVisible();
    });
    it("evita doble envío y deja visible la elección si la API rechaza", async () => {
        const wait = deferred(); const onAssign = vi.fn().mockReturnValue(wait.promise);
        render(<ThreadAssignment onAssign={onAssign} />); await open(); choose();
        const form = screen.getByRole("form"); fireEvent.submit(form); fireEvent.submit(form);
        expect(onAssign).toHaveBeenCalledTimes(1);
        expect(screen.getByRole("button", { name: "Asignando…" })).toBeDisabled();
        await act(async () => wait.resolve(false));
        expect(screen.getByRole("combobox")).toHaveValue("vet-id");
        expect(screen.getByRole("button", { name: "Asignar", exact: true })).toBeEnabled();
    });
    it("un cambio de estado deshabilita la elección y el envío", async () => {
        const onAssign = vi.fn(); const view = render(<ThreadAssignment onAssign={onAssign} />);
        await open(); choose(); view.rerender(<ThreadAssignment onAssign={onAssign} disabled />);
        expect(screen.getByRole("combobox")).toBeDisabled(); fireEvent.submit(screen.getByRole("form"));
        expect(onAssign).not.toHaveBeenCalled();
    });
    it("aborta al desmontar y descarta el directorio tardío", async () => {
        const wait = deferred(); getUsers.mockReturnValue(wait.promise);
        const view = render(<ThreadAssignment onAssign={vi.fn()} />); await open();
        const signal = getUsers.mock.calls[0][0].signal; view.unmount(); expect(signal.aborted).toBe(true);
        await act(async () => wait.resolve(users));
    });
    it("reabrir revalida el equipo y limpia la selección anterior", async () => {
        render(<ThreadAssignment onAssign={vi.fn()} />); await open(); choose();
        fireEvent.click(screen.getByRole("button", { name: "Cancelar asignación" })); await open();
        expect(getUsers).toHaveBeenCalledTimes(2); expect(screen.getByRole("combobox")).toHaveValue("");
    });
});
