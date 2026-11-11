import { describe, it, expect } from "vitest";

// Orden 5, F01: las supresiones de estas reglas son decisiones revisadas, una por
// una. Este gate impide añadir otra sin explicar por qué es legítima.
const modules = import.meta.glob("../**/*.{js,jsx}", {
    query: "?raw",
    import: "default",
    eager: true,
});

const RULES = /eslint-disable.*react-hooks\/(set-state-in-effect|immutability|refs|purity|preserve-manual-memoization)/;

function findOffenders() {
    const hits = [];
    for (const [path, src] of Object.entries(modules)) {
        if (path.includes("/test/") || /\.test\.[jt]sx?$/.test(path)) continue;
        src.split("\n").forEach((line, idx) => {
            if (RULES.test(line) && !line.includes(" -- ")) hits.push(`${path}:${idx + 1}: ${line.trim()}`);
        });
    }
    return hits;
}

describe("supresiones de react-hooks con motivo (orden 5)", () => {
    it("toda supresión de estas reglas explica su motivo tras ' -- '", () => {
        expect(findOffenders()).toEqual([]);
    });
});
