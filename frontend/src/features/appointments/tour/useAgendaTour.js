import { useCallback, useMemo, useRef, useState } from "react";
import { AGENDA_TOUR_KEY, buildAgendaSteps } from "./agendaSteps";

/**
 * useAgendaTour — orquestador del recorrido de Agenda (espeja `useProductTour`).
 *
 * Mantiene `active`/`stepIdx` y, en cada paso, ejecuta el `onEnter(actions)` que maneja
 * la página real (abrir formulario, inyectar cita demo, abrir el modal de detalle…).
 * `skip`/`finish` limpian el estado demo y marcan el gate `localStorage`.
 *
 * `actions` = { setWeekOffset, setSelectedSlot, setViewAppt, setTourDemoAppt }.
 * Debe ser estable (memoizado por el caller) para no reconstruir los pasos/demo.
 */
export function useAgendaTour(actions) {
  const [active, setActive] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);
  const steps = useMemo(() => buildAgendaSteps(actions), [actions]);
  const actionsRef = useRef(actions);
  actionsRef.current = actions;

  const runEnter = useCallback((idx) => {
    steps[idx]?.onEnter?.(actionsRef.current);
  }, [steps]);

  const start = useCallback(() => {
    setStepIdx(0);
    setActive(true);
    runEnter(0);
  }, [runEnter]);

  const goTo = useCallback((idx) => {
    if (idx < 0 || idx >= steps.length) return;
    setStepIdx(idx);
    runEnter(idx);
  }, [steps.length, runEnter]);

  const next = useCallback(() => goTo(stepIdx + 1), [goTo, stepIdx]);
  const prev = useCallback(() => goTo(stepIdx - 1), [goTo, stepIdx]);

  const end = useCallback(() => {
    setActive(false);
    setStepIdx(0);
    const a = actionsRef.current;
    a.setViewAppt(null);
    a.setTourDemoAppt(null);
    a.setSelectedSlot(null);
    a.closeCreateModal?.();
    try { localStorage.setItem(AGENDA_TOUR_KEY, "true"); } catch { /* ignore */ }
  }, []);

  return { active, stepIdx, steps, start, next, prev, skip: end, finish: end };
}
