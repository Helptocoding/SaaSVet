import { Component } from "react";
import * as Sentry from "@sentry/react";

class ErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null, eventId: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, info) {
        console.error("[ErrorBoundary]", error, info.componentStack);
        // P1-5 A3: reportar a Sentry con el componentStack y guardar el event_id
        // para mostrárselo al usuario (lo cita al contactar soporte). Si Sentry
        // no está inicializado, captureException devuelve un id local igualmente.
        const eventId = Sentry.captureException(error, {
            contexts: { react: { componentStack: info.componentStack } },
        });
        this.setState({ eventId });
    }

    render() {
        if (!this.state.hasError) return this.props.children;

        return (
            <div style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                minHeight: "100vh",
                backgroundColor: "var(--c-bg, #f5f5f3)",
                padding: "40px",
                textAlign: "center",
            }}>
                <div style={{
                    backgroundColor: "var(--c-surface, #ffffff)",
                    border: "1px solid var(--c-border, #e5e0d8)",
                    borderRadius: "12px",
                    padding: "40px",
                    maxWidth: "480px",
                    width: "100%",
                }}>
                    <p style={{ fontSize: "28px", margin: "0 0 12px" }}>⚠️</p>
                    <h2 style={{ fontSize: "16px", fontWeight: "700", color: "var(--c-text, #1a1a1a)", margin: "0 0 8px" }}>
                        Algo salió mal
                    </h2>
                    <p style={{ fontSize: "13px", color: "var(--c-text-3, #8a8a7f)", margin: "0 0 16px" }}>
                        Ocurrió un error inesperado. Recarga la página o reporta el problema.
                    </p>
                    {this.state.eventId && (
                        <p style={{ fontSize: "12px", color: "var(--c-text-3, #8a8a7f)", margin: "0 0 24px" }}>
                            Código de error:{" "}
                            <code style={{ fontFamily: "monospace", fontWeight: "600" }}>
                                {this.state.eventId}
                            </code>
                            <br />
                            Compártelo con soporte para ayudarnos a resolverlo.
                        </p>
                    )}
                    <div style={{ display: "flex", gap: "10px", justifyContent: "center" }}>
                        <button
                            onClick={() => window.location.reload()}
                            style={{
                                padding: "8px 20px",
                                background: "var(--c-primary, #1a4434)",
                                color: "#fff",
                                border: "none",
                                borderRadius: "8px",
                                fontSize: "13px",
                                fontWeight: "600",
                                cursor: "pointer",
                            }}
                        >
                            Recargar página
                        </button>
                        <button
                            onClick={() => this.setState({ hasError: false, error: null, eventId: null })}
                            style={{
                                padding: "8px 20px",
                                background: "transparent",
                                color: "var(--c-text-2, #3a3a3a)",
                                border: "1px solid var(--c-border, #e5e0d8)",
                                borderRadius: "8px",
                                fontSize: "13px",
                                fontWeight: "600",
                                cursor: "pointer",
                            }}
                        >
                            Intentar de nuevo
                        </button>
                    </div>
                </div>
            </div>
        );
    }
}

export default ErrorBoundary;
