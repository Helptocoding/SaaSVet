"""Optional receipts for this instrumentation suite, synthetic IDs only."""
import json
import os
from pathlib import Path


def save(name, journals, report, samples=()):
    directory = os.environ.get('E4_TRACE_EVIDENCE_DIR')
    if not directory:
        return
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    for index, journal in enumerate(journals):
        with (root / f'{name}-{index}.jsonl').open('x', encoding='utf-8') as stream:
            for row in journal:
                stream.write(json.dumps(row)+'\n')
    with (root / f'{name}-report.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    if samples:
        with (root / f'{name}-waits.jsonl').open('x', encoding='utf-8') as stream:
            for row in samples:
                stream.write(json.dumps(row)+'\n')


def save_equivalence(name, outputs):
    directory = os.environ.get('E4_TRACE_EVIDENCE_DIR')
    if not directory:
        return
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    with (root / f'{name}-equivalence.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(classification='DIAGNOSTIC_ONLY', on_off_equal=outputs[0] == outputs[1],
            off=outputs[0], on=outputs[1], sql_representation='SHA256 of statement shape; no params'),
            stream, indent=2)
        stream.write('\n')
