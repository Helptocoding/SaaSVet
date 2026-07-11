import { forwardRef } from "react";
import { motion } from "framer-motion";
import { Icon } from "../../../../components/icons";
import styles from "../../../../pages/medicalRecords/consultationForm.module.css";

/**
 * Sección "Cirugía" (A3) — parte quirúrgico en 3 grupos (PreOp · Procedimiento ·
 * Recuperación). Presentacional puro: el estado vive en ConsultationForm como
 * slice `protocolDraft.surgery`, autoguardado en `MedicalRecord.consultation_draft`.
 * NO crea el SurgeryRecord: lo materializa el backend al finalizar.
 */
const SURGERY_TYPES = [
  { v: "electiva", l: "Electiva" },
  { v: "programada", l: "Programada" },
  { v: "urgencia", l: "Urgencia" },
  { v: "emergencia", l: "Emergencia" },
];
const ASA_CLASSES = [
  { v: "I", l: "ASA I — sano" },
  { v: "II", l: "ASA II — enf. leve" },
  { v: "III", l: "ASA III — enf. grave" },
  { v: "IV", l: "ASA IV — amenaza vital" },
  { v: "V", l: "ASA V — moribundo" },
];
const ANESTHESIA_TYPES = [
  { v: "general", l: "General" },
  { v: "locorregional", l: "Locorregional" },
  { v: "sedacion", l: "Sedación" },
  { v: "local", l: "Local" },
];
const WOUND_CLASSES = [
  { v: "", l: "— sin clasificar —" },
  { v: "limpia", l: "Limpia" },
  { v: "limpia_contaminada", l: "Limpia-contaminada" },
  { v: "contaminada", l: "Contaminada" },
  { v: "sucia", l: "Sucia" },
];

const SurgerySection = forwardRef(function SurgerySection({ value, onChange, disabled }, ref) {
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
      {options.map((o) => (
        <option key={o.v} value={o.v}>{o.l}</option>
      ))}
    </select>
  );

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
        <h2 className={styles.cardTitle}>Cirugía</h2>
        <p className={styles.cardDesc}>Parte quirúrgico: preoperatorio, procedimiento y recuperación.</p>
      </div>

      {/* ── Preoperatorio ── */}
      <div className={styles.field}>
        <label className={styles.fieldLabel}>Diagnóstico prequirúrgico</label>
        <input
          className={styles.control}
          placeholder="p. ej. Fractura de tibia"
          value={v.preop_diagnosis || ""}
          disabled={disabled}
          onChange={(e) => set({ preop_diagnosis: e.target.value })}
        />
      </div>

      <div className={styles.grid2}>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Tipo de cirugía {req}</label>
          <Select field="surgery_type" options={SURGERY_TYPES} placeholder="Selecciona…" />
        </div>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Clasificación ASA {req}</label>
          <Select field="asa_class" options={ASA_CLASSES} placeholder="Selecciona…" />
          <label className={styles.switchLabel} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, fontWeight: 500 }}>
            <input
              type="checkbox"
              checked={!!v.asa_emergency}
              disabled={disabled}
              onChange={(e) => set({ asa_emergency: e.target.checked })}
            />
            Emergencia (sufijo E)
          </label>
        </div>
      </div>

      {/* ── Procedimiento ── */}
      <hr className={styles.railDivider} />
      <div className={styles.grid2}>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Tipo de anestesia {req}</label>
          <Select field="anesthesia_type" options={ANESTHESIA_TYPES} placeholder="Selecciona…" />
        </div>
        <div className={styles.field}>
          <label className={styles.fieldLabel}>Clasificación de herida</label>
          <Select field="wound_class" options={WOUND_CLASSES} />
        </div>
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Procedimiento realizado {req}</label>
        <textarea
          className={styles.control}
          rows={2}
          placeholder="Técnica quirúrgica realizada…"
          value={v.procedure || ""}
          disabled={disabled}
          onChange={(e) => set({ procedure: e.target.value })}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Hallazgos</label>
        <textarea
          className={styles.control}
          rows={2}
          placeholder="Hallazgos quirúrgicos relevantes…"
          value={v.findings || ""}
          disabled={disabled}
          onChange={(e) => set({ findings: e.target.value })}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Complicaciones</label>
        <textarea
          className={styles.control}
          rows={2}
          placeholder="Ninguna, o describe las complicaciones…"
          value={v.complications || ""}
          disabled={disabled}
          onChange={(e) => set({ complications: e.target.value })}
        />
      </div>

      {/* ── Recuperación ── */}
      <hr className={styles.railDivider} />
      <div className={styles.field}>
        <label className={styles.fieldLabel}>Indicaciones postoperatorias {req}</label>
        <textarea
          className={styles.control}
          rows={2}
          placeholder="Reposo, medicación, cuidados de la herida…"
          value={v.postop_instructions || ""}
          disabled={disabled}
          onChange={(e) => set({ postop_instructions: e.target.value })}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Retiro de puntos</label>
        <input
          type="date"
          className={styles.control}
          value={v.suture_removal_date || ""}
          disabled={disabled}
          onChange={(e) => set({ suture_removal_date: e.target.value || null })}
        />
      </div>
    </motion.section>
  );
});

export default SurgerySection;
