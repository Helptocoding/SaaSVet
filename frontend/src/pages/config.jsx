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

  return <SettingsLayout user={user} token={token} />;
};

export default Config;
