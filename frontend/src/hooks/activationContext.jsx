import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
} from "react";
import { getActivation } from "../api/dashboardSummary";
import { useAuth } from "../auth/authContext";

/**
 * Fuente de verdad de la activación de la clínica (primer uso).
 *
 * Deriva del endpoint read-only `v1/dashboard/activation/` (existencia real, sin
 * flags): `{has_patients, has_services, has_appointments, has_consultations, completed}`.
 *
 * Provider DELIBERADAMENTE "tonto": expone SOLO `{ activation, loading, refetch }`.
 * NO conoce nada del onboarding (qué paso se completó, celebraciones, momento de
 * cierre…) — esa lógica vive en `FirstRunAssistant`. Si el onboarding se rediseña o
 * se elimina, este provider no queda acoplado a una UI que ya no existe.
 *
 * PRINCIPIO (no romper): el onboarding NUNCA introduce estado persistente propio
 * (`has_seen_step_2`, `completed_onboarding`, `onboardingDismissed`…). Siempre se
 * deriva del estado operativo real. No duplicar la fuente de verdad.
 *
 * Vive en `Root` (dentro de `AuthProvider`) → persiste al navegar entre rutas.
 * No hace polling: la activación cambia poco. Refetcha en mount, al recibir
 * `dashboard:refresh` y bajo demanda (`refetch`, p.ej. al volver al dashboard).
 */
const ActivationContext = createContext({
  activation: null,
  loading: true,
  refetch: () => {},
});

export function ActivationProvider({ children }) {
  const { user } = useAuth();
  const [activation, setActivation] = useState(null);
  const [loading, setLoading] = useState(true);
  const mountedRef = useRef(true);

  const refetch = useCallback(async () => {
    // Solo con sesión: sin `user` el endpoint tenant-scoped responde 401.
    if (!user) return;
    try {
      const result = await getActivation();
      if (mountedRef.current) setActivation(result);
    } catch {
      // No-crítico: si falla, el onboarding simplemente no se muestra.
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    mountedRef.current = true;
    refetch();

    const onRefresh = () => refetch();
    window.addEventListener("dashboard:refresh", onRefresh);

    return () => {
      mountedRef.current = false;
      window.removeEventListener("dashboard:refresh", onRefresh);
    };
  }, [refetch]);

  return (
    <ActivationContext.Provider value={{ activation, loading, refetch }}>
      {children}
    </ActivationContext.Provider>
  );
}

export function useActivationContext() {
  return useContext(ActivationContext);
}
