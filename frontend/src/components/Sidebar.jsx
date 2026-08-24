import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/authContext";
import { Icon } from "./icons";
import styles from "./AppShell.module.css";

const NAV_ITEMS = [
    { path: "/", label: "Dashboard", icon: Icon.LayoutDashboard },
    { path: "/pets", label: "Mascotas", icon: Icon.PawPrint },
    { path: "/appointments", label: "Citas", icon: Icon.CalendarClock },
    // Bandeja del agente (É-F0): gated por capability, no por rol —
    // ASSISTANT/ADMIN operan, VET solo ve (agentinbox.view).
    { path: "/inbox", label: "WhatsApp", icon: Icon.MessageCircle, perm: "agentinbox.view" },
    { path: "/medical-records", label: "Historial Clínico", icon: Icon.FileHeart },
    { path: "/prescriptions", label: "Recetas", icon: Icon.Pill },
    { path: "/inventory", label: "Inventario", icon: Icon.Package },
    { path: "/pos", label: "Punto de Venta", icon: Icon.ShoppingBag },
    { path: "/billing", label: "Cobros", icon: Icon.Receipt },
    { path: "/cash", label: "Caja", icon: Icon.Wallet },
];

const ADMIN_ITEMS = [
    { path: "/staff", label: "Equipo", icon: Icon.Users },
    { path: "/config", label: "Configuración", icon: Icon.Settings },
];

// Items de admin gated por capability (no por nombre de rol): el importador
// requiere `import.create`. Ver authContext.can().
const CAPABILITY_ITEMS = [
    { path: "/imports", label: "Importar datos", icon: Icon.Upload, perm: "import.create" },
];

const PLATFORM_ITEMS = [
    { path: "/platform/organizations/new", label: "Crear clínica", icon: Icon.Building },
];

const ROLE_LABELS = {
    ADMIN: "Administrador",
    VET: "Veterinario",
    ASSISTANT: "Asistente",
    ADMIN_SAAS: "Super Admin",
};

const Sidebar = ({ onLogout }) => {
    const location = useLocation();
    const { user, initializing, can } = useAuth();

    if (initializing) return null;

    const isAdmin = user?.role === "ADMIN" || user?.role === "ADMIN_SAAS";
    const isPlatformOperator = user?.role === "ADMIN_SAAS";

    const isActive = (path) =>
        path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

    const NavLink = ({ item }) => {
        const active = isActive(item.path);
        const IconComp = item.icon;
        return (
            <Link
                to={item.path}
                className={`${styles.navLink} ${active ? styles.navLinkActive : ""}`}
                aria-current={active ? "page" : undefined}
                title={item.label}
            >
                <IconComp s={17} c="currentColor" />
                <span className={styles.navLabel}>{item.label}</span>
            </Link>
        );
    };

    return (
        <aside className={styles.sidebar} aria-label="Navegación principal">
            {/* Brand */}
            <div className={styles.brand}>
                <div className={styles.brandRow}>
                    <div className={styles.brandMark}>
                        <Icon.Stethoscope s={17} c="#fff" />
                    </div>
                    <div className={styles.brandText}>
                        <div className={styles.brandName}>SaaslyVet</div>
                        <div className={styles.brandOrg}>
                            {user?.organization_name || "Sistema"}
                        </div>
                    </div>
                </div>
            </div>

            {/* Nav principal */}
            <nav className={styles.nav}>
                {NAV_ITEMS
                    .filter(item => !item.perm || can?.(item.perm))
                    .map(item => <NavLink key={item.path} item={item} />)}

                {/* Admin items */}
                {isAdmin && (
                    <>
                        <div className={styles.navSection}>
                            Admin
                        </div>
                        {ADMIN_ITEMS.map(item => <NavLink key={item.path} item={item} />)}
                        {CAPABILITY_ITEMS
                            .filter(item => can?.(item.perm) && !user?.is_demo)
                            .map(item => <NavLink key={item.path} item={item} />)}
                    </>
                )}

                {/* Platform items — sólo ADMIN_SAAS */}
                {isPlatformOperator && (
                    <>
                        <div className={`${styles.navSection} ${styles.navSectionDanger}`}>
                            Plataforma
                        </div>
                        {PLATFORM_ITEMS.map(item => <NavLink key={item.path} item={item} />)}
                    </>
                )}
            </nav>

            {/* User footer */}
            <div className={styles.userFooter}>
                <div className={styles.userMeta}>
                    <div className={styles.userName}>
                        {user?.first_name ? `${user.first_name} ${user.last_name || ""}`.trim() : user?.username}
                    </div>
                    <div className={styles.userRole}>
                        {ROLE_LABELS[user?.role] || user?.role}
                    </div>
                </div>
                <button
                    onClick={onLogout}
                    className={styles.logout}
                >
                    <Icon.LogOut s={15} c="currentColor" />
                    <span className={styles.logoutLabel}>Cerrar sesión</span>
                </button>
            </div>
        </aside>
    );
};

export default Sidebar;
