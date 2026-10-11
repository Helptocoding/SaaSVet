"""Seal evidence and compare protected sources before any lab cleanup."""
import json
from lab_control import HERE,lab


def seal_attempts():
    manifests=[]
    for folder in HERE.iterdir():
        if not folder.is_dir() or not (folder/'execution-receipt.json').exists():continue
        if (folder/'job.json').exists():
            job=json.loads((folder/'job.json').read_text())
            archive=json.loads((folder/'execution-source-archive.json').read_text())
            if archive!=job['evaluation_source_hashes']:
                raise RuntimeError('EXECUTION_SOURCE_ARCHIVE_MANIFEST_CHANGED:'+folder.name)
            if any(lab.sha(folder/'execution-sources'/name)!=sha for name,sha in archive.items()):
                raise RuntimeError('EXECUTION_SOURCE_ARCHIVE_CONTENT_CHANGED:'+folder.name)
        target=folder/'attempt-artifact-index.json'
        if target.exists():
            old=json.loads(target.read_text())
            if any(lab.sha(folder/name)!=entry['sha256'] for name,entry in old.items()):
                raise RuntimeError('SEALED_ATTEMPT_ARTIFACT_CHANGED:'+folder.name)
        else:
            contents={p.relative_to(folder).as_posix():dict(sha256=lab.sha(p),bytes=p.stat().st_size)
                for p in folder.rglob('*') if p.is_file() and p.suffix!='.pyc' and p!=target}
            lab.write(target,contents)
        manifests.append(str(target.relative_to(HERE)))
    return manifests


if __name__=='__main__':
    now=lab.integrity()
    initial=json.loads((HERE/'initial-integrity.json').read_text())
    if (now['protected_sources']!=initial['protected_sources']
            or now['previous_evidence']!=initial['previous_evidence'] or now['head']!=initial['head']):
        lab.write(HERE/'precleanup-integrity-failure.json',dict(current=now,initial=initial))
        raise RuntimeError('PROTECTED_INTEGRITY_FAILED_PRESERVE_LAB')
    manifests=seal_attempts()
    lab.write(HERE/'precleanup-integrity.json',dict(protected_sources=len(now['protected_sources']),
        previous_evidence_unchanged=True,baseline=now['head'],attempt_manifests=manifests,
        status='INTACT',evidence_sealed_before_cleanup=True))
    print('PROTECTED_INTEGRITY_INTACT_AND_ATTEMPTS_SEALED',flush=True)
