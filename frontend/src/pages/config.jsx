import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/authContext";
import { CONFIG_PERMS } from "../features/config/permissions";
import SettingsLayout from "./config/index";

/**
 * Guarda de `/config` (ADR p70 D8): entra solo quien gestiona algo de la
 * configuración; el resto vuelve al inicio, también si llega por URL. La cuenta
 * personal vive en `/account`, para todos.
 */
const Config = () => {
  const { user, token, initializing, canAny } = useAuth();

  if (initializing) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "50vh" }}>
        <p style={{ color: "var(--c-text-3)", fontSize: "13px" }}>Cargando...</p>
      </div>
    );
  }

  if (!canAny?.(CONFIG_PERMS)) return <Navigate to="/" replace />;

  return <SettingsLayout user={user} token={token} />;
};

export default Config;
