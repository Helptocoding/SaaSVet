import { describe, it, expect } from "vitest";

// H-07 / H-08 regression gate (auth audit).
//
// Two console anti-patterns leak credential material to the browser console,
// where anyone with DevTools (or the persisted console history) can read it:
//
//   H-07  console.log(err) / console.error(err)  — the raw Axios error object
//         carries err.config.headers.Authorization = "Bearer <JWT>".
//   H-08  console.*(... err.response.data ...)    — dumps the full HTTP body.
//
// The fix is to log a sanitised string: console.error(apiError(err)). This
// gate fails if either anti-pattern reappears anywhere under src/ (mirrors the
// repo's existing grep gates, e.g. the public_id dual-lookup ban).

const modules = import.meta.glob("../**/*.{js,jsx}", {
    query: "?raw",
    import: "default",
    eager: true,
});

// Sole argument is the raw error object.
const RAW_ERR = /console\.(?:log|error|warn|info|debug)\(\s*err\s*\)/;
// Any console call that reaches into the Axios response body.
const RESPONSE_BODY = /console\.(?:log|error|warn|info|debug)\([^)]*\.response[^)]*data/;

function findOffenders() {
    const hits = [];
    for (const [path, src] of Object.entries(modules)) {
        // Skip test files (this file defines the patterns as regex literals).
        if (path.includes("/test/") || /\.test\.[jt]sx?$/.test(path)) continue;
        src.split("\n").forEach((line, idx) => {
            if (RAW_ERR.test(line) || RESPONSE_BODY.test(line)) {
                hits.push(`${path}:${idx + 1}: ${line.trim()}`);
            }
        });
    }
    return hits;
}

describe("console must not leak auth tokens (H-07/H-08)", () => {
    it("no console.* logs a raw Axios error object or its response body", () => {
        expect(findOffenders()).toEqual([]);
    });
});
