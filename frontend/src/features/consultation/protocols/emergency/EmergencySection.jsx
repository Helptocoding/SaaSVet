import { forwardRef } from "react";
import { motion } from "framer-motion";
import { Icon } from "../../../../components/icons";
import DateField from "../../../../components/DateField";
import styles from "../../../../pages/medicalRecords/consultationForm.module.css";

/**
 * Sección "Urgencia" (A3). "Evaluación rápida" (semáforos) por delante, A/B/C por
 * detrás; tiempos, triage, acciones de estabilización (chips de un toque) y estado
 * al egreso. Presentacional: el estado vive en ConsultationForm como slice
 * `protocolDraft.emergency`. NO crea el EmergencyRecord (backend al finalizar).
 */
const TRIAGE_LEVELS = [
  { v: "red", l: "🔴 Rojo — reanimación" },
  { v: "orange", l: "🟠 Naranja — emergencia" },
  { v: "yellow", l: "🟡 Amarillo — urgente" },
  { v: "green", l: "🟢 Verde — menos urgente" },
  { v: "blue", l: "🔵 Azul — no urgente" },
];
const ABC_STATUS = [
  { v: "normal", l: "Normal" },
  { v: "compromised", l: "Comprometido" },
  { v: "critical", l: "Crítico" },
];
const DISCHARGE_STATUS = [
  { v: "alta", l: "Alta" },
  { v: "hospitalizacion", l: "Hospitalización" },
  { v: "referido", l: "Referido" },
  { v: "fallecido", l: "Fallecido" },
];
const QUICK_ACTIONS = ["O2", "Fluidos IV", "RCP", "Hemostasia", "Analgesia", "Calor"];

const EmergencySection = forwardRef(function EmergencySection({ value, onChange, disabled }, ref) {
  const v = value || {};
  const set = (patch) => onChange(patch);

  const Select = ({ field, options, placeholder }) => (
    <select
      className={styles.control}
      value={v[field] ?? ""}
      disabled={disabled}
      onChange={(e) => set({ [field]: e.target.value })}
    >
      {placeholder != null && <option value="">{placeholder}</option>}
      {options.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
    </select>
  );

  const addAction = (label) => {
    const cur = (v.stabilization_actions || "").trim();
    if (cur.split(/[,\n]/).map((s) => s.trim().toLowerCase()).includes(label.toLowerCase())) return;
    set({ stabilization_actions: cur ? `${cur}, ${label}` : label });
  };

  const req = <span className={styles.req}>*</span>;

  return (
    <motion.section
      ref={ref}
      className={styles.card}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: 0.04 }}
    >
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>Urgencia</h2>
        <p className={styles.cardDesc}>Tiempos, triage, evaluación rápida y estado al egreso.</p>
      </div>

      {/* ── Tiempos ── */}
      <div className={styles.grid2}>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Hora de llegada {req}</label>
          <input
            type="datetime-local" className={styles.control}
            value={v.arrived_at || ""} disabled={disabled}
            onChange={(e) => set({ arrived_at: e.target.value })}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Hora de triage {req}</label>
          <input
            type="datetime-local" className={styles.control}
            value={v.triage_at || ""} disabled={disabled}
            onChange={(e) => set({ triage_at: e.target.value })}
          />
        </div>
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Nivel de triage {req}</label>
        <Select field="triage_level" options={TRIAGE_LEVELS} placeholder="Selecciona…" />
      </div>

      {/* ── Evaluación rápida (ABC por detrás) ── */}
      <hr className={styles.railDivider} />
      <div className={styles.field}>
        <label className={styles.fieldLabel}>Evaluación rápida ¿cómo llega el paciente?</label>
        <div className={styles.grid2}>
          <div>
            <span className={styles.adderLabel}>Vía aérea (A)</span>
            <Select field="airway_status" options={ABC_STATUS} />
          </div>
          <div>
            <span className={styles.adderLabel}>Respiración (B)</span>
            <Select field="breathing_status" options={ABC_STATUS} />
          </div>
          <div>
            <span className={styles.adderLabel}>Circulación (C)</span>
            <Select field="circulation_status" options={ABC_STATUS} />
          </div>
        </div>
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Problema principal {req}</label>
        <input
          className={styles.control}
          placeholder="p. ej. Dificultad respiratoria aguda"
          value={v.chief_complaint || ""} disabled={disabled}
          onChange={(e) => set({ chief_complaint: e.target.value })}
        />
      </div>

      {/* ── Estabilización ── */}
      <div className={styles.field}>
        <label className={styles.fieldLabel}>Acciones de estabilización {req}</label>
        {!disabled && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
            {QUICK_ACTIONS.map((a) => (
              <button
                key={a} type="button" className="btn btn-secondary btn-xs"
                onClick={() => addAction(a)}
              >
                <Icon.Plus s={12} /> {a}
              </button>
            ))}
          </div>
        )}
        <textarea
          className={styles.control}
          rows={2}
          placeholder="O2, fluidos IV, analgesia…"
          value={v.stabilization_actions || ""} disabled={disabled}
          onChange={(e) => set({ stabilization_actions: e.target.value })}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Respuesta</label>
        <textarea
          className={styles.control}
          rows={2}
          placeholder="Respuesta del paciente a las maniobras…"
          value={v.response || ""} disabled={disabled}
          onChange={(e) => set({ response: e.target.value })}
        />
      </div>

      {/* ── Egreso ── */}
      <hr className={styles.railDivider} />
      <div className={styles.grid2}>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Estado al egreso {req}</label>
          <Select field="discharge_status" options={DISCHARGE_STATUS} placeholder="Selecciona…" />
        </div>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Revaloración</label>
          <DateField
            value={v.reassessment_date || ""}
            onChange={(s) => set({ reassessment_date: s || null })}
            disabled={disabled}
            clearable
            inputClassName={styles.control}
          />
        </div>
      </div>
    </motion.section>
  );
});

export default EmergencySection;
