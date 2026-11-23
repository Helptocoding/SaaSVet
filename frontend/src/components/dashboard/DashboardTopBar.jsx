import { useMemo } from "react";
import { useAuth } from "../../auth/authContext";
import { useNavigate } from "react-router-dom";
import { Icon } from "../icons";
import NotificationBell from "../notifications/NotificationBell";
import FeedbackButton from "../FeedbackButton";
import "./DashboardTopBar.css";

function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return "Buenos días";
  if (h < 19) return "Buenas tardes";
  return "Buenas noches";
}

// Saludo, fecha y acciones del Dashboard. Los ingresos del día pasaron a ser un
// indicador más (plan UX D10); antes eran una tarjeta ancha encima de todo.
export default function DashboardTopBar({ summary }) {
  const { user, can } = useAuth();
  const navigate = useNavigate();

  const dateLabel = useMemo(
    () => new Date().toLocaleDateString("es-ES", {
      weekday: "long", day: "numeric", month: "long", year: "numeric",
    }),
    []
  );

  const firstName  = user?.first_name || user?.username || "Equipo";
  // La barra superior solo señala lo URGENTE (crítico). Los avisos viven en
  // sus propias cards (Pendientes clínicos, Stock crítico, Citas por resolver).
  // Crítico beta = stock agotado (severity 'critical').
  const criticos   = (summary?.stock_alerts || []).filter(a => a.severity === "critical").length;

  return (
    <div className="dtop-wrap">
      <div className="phead dtop-phead">
        <div>
          <h1 className="ptitle">{getGreeting()}, {firstName}</h1>
          <p className="psub">{dateLabel} · {user?.organization_name || "Sistema"}</p>
        </div>

        <div className="pacts dtop-pacts">
          <FeedbackButton />
          {can?.("notification.list") && <NotificationBell />}
          {criticos > 0 && (
            <span className="badge badge-danger dtop-alert-badge">
              <Icon.AlertOctagon s={12} /> {criticos} crítico{criticos > 1 ? "s" : ""}
            </span>
          )}
          <button className="btn btn-primary btn-md" onClick={() => navigate("/appointments")}>
            <Icon.Plus s={14} /> Nueva cita
          </button>
        </div>
      </div>
    </div>
  );
}
