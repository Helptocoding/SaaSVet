import { useState, useEffect, lazy, Suspense } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { getServices } from "../../api/billing";
import { getConfiguration } from "../../api/organizations";
import { apiError } from "../../utils/apiError";
import { toList } from "../../utils/toList";
import { useAuth } from "../../auth/authContext";
import { Icon } from "../../components/icons";
import styles from "./config.module.css";

const ClinicSection = lazy(() => import("./ClinicSection"));
const ScheduleSection = lazy(() => import("./ScheduleSection"));
const RulesSection = lazy(() => import("./RulesSection"));
const ServicesSection = lazy(() => import("./ServicesSection"));
const AccountSection = lazy(() => import("./AccountSection"));

const SECTIONS = [
  { id: "clinic", label: "Clínica", icon: Icon.Building },
  { id: "schedule", label: "Horarios", icon: Icon.CalendarClock },
  { id: "rules", label: "Reglas operativas", icon: Icon.Settings },
  { id: "services", label: "Servicios", icon: Icon.Receipt },
  { id: "account", label: "Cuenta", icon: Icon.Lock },
];

const LoadingFallback = () => (
  <div className={styles.loading}>Cargando sección…</div>
);

const SettingsLayout = ({ user, token }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  // El onboarding manda a una sección concreta (`state.section`); por defecto Clínica.
  const [activeSection, setActiveSection] = useState(
    () => (SECTIONS.some((s) => s.id === location.state?.section) ? location.state.section : "clinic")
  );

  const [org, setOrg] = useState(null);
  const [settings, setSettings] = useState(null);
  const [schedule, setSchedule] = useState([]);
  const [services, setServices] = useState([]);

  // Retorno automático del onboarding: al completar el hito desde aquí, volver al
  // dashboard con la señal de celebración. Vive en el layout (no en cada sección)
  // para no duplicar la lógica de router — las secciones solo avisan que el hito
  // quedó cubierto. `null` cuando NO se llegó desde el FirstRunAssistant.
  const onboardingReturn = location.state?.fromOnboarding
    ? (stepKey) => navigate("/", { state: { onboardingStep: stepKey } })
    : null;

  const isPlatformOperator = user?.role === "ADMIN_SAAS";
  const hasOrg = !!user?.organization;
  const showTenantSections = !isPlatformOperator && hasOrg;
  const canManage = user?.role !== "ASSISTANT";

  useEffect(() => {
    if (!token) return;
    if (!showTenantSections) {
      setLoading(false);
      return;
    }
    const load = async () => {
      setLoading(true);
      try {
        const config = await getConfiguration();
        setOrg(config.organization);
        setSettings(config.settings);
        setSchedule(config.schedule);
      } catch (err) {
        console.error(apiError(err));
      }
      try {
        const data = await getServices();
        setServices(toList(data));
      } catch (err) {
        console.error(apiError(err));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [token, showTenantSections]);

  if (!showTenantSections) {
    return (
      <div className="card" style={{ marginBottom: 20 }}>
        <p style={{ fontSize: 12.5, color: "var(--c-text-3)" }}>
          Las configuraciones están disponibles solo para administradores de una clínica.
        </p>
      </div>
    );
  }

  if (loading || !org) {
    return <div className={styles.page}><div className={styles.loading}>Cargando...</div></div>;
  }

  return (
    <div className={styles.page}>
      <header className={styles.pageHead}>
        <h1 className={styles.pageTitle}>Configuración</h1>
        <p className={styles.pageSubtitle}>Información, horarios y reglas operativas de tu clínica</p>
      </header>
      <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <p className={styles.sidebarLabel}>Ajustes</p>
        <nav className={styles.sidebarNav}>
          {SECTIONS.map(({ id, label, icon: IconComp }) => (
            <button
              key={id}
              onClick={() => setActiveSection(id)}
              className={`${styles.sidebarItem} ${activeSection === id ? styles.sidebarItemActive : ""}`}
            >
              <span className={styles.sidebarIcon}><IconComp s={16} /></span>
              {label}
            </button>
          ))}
        </nav>
      </aside>
      <main className={styles.content}>
        <Suspense fallback={<LoadingFallback />}>
          {activeSection === "clinic" && (
            <ClinicSection
              org={org}
              onOrgChange={setOrg}
              onOnboardingDone={onboardingReturn && (() => onboardingReturn("has_clinic_contact"))}
            />
          )}
          {activeSection === "schedule" && (
            <ScheduleSection schedule={schedule} onScheduleChange={setSchedule} />
          )}
          {activeSection === "rules" && (
            <RulesSection
              settings={settings}
              onSettingsChange={setSettings}
              canManage={canManage}
            />
          )}
          {activeSection === "services" && (
            <ServicesSection
              services={services}
              onOnboardingDone={onboardingReturn && (() => onboardingReturn("has_services"))}
              onServicesChange={async () => {
                try {
                  const data = await getServices();
                  setServices(toList(data));
                } catch (err) {
                  console.error(apiError(err));
                }
              }}
            />
          )}
          {activeSection === "account" && (
            <AccountSection />
          )}
        </Suspense>
      </main>
      </div>
    </div>
  );
};

export default SettingsLayout;
