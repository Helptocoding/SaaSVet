import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, animate, motion } from "framer-motion";
import s from "./MultiPresentationAnimation.module.css";
import {
    BoxIconSvg, FlowArrowSvg, GuanteCajaSvg,
    GuanteIndividualSvg, LinkIconSvg, StockBoxSvg,
} from "./AnimationSvgs";

const STORAGE_KEY = "multi_presentation_animation_seen";

// SVG CSS variable overrides → design system tokens
const BOX_VARS = {
    "--box-primary": "var(--c-primary)",
    "--box-top": "var(--c-primary-light)",
    "--box-side": "var(--c-primary-light)",
    "--box-face": "var(--c-surface)",
    "--box-line": "var(--c-border)",
    "--box-shadow": "var(--c-text-3)",
    "--box-guante": "var(--c-primary)",
};
const GUANTE_VARS = {
    "--guante-color": "var(--c-primary)",
    "--guante-puño": "var(--c-primary-light)",
};
const STOCK_VARS = {
    "--stock-header": "var(--c-primary)",
    "--stock-body": "var(--c-surface)",
    "--stock-line": "var(--c-border)",
    "--stock-accent": "var(--c-primary)",
    "--stock-shadow": "var(--c-text-3)",
};

const DEFAULT_CONFIG = {
    product: { name: "Guantes de látex" },
    container: { label: "Caja completa", count: 50, unit: "piezas" },
    individual: { label: "Guante individual", unit: "pieza" },
    initialStock: 150,
};

// Slide variants for scene transitions
const slideVariants = {
    enter: (dir) => ({ x: dir * 42, opacity: 0 }),
    center: { x: 0, opacity: 1 },
    exit: (dir) => ({ x: dir * -42, opacity: 0 }),
};
const transition = { duration: 0.32, ease: [0.25, 0.46, 0.45, 0.94] };

// ── Scene 1 — Intro ────────────────────────────────────────
function SceneIntro({ config }) {
    const { product } = config;
    return (
        <div className={s.introWrap}>
            <motion.div
                initial={{ opacity: 0, scale: 0.88, y: 12 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ duration: 0.55, ease: "easeOut" }}
                style={{ filter: "drop-shadow(0 8px 24px rgba(26,68,52,.18))" }}
            >
                <GuanteCajaSvg width={160} style={BOX_VARS} />
            </motion.div>
            <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.3 }}
            >
                <div className={s.introProduct}>{product.name}</div>
                <div className={s.introTitle}>Varias formas de venta</div>
                <div className={s.introSub}>
                    Un mismo producto puede venderse de diferentes formas,<br />
                    pero todas descuentan del mismo inventario.
                </div>
            </motion.div>
        </div>
    );
}

// ── Scene 2 — Two forms ────────────────────────────────────
function SceneForms({ config }) {
    const { container, individual } = config;
    return (
        <div className={s.sceneWrap}>
            <div className={s.formsGrid}>
                {/* Left card — container */}
                <motion.div
                    className={s.formCard}
                    initial={{ opacity: 0, x: -36 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ ...transition, delay: 0.05 }}
                >
                    <GuanteCajaSvg width={90} style={BOX_VARS} />
                    <div className={s.formCardLabel}>{container.label}</div>
                    <div className={s.formCardSub}>{container.count} {container.unit}</div>
                </motion.div>

                {/* Center link */}
                <motion.div
                    className={s.linkCol}
                    initial={{ opacity: 0, scale: 0.7 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ ...transition, delay: 0.28 }}
                >
                    <LinkIconSvg size={36} style={{ color: "var(--c-primary)" }} />
                    <span className={s.linkLabel}>mismo producto</span>
                </motion.div>

                {/* Right card — individual */}
                <motion.div
                    className={s.formCard}
                    initial={{ opacity: 0, x: 36 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ ...transition, delay: 0.05 }}
                >
                    <GuanteIndividualSvg width={70} style={GUANTE_VARS} />
                    <div className={s.formCardLabel}>{individual.label}</div>
                    <div className={s.formCardSub}>1 {individual.unit}</div>
                </motion.div>
            </div>

            <motion.div
                className={s.formsSub}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...transition, delay: 0.45 }}
            >
                Ambas formas venden el mismo producto —{" "}
                <strong>comparten el mismo inventario</strong>.
            </motion.div>
        </div>
    );
}

// ── Scene 3 — Shared stock ─────────────────────────────────
function useAnimatedCounter(target, active) {
    const [val, setVal] = useState(0);
    const stopRef = useRef(null);

    useEffect(() => {
        if (!active) return;
        if (stopRef.current) stopRef.current();
        const { stop } = animate(0, target, {
            duration: 1.4,
            ease: "easeOut",
            onUpdate: (v) => setVal(Math.round(v)),
        });
        stopRef.current = stop;
        return stop;
    }, [target, active]);

    return val;
}

function SceneStock({ config }) {
    const { container, individual, initialStock } = config;
    const [ready, setReady] = useState(false);

    useEffect(() => {
        const t = setTimeout(() => setReady(true), 400);
        return () => clearTimeout(t);
    }, []);

    const count = useAnimatedCounter(initialStock, ready);

    return (
        <div className={s.sceneWrap}>
            <div className={s.stockLayout}>
                {/* Sources */}
                <div className={s.stockSources}>
                    {[
                        { svg: <GuanteCajaSvg width={72} style={BOX_VARS} />, label: container.label },
                        { svg: <GuanteIndividualSvg width={54} style={GUANTE_VARS} />, label: individual.label },
                    ].map(({ svg, label }, i) => (
                        <motion.div
                            key={label}
                            className={s.stockSourceRow}
                            initial={{ opacity: 0, x: -20 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ ...transition, delay: i * 0.15 }}
                        >
                            {svg}
                            <span className={s.stockSourceLabel}>{label}</span>
                        </motion.div>
                    ))}
                </div>

                {/* Arrows */}
                <div className={s.arrowCol}>
                    {[0, 1].map((i) => (
                        <motion.div
                            key={i}
                            initial={{ scaleX: 0, opacity: 0 }}
                            animate={{ scaleX: 1, opacity: 1 }}
                            transition={{ ...transition, delay: 0.3 + i * 0.1 }}
                            style={{ originX: 0 }}
                        >
                            <FlowArrowSvg width={64} style={{ color: "var(--c-primary)" }} />
                        </motion.div>
                    ))}
                </div>

                {/* Target */}
                <motion.div
                    className={s.stockTarget}
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ ...transition, delay: 0.5 }}
                >
                    <StockBoxSvg width={180} style={STOCK_VARS} />
                    <div className={s.stockCounterBox}>
                        <div className={s.stockCounterVal}>{count}</div>
                        <div className={s.stockCounterUnit}>{container.unit} disponibles</div>
                    </div>
                </motion.div>
            </div>

            <motion.div
                className={s.stockNote}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...transition, delay: 0.8 }}
            >
                No existen dos inventarios separados.{" "}
                <strong>Una sola fuente de stock para todas las formas de venta.</strong>
            </motion.div>
        </div>
    );
}

// ── Scene 4 — Sale simulation ──────────────────────────────
function SceneSale({ config }) {
    const { container, individual, initialStock } = config;
    const afterBox = initialStock - container.count;
    const afterGlove = afterBox - 1;

    const [phase, setPhase] = useState("idle"); // idle | box | glove | done
    const [displayStock, setDisplayStock] = useState(initialStock);
    const stopRef = useRef(null);

    const runCounter = useCallback((from, to) => {
        if (stopRef.current) stopRef.current();
        const { stop } = animate(from, to, {
            duration: 1.0,
            ease: "easeOut",
            onUpdate: (v) => setDisplayStock(Math.round(v)),
        });
        stopRef.current = stop;
    }, []);

    useEffect(() => {
        setPhase("idle");
        setDisplayStock(initialStock);
        const t1 = setTimeout(() => {
            setPhase("box");
            runCounter(initialStock, afterBox);
        }, 600);
        const t2 = setTimeout(() => {
            setPhase("glove");
            runCounter(afterBox, afterGlove);
        }, 3200);
        const t3 = setTimeout(() => setPhase("done"), 4800);
        return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); if (stopRef.current) stopRef.current(); };
    }, [initialStock, afterBox, afterGlove, runCounter]);

    const events = [
        {
            id: "box",
            icon: <GuanteCajaSvg width={24} style={BOX_VARS} />,
            name: `Venta: ${container.label}`,
            detail: `Descuenta ${container.count} ${container.unit}`,
            math: `−${container.count}`,
            active: phase === "box",
            done: phase === "glove" || phase === "done",
        },
        {
            id: "glove",
            icon: <GuanteIndividualSvg width={20} style={GUANTE_VARS} />,
            name: `Venta: ${individual.label}`,
            detail: `Descuenta 1 ${individual.unit}`,
            math: "−1",
            active: phase === "glove",
            done: phase === "done",
        },
    ];

    return (
        <div className={s.saleWrap}>
            <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...transition, delay: 0.1 }}
                className={s.saleCounter}
            >
                <div className={s.saleCounterVal}>{displayStock}</div>
                <div className={s.saleCounterLabel}>{container.unit} disponibles</div>
            </motion.div>

            <div style={{ display: "flex", flexDirection: "column", gap: "10px", width: "100%", maxWidth: 460 }}>
                {events.map((ev, i) => (
                    <motion.div
                        key={ev.id}
                        className={`${s.saleEvent} ${ev.active ? s.saleEventActive : ""}`}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ ...transition, delay: 0.15 + i * 0.08 }}
                    >
                        <div className={`${s.saleEventIcon} ${ev.active ? s.saleEventActiveIcon : ""}`}>
                            {ev.icon}
                        </div>
                        <div className={s.saleEventText}>
                            <div className={s.saleEventName}>{ev.name}</div>
                            <div className={s.saleEventDetail}>{ev.detail}</div>
                        </div>
                        <AnimatePresence>
                            {(ev.active || ev.done) && (
                                <motion.div
                                    className={s.saleMath}
                                    initial={{ opacity: 0, scale: 0.8 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    exit={{ opacity: 0 }}
                                >
                                    <div className={s.saleMathVal}>{ev.math}</div>
                                    <div style={{ fontSize: 11, color: "var(--c-text-3)", marginTop: 1 }}>
                                        {ev.done ? "aplicado" : "aplicando..."}
                                    </div>
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </motion.div>
                ))}
            </div>
        </div>
    );
}

// ── Scene 5 — Rule ─────────────────────────────────────────
function SceneRule({ config }) {
    const { container, individual } = config;

    const correct = [
        { text: container.label },
        { arrow: true },
        { text: individual.label },
    ];
    const wrong = [
        { text: "Alimento 2kg" },
        { text: "Alimento 10kg" },
    ];

    return (
        <div className={s.ruleWrap}>
            <motion.div
                className={s.ruleGrid}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...transition, delay: 0.1 }}
            >
                {/* Correct column */}
                <div className={`${s.ruleCol} ${s.ruleColOk}`}>
                    <div className={`${s.ruleColTitle} ${s.ruleColTitleOk}`}>✓ Correcto</div>
                    {correct.map((item, i) => (
                        item.arrow
                            ? <div key={i} className={s.ruleArrowRow}>↓</div>
                            : (
                                <motion.div
                                    key={i}
                                    className={s.ruleItem}
                                    initial={{ opacity: 0, x: -10 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    transition={{ ...transition, delay: 0.2 + i * 0.1 }}
                                >
                                    <span className={s.ruleBadgeOk}>{i === 0 ? "📦" : "🧤"}</span>
                                    <span>{item.text}</span>
                                </motion.div>
                            )
                    ))}
                    <div style={{ fontSize: 11.5, color: "var(--c-success-text)", marginTop: 8, lineHeight: 1.45 }}>
                        Mismo producto, diferente cantidad → ok
                    </div>
                </div>

                <div className={s.ruleDivider} />

                {/* Wrong column */}
                <div className={`${s.ruleCol} ${s.ruleColNo}`}>
                    <div className={`${s.ruleColTitle} ${s.ruleColTitleNo}`}>✕ Incorrecto</div>
                    {wrong.map((item, i) => (
                        <motion.div
                            key={i}
                            className={`${s.ruleItem} ${s.ruleItemNo}`}
                            initial={{ opacity: 0, x: 10 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ ...transition, delay: 0.25 + i * 0.1 }}
                        >
                            <span className={s.ruleBadgeNo}>✕</span>
                            <span>{item.text}</span>
                        </motion.div>
                    ))}
                    <div style={{ fontSize: 11.5, color: "var(--c-danger-text)", marginTop: 8, lineHeight: 1.45 }}>
                        Productos distintos → crear por separado
                    </div>
                </div>
            </motion.div>

            <motion.div
                className={s.ruleMessage}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...transition, delay: 0.5 }}
            >
                Si un producto <strong>no puede salir del otro</strong>, créalos como
                productos separados.
            </motion.div>
        </div>
    );
}

// ── Main component ─────────────────────────────────────────
const SCENE_LABELS = ["Concepto", "Formas", "Inventario", "Venta", "Regla"];

export default function MultiPresentationAnimation({
    config = DEFAULT_CONFIG,
    onDismiss,
}) {
    const [scene, setScene] = useState(0);
    const [direction, setDirection] = useState(1);
    const total = SCENE_LABELS.length;

    const goTo = useCallback((next) => {
        setDirection(next > scene ? 1 : -1);
        setScene(next);
    }, [scene]);

    const goNext = useCallback(() => {
        if (scene < total - 1) goTo(scene + 1);
        else handleDismiss();
    }, [scene, total, goTo]);

    const goPrev = useCallback(() => {
        if (scene > 0) goTo(scene - 1);
    }, [scene, goTo]);

    const handleRepeat = useCallback(() => goTo(0), [goTo]);

    const handleDismiss = useCallback(() => {
        localStorage.setItem(STORAGE_KEY, "true");
        onDismiss?.();
    }, [onDismiss]);

    const scenes = [
        <SceneIntro key="intro" config={config} />,
        <SceneForms key="forms" config={config} />,
        <SceneStock key="stock" config={config} />,
        <SceneSale key="sale" config={config} />,
        <SceneRule key="rule" config={config} />,
    ];

    return (
        <motion.div
            className={s.overlay}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={(e) => { if (e.target === e.currentTarget) handleDismiss(); }}
        >
            <motion.div
                className={s.panel}
                initial={{ scale: 0.94, opacity: 0, y: 12 }}
                animate={{ scale: 1, opacity: 1, y: 0 }}
                exit={{ scale: 0.94, opacity: 0, y: 8 }}
                transition={{ duration: 0.28, ease: [0.25, 0.46, 0.45, 0.94] }}
            >
                {/* Header */}
                <div className={s.header}>
                    <div className={s.headerLeft}>
                        <span className={s.headerTag}>Concepto</span>
                        <div className={s.progress}>
                            {SCENE_LABELS.map((_, i) => (
                                <div
                                    key={i}
                                    className={`${s.progressBar} ${i === scene ? s.progressBarActive : i < scene ? s.progressBarDone : ""}`}
                                />
                            ))}
                        </div>
                    </div>
                    <button className={s.closeBtn} onClick={handleDismiss} aria-label="Cerrar">
                        ×
                    </button>
                </div>

                {/* Body */}
                <div className={s.body}>
                    <AnimatePresence mode="wait" custom={direction}>
                        <motion.div
                            key={scene}
                            custom={direction}
                            variants={slideVariants}
                            initial="enter"
                            animate="center"
                            exit="exit"
                            transition={transition}
                            className={s.sceneWrap}
                        >
                            {scenes[scene]}
                        </motion.div>
                    </AnimatePresence>
                </div>

                {/* Footer */}
                <div className={s.footer}>
                    <button className={s.btnSkip} onClick={handleDismiss}>
                        Saltar
                    </button>

                    <div className={s.footerNav}>
                        {scene === total - 1 && (
                            <button className={s.btnRepeat} onClick={handleRepeat}>
                                ↺ Repetir
                            </button>
                        )}
                        <button
                            className={s.btnPrev}
                            onClick={goPrev}
                            disabled={scene === 0}
                        >
                            ← Anterior
                        </button>
                        <button className={s.btnNext} onClick={goNext}>
                            {scene === total - 1 ? "Entendido ✓" : "Siguiente →"}
                        </button>
                    </div>
                </div>
            </motion.div>
        </motion.div>
    );
}
