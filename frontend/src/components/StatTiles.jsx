import Skeleton from "react-loading-skeleton";
import s from "./StatTiles.module.css";

// Indicadores: estructura adaptada de ReUI `statistic-card-2` (MIT,
// keenthemes/reui). Fuente única para Inventario, Dashboard y Mascotas — ver
// design-system.md §5. Presentacional: el caller decide tono, pie y acción.
// Sin rótulo sobre la rejilla salvo que el caller pase `eyebrow` (plan UX D2:
// el antiguo «Linear Insights» era un nombre interno en inglés).

const TONE_CLASS = {
    ink: s.toneInk,
    primary: s.tonePrimary,
    attention: s.toneAttention,
    danger: s.toneDanger,
    forest: s.toneForest,
    calm: s.toneCalm,
};

// Alto de una tarjeta, para que el esqueleto no salte al llegar los datos.
const TILE_HEIGHT = 126;

const Intro = ({ eyebrow }) => (
    <div className={s.intro}>
        <span className={s.eyebrow}>{eyebrow}</span>
    </div>
);

// `gridClassName` solo debe fijar `--stat-grid-cols` (y sus media queries):
// así la rejilla de una página no compite en especificidad con la de aquí.
export function StatSection({ label, eyebrow = null, gridClassName, children }) {
    return (
        <section className={s.section} aria-label={label}>
            {eyebrow && <Intro eyebrow={eyebrow} />}
            <div className={[s.grid, gridClassName].filter(Boolean).join(" ")}>{children}</div>
        </section>
    );
}

// Con `onClick` la tarjeta es un botón conmutador (`pressed`); sin él, un div.
// `live` antepone al pie un punto que late (dato que se actualiza solo).
export function StatTile({
    label, value, icon: TileIcon, tone = "ink", badge, foot,
    live = false, counting = false, className, onClick, pressed = false,
}) {
    const cls = [
        s.tile,
        TONE_CLASS[tone] || s.toneInk,
        onClick ? s.action : "",
        onClick && pressed ? s.actionOn : "",
        className,
    ].filter(Boolean).join(" ");

    const body = (
        <>
            <span className={s.head}>
                <span className={s.title}>{label}</span>
                {TileIcon && <span className={s.icon} aria-hidden="true"><TileIcon s={16} c="currentColor" /></span>}
            </span>
            <span className={s.main}>
                <span className={`${s.value} ${counting ? s.valueCounting : ""}`}>{value}</span>
                {badge && <span className={s.badge}>{badge}</span>}
            </span>
            <span className={s.foot}>
                {live && <span className={s.liveDot} aria-hidden="true" />}
                {foot}
            </span>
        </>
    );

    if (onClick) {
        return (
            <button
                type="button"
                className={cls}
                aria-pressed={pressed}
                aria-label={`${label}: ${value}`}
                onClick={onClick}
            >
                {body}
            </button>
        );
    }
    return <div className={cls}>{body}</div>;
}

// Esqueleto con la misma rejilla. Presentacional: el caller pone el `role="status"`.
export function StatSectionSkeleton({ count, eyebrow = null, gridClassName, tileClassName }) {
    return (
        <section className={s.section} aria-hidden="true">
            {eyebrow && <Intro eyebrow={eyebrow} />}
            <div className={[s.grid, gridClassName].filter(Boolean).join(" ")}>
                {Array.from({ length: count }, (_, i) => (
                    <Skeleton
                        key={i}
                        height={TILE_HEIGHT}
                        borderRadius="var(--r-lg)"
                        containerClassName={tileClassName?.(i)}
                    />
                ))}
            </div>
        </section>
    );
}
