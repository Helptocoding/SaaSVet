#!/usr/bin/env node
/* eslint-disable */
/**
 * url_construction.cjs — Frontend smoke gate Día 6 (ADR p18)
 *
 * 5 grep gates bloqueantes pre-cutover (ALLOW_LEGACY_ID_LOOKUP=False):
 *
 *  G1 — Cero fallback dual-lookup `editing.public_id || editing.id`.
 *  G2 — Cero `${x.id}` en URL templates de `src/api/*.js`.
 *  G3 — Cero `editing<X>.id` / `selected<X>.id` pasados como primer arg
 *       a funciones API HTTP (cross-HTTP path leak).
 *  G4 — Cero deep-link `?<modelo_publico>=${x.id}` en pages.
 *  G5 — Inventario warning: navegación a recursos públicos con `.id` literal.
 *       (warn-only: el patrón puede ser válido si el .id es del context,
 *       pero requiere revisión manual.)
 *
 * Uso: `node frontend/__smoke__/url_construction.cjs`
 *      Exit 0 = OK. Exit 1 = violations.
 *
 * Sin dependencias externas — solo `fs`/`path`. Corre en CI sin npm install.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'src');
const API_DIR = path.join(SRC, 'api');
const PAGES_DIR = path.join(SRC, 'pages');
const COMPONENTS_DIR = path.join(SRC, 'components');

const EXTS = new Set(['.js', '.jsx', '.ts', '.tsx']);
const PUBLIC_MODELS = [
  'pet', 'owner', 'appointment', 'medical_record',
  'invoice', 'prescription', 'product', 'presentation', 'service',
];
const PUBLIC_RESOURCES = [
  'pets', 'owners', 'appointments', 'medical-records',
  'billing/invoices', 'prescriptions', 'inventory/products',
  'inventory/presentations', 'billing/services', 'staff', 'vaccines',
];

// Funciones API que reciben ID en path como primer arg.
// Pasar `editingX.id` a estas funciones = PK leak cross-HTTP.
const ID_FIRST_ARG_FUNCS = [
  'updatePet', 'deletePet',
  'updateAppointment', 'deleteAppointment', 'updateAppointmentStatus',
  'assignPatient', 'getAppointmentHistory',
  'updateProduct', 'deleteProduct', 'adjustStock', 'adjustPresentationStock',
  'updatePresentation', 'deletePresentation',
  'getMedicalRecord', 'updateMedicalRecord', 'deleteMedicalRecord',
  'closeMedicalRecord', 'downloadMedicalRecordPdf',
  'getPrescription', 'updatePrescription', 'deletePrescription',
  'downloadPrescriptionPdf',
  'getInvoice', 'patchInvoice', 'confirmInvoice', 'payInvoice',
  'cancelInvoice', 'directPayInvoice', 'downloadInvoicePdf',
  'updateService', 'deleteService',
  'deactivateStaff',
  'updateVaccine', 'deleteVaccine',
];

function walk(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(full));
    } else if (EXTS.has(path.extname(entry.name))) {
      out.push(full);
    }
  }
  return out;
}

function readLines(file) {
  return fs.readFileSync(file, 'utf8').split(/\r?\n/);
}

function relativeFromRoot(file) {
  return path.relative(ROOT, file).replace(/\\/g, '/');
}

const violations = { G1: [], G2: [], G3: [], G4: [], G5: [] };

// --- G1: fallback dual-lookup en TODO frontend/src ---
{
  const RE = /\.public_id\s*\|\|\s*[A-Za-z_][\w]*\.id\b/;
  for (const file of walk(SRC)) {
    const lines = readLines(file);
    for (let i = 0; i < lines.length; i++) {
      if (RE.test(lines[i])) {
        violations.G1.push(`${relativeFromRoot(file)}:${i + 1}: ${lines[i].trim()}`);
      }
    }
  }
}

// --- G2: ${x.id} en URL templates de api/ ---
{
  // Match template literal segment con `${ident.id}` precedido por `/` o inicio
  // de literal — restringido a `.id` (no `.public_id`).
  const RE = /[`'"][^`'"]*\$\{[A-Za-z_][\w]*\.id\}/;
  for (const file of walk(API_DIR)) {
    const lines = readLines(file);
    for (let i = 0; i < lines.length; i++) {
      if (RE.test(lines[i])) {
        violations.G2.push(`${relativeFromRoot(file)}:${i + 1}: ${lines[i].trim()}`);
      }
    }
  }
}

// --- G3: editingX.id / selectedX.id / objX.id como primer arg a API ---
{
  const funcs = ID_FIRST_ARG_FUNCS.join('|');
  // Permite primer arg `token,` antes del id (callers actuales con auth manual).
  // Match: `<func>(<algo>, ?obj.id, ...)` o `<func>(obj.id, ...)`
  const RE = new RegExp(
    `\\b(?:${funcs})\\(\\s*(?:[A-Za-z_][\\w]*,\\s*)?([A-Za-z_][\\w]*)\\.id\\b`
  );
  // Excluye dirs ya cubiertos por otros gates si quieres, pero pages+components
  // son donde están los callers.
  const scanDirs = [PAGES_DIR, COMPONENTS_DIR];
  for (const dir of scanDirs) {
    for (const file of walk(dir)) {
      const lines = readLines(file);
      for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(RE);
        if (m) {
          violations.G3.push(`${relativeFromRoot(file)}:${i + 1}: ${lines[i].trim()}`);
        }
      }
    }
  }
}

// --- G4: deep-link `?<modelo>=${x.id}` ---
{
  const models = PUBLIC_MODELS.join('|');
  const RE = new RegExp(`\\?(?:${models})=\\$\\{[A-Za-z_][\\w]*\\.id\\}`);
  for (const file of walk(SRC)) {
    const lines = readLines(file);
    for (let i = 0; i < lines.length; i++) {
      if (RE.test(lines[i])) {
        violations.G4.push(`${relativeFromRoot(file)}:${i + 1}: ${lines[i].trim()}`);
      }
    }
  }
}

// --- G5: navigate("/recurso/<.id>") warn — audit manual ---
{
  const resources = PUBLIC_RESOURCES.map(r => r.replace(/\//g, '\\/')).join('|');
  // navigate/push/replace/Link to= con literal path + `${x.id}` (no .public_id)
  const RE = new RegExp(
    `(?:navigate|push|replace)\\(\\s*[\`'"]\\/(?:${resources})\\/\\$\\{[A-Za-z_][\\w]*\\.id\\}`
  );
  for (const file of walk(SRC)) {
    const lines = readLines(file);
    for (let i = 0; i < lines.length; i++) {
      if (RE.test(lines[i])) {
        violations.G5.push(`${relativeFromRoot(file)}:${i + 1}: ${lines[i].trim()}`);
      }
    }
  }
}

// ----------------------- Report -----------------------
const GATE_DESC = {
  G1: 'Fallback dual-lookup `.public_id || .id` (un identificador por superficie)',
  G2: '`${x.id}` en URL templates de src/api/ (PK leak cross-HTTP)',
  G3: 'PK como primer arg a funciones API HTTP (path leak)',
  G4: 'Deep-link `?<modelo_publico>=${x.id}` (query param PK leak)',
  G5: '`navigate("/recurso/${x.id}")` literal path con PK (path leak)',
};

let total = 0;
const lines = [];
for (const [gate, hits] of Object.entries(violations)) {
  if (hits.length === 0) continue;
  total += hits.length;
  lines.push(`\n[${gate}] ${GATE_DESC[gate]} — ${hits.length} match(es):`);
  for (const h of hits) lines.push(`  ${h}`);
}

if (total === 0) {
  console.log('url_construction.cjs — OK (5/5 gates verde, 0 matches)');
  process.exit(0);
}

console.error(
  `url_construction.cjs — FAIL (${total} violation(s) across ` +
  `${Object.values(violations).filter(v => v.length).length} gate(s))`
);
console.error(lines.join('\n'));
console.error(
  '\nADR p18: un identificador por superficie. UUID public_id ' +
  'en URLs/query params/deep links. PK solo en FK body fields.'
);
process.exit(1);
