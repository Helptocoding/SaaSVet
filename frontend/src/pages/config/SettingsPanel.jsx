import styles from "./config.module.css";

/**
 * Shell presentacional único de cada apartado de Configuración.
 * Estructura premium (Vercel/GitHub): encabezado de sección (título + una línea
 * de descripción muteada) → panel con borde suave → cuerpo → footer opcional
 * con acción a la derecha y una nota de contexto a la izquierda.
 *
 * Todas las secciones lo usan para tener MISMA jerarquía, espaciado y ritmo.
 */
const SettingsPanel = ({ title, description, children, footer, footerNote, action, padded = true }) => (
    <section className={styles.section}>
        <header className={styles.sectionHead}>
            <div className={styles.sectionHeadRow}>
                <h2 className={styles.sectionTitle}>{title}</h2>
                {action && <div className={styles.sectionAction}>{action}</div>}
            </div>
            {description && <p className={styles.sectionDesc}>{description}</p>}
        </header>
        <div className={styles.panel}>
            <div className={padded ? styles.panelBody : styles.panelBodyFlush}>
                {children}
            </div>
            {footer && (
                <div className={styles.panelFooter}>
                    <span className={styles.footerNote}>{footerNote}</span>
                    <div className={styles.footerActions}>{footer}</div>
                </div>
            )}
        </div>
    </section>
);

export default SettingsPanel;
