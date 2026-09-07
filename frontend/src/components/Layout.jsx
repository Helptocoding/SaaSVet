import { useAuth } from "../auth/authContext";
import { useNavigate, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import NotificationBell from "./notifications/NotificationBell";
import { Icon } from "./icons";
import styles from "./AppShell.module.css";

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
    const { logout, user, initializing, can } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();

    if (initializing) {
        return (
            <div className={styles.loading}>
                <div className={styles.loadingInner}>
                    <Icon.Stethoscope s={30} c="currentColor" />
                    <p>Cargando…</p>
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
        <div className={styles.shell}>
            <Sidebar onLogout={handleLogout} />

            <main className={styles.main}>
                {!isDashboard && (
                    <header className={styles.topbar}>
                        {fromOnboarding ? (
                            <button
                                onClick={() => navigate("/")}
                                className={styles.backAction}
                            >
                                <Icon.ChevronLeft s={16} c="currentColor" /> Volver al Dashboard
                            </button>
                        ) : (
                            <span className={styles.topbarTitle}>
                                {pageTitle}
                            </span>
                        )}
                        <div className={styles.topbarActions}>
                            {can?.("notification.list") && <NotificationBell />}
                            {location.pathname === "/config" && !user?.is_demo && (
                                <button
                                    onClick={() => window.dispatchEvent(new CustomEvent("open-change-password"))}
                                    className={styles.passwordAction}
                                >
                                    Cambiar contraseña
                                </button>
                            )}
                            <div className={styles.avatar} aria-label="Perfil de usuario">
                                {(user?.first_name?.[0] || user?.username?.[0] || "U").toUpperCase()}
                            </div>
                        </div>
                    </header>
                )}

                <div className={isDashboard ? styles.contentDashboard : styles.content}>
                    {children}
                </div>
            </main>
        </div>
    );
};

export default Layout;
