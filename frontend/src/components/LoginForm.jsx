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
    handleSubmit,
    mfaRequired,
    mfaCode,
    setMfaCode,
    cancelMfa,
  } = useLoginForm();

  // No hay recuperación por correo: la contraseña la restablece un ADMIN de la
  // clínica desde Equipo (ADR p21). El enlace explica eso en vez de no hacer
  // nada (plan UX D4).
  const [showRecovery, setShowRecovery] = useState(false);

  const disabled = loading || !username || !password;

  // ADR p68: la contraseña fue correcta y la cuenta tiene verificación en dos
  // pasos; falta el código de la app (o uno de respaldo).
  if (mfaRequired) {
    return (
      <form className="login-form" onSubmit={handleSubmit} noValidate>
        <div className="field-group">
          <p className="login-recovery-hint" role="status">
            Escribe el código de 6 dígitos de tu app autenticadora, o uno de tus códigos de respaldo.
          </p>
          <Field
            id="mfa-code"
            label="Código de verificación"
            value={mfaCode}
            onChange={setMfaCode}
            placeholder="123456"
            autoComplete="one-time-code"
            required
            leadingIcon={<ShieldIcon size={18} />}
            disabled={loading}
          />
        </div>
        <button
          type="submit"
          className="btn-primary"
          disabled={loading || !mfaCode.trim()}
          data-testid="mfa-submit-button"
        >
          {loading ? "Verificando…" : "Verificar"}
        </button>
        <button type="button" className="forgot-password" onClick={cancelMfa} disabled={loading}>
          Volver
        </button>
      </form>
    );
  }

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
