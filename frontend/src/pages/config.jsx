import { useAuth } from "../auth/authContext";
import SettingsLayout from "./config/index";

const Config = () => {
  const { user, token, initializing } = useAuth();

  if (initializing) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "50vh" }}>
        <p style={{ color: "var(--c-text-3)", fontSize: "13px" }}>Cargando...</p>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Configuración</h1>
          <p className="page-subtitle">Información, horarios y reglas operativas de tu clínica</p>
        </div>
      </div>

      <SettingsLayout user={user} token={token} />
    </div>
  );
};

export default Config;
