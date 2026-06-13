import { useState, useEffect, useCallback } from "react";
import { useAuth } from "../auth/authContext";
import { getAppointments } from "../api/appointments";

/**
 * Citas de un día (org-local) para la Agenda del dashboard.
 *
 * Reusa el endpoint existente GET appointments/?date=YYYY-MM-DD (sin backend
 * nuevo). Refetch al cambiar la fecha y al evento global `dashboard:refresh`
 * (acciones del AppointmentQuickModal lo disparan → agenda se actualiza sola).
 *
 * @param {string} date  fecha en formato 'YYYY-MM-DD' (día local).
 */
export function useDayAppointments(date) {
  const { token } = useAuth();
  const [appts, setAppts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    if (!date) return;
    try {
      const data = await getAppointments(token, { date });
      setAppts(Array.isArray(data) ? data : data?.results || []);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [token, date]);

  useEffect(() => {
    // Fetch-on-mount/date-change. setState ocurre tras await (mismo patrón que
    // useDashboardSummary). El plugin React Compiler marca la llamada igual.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    const onRefresh = () => fetchData();
    window.addEventListener("dashboard:refresh", onRefresh);
    return () => window.removeEventListener("dashboard:refresh", onRefresh);
  }, [fetchData]);

  return { appts, loading, error, refetch: fetchData };
}
