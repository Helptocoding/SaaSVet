export function Field({
  label,
  id,
  type = "text",
  value,
  onChange,
  placeholder,
  autoComplete,
  children,
  required = false,
  leadingIcon = null,
  labelAside = null,
  invalid = false,
  disabled = false,
}) {
  return (
    <div className="field" data-testid={`field-${id}`}>
      <div className="field-label-row">
        <label className="field-label" htmlFor={id}>{label}</label>
        {labelAside}
      </div>
      <div className={`field-wrap ${invalid ? "is-invalid" : ""}`}>
        {leadingIcon && <span className="field-leading-icon" aria-hidden="true">{leadingIcon}</span>}
        <input
          id={id}
          type={type}
          className={`field-input ${leadingIcon ? "has-leading" : ""} ${children ? "has-toggle" : ""}`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete={autoComplete}
          required={required}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          data-testid={`input-${id}`}
        />
        {children}
      </div>
    </div>
  );
}
