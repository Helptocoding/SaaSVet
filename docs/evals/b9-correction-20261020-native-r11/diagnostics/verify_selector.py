"""Pre-seal selector proof: Windows argv echo and static Vitest discovery only."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
EVIDENCE=HERE.parent
sys.path.insert(0,str(EVIDENCE))
from native_support import TREE, NODE, PNPM, RTK, SHA, environment

TARGET_FILE='src/pages/inbox/index.test.jsx'
TARGET_NAME='Inbox — aislamiento del borrador un éxito antiguo A→B→A no borra un draft nuevo aunque tenga el mismo texto'
CANDIDATE='f5f18d71847a46d66644775cd90d30268f072e3b'
SOURCE_SHA='21de54d2d3d1b1ad629b76aca48242249c22889c1cfb0962cabc529956a2ecd2'
RECEIPT=HERE/'selector-discovery-check.json'
RAW=HERE/'selector-static-discovery.json'
SELECTION=HERE/'selection-discovery.json'
PLANNED=HERE/'planned-selector.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,data,exclusive=False):
    with path.open('x' if exclusive else 'w',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(data,indent=2,ensure_ascii=False)+'\n')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def planned_selector():
    """Inspect only AST/data; never import the frontend runner or call run()."""
    helper=EVIDENCE/'frontend_resumption.py'
    source=helper.read_text(encoding='utf-8')
    tree=ast.parse(source,filename=str(helper))
    constants={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            if node.targets[0].id in ('TARGET_FILE','TARGET_NAME','RAW_REMAINDER'):
                constants[node.targets[0].id]=ast.literal_eval(node.value)
    assert constants==dict(TARGET_FILE=TARGET_FILE,TARGET_NAME=TARGET_NAME,
        RAW_REMAINDER='blocks/frontend-test-remainder.json')
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='run']
    assert len(functions)==1
    assignments={node.targets[0].id:node.value for node in functions[0].body
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)}
    expected_pattern=ast.parse("'^' + TARGET_NAME + '$'",mode='eval').body
    expected_argv=ast.parse("[str(RTK), 'proxy', str(NODE), str(PNPM), 'run', 'test', TARGET_FILE, "
        "'--testNamePattern', pattern, '--reporter=default', '--reporter=json', "
        "'--outputFile=' + str(HERE / RAW_REMAINDER)]",mode='eval').body
    normalize=lambda node:ast.dump(node,include_attributes=False)
    assert normalize(assignments['pattern'])==normalize(expected_pattern), 'Runtime pattern AST differs'
    assert normalize(assignments['argv'])==normalize(expected_argv), 'Runtime argv AST differs'
    expected_run=ast.parse("subprocess.run(argv, cwd=TREE / 'frontend', env=environment(), "
        "stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)",mode='eval').body
    assert normalize(assignments['result'])==normalize(expected_run), 'Runtime invocation AST differs'
    selected=EVIDENCE/'frontend-remainder-selected.json'
    assert read(selected)==[dict(file=TARGET_FILE,fullName=TARGET_NAME)]
    assert not (EVIDENCE/'frontend-remainder-selection.json').exists(), 'Formal run already created its receipt'
    literal='^'+TARGET_NAME+'$'
    planned=dict(state='PLANNED_SELECTOR_VERIFIED_BY_STATIC_AST',actual_tests_executed=0,
        formal_run_invoked=False,source_helper=helper.name,source_helper_sha256=sha(helper),
        selected_inventory=selected.name,selected_inventory_sha256=sha(selected),
        argv=[str(RTK),'proxy',str(NODE),str(PNPM),'run','test',TARGET_FILE,
            '--testNamePattern',literal,'--reporter=default','--reporter=json',
            '--outputFile='+str(EVIDENCE/constants['RAW_REMAINDER'])],
        cwd=str(TREE/'frontend'),identity=dict(file=TARGET_FILE,fullName=TARGET_NAME),
        runtime_pattern_and_argv_AST_match=True,test_timeout_override=False,retries_added=False,
        pool_or_concurrency_changed=False,default_timeout_preserved_ms=5000,previous_PASS_cases_selected=0)
    save(PLANNED,planned,exclusive=True)
    return helper,selected


def run(label,args):
    argv=[str(RTK),'proxy',*map(str,args)]
    stdout=HERE/(label+'.stdout.log');stderr=HERE/(label+'.stderr.log')
    target=HERE/(label+'.command.json')
    info=dict(state='RUNNING',argv=argv,cwd=str(TREE/'frontend'),
        actual_tests_executed=0,application_test_functions_invoked=False,
        utc_started=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    save(target,info,exclusive=True);started=time.monotonic()
    with stdout.open('xb') as out,stderr.open('xb') as err:
        result=subprocess.run(argv,cwd=TREE/'frontend',env=environment(),stdin=subprocess.DEVNULL,
            stdout=out,stderr=err,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    info.update(state='COMPLETED',exit_code=result.returncode,seconds=time.monotonic()-started,
        stdout=stdout.name,stderr=stderr.name,stdout_sha256=sha(stdout),stderr_sha256=sha(stderr))
    save(target,info)
    assert result.returncode==0,label+' failed; see retained stdout/stderr'
    return info,stdout,stderr


def main():
    assert sys.platform=='win32' and SHA==CANDIDATE
    assert not (EVIDENCE/'evaluation-seal.json').exists()
    assert not (EVIDENCE/'invocation-formal.json').exists(), 'Selector discovery is pre-seal only'
    assert not RECEIPT.exists() and not RAW.exists() and not SELECTION.exists() and not PLANNED.exists()
    literal='^'+TARGET_NAME+'$'
    assert not any(char in '\\^$.*+?()[]{}|' for char in TARGET_NAME)
    old=EVIDENCE.with_name('b9-correction-20261020-native-r10')
    old_selection=old/'frontend-remainder-selection.json'
    old_report=old/'blocks/frontend-test-remainder.json'
    runtime_helper,selected_inventory=planned_selector()
    candidate_source=TREE/'frontend'/TARGET_FILE
    assert sha(candidate_source)==SOURCE_SHA
    dist=TREE/'frontend/node_modules/vitest/dist/chunks'
    cli=dist/'cac.C9xsMMkH.js';api=dist/'cli-api.BfdDOPPI.js'
    runner=TREE/'frontend/node_modules/@vitest/runner/dist/chunk-artifact.js'
    text_cli=cli.read_text(encoding='utf-8');text_api=api.read_text(encoding='utf-8')
    text_runner=runner.read_text(encoding='utf-8')
    assert 'cli.command("list [...filters]"' in text_cli
    assert 'staticParse: options.staticParse' in text_cli
    assert 'if (options?.staticParse) return {' in text_api
    assert 'testModules: await this.experimental_parseSpecifications(files,' in text_api
    assert 'getTaskFullName(t).match(namePattern)' in text_runner
    assert 'delete collector.suite;' in text_runner
    assert 'let lastSuite = file;' in text_api and 'suite: latestSuite,' in text_api
    assert 'name: test.fullName,' in text_api and 'file: test.module.moduleId' in text_api
    assert read(TREE/'frontend/node_modules/vitest/package.json')['version']=='4.1.8'
    inputs={str(path):sha(path) for path in (Path(__file__),HERE/'verify_selector.cjs',old_selection,old_report,
        PLANNED,runtime_helper,selected_inventory,candidate_source,cli,api,runner)}
    receipt=dict(state='RUNNING',candidate_tree=SHA,actual_tests_executed=0,
        authorized_identity=dict(file=TARGET_FILE,fullName=TARGET_NAME),
        runtime_literal_pattern=literal,expected_static_file_identities=26,
        discovery_mode='pnpm exec vitest list --staticParse, never pnpm run test',
        discovery_name_filter=None,
        static_runtime_matcher_difference='Static task parent chain includes the file; runtime omits it. Collect exact file without name filter, then prove identical runtime literal selects one canonical identity.',
        planned_selector=PLANNED.name,planned_selector_sha256=sha(PLANNED),
        formal_run_receipt_required=False,frontend_run_imported_or_invoked=False,
        inputs_sha256=inputs,commands=[],
        source_assertions_hooks_timeouts_modified=False,previous_PASS_cases_executed=0)
    save(RECEIPT,receipt,exclusive=True)
    try:
        discovery,_,_=run('selector-static-discovery',[NODE,PNPM,'exec','vitest','list',TARGET_FILE,
            '--staticParse','--json',RAW.as_posix()])
        receipt['commands'].append(discovery);save(RECEIPT,receipt)
        assert RAW.is_file(), 'Static Vitest list did not emit its JSON inventory'
        raw=read(RAW)
        assert isinstance(raw,list) and len(raw)==26
        pure,out,err=run('selector-windows-argv-proof',[NODE,HERE/'verify_selector.cjs',PNPM,
            old_selection,RAW,old_report])
        receipt['commands'].append(pure);save(RECEIPT,receipt)
        proof=read(out)
        assert proof['state']=='PASS' and proof['actual_tests_executed']==0
        assert proof['target']==dict(file=TARGET_FILE,fullName=TARGET_NAME)
        assert proof['original']['matches_original_identity'] is False
        assert proof['repaired']['input_pattern']==proof['repaired']['received_pattern']==literal
        assert proof['repaired']['pattern_preserved'] and proof['repaired']['matches_original_identity']
        result=proof['discovery']
        assert result['actual_tests_executed']==0 and result['static_identity_count']==26
        assert result['runtime_literal_matches']==1 and len(result['selected'])==1
        assert result['selected'][0]['file']==TARGET_FILE and result['selected'][0]['fullName']==TARGET_NAME
        unchanged={path:sha(Path(path))==wanted for path,wanted in inputs.items()}
        assert all(unchanged.values()), 'Input changed during static selector proof'
        save(SELECTION,dict(state='EXACT_ONE_RUNTIME_IDENTITY_FROM_STATIC_COLLECTION',
            candidate_tree=SHA,actual_tests_executed=0,static_rows=raw,
            canonical_identities=result['identities'],selected=result['selected'],
            literal_pattern=literal,source=RAW.name,source_sha256=sha(RAW)),exclusive=True)
        receipt.update(state='PASS',finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            actual_tests_executed=0,static_collected=26,matched_runtime_identity=1,
            original_windows_pattern_matches=False,repaired_windows_pattern_matches=True,
            selected=result['selected'],inputs_unchanged=unchanged,
            static_discovery_json=RAW.name,static_discovery_sha256=sha(RAW),
            selection_discovery_json=SELECTION.name,selection_discovery_sha256=sha(SELECTION),
            pure_windows_argv_proof=proof,
            candidate_test_file_unchanged=True,preformal_only=True,
            application_test_functions_invoked=False)
        save(RECEIPT,receipt)
        print('SELECTOR_DISCOVERY_PASS_ZERO_TESTS_EXECUTED',flush=True)
    except BaseException as error:
        receipt.update(state='NONPASS',error_type=type(error).__name__,error=str(error),
            actual_tests_executed=0,application_test_functions_invoked=False)
        save(RECEIPT,receipt)
        raise


if __name__=='__main__':main()

