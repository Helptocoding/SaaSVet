import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import process from "node:process";

// Trinquete del design system (plan UX 2026-11-21, F0.3; design-system.md §8).
//
// Cuenta, en todo src/, los valores visuales que el design system no admite:
//
//   hex          colores escritos a mano fuera de styles/tokens.css
//   fontWeight   pesos distintos de 400/500/600/700
//   tinyFont     tamaños de letra menores a 11px
//   spacing      padding/margin/gap fuera de la escala (design-system.md §3)
//
// No exige cero de golpe: hay deuda vieja. Exige que el número no suba, y que
// cuando baje se baje también la línea base en el mismo cambio, para que lo
// ganado no se pierda. La meta es 0 (F4.5).
//
// Es un conteo léxico, no un parser: lo que importa es que sea determinista.

// Se lee del disco: `import.meta.glob(..., ?raw)` no entrega el texto de los
// .css bajo vitest, y bajo jsdom `import.meta.url` no es un file://. Vitest
// corre desde frontend/ (local y CI).
const SRC = join(process.cwd(), "src");

function readSources(dir = SRC, out = {}) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) {
            readSources(full, out);
        } else if (/\.(jsx?|css)$/.test(entry.name)) {
            out[`/${relative(SRC, full).split(sep).join("/")}`] = readFileSync(full, "utf8");
        }
    }
    return out;
}

const modules = readSources();

// Excepciones documentadas en design-system.md §7.
const EXCLUDED = [
    "/styles/tokens.css",          // la única casa de los hex
    "/styles/login.css",           // set propio del login
    "/pages/analytics/",           // lenguaje editorial aislado, fuera del piloto
    "/features/inventory/tutorial/", // ilustraciones SVG con color propio
    "/test/",
];
const isExcluded = (path) =>
    EXCLUDED.some((part) => path.includes(part)) || /\.test\.[jt]sx?$/.test(path);

const ALLOWED_WEIGHTS = new Set([400, 500, 600, 700]);
const ALLOWED_SPACING = new Set([0, 1, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32, 40, 48, 56, 64]);
const MIN_FONT_PX = 11;

// Línea base del 2026-11-22. Solo puede bajar.
const BASELINE = {
    hex: 523,
    fontWeight: 45,
    tinyFont: 84,
    spacing: 388,
};

const stripComments = (src) =>
    src
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");

// CSS embebido en JSX (`<style>{`…`}</style>`) se cuenta como CSS.
const STYLE_BLOCK = /<style>\{`([\s\S]*?)`\}<\/style>/g;

const HEX = /(?<![&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/g;

const CSS_WEIGHT = /font-weight\s*:\s*(\d{3})/g;
const JSX_WEIGHT = /fontWeight\s*:\s*["']?(\d{3})/g;

const CSS_SIZE = /font-size\s*:\s*([\d.]+)px/g;
const JSX_SIZE_STR = /fontSize\s*:\s*["']([\d.]+)px["']/g;
const JSX_SIZE_NUM = /fontSize\s*:\s*([\d.]+)\s*[,}]/g;

const CSS_SPACING = /(?:^|[\s;{])(?:padding|margin|gap|row-gap|column-gap)(?:-(?:top|right|bottom|left|inline|block)(?:-start|-end)?)?\s*:\s*([^;}\n]+)/g;
const JSX_SPACING = /\b(?:padding|margin|gap|rowGap|columnGap)(?:Top|Right|Bottom|Left|Inline|Block)?\s*:\s*(?:"([^"]*)"|'([^']*)'|(\d+(?:\.\d+)?)\s*[,}])/g;
const PX = /(\d+(?:\.\d+)?)px/g;

function countCss(css, add) {
    for (const m of css.matchAll(CSS_WEIGHT)) {
        if (!ALLOWED_WEIGHTS.has(Number(m[1]))) add("fontWeight");
    }
    for (const m of css.matchAll(CSS_SIZE)) {
        if (Number(m[1]) < MIN_FONT_PX) add("tinyFont");
    }
    for (const m of css.matchAll(CSS_SPACING)) {
        for (const px of m[1].matchAll(PX)) {
            if (!ALLOWED_SPACING.has(Number(px[1]))) add("spacing");
        }
    }
}

function countJsx(src, add) {
    for (const m of src.matchAll(JSX_WEIGHT)) {
        if (!ALLOWED_WEIGHTS.has(Number(m[1]))) add("fontWeight");
    }
    for (const re of [JSX_SIZE_STR, JSX_SIZE_NUM]) {
        for (const m of src.matchAll(re)) {
            if (Number(m[1]) < MIN_FONT_PX) add("tinyFont");
        }
    }
    for (const m of src.matchAll(JSX_SPACING)) {
        if (m[3] !== undefined) {
            if (!ALLOWED_SPACING.has(Number(m[3]))) add("spacing");
            continue;
        }
        for (const px of (m[1] ?? m[2]).matchAll(PX)) {
            if (!ALLOWED_SPACING.has(Number(px[1]))) add("spacing");
        }
    }
}

function measure() {
    const totals = { hex: 0, fontWeight: 0, tinyFont: 0, spacing: 0 };
    const byFile = {};
    for (const [path, raw] of Object.entries(modules)) {
        if (isExcluded(path)) continue;
        const src = stripComments(raw);
        const add = (kind) => {
            totals[kind] += 1;
            byFile[kind] ??= {};
            byFile[kind][path] = (byFile[kind][path] ?? 0) + 1;
        };
        for (let i = 0, n = (src.match(HEX) ?? []).length; i < n; i += 1) add("hex");
        if (path.endsWith(".css")) {
            countCss(src, add);
        } else {
            for (const block of src.matchAll(STYLE_BLOCK)) countCss(block[1], add);
            countJsx(src.replace(STYLE_BLOCK, ""), add);
        }
    }
    return { totals, byFile };
}

const topFiles = (files = {}) =>
    Object.entries(files)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([file, n]) => `${file} (${n})`)
        .join(", ");

describe("trinquete del design system (design-system.md §8)", () => {
    it("ningún conteo sube, y si baja se actualiza la línea base", () => {
        const { totals, byFile } = measure();
        const problems = [];
        for (const [kind, base] of Object.entries(BASELINE)) {
            const now = totals[kind];
            if (now > base) {
                problems.push(`${kind} subió de ${base} a ${now}. Más casos en: ${topFiles(byFile[kind])}`);
            } else if (now < base) {
                problems.push(`${kind} bajó de ${base} a ${now}: actualiza BASELINE.${kind} = ${now}`);
            }
        }
        expect(problems).toEqual([]);
    });
});
