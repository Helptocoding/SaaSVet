import { useCallback, useRef, useState } from "react";
import { DEMO_PRODUCT, DEMO_SALES, DEMO_STOCK, TOUR_STEPS } from "./productTourSteps";

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const typeInto = async (setter, field, text, signal, speed = 90) => {
    for (let i = 1; i <= text.length; i++) {
        if (signal.cancelled) return false;
        await sleep(speed);
        setter(prev => ({ ...prev, [field]: text.slice(0, i) }));
    }
    return true;
};

const scrollToTarget = (selector, delay = 80) => {
    if (!selector) return;
    setTimeout(() => {
        document.querySelector(selector)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, delay);
};

export const useProductTour = () => {
    const [demoActive, setDemoActive] = useState(false);
    const [stepIdx, setStepIdx] = useState(0);
    const [filling, setFilling] = useState(false);
    const cancelRef = useRef({ cancelled: false });
    const resolveRef = useRef(null);

    const goToStep = useCallback((idx) => {
        setStepIdx(idx);
        scrollToTarget(TOUR_STEPS[idx]?.target, 100);
    }, []);

    const next = useCallback(() => {
        if (resolveRef.current) {
            resolveRef.current();
            resolveRef.current = null;
        }
    }, []);

    const skip = useCallback(() => {
        cancelRef.current.cancelled = true;
        if (resolveRef.current) {
            resolveRef.current();
            resolveRef.current = null;
        }
        setDemoActive(false);
        setFilling(false);
        setStepIdx(0);
    }, []);

    const finish = useCallback(() => {
        setDemoActive(false);
        setFilling(false);
        setStepIdx(0);
    }, []);

    const waitForNext = (signal) =>
        new Promise(resolve => {
            if (signal.cancelled) { resolve(); return; }
            resolveRef.current = resolve;
        });

    const start = useCallback(async (callbacks) => {
        const signal = { cancelled: false };
        cancelRef.current = signal;

        const {
            openWizardCreate,
            setWizardProduct,
            setWizardMode,
            setDivides,
            setCountQty,
            setCountUnit,
            setDividesCount,
            setDividesUnit,
            updateSalesPres,
            setTutorialMode,
        } = callbacks;

        setTutorialMode(true);
        openWizardCreate();
        await sleep(420);
        if (signal.cancelled) return;

        // ── Step 0: mode selector ──────────────────────────────
        goToStep(0);
        setDemoActive(true);
        setFilling(false);

        await waitForNext(signal);
        if (signal.cancelled) return;

        // Select "multi" mode (useEffect in inventory.jsx auto-inits 2nd pres)
        setFilling(true);
        await sleep(350);
        setWizardMode("multi");
        setDivides(true);
        await sleep(500);
        setFilling(false);

        // ── Step 1: nombre del producto ────────────────────────
        goToStep(1);
        setFilling(true);
        if (!await typeInto(setWizardProduct, "name", DEMO_PRODUCT.name, signal, 90)) return;
        await sleep(220);
        setWizardProduct(prev => ({ ...prev, category: DEMO_PRODUCT.category }));
        setFilling(false);

        await waitForNext(signal);
        if (signal.cancelled) return;

        // ── Step 2: stock — cantidad + unidad + división ───────
        goToStep(2);
        setFilling(true);
        await sleep(350);
        setCountQty(DEMO_STOCK.qty);
        await sleep(380);
        setCountUnit(DEMO_STOCK.countUnit);   // auto-syncs salesPres[1].name → "Caja"
        await sleep(380);
        setDividesCount(DEMO_STOCK.dividesCount);  // auto-syncs salesPres[1].cf → 100
        await sleep(350);
        setDividesUnit(DEMO_STOCK.dividesUnit);
        await sleep(300);
        setFilling(false);

        await waitForNext(signal);
        if (signal.cancelled) return;

        // ── Step 3: precio primera forma (pieza individual) ───
        goToStep(3);
        setFilling(true);
        await sleep(350);
        updateSalesPres(0, "sale_price", DEMO_SALES[0].sale_price);
        updateSalesPres(0, "purchase_price", DEMO_SALES[0].purchase_price);
        await sleep(280);
        setFilling(false);

        await waitForNext(signal);
        if (signal.cancelled) return;

        // ── Step 4: precio segunda forma (caja, nombre+cf ya auto-llenados) ──
        goToStep(4);
        setFilling(true);
        await sleep(350);
        updateSalesPres(1, "sale_price", DEMO_SALES[1].sale_price);
        updateSalesPres(1, "purchase_price", DEMO_SALES[1].purchase_price);
        await sleep(280);
        setFilling(false);

        await waitForNext(signal);
        if (signal.cancelled) return;

        // ── Step 5: resumen final ──────────────────────────────
        goToStep(5);
    }, [goToStep]);

    return {
        demoActive,
        stepIdx,
        filling,
        currentStep: TOUR_STEPS[stepIdx],
        isLastStep: stepIdx === TOUR_STEPS.length - 1,
        start,
        next,
        skip,
        finish,
    };
};
