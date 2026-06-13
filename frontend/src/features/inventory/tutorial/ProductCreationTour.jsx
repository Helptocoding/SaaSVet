import { useEffect, useRef, useState } from "react";
import { TOUR_STEPS } from "./productTourSteps";
import s from "./ProductCreationTour.module.css";

const PAD = 12;
const POPOVER_W = 292;
const POPOVER_H_EST = 260;
const GAP = 20;

const getPopoverPos = (rect) => {
    const vH = window.innerHeight;
    const vW = window.innerWidth;

    // Vertical anchor: align to spotlighted element, clamped to viewport
    const anchorTop = rect
        ? Math.min(Math.max(rect.top, 16), vH - POPOVER_H_EST - 16)
        : vH / 2 - POPOVER_H_EST / 2;

    // Find the open wizard modal to place popover outside it
    const modal = document.querySelector(".modal.modal-md");
    if (modal) {
        const mr = modal.getBoundingClientRect();
        // Prefer right side
        if (mr.right + GAP + POPOVER_W <= vW - 8) {
            return { top: anchorTop, left: mr.right + GAP };
        }
        // Fallback: left side
        if (mr.left - GAP - POPOVER_W >= 8) {
            return { top: anchorTop, left: mr.left - GAP - POPOVER_W };
        }
        // Last resort: below modal (narrow screens)
        const below = mr.bottom + GAP;
        const left = Math.max(8, Math.min(mr.left, vW - POPOVER_W - 8));
        return { top: below, left };
    }

    // No modal found: center of screen
    return { top: "50%", left: "50%", transform: "translate(-50%,-50%)" };
};

const ProductCreationTour = ({
    demoActive, stepIdx, currentStep, isLastStep, filling,
    onNext, onSkip, onFinish,
}) => {
    const [rect, setRect] = useState(null);
    const rafRef = useRef(null);
    const prevTargetRef = useRef(null);

    useEffect(() => {
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
        if (!demoActive || !currentStep?.target) {
            setRect(null);
            prevTargetRef.current = null;
            return;
        }
        if (currentStep.target === prevTargetRef.current) return;
        prevTargetRef.current = currentStep.target;

        let attempts = 0;
        const poll = () => {
            const el = document.querySelector(currentStep.target);
            if (el) {
                setRect(el.getBoundingClientRect());
            } else if (attempts < 40) {
                attempts++;
                rafRef.current = requestAnimationFrame(poll);
            }
        };
        poll();
        return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
    }, [demoActive, currentStep?.target]);

    useEffect(() => {
        if (!demoActive || !currentStep?.target) return;
        const update = () => {
            const el = document.querySelector(currentStep.target);
            if (el) setRect(el.getBoundingClientRect());
        };
        window.addEventListener("scroll", update, true);
        window.addEventListener("resize", update);
        return () => {
            window.removeEventListener("scroll", update, true);
            window.removeEventListener("resize", update);
        };
    }, [demoActive, currentStep?.target]);

    if (!demoActive || !currentStep) return null;

    const popPos = getPopoverPos(rect);

    return (
        <>
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

            <div className={s.popover} style={popPos}>
                <div className={s.dots}>
                    {TOUR_STEPS.map((_, i) => (
                        <div
                            key={i}
                            className={`${s.dot} ${i === stepIdx ? s.dotActive : i < stepIdx ? s.dotDone : ""}`}
                        />
                    ))}
                </div>

                <div className={s.stepBadge}>
                    Paso {stepIdx + 1} de {TOUR_STEPS.length}
                </div>

                <div className={s.popTitle}>{currentStep.title}</div>
                <div className={s.popBody}>{currentStep.body}</div>

                <div className={s.popFoot}>
                    <button type="button" className={s.skipBtn} onClick={onSkip}>
                        Saltar demo
                    </button>

                    {isLastStep ? (
                        <div className={s.finishBtns}>
                            <button type="button" className={s.useBtn} onClick={onFinish}>
                                Usar estos datos
                            </button>
                            <button type="button" className={s.cleanBtn} onClick={onSkip}>
                                Limpiar
                            </button>
                        </div>
                    ) : (
                        <button
                            type="button"
                            className={`${s.nextBtn} ${filling ? s.nextBtnFilling : ""}`}
                            onClick={onNext}
                            disabled={filling}
                        >
                            {filling ? (
                                <span className={s.typingDots}>
                                    <span /><span /><span />
                                </span>
                            ) : (
                                "Siguiente →"
                            )}
                        </button>
                    )}
                </div>
            </div>
        </>
    );
};

export default ProductCreationTour;
