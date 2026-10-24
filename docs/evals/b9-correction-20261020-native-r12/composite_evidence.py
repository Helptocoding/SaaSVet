"""Route retained backend/build and the completed r11 frontend prefix honestly."""
import json
import re
from pathlib import Path
import backend_resumption as backend
import completed_prefix as prefix

HERE=Path(__file__).resolve().parent
TREE_SHA=backend.NEW
SOURCE_TREE_SHA=backend.OLD
REUSED={label:backend.CAMPAIGN for label in backend.REUSED_LABELS}
REUSED.update({label:prefix.CAMPAIGN for label in prefix.LABELS})


def _require(condition,message):
    backend.require(condition,message)


def validate_references():
    result=backend.validate_references()
    result['completed_prefix']=prefix.validate_completed_prefix()
    return result


def validate_current_inputs():
    return backend.validate_current_inputs()


def source_for(label):
    if label in prefix.LABELS:return prefix.source_root()
    if label not in REUSED:return HERE
    with backend.legacy_context() as (legacy,_):
        return legacy.source_for(label) if label in legacy.REUSED else backend.source_root()


def _check_reference(path):
    root=backend.source_root()
    _require(path.resolve().is_relative_to(root.resolve()),'routed source outside retained backend bundle')
    relative=path.relative_to(root).as_posix();files=backend.manifest()['files']
    _require(relative in files and backend.sha(path)==files[relative]['sha256'],
        'routed retained backend artifact changed '+relative)
    return path


def _check_prefix(path):
    root=prefix.source_root()
    _require(path.resolve().is_relative_to(root.resolve()),'routed source outside retained r11 prefix')
    relative=path.relative_to(root).as_posix();files=prefix.manifest()['files']
    _require(relative in files and backend.sha(path)==files[relative]['sha256'],
        'routed retained prefix artifact changed '+relative)
    return path


def block_path(label,suffix):
    _require(isinstance(label,str) and re.fullmatch('[a-z0-9-]+',label) is not None,'invalid block label')
    _require(isinstance(suffix,str) and re.fullmatch(r'\.[a-zA-Z0-9_.-]+',suffix) is not None and '..' not in suffix,
        'invalid block suffix')
    if label in prefix.LABELS:
        if label=='frontend-test' and suffix=='.command.json':
            relative='blocks/frontend-test-assemble.command.json'
        elif label=='frontend-test' and suffix in ('.results.json','.json'):
            relative='blocks/frontend-tests.json'
        else:relative='blocks/'+label+suffix
        return _check_prefix(backend.safe(prefix.source_root(),relative))
    if label in REUSED:
        with backend.legacy_context() as (legacy,_):
            path=legacy.block_path(label,suffix)
        return _check_reference(path)
    return backend.safe(HERE,'blocks/'+label+suffix)


def read_block(label,suffix='.gate.json'):
    return json.loads(block_path(label,suffix).read_text(encoding='utf-8'))


def is_reused(label):
    return label in REUSED


def candidate_compatible(label,receipt_sha):
    if label in prefix.LABELS:
        _require(receipt_sha==TREE_SHA,'retained r11 prefix candidate differs')
    elif label in REUSED:
        with backend.legacy_context() as (legacy,_):
            if label in legacy.REUSED:legacy.candidate_compatible(label,receipt_sha)
            else:_require(receipt_sha==SOURCE_TREE_SHA,'retained backend receipt candidate differs')
    else:_require(receipt_sha==TREE_SHA,'current receipt candidate differs')
    return True


def provenance(label):
    if label in prefix.LABELS:
        root=prefix.source_root()
        result=dict(origin='REFERENCED_ADVISORY' if label=='frontend-lint' else 'REFERENCED_PASS',
            campaign=prefix.CAMPAIGN,artifactdir=str(root/'blocks'),
            tested_candidate_tree=TREE_SHA,accepted_candidate_tree=TREE_SHA,
            reference_manifest=prefix.MANIFEST,reference_manifest_sha256=backend.sha(HERE/prefix.MANIFEST),
            current_formal_runs=0,source_formal_runs=1,reused=True,current_test_runs=0,
            accepted_historical_evidence_limitation=True,continuous_campaign_claimed=False,
            source_formal_exit_code=2,source_stop_phase='security',source_gitleaks_executed=False)
        if label=='frontend-test':
            result.update(command_origin='REFERENCED_ASSEMBLER',
                command_receipt=str((root/'blocks/frontend-test-assemble.command.json').relative_to(HERE)),
                actual_source_case_command=str((root/'blocks/frontend-test-remainder.command.json').relative_to(HERE)),
                actual_source_case_json=str((root/'blocks/frontend-test-remainder.json').relative_to(HERE)),
                logical_result=str((root/'blocks/frontend-tests.json').relative_to(HERE)),
                retained_PASS=355,historical_r9_retained_PASS=354,historical_r11_new_PASS=1,
                original_timeout_and_exit_preserved=True,filtered_metadata_count=25,
                filtered_metadata_counted_as_acceptance_skips=False)
        else:
            result.update(command_origin='REFERENCED_EXECUTION',
                command_receipt=str((root/('blocks/'+label+'.command.json')).relative_to(HERE)))
        return result
    if label not in REUSED:
        return dict(origin='CURRENT',campaign=HERE.name,artifactdir=str(HERE/'blocks'),
            tested_candidate_tree=TREE_SHA,accepted_candidate_tree=TREE_SHA,
            command_origin='CURRENT',current_formal_runs=1,source_formal_runs=0)
    root=backend.source_root()
    with backend.legacy_context() as (legacy,_):
        prior=legacy.provenance(label)
    result=dict(origin='REFERENCED_PASS',campaign=backend.CAMPAIGN,
        artifactdir=str(source_for(label)/'blocks'),source_aggregate_directory=str(root/'blocks'),
        tested_candidate_tree=prior['tested_candidate_tree'],accepted_candidate_tree=TREE_SHA,
        accepted_source_candidate_tree=SOURCE_TREE_SHA,source_provenance=prior,
        frontend_equivalence='frontend-equivalence.json',reference_manifest=backend.MANIFEST,
        reference_manifest_sha256=backend.sha(HERE/backend.MANIFEST),
        accepted_historical_evidence_limitation=True,continuous_campaign_claimed=False,
        current_formal_runs=0,source_formal_runs=1,reused=True)
    if label=='full-general':
        result.update(command_origin='REFERENCED_ASSEMBLER',
            command_receipt=str((root/'blocks/full-general-assemble.command.json').relative_to(HERE)),
            full_general_scope='retained logical r9 case aggregate; original interrupted exits preserved',
            case_manifest=str((root/'case-resumption-manifest.json').relative_to(HERE)))
    elif label=='full':
        result.update(command_origin='REFERENCED_IN_PROCESS_AGGREGATE',
            aggregate_receipt=str((root/'blocks/full.aggregate.json').relative_to(HERE)),
            no_single_full_test_command_claimed=True)
    return result

