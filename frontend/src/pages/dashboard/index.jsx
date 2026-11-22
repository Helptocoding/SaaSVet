import { useMemo, useState, useEffect, useCallback } from "react";
import { useAuth } from "../../auth/authContext";
import { useDashboardSummary } from "../../hooks/useDashboardSummary";
import { useFinancialSeries } from "../../hooks/useFinancialSeries";
import { useActivationContext } from "../../hooks/activationContext";
import DashboardTopBar from "../../components/dashboard/DashboardTopBar";
import FirstRunAssistant from "../../components/dashboard/FirstRunAssistant";
import { StatSection, StatSectionSkeleton, StatTile } from "../../components/StatTiles";
import { Icon } from "../../components/icons";
import TodayAgendaList from "../../components/dashboard/TodayAgendaList";
import NowPanel from "../../components/dashboard/NowPanel";
import PendingFollowUp from "../../components/dashboard/PendingFollowUp";
import ClinicalBacklog from "../../components/dashboard/ClinicalBacklog";
import StockAlerts from "../../components/dashboard/StockAlerts";
import DashboardAnalytics from "../../components/dashboard/DashboardAnalytics";
import Skeleton from "react-loading-skeleton";
import "./dashboard.css";

function revenueDeltaVsYesterday(finSeries, finToday) {
  if (!finToday?.metrics) return null;
  const today = Number(finToday.metrics.revenuePaid ?? 0);
  const sorted = [...(finSeries || [])]
    .filter((p) => p?.metrics)
    .sort((a, b) => (a.bucketDate > b.bucketDate ? 1 : -1));
  const yesterday = sorted[sorted.length - 1];
  if (!yesterday) return null;
  const prev = Number(yesterday.metrics.revenuePaid ?? 0);
  if (prev === 0) return today > 0 ? 100 : null;
  return ((today - prev) / prev) * 100;
}

function buildRevenueSpark(finSeries, finToday) {
  const fin = [...(finSeries || []), ...(finToday ? [finToday] : [])]
    .filter((p) => p && p.metrics)
    .sort((a, b) => (a.bucketDate > b.bucketDate ? 1 : -1))
    .slice(-7);
  return fin.map((p) => ({ v: Number(p.metrics.revenuePaid ?? 0) }));
}

const fmtMoney = (v) => `$${Number(v).toLocaleString("es-MX")}`;

// Indicadores de HOY (point-in-time, /dashboard/summary/). Los pies describen
// qué cuenta cada número; no hay comparativos que el endpoint no calcule.
function buildKpiItems(kpis, role) {
  const isAdmin   = role === "ADMIN" || role === "ADMIN_SAAS";
  const showStock = isAdmin || role === "VET";

  const arValue = isAdmin && kpis?.ar_outstanding != null
    ? Number(kpis.ar_outstanding)
    : 0;

  const inProgress = kpis?.in_progress_now ?? 0;
  const stockCount = kpis?.low_stock_count ?? 0;

  return [
    {
      label: "En consulta",
      value: inProgress,
      icon: Icon.Stethoscope,
      tone: inProgress > 0 ? "primary" : "ink",
      live: true,
      foot: "En vivo",
    },
    {
      label: "Citas hoy",
      value: kpis?.pending_today ?? 0,
      icon: Icon.Calendar,
      tone: "ink",
      foot: "Por atender",
    },
    ...(isAdmin
      ? [
          {
            label: "Pendiente cobro",
            value: fmtMoney(arValue),
            icon: Icon.Wallet,
            tone: arValue > 0 ? "attention" : "calm",
            foot: "Emitidos sin pagar",
          },
        ]
      : []),
    ...(showStock
      ? [
          {
            label: "Stock bajo",
            value: stockCount,
            icon: Icon.AlertTriangle,
            tone: stockCount > 0 ? "danger" : "calm",
            foot: stockCount > 0 ? "En o bajo el mínimo" : "Nada bajo el mínimo",
          },
        ]
      : []),
    {
      label: "Pacientes hoy",
      value: kpis?.patients_today ?? 0,
      icon: Icon.Paw,
      tone: "ink",
      foot: "Mascotas con cita",
    },
  ];
}

const Dashboard = () => {
  const { user } = useAuth();
  const { data, loading, error, refetch } = useDashboardSummary();
  const { refetch: refetchActivation } = useActivationContext();
  const { series: finSeries, today: finToday } = useFinancialSeries(7, true);

  // Al (re)entrar al dashboard, re-chequear la activación: si el usuario acaba de
  // crear un paciente/servicio en otro módulo, el paso avanza y se dispara la
  // micro-celebración (o el cierre) del FirstRunAssistant.
  useEffect(() => { refetchActivation(); }, [refetchActivation]);

  // Reveal de página (una sola animación) al terminar el onboarding: el overlay se
  // desvanece y el dashboard entra con `.dash-reveal`. One-shot.
  const [revealing, setRevealing] = useState(false);
  const handleFirstRunComplete = useCallback(() => {
    setRevealing(true);
    const t = setTimeout(() => setRevealing(false), 1000);
    return () => clearTimeout(t);
  }, []);

  const revenueToday = finToday?.metrics?.revenuePaid ?? null;
  const revenueDelta = useMemo(
    () => revenueDeltaVsYesterday(finSeries, finToday),
    [finSeries, finToday]
  );
  const revenueSpark = useMemo(
    () => buildRevenueSpark(finSeries, finToday),
    [finSeries, finToday]
  );

  const kpiItems = useMemo(
    () => buildKpiItems(data?.kpis, user?.role),
    [data?.kpis, user?.role]
  );

  const kpiGridClass = `dash-kpis dash-kpis-${kpiItems.length}`;

  // Antes usaba clases `skeleton-block`/`sk-*` que no existían en ningún CSS:
  // los bloques no tenían alto ni color y la carga se veía en blanco.
  const renderSkeleton = () => (
    <div className="dash-page" role="status" aria-label="Cargando dashboard">
      <div className="dtop-wrap" aria-hidden="true">
        <div className="phead dtop-phead">
          <div>
            <Skeleton width={280} height={26} />
            <Skeleton width={240} height={13} />
          </div>
          <Skeleton width={120} height={36} borderRadius="var(--r-lg)" />
        </div>
      </div>
      <div className="dash-grid" aria-hidden="true">
        <div className="dash-main">
          <StatSectionSkeleton count={kpiItems.length} gridClassName={kpiGridClass} />
          <section className="card dash-timeline-card">
            <Skeleton width={160} height={16} />
            <Skeleton count={4} height={52} borderRadius="var(--r-md)" className="dash-skel-row" />
          </section>
          <Skeleton height={340} borderRadius="var(--r-lg)" />
        </div>
        <div className="dash-side">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card">
              <Skeleton width="45%" height={14} />
              <Skeleton count={3} height={12} className="dash-skel-row" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  if (loading && !data) return renderSkeleton();

  return (
    <>
      {/* Overlay de primer uso (fuera de .dash-page: el reveal anima solo el
          dashboard, no el overlay que se desvanece por su cuenta). */}
      <FirstRunAssistant onComplete={handleFirstRunComplete} />

      <div className={`dash-page${revealing ? " dash-reveal" : ""}`}>
        <DashboardTopBar
          summary={data}
          revenueToday={revenueToday}
          revenueSpark={revenueSpark}
          revenueDelta={revenueDelta}
        />

      {error && (
        <div className="dash-error-banner">
          <span>No se pudieron cargar los datos del dashboard.</span>
          <button className="btn btn-ghost btn-xs" onClick={refetch}>Reintentar</button>
        </div>
      )}

      <div className="dash-grid">
        <main className="dash-main">
          <StatSection label="Indicadores de hoy" gridClassName={kpiGridClass}>
            {kpiItems.map((item) => (
              <StatTile key={item.label} {...item} />
            ))}
          </StatSection>

          <section className="card dash-timeline-card">
            <TodayAgendaList />
          </section>

          <DashboardAnalytics />
        </main>

        <aside className="dash-side">
          <div className="card"><NowPanel summary={data} /></div>
          <div className="card"><PendingFollowUp /></div>
          <div className="card"><ClinicalBacklog backlog={data?.backlog} /></div>
          <div className="card"><StockAlerts alerts={data?.stock_alerts} /></div>
        </aside>
      </div>
      </div>
    </>
  );
};

export default Dashboard;
