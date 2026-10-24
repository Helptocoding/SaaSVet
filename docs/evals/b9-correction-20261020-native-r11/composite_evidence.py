"""Route retained PASS artifacts to r9; keep current command receipts in r10."""
import json
import re
from pathlib import Path
import backend_resumption as backend

HERE=Path(__file__).resolve().parent
TREE_SHA=backend.NEW
SOURCE_TREE_SHA=backend.OLD
REUSED={label:backend.CAMPAIGN for label in backend.REUSED_LABELS}


def _require(condition,message):
    backend.require(condition,message)


def validate_references():
    return backend.validate_references()


def validate_current_inputs():
    return backend.validate_current_inputs()


def source_for(label):
    if label not in REUSED:return HERE
    with backend.legacy_context() as (legacy,_):
        return legacy.source_for(label) if label in legacy.REUSED else backend.source_root()


def _check_reference(path):
    root=backend.source_root()
    _require(path.resolve().is_relative_to(root.resolve()),'routed source outside retained bundle')
    relative=path.relative_to(root).as_posix();files=backend.manifest()['files']
    _require(relative in files and backend.sha(path)==files[relative]['sha256'],
        'routed retained artifact changed '+relative)
    return path


def block_path(label,suffix):
    _require(isinstance(label,str) and re.fullmatch('[a-z0-9-]+',label) is not None,'invalid block label')
    _require(isinstance(suffix,str) and re.fullmatch(r'\.[a-zA-Z0-9_.-]+',suffix) is not None and '..' not in suffix,
        'invalid block suffix')
    if label in REUSED:
        with backend.legacy_context() as (legacy,_):
            path=legacy.block_path(label,suffix)
        return _check_reference(path)
    filename='frontend-test-assemble' if label=='frontend-test' and suffix=='.command.json' else label
    return backend.safe(HERE,'blocks/'+filename+suffix)


def read_block(label,suffix='.gate.json'):
    return json.loads(block_path(label,suffix).read_text(encoding='utf-8'))


def is_reused(label):
    return label in REUSED


def candidate_compatible(label,receipt_sha):
    if label in REUSED:
        with backend.legacy_context() as (legacy,_):
            if label in legacy.REUSED:legacy.candidate_compatible(label,receipt_sha)
            else:_require(receipt_sha==SOURCE_TREE_SHA,'retained receipt candidate differs')
    else:_require(receipt_sha==TREE_SHA,'current receipt candidate differs')
    return True


def provenance(label):
    if label not in REUSED:
        return dict(origin='CURRENT',campaign=HERE.name,artifactdir=str(HERE/'blocks'),
            tested_candidate_tree=TREE_SHA,accepted_candidate_tree=TREE_SHA,
            command_origin='CURRENT_ASSEMBLER' if label=='frontend-test' else 'CURRENT',
            current_formal_runs=1,source_formal_runs=0)
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

