"""Refresh the isolated test tree after the new, bounded assertion correction."""
import json
from prepare_wsl import EVIDENCE, TREE, SHA, save, run, sha256, integrity

def main():
    candidate=json.loads((EVIDENCE/'candidate.json').read_text())
    assert candidate['candidate_tree']==SHA
    for name in candidate['changed_paths']:
        (TREE/name).write_bytes(run('git','show',SHA+':'+name))
    manifest=json.loads((EVIDENCE/'candidate-sources.json').read_text())
    for row in manifest['files']:
        if row['path'] in candidate['changed_paths']:
            content=(TREE/row['path']).read_bytes()
            row.update(sha256=sha256(content),bytes=len(content),git_blob=run('git','rev-parse',SHA+':'+row['path']).decode().strip())
    manifest['candidate_sha']=SHA
    manifest['archive_sha256']=sha256(run('git','archive','--format=tar',SHA))
    save('candidate-sources.json',manifest)
    assembly=json.loads((EVIDENCE/'assembly.json').read_text());assembly['candidate_sha']=SHA
    save('assembly.json',assembly)
    prepared=json.loads((EVIDENCE/'prepared.json').read_text());prepared['candidate_sha']=SHA
    save('prepared.json',prepared)
    # Re-freeze the changed receipt adapter and exact new test tree.
    seal=json.loads((EVIDENCE/'diagnostic-seal.json').read_text())
    from pathlib import Path
    seal['files']={name:sha256(Path(name).read_bytes()) for name in seal['files']}
    save('diagnostic-seal.json',seal)
    integrity('before-focused-attempt2')
    print('FOCUSED_CANDIDATE_REFRESHED')

if __name__=='__main__':main()
