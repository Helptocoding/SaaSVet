import { useEffect, useRef } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/authContext";
import { STAFF_MANAGEMENT_PERMS } from "../features/staff/permissions";
import { Icon } from "./icons";
import styles from "./AppShell.module.css";

// Menú agrupado (plan UX D9, ley de Hick): cuatro bloques con nombre en vez de
// diez entradas sueltas. Inicio va sin rótulo, arriba de todo.
const NAV_GROUPS = [
    { label: null, items: [
        { path: "/", label: "Dashboard", icon: Icon.LayoutDashboard },
    ] },
    { label: "Atención", items: [
        { path: "/appointments", label: "Citas", icon: Icon.CalendarClock },
        { path: "/pets", label: "Mascotas", icon: Icon.PawPrint },
        { path: "/medical-records", label: "Historial clínico", icon: Icon.FileHeart },
        { path: "/prescriptions", label: "Recetas", icon: Icon.Pill },
    ] },
    { label: "Ventas", items: [
        { path: "/pos", label: "Punto de venta", icon: Icon.ShoppingBag },
        { path: "/billing", label: "Cobros", icon: Icon.Receipt },
        { path: "/cash", label: "Caja", icon: Icon.Wallet },
    ] },
    { label: "Operación", items: [
        { path: "/inventory", label: "Inventario", icon: Icon.Package },
        // Bandeja del agente (É-F0): gated por capability, no por rol —
        // ASSISTANT/ADMIN operan, VET solo ve (agentinbox.view).
        { path: "/inbox", label: "WhatsApp", icon: Icon.MessageCircle, perm: "agentinbox.view" },
    ] },
];

// Equipo y Configuración se gatean por capacidad, no por rol: quien pueda
// gestionar personal ve Equipo (plan Equipo, F4); quien pueda editar la
// clínica (`organization.update`, sensible: ADMIN y ADMIN_SAAS) ve
// Configuración (plan UX F1.10).
const STAFF_ITEM = { path: "/staff", label: "Equipo", icon: Icon.Users };
const CONFIG_ITEM = { path: "/config", label: "Configuración", icon: Icon.Settings };

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

// `mobileOpen`: en pantallas ≤560px el menú es un panel que se abre desde la
// barra superior (plan UX D11). Abierto, atrapa el foco y se cierra con Escape.
const Sidebar = ({ onLogout, mobileOpen = false, onClose, onNavigate }) => {
    const location = useLocation();
    const { user, initializing, can, canAny } = useAuth();
    const asideRef = useRef(null);

    useEffect(() => {
        if (!mobileOpen || !asideRef.current) return undefined;
        const aside = asideRef.current;
        const focusables = () => [...aside.querySelectorAll("a[href], button:not([disabled])")];
        focusables()[0]?.focus();
        const onKey = (e) => {
            if (e.key === "Escape") { e.preventDefault(); onClose?.(); return; }
            if (e.key !== "Tab") return;
            const items = focusables();
            if (items.length === 0) return;
            const first = items[0];
            const last = items[items.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        };
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [mobileOpen, onClose]);

    if (initializing) return null;

    const canConfigure = Boolean(can?.("organization.update"));
    // El operador de plataforma tiene `*.*`: ninguna capacidad lo distingue de
    // un ADMIN, así que su sección se decide por rol.
    const isPlatformOperator = user?.role === "ADMIN_SAAS";
    const canManageStaff = Boolean(canAny?.(STAFF_MANAGEMENT_PERMS));

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
                onClick={() => { if (mobileOpen) onNavigate?.(); }}
            >
                <IconComp s={17} c="currentColor" />
                <span className={styles.navLabel}>{item.label}</span>
            </Link>
        );
    };

    return (
        <aside
            id="app-sidebar"
            ref={asideRef}
            className={`${styles.sidebar} ${mobileOpen ? styles.sidebarOpen : ""}`}
            aria-label="Navegación principal"
        >
            {/* Brand */}
            <div className={styles.brand}>
                <div className={styles.brandRow}>
                    <div className={styles.brandMark}>
                        <Icon.Stethoscope s={17} c="var(--c-on-primary)" />
                    </div>
                    <div className={styles.brandText}>
                        <div className={styles.brandName}>SaaslyVet</div>
                        <div className={styles.brandOrg}>
                            {user?.organization_name || "Sistema"}
                        </div>
                    </div>
                    <button
                        type="button"
                        className={styles.closeNav}
                        onClick={() => onClose?.()}
                        aria-label="Cerrar menú"
                    >
                        <Icon.X s={18} />
                    </button>
                </div>
            </div>

            {/* Nav principal */}
            <nav className={styles.nav}>
                {NAV_GROUPS.map(group => {
                    const items = group.items.filter(item => !item.perm || can?.(item.perm));
                    if (items.length === 0) return null;
                    return (
                        <div className={styles.navGroup} key={group.label || "inicio"}
                            role="group" aria-label={group.label || "Inicio"}>
                            {group.label && <div className={styles.navSection}>{group.label}</div>}
                            {items.map(item => <NavLink key={item.path} item={item} />)}
                        </div>
                    );
                })}

                {/* Admin items */}
                {(canConfigure || canManageStaff) && (
                    <div className={styles.navGroup} role="group" aria-label="Admin">
                        <div className={styles.navSection}>
                            Admin
                        </div>
                        {[canManageStaff && STAFF_ITEM, canConfigure && CONFIG_ITEM]
                            .filter(Boolean)
                            .map(item => <NavLink key={item.path} item={item} />)}
                        {CAPABILITY_ITEMS
                            .filter(item => can?.(item.perm) && !user?.is_demo)
                            .map(item => <NavLink key={item.path} item={item} />)}
                    </div>
                )}

                {/* Platform items — sólo ADMIN_SAAS */}
                {isPlatformOperator && (
                    <div className={styles.navGroup} role="group" aria-label="Plataforma">
                        <div className={`${styles.navSection} ${styles.navSectionDanger}`}>
                            Plataforma
                        </div>
                        {PLATFORM_ITEMS.map(item => <NavLink key={item.path} item={item} />)}
                    </div>
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
