const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { transform } = require('C:/Users/LAP/Desktop/LandingSaaS/frontend/node_modules/@astrojs/compiler/dist/node/index.cjs');
(async () => {
  const root = path.resolve(__dirname, '../../..');
  const filename = path.join(root, 'docs/compliance/inbox-privacy-review-2026-10-22/aviso-de-privacidad.astro');
  const source = fs.readFileSync(filename, 'utf8');
  const result = await transform(source, { filename });
  const errors = result.diagnostics.filter(item => item.severity === 1);
  const receipt = {
    state: errors.length ? 'FAIL' : 'PASS',
    check: 'Astro compiler transform: syntax only; no landing build or publication',
    sha256: crypto.createHash('sha256').update(source).digest('hex'),
    diagnostics: result.diagnostics,
    published: false,
    legalDocumentPromoted: false,
  };
  fs.writeFileSync(path.join(__dirname, 'privacy-syntax.json'), JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ state: receipt.state, diagnostics: result.diagnostics.length }));
  process.exitCode = errors.length ? 1 : 0;
})().catch(error => { console.error(error.message); process.exitCode = 1; });
