import { CheckCircleIcon } from "./icons/CheckCircleIcon";

export function HeroPanel() {
  return (
    <div className="hero-panel">
      <h1 className="headline">
        Gestiona tu clínica<br />
        veterinaria desde un<br />
        solo lugar.
      </h1>
      <p className="hero-sub">
        Pacientes, citas, historiales e inventario en una sola plataforma.
      </p>

      <div className="hero-stats-wrap">
        <div className="hero-stats" data-testid="hero-stats">
          <div className="hero-stats-label">RESUMEN DE HOY</div>

          <div className="hero-stats-grid">
            <div className="hero-stat">
              <div className="hero-stat-value">12</div>
              <div className="hero-stat-label">Citas</div>
            </div>
            <div className="hero-stat">
              <div className="hero-stat-value">48</div>
              <div className="hero-stat-label">Pacientes</div>
            </div>
            <div className="hero-stat">
              <div className="hero-stat-value">$8,450</div>
              <div className="hero-stat-label">Ingresos</div>
            </div>
            <div className="hero-stat">
              <div className="hero-stat-value">3</div>
              <div className="hero-stat-label">Stock bajo</div>
            </div>
          </div>
        </div>

        <div className="hero-toast" role="status" aria-live="polite">
          <CheckCircleIcon size={20} />
          <div className="hero-toast-body">
            <div className="hero-toast-title">Luna</div>
            <div className="hero-toast-sub">Consulta completada</div>
          </div>
        </div>
      </div>
    </div>
  );
}
