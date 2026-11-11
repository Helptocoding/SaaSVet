import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "../../auth/authContext";
import { getOperationsSeries, getFinancialSeries, getProtocolAnalytics } from "../../api/analytics";
import styles from "./analytics.module.css";

const RANGES = [
    { id: "7d", label: "7 días", days: 7 },
    { id: "30d", label: "30 días", days: 30 },
    { id: "90d", label: "90 días", days: 90 },
];

const SCOPE = {
    OPERATIONS: "operations",
    FINANCIAL: "financial",
};

const FIN_HERO = "revenue_paid";
const OPS_HERO = "appointments_done";

const FIN_SIDE = [
    { key: "revenue_accrual", label: "Devengado", caption: "Servicio rendido", money: true },
    { key: "invoices_paid_count", label: "Facturas cobradas", caption: "Tickets liquidados" },
];
const OPS_SIDE = [
    { key: "appointments_total", label: "Citas totales", caption: "Agendadas + sin cita" },
    { key: "appointments_no_show", label: "No asistieron", caption: "Clientes que no llegaron" },
    { key: "medical_records_closed", label: "Consultas cerradas", caption: "Atenciones documentadas" },
];

const LIFECYCLE_LABEL = {
    frozen: "Cerrado",
    provisional: "Provisional",
    rebuilt: "Recompuesto",
    corrupt: "Corrupto",
    missing: "Sin construir",
};

const MONTH_ABBR = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"];

const fmtMXN = (v) => {
    const n = Number(v ?? 0);
    return n.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
const fmtInt = (v) => Number(v ?? 0).toLocaleString("es-MX");

const parseISODate = (iso) => {
    if (!iso) return null;
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
};

const headlineForToday = () => {
    const now = new Date();
    const dayName = now.toLocaleDateString("es-MX", { weekday: "long" });
    return dayName.charAt(0).toUpperCase() + dayName.slice(1);
};

const issueLabel = () => {
    const now = new Date();
    const day = now.getDate();
    const month = now.toLocaleDateString("es-MX", { month: "long" });
    return `${day} de ${month} · ${now.getFullYear()}`;
};

const Analytics = () => {
    const { user } = useAuth();
    const isAdmin = user?.role === "ADMIN" || user?.role === "ADMIN_SAAS";

    const [scope, setScope] = useState(isAdmin ? SCOPE.FINANCIAL : SCOPE.OPERATIONS);
    const [rangeId, setRangeId] = useState("30d");
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const range = useMemo(() => RANGES.find(r => r.id === rangeId) || RANGES[1], [rangeId]);

    useEffect(() => {
        if (scope === SCOPE.FINANCIAL && !isAdmin) {
            // eslint-disable-next-line react-hooks/set-state-in-effect -- corrige un alcance no permitido antes de cargar
            setScope(SCOPE.OPERATIONS);
            return;
        }
        let cancelled = false;
        setLoading(true);
        setError(null);

        const to = new Date();
        const from = new Date();
        from.setDate(from.getDate() - (range.days - 1));

        const fetcher = scope === SCOPE.FINANCIAL ? getFinancialSeries : getOperationsSeries;
        fetcher({ from, to, includeToday: true })
            .then((res) => { if (!cancelled) setData(res); })
            .catch((err) => {
                if (cancelled) return;
                const msg =
                    err?.response?.status === 403
                        ? "No tienes permiso para ver estos datos."
                        : "No se pudo cargar la analítica.";
                setError(msg);
            })
            .finally(() => { if (!cancelled) setLoading(false); });

        return () => { cancelled = true; };
    }, [scope, range.days, isAdmin]);

    const isFinancial = scope === SCOPE.FINANCIAL;
    const heroKey = isFinancial ? FIN_HERO : OPS_HERO;
    const sideMetrics = isFinancial ? FIN_SIDE : OPS_SIDE;

    const todayValue = data?.today?.metrics?.[heroKey];
    const todayMissing = data?.today == null;

    const series = data?.series ?? [];

    return (
        <div className={styles.canvas}>
            <Masthead />

            <Toolbar
                scope={scope}
                onScope={setScope}
                rangeId={rangeId}
                onRange={setRangeId}
                isAdmin={isAdmin}
            />

            {error && <div className={styles.errorPanel}>{error}</div>}

            {loading && !data && <SkeletonHero />}

            {data && (
                <>
                    <HeroBlock
                        isFinancial={isFinancial}
                        heroKey={heroKey}
                        todayValue={todayValue}
                        todayMissing={todayMissing}
                        sideMetrics={sideMetrics}
                        todayMetrics={data?.today?.metrics ?? null}
                        series={series}
                    />

                    <SeriesBlock
                        isFinancial={isFinancial}
                        heroKey={heroKey}
                        data={data}
                        range={range}
                    />

                    <Ledger
                        isFinancial={isFinancial}
                        sideMetrics={sideMetrics}
                        heroKey={heroKey}
                        series={series}
                    />

                    {data.notes?.length > 0 && (
                        <Notes items={data.notes} />
                    )}
                </>
            )}

            <ProtocolSection rangeDays={range.days} />
        </div>
    );
};

/* ─── Analítica por protocolo (LITE, agregación read-only) ─────── */

const TRIAGE_LABEL = { red: "Rojo", orange: "Naranja", yellow: "Amarillo", green: "Verde", blue: "Azul" };
const DISCHARGE_LABEL = { alta: "Alta", hospitalizacion: "Hospitalización", referido: "Referido", fallecido: "Fallecido" };
const SURGERY_TYPE_LABEL = { electiva: "Electiva", programada: "Programada", urgencia: "Urgencia", emergencia: "Emergencia" };

const HAIRLINE = "var(--hairline, #e5e0d0)";

const PStat = ({ label, value, hint }) => (
    <div style={{ padding: "10px 14px", border: `1px solid ${HAIRLINE}`, borderRadius: 10 }}>
        <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".05em", opacity: 0.6 }}>{label}</div>
        <div style={{ fontSize: 24, fontWeight: 700, fontFamily: "var(--font-display)" }}>{value}</div>
        {hint && <div style={{ fontSize: 11, opacity: 0.55 }}>{hint}</div>}
    </div>
);

const DistBars = ({ dict, labels, color }) => {
    const entries = Object.entries(dict || {}).sort((a, b) => b[1] - a[1]);
    if (!entries.length) return <div style={{ fontSize: 12, opacity: 0.5 }}>Sin datos</div>;
    const max = Math.max(1, ...entries.map(([, n]) => n));
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {entries.map(([k, n]) => (
                <div key={k} style={{ display: "grid", gridTemplateColumns: "110px 1fr 28px", alignItems: "center", gap: 8, fontSize: 12 }}>
                    <span style={{ opacity: 0.75 }}>{(labels && labels[k]) || k}</span>
                    <span style={{ height: 8, background: HAIRLINE, borderRadius: 4, overflow: "hidden" }}>
                        <span style={{ display: "block", height: "100%", width: `${(n / max) * 100}%`, background: color || "var(--mulberry, #7c3a52)" }} />
                    </span>
                    <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{n}</span>
                </div>
            ))}
        </div>
    );
};

const PCard = ({ children }) => (
    <div style={{ border: `1px solid ${HAIRLINE}`, borderRadius: 14, padding: 18 }}>{children}</div>
);
const PGroupLabel = ({ children }) => (
    <div style={{ fontSize: 11, textTransform: "uppercase", opacity: 0.6, margin: "12px 0 6px" }}>{children}</div>
);

const ProtocolSection = ({ rangeDays }) => {
    const [pa, setPa] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        // eslint-disable-next-line react-hooks/set-state-in-effect -- marca carga justo antes de la petición
        setLoading(true);
        const to = new Date();
        const from = new Date();
        from.setDate(from.getDate() - (rangeDays - 1));
        getProtocolAnalytics({ from, to })
            .then((res) => { if (!cancelled) setPa(res); })
            .catch(() => { if (!cancelled) setPa(null); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [rangeDays]);

    if (loading || !pa) return null;
    const s = pa.surgery, e = pa.emergency, v = pa.vaccine;

    return (
        <section style={{ marginTop: 48 }}>
            <div className={styles.sectionMast}>
                <h2 className={styles.sectionTitle}>Protocolos clínicos</h2>
                <div className={styles.sectionRule} />
                <span className={styles.sectionMeta}>Cirugía · Urgencia · Vacuna</span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 20 }}>
                <PCard>
                    <h3 style={{ marginTop: 0 }}>Cirugía</h3>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                        <PStat label="Cirugías" value={s.total} />
                        <PStat label="Complicaciones" value={`${Math.round((s.complication_rate || 0) * 100)}%`} hint={`${s.complications_count} de ${s.total}`} />
                    </div>
                    <PGroupLabel>Por tipo</PGroupLabel>
                    <DistBars dict={s.by_type} labels={SURGERY_TYPE_LABEL} />
                    <PGroupLabel>Por clase de herida</PGroupLabel>
                    <DistBars dict={s.by_wound_class} />
                </PCard>

                <PCard>
                    <h3 style={{ marginTop: 0 }}>Urgencia</h3>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                        <PStat label="Urgencias" value={e.total} />
                        <PStat label="Puerta→triage" value={e.avg_door_to_triage_min != null ? `${e.avg_door_to_triage_min}m` : "—"} />
                        <PStat label="Estancia" value={e.avg_length_of_stay_min != null ? `${e.avg_length_of_stay_min}m` : "—"} />
                    </div>
                    <PGroupLabel>Nivel de triage</PGroupLabel>
                    <DistBars dict={e.by_triage_level} labels={TRIAGE_LABEL} color="#c0392b" />
                    <PGroupLabel>Estado al egreso</PGroupLabel>
                    <DistBars dict={e.by_discharge_status} labels={DISCHARGE_LABEL} />
                </PCard>

                <PCard>
                    <h3 style={{ marginTop: 0 }}>Vacuna</h3>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                        <PStat label="Aplicadas" value={v.total} />
                        <PStat label="Refuerzos 30d" value={v.upcoming_boosters_30d} hint="Próximos a vencer" />
                    </div>
                </PCard>
            </div>
        </section>
    );
};

/* ─── Subcomponents ───────────────────────────────────────────── */

const Masthead = () => (
    <header className={styles.masthead}>
        <div>
            <div className={styles.eyebrow}>Boletín · Analítica clínica · Vol. 1</div>
            <h1 className={styles.headline}>
                {headlineForToday()}, <em>en cifras.</em>
            </h1>
            <p className={styles.lede}>
                Lectura editorial de la operación clínica y financiera. <strong>Hoy es lectura en vivo</strong>;
                el histórico se imprime en madrugada como instantánea inmutable.
            </p>
        </div>
        <div className={styles.issue}>
            <div className={styles.issueLabel}>Edición</div>
            <div className={styles.issueDate}>{issueLabel()}</div>
        </div>
    </header>
);

const Toolbar = ({ scope, onScope, rangeId, onRange, isAdmin }) => (
    <div className={styles.toolbar}>
        <div className={styles.tabs} role="tablist">
            <button
                className={`${styles.tab} ${scope === SCOPE.OPERATIONS ? styles.tabActive : ""}`}
                onClick={() => onScope(SCOPE.OPERATIONS)}
                role="tab"
                aria-selected={scope === SCOPE.OPERATIONS}
            >
                Operativo
            </button>
            {isAdmin && (
                <button
                    className={`${styles.tab} ${scope === SCOPE.FINANCIAL ? styles.tabActive : ""}`}
                    onClick={() => onScope(SCOPE.FINANCIAL)}
                    role="tab"
                    aria-selected={scope === SCOPE.FINANCIAL}
                >
                    Financiero
                </button>
            )}
        </div>

        <div className={styles.range}>
            {RANGES.map((r) => (
                <button
                    key={r.id}
                    onClick={() => onRange(r.id)}
                    className={`${styles.rangeBtn} ${rangeId === r.id ? styles.rangeActive : ""}`}
                >
                    {r.label}
                </button>
            ))}
        </div>
    </div>
);

const HeroBlock = ({ isFinancial, todayValue, todayMissing, sideMetrics, todayMetrics }) => {
    const heroLabel = isFinancial ? "Ingreso del día (cobrado)" : "Citas completadas";
    const heroCaption = isFinancial
        ? "Cash-basis en vivo. Suma de facturas con status='paid' cuya marca paid_at cae en hoy en hora local de la organización."
        : "Atenciones marcadas como 'done'. Atenciones sin cita incluidas. Anchor: start_datetime en hora local.";

    return (
        <motion.div
            className={styles.heroGrid}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
        >
            <div className={styles.heroLead}>
                <div className={styles.heroLabel}>
                    <span className={styles.livePulse} />
                    <span className={styles.liveText}>EN VIVO</span>
                    <span style={{ opacity: 0.4 }}>·</span>
                    {heroLabel}
                </div>
                {todayMissing ? (
                    <div className={styles.heroNumber}>—</div>
                ) : isFinancial ? (
                    <div className={styles.heroNumber}>
                        <span className={styles.heroCurrency}>$</span>
                        {fmtMXN(todayValue)}
                        <span className={styles.heroCurrency}>MXN</span>
                    </div>
                ) : (
                    <div className={styles.heroNumber}>{fmtInt(todayValue)}</div>
                )}
                <p className={styles.heroCaption}>{heroCaption}</p>
            </div>

            <div className={styles.heroSide}>
                {sideMetrics.map((m) => (
                    <SideCard
                        key={m.key}
                        label={m.label}
                        rawValue={todayMetrics?.[m.key]}
                        hint={m.caption}
                        money={m.money}
                    />
                ))}
            </div>
        </motion.div>
    );
};

const SideCard = ({ label, hint, money, rawValue }) => {
    const display = rawValue == null
        ? "—"
        : (money ? `$${fmtMXN(rawValue)}` : fmtInt(rawValue));
    return (
        <div className={styles.sideCard}>
            <div>
                <div className={styles.sideCardLabel}>
                    <span>{label}</span>
                    <span className={`${styles.sideCardTag} ${styles.badgeLive}`} style={{ borderStyle: "dashed" }}>
                        LIVE
                    </span>
                </div>
                <div className={styles.sideCardValue}>{display}</div>
            </div>
            <div className={styles.sideCardHint}>{hint}</div>
        </div>
    );
};

/* ─── Series chart (custom SVG, no library) ───────────────────── */

const SeriesBlock = ({ isFinancial, heroKey, data, range }) => {
    const all = useMemo(() => {
        const s = (data.series || []).map((d) => ({ ...d, isToday: false }));
        if (data.today) s.push({ ...data.today, isToday: true });
        return s;
    }, [data]);

    if (!all.length) {
        return (
            <div className={styles.chartFrame}>
                <div className={styles.emptyState}>Sin datos para el rango seleccionado.</div>
            </div>
        );
    }

    const values = all.map((d) => Number(d.metrics?.[heroKey] ?? 0));
    const maxV = Math.max(1, ...values);
    const W = 100; // viewBox width %
    const H = 100;
    const barW = W / all.length;
    const pad = barW * 0.18;

    const friendlyTitle = isFinancial ? "Serie diaria · Ingresos cobrados (MXN)" : "Serie diaria · Citas completadas";

    return (
        <div className={styles.chartFrame}>
            <div className={styles.chartHead}>
                <span className={styles.chartTitle}>{friendlyTitle}</span>
                <span className={styles.chartLegend}>
                    <span className={styles.legendDot}>Snapshot</span>
                    <span className={`${styles.legendDot} ${styles.legendDotSlate}`} style={{ opacity: 1 }}>
                        <span style={{ position: "absolute" }} />
                    </span>
                    <span className={styles.legendDot} style={{ position: "relative" }}>
                        <span
                            style={{
                                width: 10, height: 10, background: "var(--mulberry)",
                                display: "inline-block", marginRight: 6,
                            }}
                        />
                        En vivo
                    </span>
                    <span className={styles.legendDot}>
                        <span
                            style={{
                                width: 10, height: 10, marginRight: 6,
                                backgroundImage: "repeating-linear-gradient(45deg, #d6cfb8 0 3px, transparent 3px 6px)",
                                border: "1px solid var(--hairline)",
                            }}
                        />
                        Sin construir
                    </span>
                </span>
            </div>

            <div className={styles.chartArea}>
                <svg className={styles.chartSvg} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
                    <defs>
                        <pattern id="hatchPattern" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                            <line x1="0" y1="0" x2="0" y2="4" stroke="#d6cfb8" strokeWidth="1.2" />
                        </pattern>
                    </defs>

                    {[0.25, 0.5, 0.75].map((g) => (
                        <line
                            key={g}
                            x1="0" x2={W}
                            y1={H * g} y2={H * g}
                            className={styles.chartGuide}
                            vectorEffect="non-scaling-stroke"
                        />
                    ))}

                    {all.map((d, i) => {
                        const v = Number(d.metrics?.[heroKey] ?? 0);
                        const h = (v / maxV) * (H - 12);
                        const x = i * barW + pad;
                        const w = barW - pad * 2;
                        const y = H - h;
                        const isMissing = d.lifecycle_state === "missing";
                        const isProvisional = d.lifecycle_state === "provisional";
                        const isLive = d.source === "live";

                        return (
                            <motion.rect
                                key={`${d.bucket_date}-${i}`}
                                x={x}
                                y={H}
                                width={w}
                                height={0}
                                animate={{ y, height: Math.max(h, 0.6) }}
                                transition={{ delay: i * 0.012, duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
                                className={`${styles.chartBar} ${isMissing ? styles.chartBarMissing : ""} ${isLive ? styles.chartBarLive : ""} ${isProvisional ? styles.chartBarProvisional : ""}`}
                                vectorEffect="non-scaling-stroke"
                            >
                                <title>{`${d.bucket_date} · ${d.lifecycle_state ?? d.source} · ${isFinancial ? `$${fmtMXN(v)}` : fmtInt(v)}`}</title>
                            </motion.rect>
                        );
                    })}
                </svg>
            </div>

            <div style={{
                display: "flex", justifyContent: "space-between",
                marginTop: 12,
                fontFamily: "var(--font-display)", fontSize: 9,
                letterSpacing: "0.18em", textTransform: "uppercase",
                opacity: 0.6,
            }}>
                <span>{all[0]?.bucket_date}</span>
                <span style={{ fontStyle: "italic", opacity: 0.7, fontFamily: "var(--font-dm-serif)", textTransform: "none", letterSpacing: 0, fontSize: 12 }}>
                    {range.label}
                </span>
                <span>{all[all.length - 1]?.bucket_date}</span>
            </div>
        </div>
    );
};

/* ─── Lifecycle ledger (rich list of every datapoint) ─────────── */

const Ledger = ({ isFinancial, heroKey, series }) => {
    const allRows = useMemo(() => {
        // Most-recent-first, paginate to last 14 for editorial focus.
        return [...series].reverse().slice(0, 14);
    }, [series]);

    if (!allRows.length) return null;

    // Split into two columns
    const half = Math.ceil(allRows.length / 2);
    const left = allRows.slice(0, half);
    const right = allRows.slice(half);

    return (
        <section>
            <div className={styles.sectionMast}>
                <h2 className={styles.sectionTitle}>Bitácora del periodo</h2>
                <div className={styles.sectionRule} />
                <span className={styles.sectionMeta}>{allRows.length} · días · más reciente arriba</span>
            </div>

            <div className={styles.ledger}>
                <LedgerColumn rows={left} isFinancial={isFinancial} heroKey={heroKey} />
                <LedgerColumn rows={right} isFinancial={isFinancial} heroKey={heroKey} />
            </div>
        </section>
    );
};

const LedgerColumn = ({ rows, isFinancial, heroKey }) => (
    <div className={styles.ledgerCol}>
        <AnimatePresence initial={false}>
            {rows.map((d, idx) => (
                <LedgerRow
                    key={d.bucket_date}
                    row={d}
                    isFinancial={isFinancial}
                    heroKey={heroKey}
                    delay={idx * 0.04}
                />
            ))}
        </AnimatePresence>
    </div>
);

const LedgerRow = ({ row, isFinancial, heroKey, delay }) => {
    const date = parseISODate(row.bucket_date);
    if (!date) return null;
    const day = date.getDate();
    const monthAbbr = MONTH_ABBR[date.getMonth()];
    const v = Number(row.metrics?.[heroKey] ?? 0);

    const valueDisplay = isFinancial ? `$${fmtMXN(v)}` : fmtInt(v);
    const unitLabel = isFinancial ? "MXN" : (heroKey === OPS_HERO ? "consultas" : "ítems");

    return (
        <motion.div
            className={styles.ledgerRow}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay, duration: 0.32, ease: [0.2, 0.8, 0.2, 1] }}
        >
            <div className={styles.ledgerDate}>
                <div className={styles.ledgerDay}>{day}</div>
                <div className={styles.ledgerMonth}>{monthAbbr}</div>
            </div>

            <div className={styles.ledgerBody}>
                <div className={styles.ledgerValue}>
                    {valueDisplay}
                    <span className={styles.ledgerValueUnit}>{unitLabel}</span>
                </div>
                <div className={styles.ledgerCaption}>
                    {row.metrics_schema_version != null && (
                        <span className={styles.schemaTag}>EDICIÓN v{row.metrics_schema_version} · </span>
                    )}
                    {row.source === "live" ? "Lectura en vivo" : `Anchor ${heroKey === FIN_HERO ? "paid_at" : "start_datetime"}`}
                </div>
            </div>

            <LifecycleBadge row={row} />
        </motion.div>
    );
};

const LifecycleBadge = ({ row }) => {
    const state = row.source === "live" ? "live" : (row.lifecycle_state ?? "missing");
    const cls = {
        frozen: styles.badgeFrozen,
        provisional: styles.badgeProvisional,
        rebuilt: styles.badgeRebuilt,
        corrupt: styles.badgeCorrupt,
        missing: styles.badgeMissing,
        live: styles.badgeLive,
    }[state] || styles.badgeMissing;

    const label = state === "live" ? "EN VIVO" : (LIFECYCLE_LABEL[state] ?? state);

    return <span className={`${styles.badge} ${cls}`}>{label}</span>;
};

const Notes = ({ items }) => (
    <div className={styles.notes}>
        <div className={styles.notesLabel}>Notas al pie</div>
        <ol className={styles.notesList}>
            {items.map((n, i) => (
                <li key={i} className={styles.notesItem}>{n}</li>
            ))}
        </ol>
    </div>
);

/* ─── Skeleton ────────────────────────────────────────────────── */

const SkeletonHero = () => (
    <>
        <div className={styles.heroGrid} aria-hidden>
            <div className={`${styles.heroLead} ${styles.skeletonBlock}`} style={{ height: 280 }} />
            <div className={styles.heroSide}>
                <div className={`${styles.sideCard} ${styles.skeletonBlock}`} style={{ height: 132 }} />
                <div className={`${styles.sideCard} ${styles.skeletonBlock}`} style={{ height: 132 }} />
            </div>
        </div>
        <div className={`${styles.chartFrame} ${styles.skeletonBlock}`} style={{ height: 280, marginBottom: 56 }} />
    </>
);

export default Analytics;
