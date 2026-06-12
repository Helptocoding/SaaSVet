export function Checkbox({ checked, onChange, children, ...rest }) {
  return (
    <label className="checkbox">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        {...rest}
      />
      <span className="checkbox-box" aria-hidden="true" />
      <span>{children}</span>
    </label>
  );
}
