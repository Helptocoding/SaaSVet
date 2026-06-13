import { memo, useMemo, useState } from "react";
import { FunnelChart, Funnel, LabelList, Tooltip, ResponsiveContainer } from "recharts";
import { useDashboardSeries } from "../../hooks/useDashboardSeries";
import { useFinancialSeries } from "../../hooks/useFinancialSeries";

/* ── CSS var resolver ─────────────────────────────────────── */
const readCssVar = (name, fallback) => {
  if (typeof window === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
};

function sumOps(points, key) {
  return (points || []).reduce((acc, p) => acc + (p?.metrics?.[key] ?? 0), 0);
}

function sumFin(series, today, key) {
  const arr = [...(series || []), ...(today ? [today] : [])];
  return arr.reduce((acc, p) => acc + Number(p?.metrics?.[key] ?? 0), 0);
}

const FunnelTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const { name, value, conv } = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip-title">{name}</p>
      <div className="chart-tooltip-row">
        <span>Volumen</span>
        <span className="chart-tooltip-val">{value}</span>
      </div>
      {conv != null && (
        <div className="chart-tooltip-row">
          <span>vs paso previo</span>
          <span className="chart-tooltip-val">{conv}%</span>
        </div>
      )}
    </div>
  );
};

/**
 * Embudo clínico — etapas ancladas al flujo de atención (citas → consulta).
 *
 * Por qué NO incluye "Cobradas" como etapa: la métrica invoices_paid_count
 * cuenta TODAS las facturas pagadas (incluye ventas de mostrador sin cita),
 * por lo que dividir cobros/citas daba conversiones >100% sin sentido. Los
 * cobros se muestran como dato de contexto separado, no como conversión.
 *
 * Las 3 etapas (citas → atendidas → consultas finalizadas) sí pertenecen al
 * flujo clínico; la "tasa de atención" (atendidas/citas) es el único ratio
 * garantizado ≤100% (subconjunto real) y se usa como titular.
 */
function ConversionFunnel({ rangeDays = 30 }) {
  const { allPoints, loading: opsLoading } = useDashboardSeries(rangeDays, true);
  const { series: fin, today: finToday, loading: finLoading } = useFinancialSeries(rangeDays, true);

  // Lee los tokens de color una vez en el primer render (CSS ya está aplicado
  // en :root; el SPA no usa SSR). Evita el efecto + setState que disparaba
  // react-hooks/set-state-in-effect.
  const [colors] = useState(() => ({
    primary: readCssVar("--c-primary", "#1a4434"),
    sage:    readCssVar("--sage-500", "#7faa78"),
    amber:   readCssVar("--amber",     "#e8b87a"),
    accent:  readCssVar("--c-accent",  "#d67b5c"),
  }));

  const usable = useMemo(
    () => (allPoints || []).filter((p) => p && !p.isMissing && p.metrics),
    [allPoints]
  );

  const totals = useMemo(() => ({
    citas:  sumOps(usable, "appointmentsTotal"),
    done:   sumOps(usable, "appointmentsDone"),
    closed: sumOps(usable, "medicalRecordsClosed"),
    paid:   sumFin(fin, finToday, "invoicesPaidCount"),
  }), [usable, fin, finToday]);

  const data = useMemo(() => {
    const steps = [
      { name: "Citas programadas",     value: totals.citas,  fill: colors.primary },
      { name: "Atendidas",             value: totals.done,   fill: colors.sage },
      { name: "Consultas finalizadas", value: totals.closed, fill: colors.amber },
    ];
    return steps.map((s, i) => {
      const prev = i > 0 ? steps[i - 1].value : null;
      const conv = prev && prev > 0 ? Math.round((s.value / prev) * 100) : null;
      return { ...s, conv };
    });
  }, [totals, colors]);

  const attendanceRate = totals.citas > 0
    ? Math.round((totals.done / totals.citas) * 100)
    : 0;

  const loading = opsLoading || finLoading;

  if (loading && totals.citas === 0 && totals.closed === 0) {
    return <div className="chart-area"><div className="skeleton-block sk-chart" /></div>;
  }

  if (totals.citas === 0) {
    return (
      <div className="chart-area">
        <div className="chart-state-wrap">
          <p className="chart-state-msg">
            Sin actividad de citas en los últimos {rangeDays} días.
          </p>
        </div>
      </div>
    );
  }

  const base = data[0].value || 1;

  return (
    <div className="chart-area">
      <div className="funnel-header">
        <div className="funnel-headline">
          <span className="funnel-headline-val">{attendanceRate}%</span>
          <span className="funnel-headline-lbl">tasa de atención</span>
        </div>
        <div className="funnel-sub">
          {totals.done} de {totals.citas} citas atendidas · últimos {rangeDays}d
        </div>
      </div>

      <div className="funnel-wrap">
        <div className="funnel-chart-wrap">
          <ResponsiveContainer width="100%" height="100%">
            <FunnelChart>
              <Tooltip content={<FunnelTooltip />} />
              <Funnel
                dataKey="value"
                data={data}
                isAnimationActive={false}
                stroke="var(--c-surface)"
                strokeWidth={2}
              >
                <LabelList
                  position="right"
                  fill="var(--c-text-2)"
                  stroke="none"
                  dataKey="name"
                  fontSize={11}
                  fontFamily="var(--font-display)"
                  fontWeight={600}
                />
              </Funnel>
            </FunnelChart>
          </ResponsiveContainer>
        </div>

        <div className="funnel-steps">
          {data.map((step) => (
            <div key={step.name} className="funnel-step">
              <span
                className="funnel-step-bar"
                style={{
                  "--bar-w": `${Math.min(100, (step.value / base) * 100)}%`,
                  "--bar-c": step.fill,
                }}
              />
              <div className="funnel-step-body">
                <span className="funnel-step-name">{step.name}</span>
                <span className="funnel-step-meta">
                  <span className="funnel-step-val">{step.value.toLocaleString("es-MX")}</span>
                  {step.conv != null && (
                    <span className="funnel-step-conv">{step.conv}%</span>
                  )}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="funnel-context">
        <div className="funnel-context-main">
          <span className="funnel-context-val">{totals.paid.toLocaleString("es-MX")}</span>
          <span className="funnel-context-lbl">facturas cobradas</span>
        </div>
        <span className="funnel-context-note">
          incluye ventas de mostrador · últimos {rangeDays}d
        </span>
      </div>
    </div>
  );
}

export default memo(ConversionFunnel);
