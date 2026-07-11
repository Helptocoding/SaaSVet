import { forwardRef, useCallback, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Icon } from "../../../../components/icons";
import styles from "../../../../pages/medicalRecords/consultationForm.module.css";
import g from "./general.module.css";

/**
 * Sección "Valoración clínica" — protocolo General (familia diagnóstica).
 * Presentacional puro: el estado vive en ConsultationForm como slice
 * `protocolDraft.general`, que autoguarda en `MedicalRecord.consultation_draft`.
 * NO crea el ConsultationAssessment: eso ocurre en el backend al finalizar
 * (services._materialize_general).
 *
 * Exploración por sistemas con el patrón "resumen + excepciones + acordeón":
 * una fila resumen (puntos + frase), las excepciones alteradas siempre visibles
 * con su hallazgo, y la lista completa como nube de chips en un acordeón
 * colapsado. Candidato a extraerse como `ExamGrid` compartido en la 2ª
 * repetición (preop de Cirugía / ABC de Urgencia).
 *
 * `value` = { chief_complaint, history, exam, differentials, recheck_date }
 * `exam`  = { "<sistema>": { status: "altered", finding: "<texto>" } }  (solo alterados)
 */
const EXAM_SYSTEMS = [
  { key: "actitud", label: "Actitud / estado general" },
  { key: "mucosas", label: "Mucosas" },
  { key: "piel", label: "Piel y pelaje" },
  { key: "cardiovascular", label: "Cardiovascular" },
  { key: "respiratorio", label: "Respiratorio" },
  { key: "digestivo", label: "Digestivo / abdomen" },
  { key: "genitourinario", label: "Genitourinario" },
  { key: "musculoesqueletico", label: "Musculoesquelético" },
  { key: "nervioso", label: "Nervioso" },
  { key: "linfatico", label: "Linfonodos" },
  { key: "ojos_oidos", label: "Ojos y oídos" },
];

const GeneralSection = forwardRef(function GeneralSection(
  { value, onChange, disabled },
  ref
) {
  const v = value || {};
  const exam = v.exam || {};
  const [open, setOpen] = useState(false);

  const setExam = useCallback(
    (key, patch) => {
      const next = { ...(v.exam || {}) };
      if (patch === null) {
        delete next[key]; // volver a "normal" = quitar la clave (JSON magro)
      } else {
        next[key] = { status: "altered", finding: "", ...next[key], ...patch };
      }
      onChange({ exam: next });
    },
    [v.exam, onChange]
  );

  const toggleSystem = useCallback(
    (key) => {
      if (exam[key]?.status === "altered") setExam(key, null);
      else setExam(key, { status: "altered" });
    },
    [exam, setExam]
  );

  const altered = EXAM_SYSTEMS.filter((s) => exam[s.key]?.status === "altered");
  const summaryText =
    altered.length === 0
      ? "Todo dentro de lo normal"
      : `${altered.length} ${altered.length === 1 ? "sistema alterado" : "sistemas alterados"}`;

  return (
    <motion.section
      ref={ref}
      className={styles.card}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: 0.04 }}
    >
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>Valoración clínica</h2>
        <p className={styles.cardDesc}>Motivo, historia y exploración. Captura solo lo que aplique.</p>
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Motivo principal</label>
        <input
          className={styles.control}
          placeholder="p. ej. Vómito desde ayer"
          value={v.chief_complaint || ""}
          disabled={disabled}
          onChange={(e) => onChange({ chief_complaint: e.target.value })}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Historia clínica</label>
        <textarea
          className={styles.control}
          rows={2}
          placeholder="Evolución, antecedentes, cambios recientes…"
          value={v.history || ""}
          disabled={disabled}
          onChange={(e) => onChange({ history: e.target.value })}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Exploración por sistemas</label>
        <p className={g.hint}>Cada sistema inicia normal. Marca solo lo alterado.</p>

        <div className={g.examSummary}>
          <div className={g.examDots}>
            {EXAM_SYSTEMS.map((s) => (
              <span
                key={s.key}
                className={`${g.summaryDot} ${
                  exam[s.key]?.status === "altered" ? g.summaryDotAltered : ""
                }`}
              />
            ))}
          </div>
          <span className={g.examSummaryText}>{summaryText}</span>
          <button type="button" className={g.examReveal} onClick={() => setOpen((o) => !o)}>
            {open ? "Ocultar" : "Revisar"}
            <span className={`${g.chev} ${open ? g.chevOpen : ""}`}>
              <Icon.ChevronDown s={14} />
            </span>
          </button>
        </div>

        {altered.length > 0 && (
          <div className={g.examExceptions}>
            <AnimatePresence initial={false}>
              {altered.map((s) => (
                <motion.div
                  key={s.key}
                  className={g.exceptionCard}
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  transition={{ duration: 0.18 }}
                >
                  <div className={g.exceptionHead}>
                    <span className={g.exceptionName}>{s.label}</span>
                    {!disabled && (
                      <button
                        type="button"
                        className={g.exceptionRemove}
                        onClick={() => setExam(s.key, null)}
                      >
                        Marcar normal
                      </button>
                    )}
                  </div>
                  <input
                    className={styles.control}
                    placeholder="Hallazgo…"
                    value={exam[s.key]?.finding || ""}
                    disabled={disabled}
                    onChange={(e) => setExam(s.key, { finding: e.target.value })}
                  />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}

        <div className={`${g.examAccordion} ${open ? g.examAccordionOpen : ""}`}>
          <div className={g.examAccordionInner}>
            <div className={g.chipCloud}>
              {EXAM_SYSTEMS.map((s) => {
                const isAltered = exam[s.key]?.status === "altered";
                return (
                  <button
                    key={s.key}
                    type="button"
                    disabled={disabled}
                    aria-pressed={isAltered}
                    className={`${g.chip} ${isAltered ? g.chipAltered : ""}`}
                    onClick={() => toggleSystem(s.key)}
                  >
                    <span className={g.chipDot} />
                    {s.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Diagnósticos diferenciales</label>
        <textarea
          className={styles.control}
          rows={2}
          placeholder="Otras posibilidades a descartar…"
          value={v.differentials || ""}
          disabled={disabled}
          onChange={(e) => onChange({ differentials: e.target.value })}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.fieldLabel}>Próxima revisión</label>
        <input
          type="date"
          className={styles.control}
          value={v.recheck_date || ""}
          disabled={disabled}
          onChange={(e) => onChange({ recheck_date: e.target.value || null })}
        />
      </div>
    </motion.section>
  );
});

export default GeneralSection;
