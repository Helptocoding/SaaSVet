import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Icon } from "../../components/icons";
import styles from "./consultationForm.module.css";

/**
 * Riel de contexto de la consulta (columna izquierda sticky). Reúne lo que antes
 * vivía en el banner superior + el footer inferior:
 *   identidad de la mascota → vitales editables INLINE (sin modal, spec §2)
 *   → navegación por secciones con scroll-spy → autosave + acciones apiladas.
 * Presentacional: el estado (draft, saveState, navegación activa) lo posee
 * ConsultationForm.
 */

/** Chip de vital editable inline: click → input enfocado; blur/Enter → lectura. */
function EditableVital({ field, draft, formErrors, disabled, onChange, onClearError }) {
  const [editing, setEditing] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const raw = draft[field.f];
  const hasVal = raw !== "" && raw != null;
  const hasError = !!formErrors[field.f];

  const commit = () => setEditing(false);

  return (
    <div
      className={`${styles.railVital} ${hasError ? styles.railVitalError : ""} ${
        disabled ? styles.railVitalDisabled : ""
      }`}
      onClick={() => !disabled && !editing && setEditing(true)}
    >
      <span className={styles.railVitalIcon}>{field.icon}</span>
      <div className={styles.railVitalBody}>
        <span className={styles.railVitalLabel}>{field.l}</span>
        {editing && !disabled ? (
          <input
            ref={inputRef}
            className={styles.railVitalInput}
            type="text"
            inputMode="decimal"
            value={raw ?? ""}
            placeholder={field.u}
            onChange={(e) => {
              onChange({ [field.f]: e.target.value });
              if (hasError) onClearError(field.f);
            }}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === "Escape") {
                e.preventDefault();
                commit();
              }
            }}
          />
        ) : (
          <span className={styles.railVitalValue}>
            {hasVal ? (
              <>
                {raw}
                <span className={styles.railVitalUnit}> {field.u}</span>
              </>
            ) : (
              <span className={styles.railVitalPlaceholder}>—</span>
            )}
          </span>
        )}
      </div>
    </div>
  );
}

/** Indicador de autosave con contador de segundos desde el último guardado. */
function SaveIndicator({ saveState, lastSavedAt }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!lastSavedAt || saveState !== "saved") return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [lastSavedAt, saveState]);

  const savedText = useMemo(() => {
    if (!lastSavedAt) return "Todo sincronizado";
    const secs = Math.max(0, Math.round((now - lastSavedAt) / 1000));
    if (secs === 0) return "Guardado justo ahora";
    if (secs < 60) return `Guardado hace ${secs} s`;
    return "Todo sincronizado";
  }, [lastSavedAt, now]);

  const map = {
    saving: { cls: "", icon: <Icon.Loader s={14} />, text: "Guardando…", spin: true },
    saved: { cls: styles.railSaveOk, icon: <Icon.Check s={14} />, text: savedText, spin: false },
    error: { cls: styles.railSaveErr, icon: <Icon.AlertTriangle s={14} />, text: "No se pudo guardar", spin: false },
    idle: { cls: "", icon: null, text: "", spin: false },
  };
  const cfg = map[saveState] || map.idle;
  if (saveState === "idle") return <span className={styles.railSave} />;

  return (
    <span className={`${styles.railSave} ${cfg.cls}`}>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={saveState}
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1, rotate: cfg.spin ? 360 : 0 }}
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

export default function ConsultationRail({
  pet,
  title,
  draft,
  vitalFields,
  formErrors,
  closed,
  onVitalsChange,
  onClearError,
  navItems,
  activeSection,
  onNavigate,
  saveState,
  lastSavedAt,
  saving,
  onCancel,
  onSaveDraft,
  onFinalize,
}) {
  const ownerName = pet?.owner?.name || pet?.owner_name || "No asignado";
  const metaParts = [pet?.species, pet?.breed, pet?.age_label || pet?.age].filter(Boolean);
  const initial = (pet?.name || "?").trim().charAt(0).toUpperCase();

  return (
    <aside className={styles.rail}>
      <div className={styles.railIdentity}>
        <span className={styles.railAvatar}>{initial}</span>
        <div className={styles.railWho}>
          <div className={styles.railEyebrow}>{title}</div>
          <div className={styles.railName}>{pet?.name || "—"}</div>
          <div className={styles.railSub}>
            {metaParts.length ? metaParts.join(" · ") : "Sin datos"} · Tutor {ownerName}
          </div>
        </div>
      </div>

      <hr className={styles.railDivider} />

      <div className={styles.railVitals}>
        {vitalFields.map((f) => (
          <EditableVital
            key={f.f}
            field={f}
            draft={draft}
            formErrors={formErrors}
            disabled={closed}
            onChange={onVitalsChange}
            onClearError={onClearError}
          />
        ))}
      </div>

      {!closed && navItems.length > 0 && (
        <>
          <hr className={styles.railDivider} />
          <nav className={styles.railNav}>
            {navItems.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`${styles.railNavBtn} ${
                  activeSection === item.id ? styles.railNavBtnActive : ""
                }`}
                onClick={() => onNavigate(item.id)}
              >
                <span>{item.label}</span>
                {item.badge != null && <span className={styles.railNavBadge}>{item.badge}</span>}
              </button>
            ))}
          </nav>
        </>
      )}

      <div className={styles.railFoot}>
        {closed ? (
          <>
            <span className={`${styles.railSave} ${styles.railSaveOk}`}>
              <Icon.Check s={14} /> Consulta finalizada
            </span>
            <div className={styles.railActions}>
              <button className="btn btn-secondary btn-md" onClick={onCancel}>
                Cerrar
              </button>
            </div>
          </>
        ) : (
          <>
            <SaveIndicator saveState={saveState} lastSavedAt={lastSavedAt} />
            <div className={styles.railActions}>
              <button className="btn btn-primary btn-md" onClick={onFinalize} disabled={saving}>
                Finalizar y enviar a Cobros <Icon.ChevronRight s={16} />
              </button>
              <button className="btn btn-secondary btn-md" onClick={onSaveDraft} disabled={saving}>
                <Icon.Check s={16} /> Guardar borrador
              </button>
              <button className="btn btn-ghost btn-md" onClick={onCancel} disabled={saving}>
                Cancelar
              </button>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
