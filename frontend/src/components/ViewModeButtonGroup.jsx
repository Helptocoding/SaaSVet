import { Icon } from "./icons";
import "./ViewModeButtonGroup.css";

const DEFAULT_VIEWS = [
    { id: "month", label: "Mes", icon: Icon.CalendarDays },
    { id: "week", label: "Semana", icon: Icon.Grid },
    { id: "day", label: "Día", icon: Icon.Clock },
    { id: "list", label: "Lista", icon: Icon.Rows },
];

/**
 * Selector compacto y reutilizable para alternar entre vistas.
 * Puede recibir otras opciones para reutilizarlo fuera del calendario.
 */
export default function ViewModeButtonGroup({
    value,
    onChange,
    options = DEFAULT_VIEWS,
    className = "",
    dataTour,
    ariaLabel = "Cambiar vista",
}) {
    return (
        <div className={`view-mode-button-group ${className}`.trim()} data-tour={dataTour} role="group" aria-label={ariaLabel}>
            {options.map(({ id, label, icon: ViewIcon }) => {
                const active = value === id;
                return (
                    <button
                        key={id}
                        type="button"
                        className={`view-mode-button${active ? " is-active" : ""}`}
                        aria-pressed={active}
                        onClick={() => onChange(id)}
                    >
                        {ViewIcon && <ViewIcon s={14} />}
                        <span>{label}</span>
                    </button>
                );
            })}
        </div>
    );
}
