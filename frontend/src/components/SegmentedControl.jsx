import { Icon } from "./icons";

/**
 * Selector compacto para filtros mutuamente excluyentes dentro de una vista.
 *
 * Cada opción: `{ id, label, disabled?, count?, tone? }`. `count` muestra cuántos
 * resultados deja esa opción; con `tone: "attention"` y un conteo mayor que cero,
 * el contador lleva color de aviso y un ícono (el color nunca es la única señal).
 */
const SegmentedControl = ({ options, value, onChange, ariaLabel }) => (
  <div className="segmented-control" role="group" aria-label={ariaLabel}>
    {options.map(({ id, label, disabled = false, count, tone }) => {
      const attention = tone === "attention" && count > 0;
      return (
        <button
          key={id}
          type="button"
          aria-pressed={value === id}
          disabled={disabled}
          onClick={() => onChange(id)}
        >
          {label}
          {count != null && (
            <>
              {" "}
              <span className={`segmented-count${attention ? " segmented-count-attention" : ""}`}>
                {attention && <Icon.AlertTriangle s={11} />}
                {count}
              </span>
            </>
          )}
        </button>
      );
    })}
  </div>
);

export default SegmentedControl;
