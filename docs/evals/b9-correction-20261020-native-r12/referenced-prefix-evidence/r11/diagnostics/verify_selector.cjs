"use strict";
// Pure argv/RegExp proof. It never imports Vitest or application modules.
const fs = require("fs");
const cp = require("child_process");
const crypto = require("crypto");
const path = require("path");
const pnpm = process.argv[2];
const oldSelectionPath = process.argv[3];
const TARGET_FILE = "src/pages/inbox/index.test.jsx";
const TARGET_NAME = "Inbox — aislamiento del borrador un éxito antiguo A→B→A no borra un draft nuevo aunque tenga el mismo texto";
const hash = (raw) => crypto.createHash("sha256").update(raw).digest("hex");
const requireProof = (ok, message) => { if (!ok) throw new Error(message); };
requireProof(process.platform === "win32", "This proof requires the same native Windows shell");
requireProof(pnpm && oldSelectionPath, "Expected pnpm CLI and original selection path");
const originalBytes = fs.readFileSync(oldSelectionPath);
const old = JSON.parse(originalBytes);
const index = old.argv.indexOf("--testNamePattern");
requireProof(index >= 0 && old.identity.file === TARGET_FILE && old.identity.fullName === TARGET_NAME,
    "Original selection identity changed");
const originalPattern = old.argv[index + 1];
requireProof(originalPattern === "^" + TARGET_NAME.replaceAll(" ", "\\ ") + "$",
    "Original pattern differs from the actual Python re.escape whitespace pattern");
requireProof(!Array.from(TARGET_NAME).some((char) => "\\^$.*+?()[]{}|".includes(char)),
    "Target name contains RegExp metacharacters");
const repairedPattern = "^" + TARGET_NAME + "$";
const sourcePath = path.resolve(path.dirname(pnpm), "../dist/pnpm.cjs");
const sourceBytes = fs.readFileSync(sourcePath);
const source = sourceBytes.toString("utf8");
const token = 'opts.args.map((arg) => JSON.stringify(arg)).join(" ")';
const offset = source.indexOf(token);
requireProof(offset >= 0, "Installed pnpm Windows argument serialization not found");
const snippet = source.slice(Math.max(0, offset - 100), offset + token.length + 100);
requireProof(snippet.includes("is_windows_1.default"), "pnpm branch is not the Windows serializer");
const childCode = "console.log(JSON.stringify(process.argv.slice(1)))";
function probe(pattern) {
    const command = '"' + process.execPath + '" -e ' + JSON.stringify(childCode) + " " + JSON.stringify(pattern);
    const argv = ["/d", "/s", "/c", '"' + command + '"'];
    const result = cp.spawnSync(process.env.ComSpec || "C:/Windows/System32/cmd.exe", argv, {
        windowsHide: true, windowsVerbatimArguments: true, encoding: "utf8", timeout: 30000
    });
    requireProof(!result.error && result.status === 0 && result.stderr.trim() === "", "Pure argv echo child failed");
    const received = JSON.parse(result.stdout);
    requireProof(Array.isArray(received) && received.length === 1, "Unexpected pure child argv");
    return { input_pattern: pattern, serialization: "JSON.stringify(arg), same installed pnpm Windows branch",
        command, shell_argv: argv, exit_code: result.status, stdout: result.stdout, stderr: result.stderr,
        received_pattern: received[0], pattern_preserved: pattern === received[0],
        matches_original_identity: new RegExp(received[0]).test(TARGET_NAME) };
}
const original = probe(originalPattern);
const repaired = probe(repairedPattern);
requireProof(original.received_pattern === originalPattern.replaceAll("\\", "\\\\") &&
    original.matches_original_identity === false && original.pattern_preserved === false,
    "Original Windows double-backslash failure was not reproduced");
requireProof(repaired.pattern_preserved && repaired.matches_original_identity,
    "Repaired literal pattern was not preserved by the same Windows serializer");
const discoveryPath = process.argv[4];
const originalReportPath = process.argv[5];
requireProof(discoveryPath && originalReportPath, "Expected static discovery and prior zero-outcome report paths");
const discoveryBytes = fs.readFileSync(discoveryPath);
const originalReportBytes = fs.readFileSync(originalReportPath);
const discovered = JSON.parse(discoveryBytes);
const originalReport = JSON.parse(originalReportBytes);
requireProof(Array.isArray(discovered) && discovered.length === 26, "Static collection must preserve all 26 file identities");
requireProof(originalReport.numPassedTests === 0 && originalReport.numFailedTests === 0 &&
    originalReport.numPendingTests === 26, "Prior harness result is not the preserved zero-execution inventory");
const previous = originalReport.testResults.flatMap((file) =>
    file.assertionResults.map((row) => ({ file: file.name, ...row })));
requireProof(previous.length === 26, "Prior runtime identity inventory changed");
const relativeFile = (name) => name.replaceAll("\\", "/").split("/src/frontend/").pop();
const mapping = new Map();
for (const row of previous) {
    requireProof(relativeFile(row.file) === TARGET_FILE && ["pending", "skipped"].includes(row.status) &&
        (row.duration == null || row.duration === 0),
        "Prior inventory includes another file or actual test outcome");
    const display = [...row.ancestorTitles, row.title].join(" > ");
    requireProof(!mapping.has(display) && row.fullName === [...row.ancestorTitles, row.title].join(" "),
        "Prior runtime/display name mapping is ambiguous");
    mapping.set(display, row.fullName);
}
const rows = discovered.map((row) => {
    requireProof(typeof row.name === "string" && typeof row.file === "string" &&
        relativeFile(row.file) === TARGET_FILE && mapping.has(row.name),
        "Unexpected static discovery identity");
    return { file: TARGET_FILE, static_display_name: row.name, fullName: mapping.get(row.name),
        selected_by_runtime_literal: new RegExp(repaired.received_pattern).test(mapping.get(row.name)) };
});
requireProof(new Set(rows.map((row) => row.static_display_name)).size === 26,
    "Duplicate or missing static identity");
const matches = rows.filter((row) => row.selected_by_runtime_literal);
requireProof(matches.length === 1 && matches[0].fullName === TARGET_NAME,
    "Runtime literal must select exactly the authorized one identity");
console.log(JSON.stringify({ state: "PASS", scope: "Pure Windows child argv echo and RegExp; no Vitest/application imports",
    actual_tests_executed: 0, target: { file: TARGET_FILE, fullName: TARGET_NAME },
    original_selection: { path: oldSelectionPath, sha256: hash(originalBytes), bytes: originalBytes.length },
    installed_pnpm: { path: sourcePath, sha256: hash(sourceBytes),
        serializer_line: source.slice(0, offset).split("\n").length, serializer_source: snippet },
    original, repaired,
    discovery: { source: discoveryPath, sha256: hash(discoveryBytes), identities: rows,
        original_zero_outcome_report: originalReportPath, original_zero_outcome_report_sha256: hash(originalReportBytes),
        static_identity_count: 26, runtime_literal_matches: matches.length, selected: matches,
        static_name_format: "Vitest list TestCase.fullName joins suites and title with ' > '",
        canonical_name_mapping: "Exact ancestorTitles + title mapping from the preserved zero-outcome runtime inventory",
        static_matcher_difference: "Static AST task.suite includes the file; runtime task.suite omits it. Collect the single file without a CLI name filter, then verify the identical runtime literal against canonical names.",
        actual_tests_executed: 0 } }, null, 2));

