/** Selector compacto para filtros mutuamente excluyentes dentro de una vista. */
const SegmentedControl = ({ options, value, onChange, ariaLabel }) => (
  <div className="segmented-control" role="group" aria-label={ariaLabel}>
    {options.map(({ id, label, disabled = false }) => (
      <button
        key={id}
        type="button"
        aria-pressed={value === id}
        disabled={disabled}
        onClick={() => onChange(id)}
      >
        {label}
      </button>
    ))}
  </div>
);

export default SegmentedControl;
