import { useLoginForm } from "../hooks/useLoginForm";
import { Field } from "./Field";
import { PasswordField } from "./PasswordField";
import { Checkbox } from "./Checkbox";
import { MailIcon } from "./icons/MailIcon";
import { LockIcon } from "./icons/LockIcon";
import { ShieldIcon } from "./icons/ShieldIcon";

export function LoginForm() {
  const {
    username,
    setUsername,
    password,
    setPassword,
    remember,
    setRemember,
    loading,
    handleSubmit
  } = useLoginForm();

  const disabled = loading || !username || !password;

  return (
    <form className="login-form" onSubmit={handleSubmit} noValidate>
      <div className="field-group">
        <Field
          id="username"
          label="Correo o usuario"
          value={username}
          onChange={setUsername}
          placeholder="correo@clinica.com o usuario"
          autoComplete="username"
          required
          leadingIcon={<MailIcon size={18} />}
          disabled={loading}
        />

        <PasswordField
          id="password"
          value={password}
          onChange={setPassword}
          required
          disabled={loading}
          leadingIcon={<LockIcon size={18} />}
          labelAside={
            <a
              href="#"
              className="forgot-password"
              onClick={(e) => e.preventDefault()}
              data-testid="forgot-password-link"
            >
              ¿Olvidaste tu contraseña?
            </a>
          }
        />
      </div>

      <div className="form-meta">
        <Checkbox checked={remember} onChange={setRemember} data-testid="remember-checkbox">
          Recordarme
        </Checkbox>
      </div>

      <button
        type="submit"
        className="btn-primary"
        disabled={disabled}
        data-testid="login-submit-button"
      >
        {loading ? "Iniciando sesión…" : "Iniciar sesión"}
      </button>

      <div className="login-secure-note" data-testid="login-secure-note">
        <ShieldIcon size={14} />
        <span>Acceso seguro para clínicas registradas</span>
      </div>
    </form>
  );
}
