"""Read only extraction where untracked evaluation sources are not indexed."""
import ast
import json
from common import ROOT, PRIOR, read, save, sha

targets={
    ROOT/'backend/apps/agent/services.py':['_extend_quiet_window'],
    ROOT/'backend/apps/agent/tests/scheduling_characterization/execution.py':['offer','queued_samples','participants'],
    PRIOR/'revision2/evaluation_provider.py':['request'],
}
result={}
for path,names in targets.items():
    source=path.read_text(encoding='utf-8-sig')
    rows=source.splitlines()
    found=[]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names:
            found.append({'name':node.name,'line':node.lineno,'end_line':node.end_lineno,
                          'source':'\n'.join(rows[node.lineno-1:node.end_lineno])})
    result[str(path.relative_to(ROOT))]={'sha256':sha(path),'symbols':found}
save('source-extracts.json',result)
for path,entry in result.items():
    if path.endswith(('execution.py','services.py')):
        print(path,json.dumps(entry,ensure_ascii=False))
