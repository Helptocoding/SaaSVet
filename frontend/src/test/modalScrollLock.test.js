/**
 * Bloqueo del scroll de fondo con un modal abierto (2026-11-25).
 *
 * La regla vive una sola vez en `styles/global.css`: `html:has(.modal-overlay,
 * [data-scroll-lock])` oculta el scroll de la página. Un modal nuevo queda
 * cubierto si usa la clase global `.modal-overlay`; si trae su propio fondo
 * (ficha lateral de Equipo, selector del importador) debe declarar
 * `data-scroll-lock`. Esta prueba impide que uno se cuele sin ninguna de las
 * dos: jsdom no evalúa `:has`, así que se comprueba el código, no el efecto.
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import process from "node:process";

const SRC = join(process.cwd(), "src");

function readJsx(dir = SRC, out = {}) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) readJsx(full, out);
        else if (entry.name.endsWith(".jsx") && !entry.name.includes(".test.")) {
            out[relative(SRC, full).split(sep).join("/")] = readFileSync(full, "utf8");
        }
    }
    return out;
}

describe("bloqueo del scroll de fondo en modales", () => {
    it("la regla está en global.css", () => {
        const css = readFileSync(join(SRC, "styles", "global.css"), "utf8");
        expect(css).toMatch(/html:has\(\.modal-overlay, \[data-scroll-lock\]\)\s*\{[^}]*overflow:\s*hidden/);
    });

    it("todo diálogo modal usa .modal-overlay o declara data-scroll-lock", () => {
        const missing = Object.entries(readJsx())
            .filter(([, code]) => /aria-modal(=\{?"?true|\b(?!=))/.test(code))
            .filter(([, code]) => !/className=["{`][^"]*\bmodal-overlay\b/.test(code) && !code.includes("data-scroll-lock"))
            .map(([file]) => file);
        expect(missing).toEqual([]);
    });
});
