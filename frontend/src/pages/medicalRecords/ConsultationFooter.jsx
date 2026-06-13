import { motion, AnimatePresence } from "framer-motion";
import { Icon } from "../../components/icons";
import styles from "./consultationForm.module.css";

/**
 * Footer de la consulta (presentacional). Izquierda: indicador de autosave
 * (idle / saving / saved / error). Derecha: una sola acción primaria
 * "Finalizar y enviar a Cobros" + "Guardar borrador" secundario.
 *
 * Cuando la consulta está cerrada, solo se ofrece "Cerrar".
 */
function SaveIndicator({ saveState }) {
  const map = {
    saving: { cls: "", icon: <Icon.Loader s={15} />, text: "Guardando…", spin: true },
    saved: {
      cls: styles.saveStateOk,
      icon: <Icon.Check s={15} />,
      text: "Cambios guardados",
      spin: false,
    },
    error: {
      cls: styles.saveStateErr,
      icon: <Icon.AlertTriangle s={15} />,
      text: "No se pudo guardar",
      spin: false,
    },
    idle: { cls: "", icon: null, text: "", spin: false },
  };
  const cfg = map[saveState] || map.idle;
  if (saveState === "idle") return <span className={styles.saveState} />;

  return (
    <span className={`${styles.saveState} ${cfg.cls}`}>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={saveState}
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{
            opacity: 1,
            scale: 1,
            rotate: cfg.spin ? 360 : 0,
          }}
          exit={{ opacity: 0, scale: 0.8 }}
          transition={
            cfg.spin
              ? { rotate: { repeat: Infinity, duration: 0.8, ease: "linear" } }
              : { duration: 0.18 }
          }
          style={{ display: "inline-flex" }}
        >
          {cfg.icon}
        </motion.span>
      </AnimatePresence>
      {cfg.text}
    </span>
  );
}

export default function ConsultationFooter({
  closed,
  saveState,
  saving,
  onCancel,
  onSaveDraft,
  onFinalize,
}) {
  return (
    <div className={styles.foot}>
      <div className={styles.footInner}>
        {closed ? (
          <>
            <span className={`${styles.saveState} ${styles.saveStateOk}`}>
              <Icon.Check s={15} /> Consulta finalizada
            </span>
            <div className={styles.actions}>
              <button className="btn btn-secondary btn-md" onClick={onCancel}>
                Cerrar
              </button>
            </div>
          </>
        ) : (
          <>
            <SaveIndicator saveState={saveState} />
            <div className={styles.actions}>
              <button className="btn btn-secondary btn-md" onClick={onCancel} disabled={saving}>
                Cancelar
              </button>
              <button className="btn btn-secondary btn-md" onClick={onSaveDraft} disabled={saving}>
                <Icon.Check s={16} /> Guardar borrador
              </button>
              <button className="btn btn-primary btn-md" onClick={onFinalize} disabled={saving}>
                Finalizar y enviar a Cobros <Icon.ChevronRight s={16} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
