import { render, screen } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";

// P1-5 A3: el ErrorBoundary debe reportar a Sentry. Mockeamos el SDK para
// observar la llamada sin red.
vi.mock("@sentry/react", () => ({
    captureException: vi.fn(() => "evt_abc123"),
}));

import * as Sentry from "@sentry/react";
import ErrorBoundary from "./ErrorBoundary";

function Boom() {
    throw new Error("boom");
}

describe("ErrorBoundary", () => {
    let errSpy;

    beforeEach(() => {
        // React loguea el error capturado a console.error — silenciarlo.
        errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    });

    afterEach(() => {
        errSpy.mockRestore();
        vi.clearAllMocks();
    });

    it("renderiza children cuando no hay error", () => {
        render(
            <ErrorBoundary>
                <p>contenido ok</p>
            </ErrorBoundary>
        );
        expect(screen.getByText("contenido ok")).toBeInTheDocument();
    });

    it("muestra fallback, reporta a Sentry con componentStack y muestra el event id", () => {
        render(
            <ErrorBoundary>
                <Boom />
            </ErrorBoundary>
        );

        // Fallback visible (no pantalla blanca).
        expect(screen.getByText("Algo salió mal")).toBeInTheDocument();

        // Reportó a Sentry con el componentStack.
        expect(Sentry.captureException).toHaveBeenCalledTimes(1);
        const [err, opts] = Sentry.captureException.mock.calls[0];
        expect(err).toBeInstanceOf(Error);
        expect(opts.contexts.react).toHaveProperty("componentStack");

        // event_id visible para que el usuario lo cite a soporte.
        expect(screen.getByText("evt_abc123")).toBeInTheDocument();
    });
});
