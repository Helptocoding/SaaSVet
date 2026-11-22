import { useAuth } from "../auth/authContext";
import { useNavigate, useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";
import NotificationBell from "./notifications/NotificationBell";
import FeedbackButton from "./FeedbackButton";
import { Icon } from "./icons";
import styles from "./AppShell.module.css";

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
                        {/* Sin título: el H1 de cada página ya dice dónde estás (plan UX D8).
                            Las rutas anidadas, como la ficha de mascota, tienen su propio
                            «Volver a…» junto al H1; una miga aquí lo repetiría. */}
                        {fromOnboarding && (
                            <button
                                onClick={() => navigate("/")}
                                className={styles.backAction}
                            >
                                <Icon.ChevronLeft s={16} c="currentColor" /> Volver al Dashboard
                            </button>
                        )}
                        <div className={styles.topbarActions}>
                            <FeedbackButton />
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
