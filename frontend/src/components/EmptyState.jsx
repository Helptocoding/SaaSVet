/**
 * EmptyState — estado vacío accionable, reusable y PRESENTACIONAL.
 *
 * Responde: qué pasa (title), por qué / siguiente paso (body) y la acción
 * (actions). NO conoce RBAC: el caller arma las acciones ya filtradas por
 * permiso (`can("x") ? action : null`) y las pasa; aquí solo se descartan las
 * nulas. Así el componente no depende de useAuth ni del dominio.
 *
 * Props:
 *   icon     — componente de icono opcional (ej. Icon.PawPrint).
 *   title    — string requerido.
 *   body     — string opcional (motivo + siguiente paso).
 *   actions  — array de { label, onClick, variant? } | null. Las nulas se omiten.
 *   compact  — padding reducido (para tarjetas/secciones).
 */
const EmptyState = ({ icon: IconComp, title, body, actions = [], compact = false }) => {
  const visible = (actions || []).filter(Boolean);

  return (
    <div className={`empty-state${compact ? " empty-state-compact" : ""}`}>
      {IconComp && (
        <div className="empty-state-icon">
          <IconComp s={28} c="var(--c-text-3)" />
        </div>
      )}
      <p className="empty-state-title">{title}</p>
      {body && <p className="empty-state-sub">{body}</p>}
      {visible.length > 0 && (
        <div className="empty-state-actions">
          {visible.map((a, i) => (
            <button
              key={a.label || i}
              className={`btn btn-${a.variant || "secondary"} btn-md`}
              onClick={a.onClick}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default EmptyState;
