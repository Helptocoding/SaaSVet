from pathlib import Path
import json,collections,shutil,time
p=Path('docs/evals/b9-correction-20261014-r3')
active=[];commands={};last_completed={}
for f in (p/'blocks').glob('*.command.json') if (p/'blocks').exists() else []:
 d=json.loads(f.read_text());commands[d['label']]=d['state']
 if d['state']=='RUNNING':active.append(d['label'])
gates={f.name.split('.')[0]:json.loads(f.read_text())['state'] for f in (p/'blocks').glob('*.gate.json')} if (p/'blocks').exists() else {}
def last_row(path):
 with path.open('rb') as s:s.seek(0,2);size=s.tell();s.seek(max(0,size-8192));raw=s.read()
 return json.loads(raw.rsplit(b'\n',1)[0].splitlines()[-1])
host=last_row(p/'resource-observer/samples.jsonl');awake=last_row(p/'awake-request/heartbeat.jsonl')
counts={}
for label in ['directed','b0','b3','b4','b5','full']:
 f=p/'blocks'/(label+'.ids.jsonl')
 if f.exists():
  rows=[json.loads(s) for s in f.read_text().splitlines()]
  counts[label]=dict(collections.Counter(row['outcome'] for row in rows))
  if rows:last_completed[label]=rows[-1]['id']
f=p/'blocks/directed.results.passed.jsonl'
if f.exists():
 rows=[json.loads(s) for s in f.read_text().splitlines()]
 counts['directed']={'ok':len(rows)}
 if rows:last_completed['directed']=rows[-1]['test_id']
print(json.dumps({'formal':json.loads((p/'invocation-formal.json').read_text())['state'],'preflight':json.loads((p/'preflight.json').read_text())['state'] if (p/'preflight.json').exists() else None,'seal_files':len(json.loads((p/'evaluation-seal.json').read_text())['files']) if (p/'evaluation-seal.json').exists() else None,'active':active,'counts':counts,'last_completed_in_active_block':{label:last_completed.get(label) for label in active},'gates':gates,'host_free_GiB':round(host['physical_available']/1024**3,2),'C_free_GiB':round(shutil.disk_usage('C:/').free/1024**3,2),'awake_age':round(time.time()-awake['utc_epoch_seconds'],2),'STOP':json.loads((p/'STOP.json').read_text()) if (p/'STOP.json').exists() else None}))
