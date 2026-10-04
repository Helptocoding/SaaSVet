"""Read-only comparison with the authorized baseline; no acceptance decision."""
import ast
import hashlib
import io
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASELINE = '66702168439b9841a2c988238638a42e6aaee43d'
CHANGED = {'backend/apps/agent/durable.py', 'backend/apps/agent/services.py',
           'backend/apps/agent/worker.py'}


def git(*args):
    return subprocess.check_output(['rtk', 'proxy', 'git', *args], cwd=ROOT)


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def blobs(paths):
    requested = ''.join(BASELINE+':'+path+'\n' for path in paths).encode()
    output = subprocess.run(['rtk','proxy','git','cat-file','--batch'], cwd=ROOT,
        input=requested, stdout=subprocess.PIPE, check=True).stdout
    stream = io.BytesIO(output)
    result = {}
    for path in paths:
        header = stream.readline().split()
        assert len(header) == 3 and header[1] == b'blob', path
        result[path] = stream.read(int(header[2]))
        assert stream.read(1) == b'\n'
    return result


def function(source, name):
    tree = ast.parse(source)
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


class RemoveObservationHooks(ast.NodeTransformer):
    """Remove only the explicitly added observational expressions, not logic."""
    def visit_ImportFrom(self, node):
        if node.module is None and node.level == 1 and len(node.names) == 1:
            alias = node.names[0]
            if (alias.name, alias.asname) == ('claim_diagnostics','claim_trace'):
                return None
        return node

    def visit_FunctionDef(self, node):
        node = self.generic_visit(node)
        node.decorator_list = [d for d in node.decorator_list if not (
            isinstance(d, ast.Attribute) and isinstance(d.value, ast.Name) and
            d.value.id == 'claim_trace' and d.attr == 'database_clock') and not (
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and
            isinstance(d.func.value, ast.Name) and d.func.value.id == 'claim_trace'
            and d.func.attr == 'observed')]
        return node

    def visit_Expr(self, node):
        call = node.value
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and
                isinstance(call.func.value, ast.Name) and call.func.value.id == 'claim_trace' and
                call.func.attr in ('persisted','deadline','members','existing_work','bound')):
            return None
        return self.generic_visit(node)

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == 'member_ids':
                assert ast.unparse(node.value) in ('None', 'context.inbound_ids')
                return None
            if node.targets[0].id == 'affected':
                assert ast.unparse(node.value) == 'pending.update(available_at=target)'
                return ast.Expr(value=node.value)
        return node

    def visit_Call(self, node):
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and
                node.func.value.id == 'claim_trace' and node.func.attr == 'select_candidates'):
            assert [ast.unparse(arg) for arg in node.args] == [
                '_pending_conversation_candidates', 'now', 'attempted'] and not node.keywords
            return ast.Call(func=ast.Name(id='list', ctx=ast.Load()), args=[ast.Call(
                func=node.args[0], args=node.args[1:], keywords=[])], keywords=[])
        return self.generic_visit(node)


def main():
    paths = git('ls-tree', '-r', '--name-only', BASELINE).decode().splitlines()
    protected = [p for p in paths if p.startswith((
        'docs/evals/profile-beta-1-e4-2026-10-01/',
        'docs/evals/profile-beta-1-e4-sql-2026-10-02/',
        'backend/apps/agent/', 'backend/apps/channels/', 'backend/config/')) and p not in CHANGED]
    mismatches = []
    records = {}
    baseline_blobs = blobs(protected+sorted(CHANGED))
    for path in protected:
        expected = digest(baseline_blobs[path])
        actual = digest((ROOT/path).read_bytes())
        records[path] = actual
        if expected != actual:
            mismatches.append(path)
    old_worker = baseline_blobs['backend/apps/agent/worker.py'].decode('utf-8')
    new_worker = (ROOT/'backend/apps/agent/worker.py').read_text(encoding='utf-8')
    before = ast.dump(function(old_worker, '_pending_conversation_candidates'), include_attributes=False)
    after = ast.dump(function(new_worker, '_pending_conversation_candidates'), include_attributes=False)
    assert before == after and not mismatches, mismatches
    functional_ast = {}
    for path in sorted(CHANGED):
        old = ast.dump(ast.parse(baseline_blobs[path]), include_attributes=False)
        new = ast.dump(RemoveObservationHooks().visit(ast.parse(
            (ROOT/path).read_text(encoding='utf-8'))), include_attributes=False)
        functional_ast[path] = old == new
        assert old == new, path
    receipt = dict(baseline=BASELINE, protected_files=len(records), mismatches=mismatches,
        selector_ast_identical=True, functional_ast_after_removing_named_hooks=functional_ast,
        threshold_seconds=10, historical_PROFILE_BETA_1='FAIL',
        historical_B9E='FAIL', B9='IN_PROGRESS',
        later_2026_10_02_evaluation='PRESERVED_WITHOUT_RECLASSIFICATION',
        profile_executed=False, source_hashes_normalized_lf=records,
        modified_existing_runtime=sorted(CHANGED))
    (OUT/'source-integrity.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k != 'source_hashes_normalized_lf'}))


if __name__ == '__main__':
    main()
