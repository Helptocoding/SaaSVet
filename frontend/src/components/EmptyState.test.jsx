/**
 * EmptyState — presentacional. No conoce RBAC: el caller pasa solo acciones
 * visibles (y puede pasar null por una acción sin permiso, que se omite).
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import EmptyState from "./EmptyState";

describe("EmptyState", () => {
  it("muestra título y cuerpo", () => {
    render(<EmptyState title="Todavía no tienes pacientes" body="Importa o agrega." />);
    expect(screen.getByText("Todavía no tienes pacientes")).toBeInTheDocument();
    expect(screen.getByText("Importa o agrega.")).toBeInTheDocument();
  });

  it("renderiza las acciones y dispara onClick", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn();
    render(
      <EmptyState
        title="Sin pacientes"
        actions={[{ label: "Agregar paciente", onClick: onAdd, variant: "primary" }]}
      />
    );
    await user.click(screen.getByRole("button", { name: /agregar paciente/i }));
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it("omite las acciones nulas (sin permiso) y conserva las visibles", () => {
    render(
      <EmptyState
        title="Sin pacientes"
        actions={[
          null, // p.ej. can("import.create") === false
          { label: "Agregar paciente", onClick: () => {} },
        ]}
      />
    );
    expect(screen.queryByRole("button", { name: /importar/i })).toBeNull();
    expect(screen.getByRole("button", { name: /agregar paciente/i })).toBeInTheDocument();
  });

  it("sin acciones visibles no renderiza la fila de acciones", () => {
    render(<EmptyState title="Sin resultados" actions={[null, null]} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("no rompe sin prop actions", () => {
    render(<EmptyState title="Vacío" />);
    expect(screen.getByText("Vacío")).toBeInTheDocument();
  });
});
