// Parse JSX as data. This helper never imports or executes the application/test module.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const OLD_SHA = '8a98f6857430d5dee656e3b3ddc57a1bcecfd1f98a3c28f72cd328681d03961f';
const NEW_SHA = '21de54d2d3d1b1ad629b76aca48242249c22889c1cfb0962cabc529956a2ecd2';
const PARSER_SHA = '201724d1415df7749087d9d6e88af50f2bcafe2eb68dfbe9347f49d3361ff426';
const TITLE = 'un éxito antiguo A→B→A no borra un draft nuevo aunque tenga el mismo texto';
const TEXT = 'Texto idéntico, intención nueva';
const COMPOSERS = ['firstComposer', 'returnedComposer'];
const OMIT = new Set(['start', 'end', 'loc', 'extra', 'comments', 'leadingComments',
  'trailingComments', 'innerComments', 'tokens', 'errors']);
const digest = raw => crypto.createHash('sha256').update(raw).digest('hex');
const canonical = filename => fs.readFileSync(filename, 'utf8').replace(/\r\n/g, '\n');
const occurrenceCount = (source, statement) => source.split(statement).length - 1;
const originalStatement = composer => `await user.type(${composer}, "${TEXT}");`;
const correctedStatement = composer => `fireEvent.change(${composer}, { target: { value: "${TEXT}" } });`;

function walk(node, visit) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) {
    node.forEach(item => walk(item, visit));
    return;
  }
  if (typeof node.type === 'string') visit(node);
  for (const key of Object.keys(node)) {
    if (!OMIT.has(key)) walk(node[key], visit);
  }
}

function findTarget(ast) {
  const found = [];
  walk(ast, node => {
    if (node.type === 'CallExpression' && node.callee.type === 'Identifier' &&
        node.callee.name === 'it' && node.arguments[0]?.type === 'StringLiteral' &&
        node.arguments[0].value === TITLE) found.push(node);
  });
  assert.equal(found.length, 1, 'Target test must be uniquely identified');
  assert.equal(found[0].arguments.length, 2, 'No explicit timeout argument may be introduced');
  const callback = found[0].arguments[1];
  assert.equal(callback.type, 'ArrowFunctionExpression');
  assert.equal(callback.async, true);
  return callback;
}

function expectCount(callback) {
  let count = 0;
  walk(callback, node => {
    if (node.type === 'CallExpression' && node.callee.type === 'Identifier' && node.callee.name === 'expect') count += 1;
  });
  return count;
}

function normalized(ast, source, kind, callback) {
  const replacements = Object.fromEntries(COMPOSERS.map(composer => [composer, 0]));
  function convert(node) {
    if (!node || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map(convert);
    if (node.type === 'ExpressionStatement') {
      const statement = source.slice(node.start, node.end);
      for (const composer of COMPOSERS) {
        const wanted = kind === 'original' ? originalStatement(composer) : correctedStatement(composer);
        if (statement !== wanted) continue;
        assert(node.start >= callback.body.start && node.end <= callback.body.end,
          'Approved input setup must occur inside the target callback');
        if (kind === 'original') {
          assert.equal(node.expression.type, 'AwaitExpression');
          assert.equal(node.expression.argument.type, 'CallExpression');
        } else {
          assert.equal(node.expression.type, 'CallExpression');
        }
        replacements[composer] += 1;
        return { type: 'ApprovedCompleteValueInputSetup', composer, value: TEXT };
      }
    }
    return Object.fromEntries(Object.keys(node).filter(key => !OMIT.has(key)).sort()
      .map(key => [key, convert(node[key])]));
  }
  const result = convert(ast);
  assert.deepEqual(replacements, { firstComposer: 1, returnedComposer: 1 });
  return { ast: result, replacements };
}

function main() {
  assert.equal(process.argv.length, 5, 'Expected parser path, original JSX path and corrected JSX path');
  const [parserFile, originalFile, correctedFile] = process.argv.slice(2).map(filename => path.resolve(filename));
  assert.equal(digest(fs.readFileSync(parserFile)), PARSER_SHA);
  const parser = require(parserFile);
  const original = canonical(originalFile), corrected = canonical(correctedFile);
  assert.equal(digest(original), OLD_SHA);
  assert.equal(digest(corrected), NEW_SHA);
  let reconstructed = original;
  for (const composer of COMPOSERS) {
    const before = '        ' + originalStatement(composer);
    const after = '        ' + correctedStatement(composer);
    assert.equal(occurrenceCount(original, before), 1);
    assert.equal(occurrenceCount(corrected, after), 1);
    reconstructed = reconstructed.replace(before, after);
  }
  assert.equal(reconstructed, corrected, 'Only the two approved complete source statements may differ');
  const options = { sourceType: 'module', plugins: ['jsx'] };
  const originalAst = parser.parse(original, options), correctedAst = parser.parse(corrected, options);
  const oldCallback = findTarget(originalAst), newCallback = findTarget(correctedAst);
  assert.equal(expectCount(oldCallback), 8);
  assert.equal(expectCount(newCallback), 8);
  const before = normalized(originalAst, original, 'original', oldCallback);
  const after = normalized(correctedAst, corrected, 'corrected', newCallback);
  assert.deepEqual(before.ast, after.ast, 'The complete normalized module AST must be identical');
  process.stdout.write(JSON.stringify({ schema: 'b9-frontend-fixture-ast/1', state: 'PASS',
    parse_only: true, application_source_executed: false, application_tests_executed: false,
    normalized_complete_module_AST_identical: true, only_two_input_setup_statements_changed: true,
    original_replacements: before.replacements, corrected_replacements: after.replacements,
    test_expect_calls: 8, target_test_title: TITLE, target_test_argument_count: 2,
    original_default_timeout_ms: 5000, explicit_timeout_argument_added: false,
    imports_hooks_test_ids_other_AST_unchanged: true, exact_approved_source_substitution_only: true,
    original_canonical_sha256: OLD_SHA, corrected_canonical_sha256: NEW_SHA,
    parser_sha256: PARSER_SHA, normalized_AST_sha256: digest(JSON.stringify(before.ast)),
    ignored_metadata_keys: [...OMIT].sort() }) + '\n');
}

main();
