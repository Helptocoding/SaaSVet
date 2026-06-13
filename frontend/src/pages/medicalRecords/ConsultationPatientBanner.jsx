import { Icon } from "../../components/icons";
import styles from "./consultationForm.module.css";

/**
 * Banner de paciente (presentacional). Contexto clínico siempre visible:
 * identidad de la mascota + tutor a la izquierda; chips de vitales (mono) y
 * acceso al editor de signos vitales a la derecha.
 *
 * Los chips son solo lectura — la edición vive en VitalsModal (progressive
 * disclosure). Los valores numéricos usan tipografía monoespaciada.
 */
export default function ConsultationPatientBanner({
  pet,
  title,
  draft,
  vitalFields,
  formErrors,
  closed,
  onEditVitals,
}) {
  const ownerName = pet?.owner?.name || pet?.owner_name || "No asignado";
  const metaParts = [pet?.species, pet?.breed].filter(Boolean);

  return (
    <header className={styles.banner}>
      <div className={styles.bannerRow}>
        <div>
          <div className={styles.eyebrow}>Historial clínico</div>
          <h1 className={styles.title}>{title}</h1>
          <div className={styles.who}>
            <div className={styles.avatar}>{(pet?.name?.[0] || "P").toUpperCase()}</div>
            <div>
              <div className={styles.whoName}>{pet?.name || "—"}</div>
              <div className={styles.whoMeta}>
                {metaParts.length ? metaParts.join(" · ") : "—"}
                {"  ·  Tutor: "}
                {ownerName}
              </div>
            </div>
          </div>
        </div>

        <div className={styles.bannerRight}>
          <div className={styles.vitals}>
            {vitalFields.map((v) => {
              const val = draft[v.f];
              const hasVal = val !== "" && val != null;
              return (
                <div
                  key={v.f}
                  className={`${styles.vital} ${formErrors[v.f] ? styles.vitalError : ""}`}
                >
                  <div className={styles.vitalLabel}>{v.l}</div>
                  <div className={`${styles.vitalVal} ${styles.mono}`}>
                    {hasVal ? val : "—"}
                    {hasVal && <span className={styles.vitalUnit}> {v.u}</span>}
                  </div>
                </div>
              );
            })}
          </div>
          <button className={styles.editVitalsBtn} onClick={onEditVitals}>
            <Icon.Activity s={14} />
            {closed ? "Ver signos vitales" : "Editar signos vitales"}
          </button>
        </div>
      </div>
    </header>
  );
}
