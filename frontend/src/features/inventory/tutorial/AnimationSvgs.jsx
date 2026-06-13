// SVG components — source files live in frontend/src/assets/svgs/
// CSS variables are overridden via style prop (GUANTE_CAJA_VARS, GUANTE_VARS, STOCK_VARS)

// ── Caja de guantes ───────────────────────────────────────
// Source: assets/svgs/guante-caja.svg  (400×290 viewBox)
export const GuanteCajaSvg = ({ width = 200, style, className }) => (
    <svg viewBox="0 0 400 290" fill="none" xmlns="http://www.w3.org/2000/svg"
        width={width} style={style} className={className} aria-hidden="true">
        {/* Shadow */}
        <ellipse cx="205" cy="250" rx="160" ry="15"
            fill="var(--box-shadow, #3E6FA8)" opacity="0.16" />
        {/* Lid */}
        <polygon points="60,90 340,90 368,62 88,62"
            fill="var(--box-top, #DCE8FA)" />
        <polygon points="60,90 340,90 368,62 88,62"
            fill="var(--box-primary, #6E9BDC)" opacity="0.10" />
        {/* Side */}
        <polygon points="340,90 368,62 368,202 340,230"
            fill="var(--box-side, #B9CEEF)" />
        {/* Front face */}
        <rect x="60" y="90" width="280" height="140" rx="6"
            fill="var(--box-face, #F4F8FE)" />
        <rect x="60" y="90" width="280" height="140" rx="6"
            fill="none" stroke="var(--box-line, #C9D8EF)" strokeWidth="1.5" />
        {/* Brand band */}
        <rect x="60" y="106" width="170" height="40"
            fill="var(--box-primary, #6E9BDC)" opacity="0.92" />
        <rect x="76" y="118" width="130" height="16" rx="3"
            fill="#FFFFFF" opacity="0.16" />
        {/* Glove graphic on box (right side) */}
        <g transform="translate(228.8 102.8) scale(0.35)">
            <path
                fill="var(--box-guante, #6E9BDC)"
                d="M 102,32 L 96,38 L 95,144 L 79,143 L 79,71 L 78,68 L 73,64 L 68,65 L 64,70 L 63,232 L 47,231 L 47,160 L 38,160 L 32,166 L 33,245 L 37,255 L 42,262 L 64,285 L 64,343 L 248,343 L 247,330 L 250,323 L 254,319 L 241,313 L 227,304 L 203,282 L 189,262 L 179,239 L 175,220 L 174,89 L 170,86 L 165,86 L 161,89 L 160,92 L 160,143 L 144,144 L 143,71 L 139,65 L 132,65 L 128,70 L 128,143 L 112,144 L 111,39 L 107,33 Z"
            />
        </g>
        {/* Size badge */}
        <rect x="76" y="176" width="40" height="40" rx="8"
            fill="var(--box-primary, #6E9BDC)" />
        <rect x="86" y="186" width="20" height="20" rx="3"
            fill="#FFFFFF" opacity="0.18" />
        {/* Count placeholder */}
        <rect x="126" y="190" width="96" height="14" rx="3"
            fill="var(--box-line, #C9D8EF)" opacity="0.7" />
        <line x1="60" y1="90" x2="340" y2="90"
            stroke="var(--box-line, #C9D8EF)" strokeWidth="1.5" />
    </svg>
);

// ── Guante individual ─────────────────────────────────────
// Source: assets/svgs/guante-individual.svg  (512×512 viewBox)
export const GuanteIndividualSvg = ({ width = 140, style, className }) => (
    <svg viewBox="0 0 512 512" fill="none" xmlns="http://www.w3.org/2000/svg"
        width={width} style={style} className={className} aria-hidden="true">
        {/* Main glove body + fingers */}
        <path
            fill="var(--guante-color, #46adc0)"
            d="M 328,424 L 328,449 L 332,454 L 336,455 L 339,454 L 343,448 L 343,424 Z
               M 296,360 L 296,409 L 300,414 L 304,415 L 307,414 L 311,408 L 311,360 Z
               M 265,333 L 266,340 L 272,343 L 323,343 L 327,346 L 328,407 L 380,407 L 404,391 L 479,391 L 479,296 L 396,296 L 363,279 L 352,277 L 344,279 L 339,282 L 314,311 L 351,311 L 351,328 L 273,328 L 267,330 Z
               M 102,32 L 96,38 L 95,144 L 79,143 L 79,71 L 78,68 L 73,64 L 68,65 L 64,70 L 63,232 L 47,231 L 47,160 L 38,160 L 32,166 L 33,245 L 37,255 L 42,262 L 64,285 L 64,343 L 248,343 L 247,330 L 250,323 L 254,319 L 241,313 L 227,304 L 203,282 L 189,262 L 179,239 L 175,220 L 174,89 L 170,86 L 165,86 L 161,89 L 160,92 L 160,143 L 144,144 L 143,71 L 139,65 L 132,65 L 128,70 L 128,143 L 112,144 L 111,39 L 107,33 Z"
        />
        {/* Cuff / wrist band */}
        <path
            fill="var(--guante-puño, #fed682)"
            d="M 64,392 L 64,479 L 151,479 L 151,392 Z"
        />
    </svg>
);

// ── Link icon ─────────────────────────────────────────────
// Source: assets/svgs/link-icon.svg  (100×100 viewBox)
export const LinkIconSvg = ({ size = 36, style, className }) => (
    <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg"
        width={size} height={size} style={style} className={className} aria-hidden="true">
        <circle cx="50" cy="50" r="46"
            fill="none" stroke="currentColor" strokeWidth="2.5" opacity="0.25" />
        <g stroke="currentColor" strokeWidth="6" strokeLinecap="round" fill="none">
            <path d="M44 38 L36 46 a11 11 0 0 0 0 16 l8 8" />
            <path d="M56 62 L64 54 a11 11 0 0 0 0 -16 l-8 -8" />
            <line x1="42" y1="58" x2="58" y2="42" />
        </g>
    </svg>
);

// ── Stock box ─────────────────────────────────────────────
// Source: assets/svgs/stock-box.svg  (360×210 viewBox)
export const StockBoxSvg = ({ width = 280, style, className }) => (
    <svg viewBox="0 0 360 210" fill="none" xmlns="http://www.w3.org/2000/svg"
        width={width} style={style} className={className} aria-hidden="true">
        <rect x="24" y="20" width="312" height="180" rx="16"
            fill="var(--stock-shadow, #1E3A6B)" opacity="0.12" />
        <rect x="18" y="14" width="324" height="180" rx="16"
            fill="var(--stock-body, #FFFFFF)" />
        <rect x="18" y="14" width="324" height="180" rx="16"
            fill="none" stroke="var(--stock-line, #D8E3F5)" strokeWidth="1.5" />
        <path d="M18 30 a16 16 0 0 1 16 -16 h292 a16 16 0 0 1 16 16 v34 h-324 Z"
            fill="var(--stock-header, #1E3A6B)" />
        <g fill="#FFFFFF" opacity="0.95">
            <rect x="42" y="32" width="11" height="11" rx="1.5" />
            <rect x="55" y="32" width="11" height="11" rx="1.5" opacity="0.7" />
            <rect x="48" y="44" width="11" height="11" rx="1.5" opacity="0.85" />
        </g>
        <rect x="76" y="33" width="150" height="14" rx="3"
            fill="#FFFFFF" opacity="0.22" />
        <rect x="120" y="86" width="120" height="10" rx="3"
            fill="var(--stock-line, #D8E3F5)" />
        <rect x="108" y="104" width="144" height="32" rx="5"
            fill="var(--stock-accent, #2B5BA8)" opacity="0.18" />
        <rect x="80" y="150" width="200" height="9" rx="3"
            fill="var(--stock-line, #D8E3F5)" />
        <rect x="100" y="166" width="160" height="9" rx="3"
            fill="var(--stock-line, #D8E3F5)" />
    </svg>
);

// ── Box icon (monocolor) ──────────────────────────────────
// Source: assets/svgs/box-icon.svg  (64×64 viewBox)
export const BoxIconSvg = ({ size = 32, style, className }) => (
    <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"
        width={size} height={size} style={style} className={className} aria-hidden="true">
        <polygon points="32,8 56,20 32,32 8,20" fill="currentColor" opacity="0.95" />
        <polygon points="8,20 32,32 32,56 8,44" fill="currentColor" opacity="0.55" />
        <polygon points="56,20 32,32 32,56 56,44" fill="currentColor" opacity="0.75" />
    </svg>
);

// ── Hand icon (monocolor) ─────────────────────────────────
// Source: assets/svgs/hand-icon.svg  (64×64 viewBox)
export const HandIconSvg = ({ size = 32, style, className }) => (
    <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"
        width={size} height={size} style={style} className={className} aria-hidden="true">
        <g fill="none" stroke="currentColor" strokeWidth="3.5"
            strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 38 C18 30 18 24 18 22 a3.4 3.4 0 0 1 6.8 0 V32" />
            <path d="M24.8 32 V18 a3.4 3.4 0 0 1 6.8 0 V32" />
            <path d="M31.6 32 V18 a3.4 3.4 0 0 1 6.8 0 V32" />
            <path d="M38.4 32 V22 a3.4 3.4 0 0 1 6.8 0 V40" />
            <path d="M18 38 c0 8 4 14 12 14 h4 c7 0 11 -5 11 -12 V40" />
        </g>
    </svg>
);

// ── Flow arrow (monocolor) ────────────────────────────────
// Source: assets/svgs/flow-arrow.svg  (120×40 viewBox)
export const FlowArrowSvg = ({ width = 80, style, className }) => (
    <svg viewBox="0 0 120 40" fill="none" xmlns="http://www.w3.org/2000/svg"
        width={width} style={style} className={className} aria-hidden="true">
        <g stroke="currentColor" strokeWidth="3.5"
            strokeLinecap="round" strokeLinejoin="round" fill="none">
            <line x1="8" y1="20" x2="104" y2="20" />
            <polyline points="90,8 108,20 90,32" />
        </g>
    </svg>
);
