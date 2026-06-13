import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../icons";

/**
 * Pendientes clínicos — consultas abiertas, particionadas SIN solape.
 *
 * Vista inicial COMPACTA: solo los encabezados de grupo con su conteo. Cada
 * grupo es un acordeón clickeable que despliega inline sus consultas. Se eligió
 * acordeón (no drawer) por consistencia con el resto de paneles laterales del
 * dashboard, que expanden inline.
 *
 * Partición exacta y mutuamente excluyente sobre open_total (conteos del
 * backend, no de open_records[] que está capado a 50):
 *
 *   🟢 Listas para cerrar = open_total − without_diagnosis   (abiertas CON diagnóstico)
 *   🟡 Sin diagnóstico     = without_diagnosis                (expediente incompleto)
 *
 * Cada fila navega DIRECTO al registro vía public_id: /medical-records?record=<uuid>.
 * Nunca se usa el PK interno. No se modifica backend.
 */

// Contexto temporal disponible en open_records (el backend no expone created_at
// crudo, sí hours_open / days_open). Se muestra como antigüedad relativa.
function formatAge(rec) {
  const hours = rec.hours_open ?? 0;
  if (hours < 1) return "hace menos de 1 h";
  if (hours < 24) return `hace ${Math.round(hours)} h`;
  const days = rec.days_open ?? Math.round(hours / 24);
  return `hace ${days} d`;
}

function BacklogGroup({ icon, label, hint, count, records, expanded, onToggle, onOpenRecord }) {
  if (count === 0) return null;
  const overflow = count - records.length;

  return (
    <div className="dsp-group">
      <button
        type="button"
        className="dsp-group-toggle"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className="dsp-row-ico">{icon}</span>
        <span className="dsp-group-lbl">{label}</span>
        <span className="dsp-group-end">
          <span className="dsp-row-num">{count}</span>
          <span className="dsp-caret">{expanded ? "▾" : "▸"}</span>
        </span>
      </button>

      {expanded && (
        <>
          {records.length > 0 && (
            <ul className="dsp-backlog-list">
              {records.map((r) => (
                <li
                  key={r.public_id}
                  className="dsp-backlog-row"
                  role="button"
                  tabIndex={0}
                  onClick={() => onOpenRecord(r.public_id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onOpenRecord(r.public_id);
                    }
                  }}
                >
                  <div className="dsp-callout-name">{r.pet_name || "Paciente"}</div>
                  <div className="dsp-callout-meta">
                    {r.veterinarian_name ? `${r.veterinarian_name} · ` : ""}
                    {formatAge(r)}
                  </div>
                  {r.needs_attention && (
                    <div className="dsp-callout-warn">
                      <Icon.AlertCircle s={11} c="var(--c-warning-text)" />
                      Requiere atención
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {overflow > 0 && (
            <p className="dsp-overflow">+{overflow} más · ver en historial</p>
          )}

          <span className="dsp-group-hint">{hint}</span>
        </>
      )}
    </div>
  );
}

export default function ClinicalBacklog({ backlog }) {
  const navigate = useNavigate();
  const [openGroup, setOpenGroup] = useState(null); // 'ready' | 'noDiag' | null

  if (!backlog) return null;

  const total   = backlog.open_total ?? 0;
  const noDiag  = backlog.without_diagnosis ?? 0;
  const ready   = Math.max(0, total - noDiag);   // abiertas con diagnóstico
  const records = backlog.open_records ?? [];

  if (total === 0) {
    return (
      <div className="dsp">
        <div className="dsp-head">
          <h3 className="dsp-title">Pendientes clínicos</h3>
        </div>
        <p className="dsp-empty">Sin consultas pendientes.</p>
      </div>
    );
  }

  const readyRecords  = records.filter((r) => r.has_diagnosis);
  const noDiagRecords = records.filter((r) => !r.has_diagnosis);
  const openRecord = (publicId) => navigate(`/medical-records?record=${publicId}`);
  const toggle = (g) => setOpenGroup((prev) => (prev === g ? null : g));

  return (
    <div className="dsp">
      <div className="dsp-head">
        <h3 className="dsp-title">Pendientes clínicos</h3>
        {noDiag > 0 && <span className="badge badge-warning">{noDiag}</span>}
      </div>

      <BacklogGroup
        icon={<Icon.CheckCircle s={15} c="var(--c-success-text)" />}
        label="Listas para cerrar"
        hint="Continuar consulta →"
        count={ready}
        records={readyRecords}
        expanded={openGroup === "ready"}
        onToggle={() => toggle("ready")}
        onOpenRecord={openRecord}
      />

      <BacklogGroup
        icon={<Icon.AlertCircle s={15} c="var(--c-warning-text)" />}
        label="Sin diagnóstico"
        hint="Completar expediente →"
        count={noDiag}
        records={noDiagRecords}
        expanded={openGroup === "noDiag"}
        onToggle={() => toggle("noDiag")}
        onOpenRecord={openRecord}
      />

      <button
        className="btn btn-ghost btn-xs dsp-action"
        onClick={() => navigate("/medical-records")}
      >
        Gestionar consultas →
      </button>
    </div>
  );
}
