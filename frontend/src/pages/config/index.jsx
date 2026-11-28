import { useState, useEffect, lazy, Suspense } from "react";
import { Navigate, useBlocker, useLocation, useNavigate, useParams } from "react-router-dom";
import { getServices } from "../../api/billing";
import { getConfiguration } from "../../api/organizations";
import { useAuth } from "../../auth/authContext";
import EmptyState from "../../components/EmptyState";
import { useConfirm } from "../../components/useConfirm";
import { dirtySections, discardSection } from "../../features/config/drafts";
import { CLINIC_PERM, SERVICE_PERMS } from "../../features/config/permissions";
import { BILLING_RULES, CARE_RULES } from "../../features/config/rules";
import { apiError } from "../../utils/apiError";
import { toList } from "../../utils/toList";
import { Icon } from "../../components/icons";
import Skeleton from "react-loading-skeleton";
import styles from "./config.module.css";

const ClinicSection = lazy(() => import("./ClinicSection"));
const ScheduleSection = lazy(() => import("./ScheduleSection"));
const ClosuresSection = lazy(() => import("./ClosuresSection"));
const RulesSection = lazy(() => import("./RulesSection"));
const ServicesSection = lazy(() => import("./ServicesSection"));
const HistorySection = lazy(() => import("./HistorySection"));

// ADR p70 F1.2: un apartado por dominio, cada uno con su ruta
// (`/config/<id>`) y visible según la capacidad que lo edita. La cuenta personal
// ya no vive aquí: está en `/account`, para todos.
const SECTIONS = [
  { id: "clinic", label: "Clínica", icon: Icon.Building, perms: [CLINIC_PERM] },
  { id: "schedule", label: "Horario", icon: Icon.CalendarClock, perms: [CLINIC_PERM] },
  { id: "billing", label: "Cobros", icon: Icon.Wallet, perms: [CLINIC_PERM] },
  { id: "care", label: "Atención", icon: Icon.Stethoscope, perms: [CLINIC_PERM] },
  { id: "services", label: "Servicios", icon: Icon.Receipt, perms: SERVICE_PERMS },
  { id: "history", label: "Historial de cambios", icon: Icon.Clock, perms: [CLINIC_PERM] },
];

const CLINIC_DATA_SECTIONS = new Set(["clinic", "schedule", "billing", "care"]);

const sectionLabel = (id) => SECTIONS.find((s) => s.id === id)?.label || id;

const listOf = (items) => (items.length <= 1
  ? items.join("")
  : `${items.slice(0, -1).join(", ")} y ${items[items.length - 1]}`);

// Esqueleto de un apartado: misma forma que SettingsPanel (título, descripción y
// filas de campos). Sirve para la carga inicial y para el lazy de cada sección.
const SectionSkeleton = () => (
  <section className={styles.section} role="status" aria-label="Cargando sección">
    <header className={styles.sectionHead} aria-hidden="true">
      <Skeleton width={160} height={22} />
      <Skeleton width="70%" height={13} />
    </header>
    <div className={styles.skelFields} aria-hidden="true">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className={styles.skelField}>
          <Skeleton width={110} height={11} />
          <Skeleton height={38} borderRadius="var(--r-lg)" />
        </div>
      ))}
    </div>
  </section>
);

const SettingsLayout = ({ user, token }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const { section: sectionParam } = useParams();
  const { can, canAny } = useAuth();
  const canClinic = Boolean(can?.(CLINIC_PERM));
  const canServices = Boolean(canAny?.(SERVICE_PERMS));
  const sections = SECTIONS.filter((section) => canAny?.(section.perms));
  const activeSection = sections.some((s) => s.id === sectionParam) ? sectionParam : null;

  // Plan F1.3: lo último guardado y el borrador de cada apartado, por separado.
  // La cabecera y el punto de «cambios sin guardar» comparan uno con otro.
  const [saved, setSaved] = useState(null);
  const [draft, setDraft] = useState(null);
  const [services, setServices] = useState([]);
  const [loadState, setLoadState] = useState({ attempt: 0, status: "loading", error: null });

  const dirty = dirtySections(saved, draft);
  const anyDirty = dirty.size > 0;

  // Retorno automático del onboarding: al completar el hito desde aquí, volver al
  // dashboard con la señal de celebración. Vive en el layout (no en cada sección)
  // para no duplicar la lógica de router — las secciones solo avisan que el hito
  // quedó cubierto. `null` cuando NO se llegó desde el FirstRunAssistant.
  const onboardingReturn = location.state?.fromOnboarding
    ? (stepKey) => navigate("/", { state: { onboardingStep: stepKey } })
    : null;

  // Excepción documentada, igual que en Sidebar.jsx: el operador de plataforma
  // tiene `*.*` y ninguna capacidad lo distingue; lo que lo deja fuera es no
  // tener clínica.
  const showTenantSections = user?.role !== "ADMIN_SAAS" && !!user?.organization;

  useEffect(() => {
    if (!token || !showTenantSections) return;
    let current = true;
    const load = async () => {
      let error = null;
      if (canClinic) {
        try {
          const config = await getConfiguration();
          const snapshot = { org: config.organization, settings: config.settings, schedule: config.schedule };
          if (current) {
            setSaved(snapshot);
            setDraft(snapshot);
          }
        } catch (err) {
          error = apiError(err, "No se pudo cargar la configuración.");
        }
      }
      if (canServices && !error) {
        // Plan F1.7: con los inactivos, para poder reactivarlos.
        try {
          const data = await getServices({ include_inactive: "true" });
          if (current) setServices(toList(data));
        } catch (err) {
          error = apiError(err, "No se pudieron cargar los servicios.");
        }
      }
      if (current) setLoadState((state) => ({ ...state, status: error ? "error" : "ready", error }));
    };
    load();
    return () => { current = false; };
  }, [token, showTenantSections, canClinic, canServices, loadState.attempt]);

  // Salir de Configuración con cambios sin guardar pide confirmación; moverse
  // entre apartados no (los borradores viven en este layout).
  const blocker = useBlocker(({ nextLocation }) => anyDirty && !nextLocation.pathname.startsWith("/config"));
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    let active = true;
    (async () => {
      const ok = await confirm({
        title: "Cambios sin guardar",
        message: `Tienes cambios sin guardar en ${listOf([...dirty].map(sectionLabel))}. Si sales, se pierden.`,
        confirmText: "Salir sin guardar",
        dangerMode: true,
      });
      if (!active) return;
      if (ok) blocker.proceed();
      else blocker.reset();
    })();
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo reacciona al bloqueo; `dirty` se lee al pedir confirmación
  }, [blocker]);

  useEffect(() => {
    if (!anyDirty) return undefined;
    const handler = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [anyDirty]);

  if (!showTenantSections) {
    return (
      <div className="card" style={{ marginBottom: 20 }}>
        <p style={{ fontSize: 12.5, color: "var(--c-text-3)" }}>
          Las configuraciones están disponibles solo para administradores de una clínica.
        </p>
      </div>
    );
  }

  // `/config`, un apartado inexistente o uno sin permiso: al primero visible,
  // conservando el estado de navegación (la vuelta del onboarding).
  if (!activeSection) {
    if (sections.length === 0) return <Navigate to="/" replace />;
    return <Navigate to={`/config/${sections[0].id}`} replace state={location.state} />;
  }

  const goTo = (id) => navigate(`/config/${id}`, { state: location.state });
  const retry = () => setLoadState((state) => ({ attempt: state.attempt + 1, status: "loading", error: null }));

  const setDraftPart = (part) => (value) => setDraft((current) => ({
    ...current,
    [part]: typeof value === "function" ? value(current[part]) : value,
  }));

  // Tras guardar un apartado de reglas, lo guardado se reemplaza y el borrador
  // toma solo sus campos: lo que el otro apartado tenga sin guardar se conserva.
  const onRulesSaved = (updated, fields) => {
    setSaved((current) => ({ ...current, settings: updated }));
    setDraft((current) => ({
      ...current,
      settings: { ...current.settings, ...Object.fromEntries(fields.map((f) => [f, updated[f]])) },
    }));
  };
  const onClinicSaved = (updated) => {
    setSaved((current) => ({ ...current, org: updated }));
    setDraft((current) => ({ ...current, org: updated }));
  };
  const onScheduleSaved = (updated) => {
    setSaved((current) => ({ ...current, schedule: updated }));
    setDraft((current) => ({ ...current, schedule: updated }));
  };

  const needsClinicData = CLINIC_DATA_SECTIONS.has(activeSection);
  let content;
  if (loadState.status === "error") {
    content = (
      <EmptyState
        icon={Icon.AlertCircle}
        title="No se pudo cargar la configuración"
        body={loadState.error}
        actions={[{ label: "Reintentar", onClick: retry, variant: "secondary" }]}
      />
    );
  } else if (loadState.status === "loading" || (needsClinicData && !draft)) {
    content = <SectionSkeleton />;
  } else {
    content = (
      <Suspense fallback={<SectionSkeleton />}>
        {dirty.has(activeSection) && (
          <div className={styles.unsavedBar} role="status">
            <span>Cambios sin guardar</span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setDraft((current) => discardSection(saved, current, activeSection))}
            >
              Descartar
            </button>
          </div>
        )}
        {activeSection === "clinic" && (
          <ClinicSection
            org={draft.org}
            savedOrg={saved.org}
            onOrgChange={setDraftPart("org")}
            onSaved={onClinicSaved}
            onOnboardingDone={onboardingReturn && (() => onboardingReturn("has_clinic_contact"))}
          />
        )}
        {activeSection === "schedule" && (
          <>
            <ScheduleSection
              schedule={draft.schedule}
              onScheduleChange={setDraftPart("schedule")}
              onSaved={onScheduleSaved}
            />
            <ClosuresSection />
          </>
        )}
        {activeSection === "billing" && (
          <RulesSection
            title="Cobros"
            description="Cuándo se puede cobrar y si se permite dejar un cobro a crédito."
            rules={BILLING_RULES}
            showCreditTerm
            settings={draft.settings}
            savedSettings={saved.settings}
            onSettingsChange={setDraftPart("settings")}
            onSaved={onRulesSaved}
          />
        )}
        {activeSection === "care" && (
          <RulesSection
            title="Atención"
            description="Cómo se atiende una cita: duración, confirmación, pacientes sin registrar y expediente."
            rules={CARE_RULES}
            showDuration
            settings={draft.settings}
            savedSettings={saved.settings}
            onSettingsChange={setDraftPart("settings")}
            onSaved={onRulesSaved}
          />
        )}
        {activeSection === "services" && (
          <ServicesSection
            services={services}
            onOnboardingDone={onboardingReturn && (() => onboardingReturn("has_services"))}
            onServicesChange={async () => {
              try {
                const data = await getServices({ include_inactive: "true" });
                setServices(toList(data));
              } catch (err) {
                console.error(apiError(err));
              }
            }}
          />
        )}
        {activeSection === "history" && <HistorySection />}
      </Suspense>
    );
  }

  return (
    <div className={styles.page}>
      <header className="page-header">
        <div>
          <h1 className="page-title">Configuración</h1>
          <p className="page-subtitle">Datos, horario, reglas y servicios de tu clínica</p>
        </div>
      </header>
      <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <p className={styles.sidebarLabel}>Ajustes</p>
        <nav className={styles.sidebarNav} aria-label="Apartados de configuración">
          {sections.map(({ id, label, icon: IconComp }) => (
            <button
              key={id}
              type="button"
              onClick={() => goTo(id)}
              aria-current={activeSection === id ? "page" : undefined}
              className={`${styles.sidebarItem} ${activeSection === id ? styles.sidebarItemActive : ""}`}
            >
              <span className={styles.sidebarIcon}><IconComp s={16} /></span>
              {label}
              {dirty.has(id) && (
                <>
                  <span className={styles.dirtyDot} aria-hidden="true" />
                  <span className="sr-only"> (cambios sin guardar)</span>
                </>
              )}
            </button>
          ))}
        </nav>
      </aside>
      <main className={styles.content}>{content}</main>
      </div>
    </div>
  );
};

export default SettingsLayout;
