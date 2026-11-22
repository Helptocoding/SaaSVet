import { useState } from "react";
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

  // No hay recuperación por correo: la contraseña la restablece un ADMIN de la
  // clínica desde Equipo (ADR p21). El enlace explica eso en vez de no hacer
  // nada (plan UX D4).
  const [showRecovery, setShowRecovery] = useState(false);

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
            <button
              type="button"
              className="forgot-password"
              onClick={() => setShowRecovery((v) => !v)}
              aria-expanded={showRecovery}
              aria-controls="password-recovery-help"
              data-testid="forgot-password-link"
            >
              ¿Olvidaste tu contraseña?
            </button>
          }
        />
        {showRecovery && (
          <p id="password-recovery-help" className="login-recovery-hint" role="status">
            Pide al administrador de tu clínica que la restablezca desde <strong>Equipo</strong>.
            Te dará una contraseña temporal que cambiarás al entrar.
          </p>
        )}
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
