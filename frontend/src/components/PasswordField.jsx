import { useState } from "react";
import { Field } from "./Field";
import { EyeIcon } from "./icons/EyeIcon";
import { EyeOffIcon } from "./icons/EyeOffIcon";

export function PasswordField({
  value,
  onChange,
  label = "Contraseña",
  id = "password",
  autoComplete = "current-password",
  required = false,
  disabled = false,
  leadingIcon = null,
  labelAside = null,
}) {
  const [show, setShow] = useState(false);
  return (
    <Field
      id={id}
      label={label}
      type={show ? "text" : "password"}
      value={value}
      onChange={onChange}
      placeholder="••••••••"
      autoComplete={autoComplete}
      required={required}
      disabled={disabled}
      leadingIcon={leadingIcon}
      labelAside={labelAside}
    >
      <button
        type="button"
        className="field-toggle"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "Ocultar contraseña" : "Mostrar contraseña"}
        tabIndex={-1}
        data-testid="password-toggle-button"
      >
        {show ? <EyeIcon /> : <EyeOffIcon />}
      </button>
    </Field>
  );
}
