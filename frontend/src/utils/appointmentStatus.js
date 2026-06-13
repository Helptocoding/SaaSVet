// Fuente única de la representación visual de estados de cita.
// Reemplaza los mapas STATUS_LABELS/STATUS_BADGE duplicados por componente.
// NO define enums ni transiciones — solo presentación (label + clase badge).

export const APPT_STATUS_LABEL = {
  scheduled: "Programada",
  confirmed: "Confirmada",
  in_progress: "En consulta",
  done: "Completada",
  canceled: "Cancelada",
  no_show: "No se presentó",
};

// Unificado: no_show usa badge-default (consistente con la leyenda del timeline).
export const APPT_STATUS_BADGE = {
  scheduled: "badge-info",
  confirmed: "badge-purple",
  in_progress: "badge-warning",
  done: "badge-success",
  canceled: "badge-danger",
  no_show: "badge-default",
};

export const statusLabel = (status) => APPT_STATUS_LABEL[status] || status;
export const statusBadgeClass = (status) => APPT_STATUS_BADGE[status] || "badge-default";
