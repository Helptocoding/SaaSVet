import { Brand } from "../components/Brand";
import { HeroPanel } from "../components/HeroPanel";
import { LoginForm } from "../components/LoginForm";
import { useAuth } from "../auth/authContext";
import "../styles/login.css";

export default function Login() {
  const { initializing } = useAuth();

  if (initializing) {
    return (
      <div className="login-loading" data-testid="login-loading">
        Cargando…
      </div>
    );
  }

  return (
    <div className="login-page" data-testid="login-page">
      <section className="login-left" aria-label="Bienvenida VetCare">
        <div className="login-left-inner">
          <Brand />
          <div className="left-body">
            <HeroPanel />
          </div>
          <div className="login-foot">
            <div className="login-foot-roles">
              <span>Administrador</span>
              <span className="login-foot-dot" aria-hidden="true">·</span>
              <span>Veterinario</span>
              <span className="login-foot-dot" aria-hidden="true">·</span>
              <span>Recepción</span>
            </div>
            <div className="login-foot-copy">© 2026 VetCare</div>
          </div>
        </div>
      </section>

      <section className="login-right" aria-label="Formulario de inicio de sesión">
        <div className="login-card">
          <h2 className="login-title" data-testid="login-title">Ingresa a tu clínica</h2>
          <p className="login-subtitle">
            Inicia sesión para administrar tu clínica.
          </p>

          <LoginForm />
        </div>
      </section>
    </div>
  );
}
