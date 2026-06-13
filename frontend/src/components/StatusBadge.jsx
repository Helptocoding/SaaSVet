import { statusLabel, statusBadgeClass } from "../utils/appointmentStatus";

// Badge de estado de cita. Única fuente visual — ver utils/appointmentStatus.js.
export default function StatusBadge({ status, className = "" }) {
  return (
    <span className={`badge ${statusBadgeClass(status)} ${className}`.trim()}>
      {statusLabel(status)}
    </span>
  );
}
