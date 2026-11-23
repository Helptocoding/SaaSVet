import { useNavigate } from "react-router-dom";

const NotFound = () => {
    const navigate = useNavigate();

    return (
        <div style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "100vh",
            backgroundColor: "var(--c-bg)",
            textAlign: "center",
            padding: "40px",
        }}>
            <p style={{ fontSize: "56px", margin: "0 0 8px", lineHeight: 1 }}>404</p>
            <h1 style={{ fontSize: "20px", fontWeight: "700", color: "var(--c-text)", margin: "0 0 8px" }}>
                Página no encontrada
            </h1>
            <p style={{ fontSize: "13px", color: "var(--c-text-3)", margin: "0 0 24px" }}>
                La ruta que buscas no existe o fue movida.
            </p>
            <button
                onClick={() => navigate("/")}
                style={{
                    padding: "10px 24px",
                    background: "var(--c-primary)",
                    color: "var(--c-on-primary)",
                    border: "none",
                    borderRadius: "8px",
                    fontSize: "14px",
                    fontWeight: "600",
                    cursor: "pointer",
                }}
            >
                Ir al inicio
            </button>
        </div>
    );
};

export default NotFound;
