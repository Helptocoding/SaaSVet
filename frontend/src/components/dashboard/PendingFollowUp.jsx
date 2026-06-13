import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppointmentsByStatus } from "../../hooks/useAppointmentsByStatus";
import AppointmentQuickModal from "./AppointmentQuickModal";
import { Icon } from "../icons";

/**
 * Citas por resolver — citas con fecha pasada que quedaron en
 * scheduled/confirmed (nadie las cerró, canceló ni marcó no-asistió).
 *
 * Fase 1: usa el endpoint EXISTENTE status-breakdown vía el hook
 * useAppointmentsByStatus (sin backend nuevo). Rango query: últimos 30 días
 * hasta ayer — una cita perdida hace 3 semanas durante el trial NO debe
 * desaparecer. El límite es VISUAL (máx 5 filas), no del query.
 *
 * Acciones (Atender / No asistió / Reprogramar) se resuelven reutilizando
 * AppointmentQuickModal.
 */

const MAX_VISIBLE = 5;
const RANGE_DAYS = 30;

function fmtWhen(dateStr, timeStr) {
  const t = (timeStr || "").slice(0, 5);
  if (!dateStr) return t;
  const d = new Date(dateStr + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - d) / 86400000);
  const label = diff === 1
    ? "Ayer"
    : d.toLocaleDateString("es-MX", { day: "numeric", month: "short" });
  return t ? `${label} · ${t}` : label;
}

export default function PendingFollowUp() {
  const navigate = useNavigate();
  const [clickedApptId, setClickedApptId] = useState(null);

  const dateRange = useMemo(() => {
    const to = new Date();
    to.setDate(to.getDate() - 1);            // ayer
    const from = new Date();
    from.setDate(from.getDate() - RANGE_DAYS); // últimos 30 días
    return { from, to };
  }, []);

  const { byStatus, totals, loading, refetch } = useAppointmentsByStatus(dateRange);

  // Refresca cuando otra acción del dashboard dispara el evento global
  // (p.ej. marcar no-asistió o atender desde el modal).
  useEffect(() => {
    const onRefresh = () => refetch();
    window.addEventListener("dashboard:refresh", onRefresh);
    return () => window.removeEventListener("dashboard:refresh", onRefresh);
  }, [refetch]);

  const items = useMemo(() => {
    const sched = byStatus?.scheduled?.items || [];
    const conf = byStatus?.confirmed?.items || [];
    return [...sched, ...conf].sort((a, b) =>
      `${a.date}${a.start_time}` < `${b.date}${b.start_time}` ? 1 : -1
    );
  }, [byStatus]);

  const total = (totals?.scheduled || 0) + (totals?.confirmed || 0);

  if (loading && total === 0 && items.length === 0) {
    return (
      <div className="dsp">
        <div className="dsp-head">
          <h3 className="dsp-title">Citas por resolver</h3>
        </div>
        <p className="dsp-empty">Cargando…</p>
      </div>
    );
  }

  if (total === 0) {
    return (
      <div className="dsp">
        <div className="dsp-head">
          <h3 className="dsp-title">Citas por resolver</h3>
        </div>
        <p className="dsp-empty">Todo al día. Sin citas pendientes.</p>
      </div>
    );
  }

  const visible = items.slice(0, MAX_VISIBLE);
  const remaining = total - visible.length;

  return (
    <div className="dsp">
      <div className="dsp-head">
        <h3 className="dsp-title">Citas por resolver</h3>
        <span className="badge badge-warning">{total}</span>
      </div>

      <div className="dsp-backlog-list">
        {visible.map((a) => (
          <div
            key={a.public_id}
            className="dsp-backlog-row"
            role="button"
            tabIndex={0}
            onClick={() => setClickedApptId(a.public_id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setClickedApptId(a.public_id);
              }
            }}
          >
            <div className="dsp-callout-name">{a.pet_name || "Sin paciente"}</div>
            <div className="dsp-callout-meta">
              {fmtWhen(a.date, a.start_time)}
              {a.reason ? ` · ${a.reason}` : ""}
            </div>
            <div className="dsp-callout-warn">
              <Icon.Clock s={12} /> Sin resolver — toca para atender, marcar no asistió o reprogramar
            </div>
          </div>
        ))}
      </div>

      {remaining > 0 && (
        <button
          className="btn btn-ghost btn-xs dsp-action"
          onClick={() => navigate("/appointments")}
        >
          + Ver {remaining} más →
        </button>
      )}

      {clickedApptId && (
        <AppointmentQuickModal
          publicId={clickedApptId}
          onClose={() => setClickedApptId(null)}
        />
      )}
    </div>
  );
}
