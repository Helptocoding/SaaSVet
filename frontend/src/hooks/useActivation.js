import { useState, useEffect, useCallback, useRef } from "react";
import { getActivation } from "../api/dashboardSummary";

/**
 * Estado de activación de la clínica (primer uso).
 *
 * Deriva del endpoint read-only `v1/dashboard/activation/` (existencia real, sin
 * flags). No hace polling: la activación cambia poco. Refetcha en mount y al
 * recibir `dashboard:refresh` (mismo evento que dispara AppointmentQuickModal y
 * demás mutaciones), de modo que al volver al dashboard tras crear un paciente /
 * cita / consulta, el checklist se actualiza.
 *
 * Es no-crítico: si la llamada falla, `activation` queda null y el checklist
 * simplemente no se muestra (nunca rompe el dashboard).
 */
export function useActivation() {
  const [activation, setActivation] = useState(null);
  const [loading, setLoading] = useState(true);
  const mountedRef = useRef(true);

  const fetch = useCallback(async () => {
    try {
      const result = await getActivation();
      if (mountedRef.current) setActivation(result);
    } catch {
      // no-crítico: el checklist no se muestra si falla.
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    fetch();

    const onRefresh = () => fetch();
    window.addEventListener("dashboard:refresh", onRefresh);

    return () => {
      mountedRef.current = false;
      window.removeEventListener("dashboard:refresh", onRefresh);
    };
  }, [fetch]);

  return { activation, loading };
}
