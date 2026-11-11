import { useEffect, useRef, useState } from "react";
import s from "./SpotlightTour.module.css";

/**
 * SpotlightTour — motor genérico de recorridos guiados (coach-marks) sobre la UI REAL.
 *
 * Atenúa la pantalla, recorta un "hueco" sobre el elemento real (`step.target`, un
 * selector CSS) y muestra un popover con la narración. Un overlay a pantalla completa
 * **bloquea toda interacción** con la UI real → el usuario navega SOLO por el popover
 * (imposible disparar acciones reales por accidente). Si `target` es `null`, el popover
 * se centra y la pantalla se atenúa (bienvenida/cierre).
 *
 * Presentacional y reutilizable — NO conoce ningún módulo. El caller pasa `steps` y los
 * callbacks de navegación; los side-effects de manejar la página viven en el caller
 * (p.ej. `useAgendaTour`). Precedente: `features/inventory/tutorial/ProductCreationTour`.
 *
 * Props:
 *   steps    — [{ target?: string|null, tag?, title, body }]
 *   stepIdx  — índice actual (0-based)
 *   onNext / onPrev / onSkip / onFinish — navegación.
 */
const PAD = 10;
const POP_W = 300;
const POP_H_EST = 220;
const GAP = 16;

function computePopoverPos(rect) {
  const vW = window.innerWidth;
  const vH = window.innerHeight;
  if (!rect) return { top: "50%", left: "50%", transform: "translate(-50%,-50%)" };
  const top = Math.min(Math.max(rect.top, 16), Math.max(16, vH - POP_H_EST - 16));
  if (rect.right + GAP + POP_W <= vW - 8) return { top, left: rect.right + GAP };
  if (rect.left - GAP - POP_W >= 8) return { top, left: rect.left - GAP - POP_W };
  const left = Math.max(8, Math.min(rect.left, vW - POP_W - 8));
  return { top: Math.min(rect.bottom + GAP, Math.max(16, vH - POP_H_EST - 16)), left };
}

const SpotlightTour = ({ steps, stepIdx, onNext, onPrev, onSkip, onFinish }) => {
  const [rect, setRect] = useState(null);
  const rafRef = useRef(null);
  const step = steps?.[stepIdx];
  const target = step?.target || null;

  // Localiza el elemento real (con polling: puede montarse tras un side-effect del paso).
  useEffect(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sin objetivo en este paso se limpia la posición medida del DOM
    if (!target) { setRect(null); return undefined; }
    let attempts = 0;
    const poll = () => {
      const el = document.querySelector(target);
      if (el) {
        el.scrollIntoView?.({ block: "center", behavior: "smooth" });
        setRect(el.getBoundingClientRect());
      } else if (attempts < 60) {
        attempts += 1;
        rafRef.current = requestAnimationFrame(poll);
      } else {
        setRect(null);
      }
    };
    poll();
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [target, stepIdx]);

  // Reposiciona el hueco al hacer scroll / resize.
  useEffect(() => {
    if (!target) return undefined;
    const update = () => {
      const el = document.querySelector(target);
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [target]);

  if (!step) return null;

  const isFirst = stepIdx === 0;
  const isLast = stepIdx === steps.length - 1;
  const pos = computePopoverPos(rect);

  return (
    <>
      {/* Capa que traga clics — bloquea la UI real durante el recorrido. */}
      <div className={`${s.blocker}${rect ? "" : ` ${s.blockerDim}`}`} aria-hidden="true" />

      {rect && (
        <div
          className={s.spotlight}
          style={{
            left: rect.left - PAD,
            top: rect.top - PAD,
            width: rect.width + PAD * 2,
            height: rect.height + PAD * 2,
          }}
        />
      )}

      <div className={s.popover} style={pos} role="dialog" aria-label="Recorrido">
        <div className={s.dots}>
          {steps.map((_, i) => (
            <div
              key={i}
              className={`${s.dot} ${i === stepIdx ? s.dotActive : i < stepIdx ? s.dotDone : ""}`}
            />
          ))}
        </div>

        {step.tag && <div className={s.tag}>{step.tag}</div>}
        <div className={s.title}>{step.title}</div>
        <div className={s.body}>{step.body}</div>

        <div className={s.foot}>
          <button type="button" className={s.skipBtn} onClick={onSkip}>Saltar</button>
          <div className={s.navBtns}>
            <button type="button" className={s.prevBtn} onClick={onPrev} disabled={isFirst}>
              ← Anterior
            </button>
            <button type="button" className={s.nextBtn} onClick={isLast ? onFinish : onNext}>
              {isLast ? "Entendido ✓" : "Siguiente →"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default SpotlightTour;
