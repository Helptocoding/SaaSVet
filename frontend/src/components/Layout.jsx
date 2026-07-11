import { useAuth } from "../auth/authContext";
import { useNavigate, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import { Icon } from "./icons";

const PAGE_TITLES = {
    "/":               "Dashboard",
    "/dashboard":      "Dashboard",
    "/pets":           "Mascotas",
    "/appointments":   "Citas",
    "/medical-records":"Historial Clínico",
    "/inventory":      "Inventario",
    "/billing":        "Cobros",
    "/pos":            "Punto de Venta",
    "/staff":          "Equipo",
    "/config":         "Configuración",
    "/prescriptions":  "Recetas",
    "/imports":        "Importar datos",
};

const Layout = ({ children }) => {
    const { logout, user, initializing } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();

    if (initializing) {
        return (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh", background: "var(--c-bg)" }}>
                <div style={{ textAlign: "center", color: "var(--c-text-3)" }}>
                    <div style={{ marginBottom: "8px" }}><Icon.Stethoscope s={32} c="var(--c-text-3)" /></div>
                    <p style={{ fontSize: "13px" }}>Cargando...</p>
                </div>
            </div>
        );
    }

    const handleLogout = () => { logout(); navigate("/login"); };

    // Get page title from exact match or prefix match
    const pageTitle = PAGE_TITLES[location.pathname] ||
        (location.pathname.startsWith("/pets/") ? "Ficha de Mascota" : "");

    const isDashboard = location.pathname === "/" || location.pathname === "/dashboard";

    // Se llegó a este módulo desde un CTA del onboarding (FirstRunAssistant): mostrar
    // un "volver" guiado en vez del título, para que se sienta un recorrido, no una
    // navegación normal. Solo un hint visual; sin lógica.
    const fromOnboarding = !!location.state?.fromOnboarding;

    return (
        <div style={{ minHeight: "100vh", backgroundColor: "var(--c-bg)" }}>
            <Sidebar onLogout={handleLogout} />

            <main style={{ marginLeft: "var(--sidebar-width)", minHeight: "100vh", display: "flex", flexDirection: "column" }}>
                {!isDashboard && (
                    <header style={{
                        height: "52px",
                        backgroundColor: "var(--c-surface)",
                        borderBottom: "1px solid var(--c-border)",
                        display: "flex",
                        alignItems: "center",
                        padding: "0 28px",
                        gap: "8px",
                        position: "sticky", top: 0, zIndex: 50,
                        boxShadow: "var(--shadow-xs)",
                    }}>
                        {fromOnboarding ? (
                            <button
                                onClick={() => navigate("/")}
                                style={{
                                    display: "flex", alignItems: "center", gap: "6px",
                                    background: "none", border: "none", padding: "0",
                                    fontFamily: "inherit", fontSize: "14px", fontWeight: "600",
                                    color: "var(--c-primary)", cursor: "pointer",
                                }}
                            >
                                <Icon.ChevronLeft s={16} c="var(--c-primary)" /> Volver al Dashboard
                            </button>
                        ) : (
                            <span style={{ fontSize: "14px", fontWeight: "600", color: "var(--c-text)" }}>
                                {pageTitle}
                            </span>
                        )}
                        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "12px" }}>
                            {location.pathname === "/config" && !user?.is_demo && (
                                <button
                                    onClick={() => window.dispatchEvent(new CustomEvent("open-change-password"))}
                                    style={{
                                        background: "none", border: "none", padding: "4px 8px",
                                        fontFamily: "inherit", fontSize: "12px", fontWeight: 500,
                                        color: "var(--c-text-3)", cursor: "pointer",
                                        borderRadius: "var(--r-md)",
                                        transition: "color 0.15s, background 0.15s",
                                    }}
                                    onMouseEnter={e => { e.target.style.color = "var(--c-text)"; e.target.style.background = "var(--c-subtle)"; }}
                                    onMouseLeave={e => { e.target.style.color = "var(--c-text-3)"; e.target.style.background = "transparent"; }}
                                >
                                    Cambiar contraseña
                                </button>
                            )}
                            <div style={{
                                width: "30px", height: "30px",
                                borderRadius: "50%",
                                background: "linear-gradient(135deg, var(--c-primary-light), var(--sage-400))",
                                display: "flex", alignItems: "center", justifyContent: "center",
                                fontSize: "12px", fontWeight: "700", color: "var(--c-primary-dark)",
                                border: "1.5px solid var(--sage-400)",
                            }}>
                                {(user?.first_name?.[0] || user?.username?.[0] || "U").toUpperCase()}
                            </div>
                        </div>
                    </header>
                )}

                <div style={{ padding: isDashboard ? "0" : "28px", flex: 1 }}>
                    {children}
                </div>
            </main>
        </div>
    );
};

export default Layout;
