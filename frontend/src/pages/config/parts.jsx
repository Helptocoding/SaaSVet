import styles from "./config.module.css";

/** Fila de ajuste: etiqueta + descripción a la izquierda, control a la derecha.
 *  `error`: mensaje del servidor (o de la validación previa) para ese campo. */
export const SettingRow = ({ label, desc, error, errorId, children }) => (
  <div className={styles.settingRow}>
    <div>
      <p className={styles.settingLabel}>{label}</p>
      {desc && <p className={styles.settingDesc}>{desc}</p>}
    </div>
    <div className={styles.settingControl}>
      {children}
      {error && <p id={errorId} className={styles.fieldError} role="alert">{error}</p>}
    </div>
  </div>
);

/** Fila con control tipo toggle (alineado a la derecha, centrado). */
export const ToggleRow = ({ label, desc, on, disabled, onToggle }) => (
  <div className={`${styles.settingRow} ${styles.settingRowToggle}`}>
    <div>
      <p className={`${styles.settingLabel} ${styles.settingLabelToggle}`}>{label}</p>
      {desc && <p className={styles.settingDesc}>{desc}</p>}
    </div>
    <div className={styles.settingControl}>
      <button
        type="button"
        role="switch"
        aria-label={label}
        aria-checked={!!on}
        disabled={disabled}
        onClick={onToggle}
        className={`${styles.toggle} ${on ? styles.toggleOn : styles.toggleOff} ${disabled ? styles.toggleDisabled : ""}`}
      >
        <span className={`${styles.toggleKnob} ${on ? styles.toggleKnobOn : styles.toggleKnobOff}`} />
      </button>
    </div>
  </div>
);

/** Header de identidad de la clínica (avatar + nombre + meta). */
export const IdentityHeader = ({ name, meta }) => (
  <div className={styles.identity}>
    <div className={styles.avatar}>{(name || "?").trim().charAt(0).toUpperCase()}</div>
    <div className={styles.identityInfo}>
      <p className={styles.identityName}>{name || "Sin nombre"}</p>
      {meta.length > 0 && (
        <p className={styles.identityMeta}>
          {meta.map((m, i) => (
            <span key={i}>
              {i > 0 && <span className={styles.identityDot}>·</span>} {m}
            </span>
          ))}
        </p>
      )}
    </div>
  </div>
);
