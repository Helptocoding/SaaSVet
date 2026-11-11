import { createContext, useContext } from "react";

// Contexto y hook de autenticación. Viven aparte de AuthProvider.jsx para que ese
// archivo exporte solo componentes (react-refresh/only-export-components).
export const AuthContext = createContext();

export const useAuth = () => useContext(AuthContext);
