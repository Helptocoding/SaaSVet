"""Locate the first contradictions; preserve all samples and INVALID_RUN."""
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(OUT/'revision2'))
from clock_guard import Continuity,ClockInvalid,ns
d=OUT/'r2-04/authorized-r204-postcommit-base-20261007-0004';side=d.with_name(d.name+'-clock')
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
def iso_ns(s):
    main=s[:19];fraction=s[20:].rstrip('Z') if len(s)>20 and s[19]=='.' else ''
    dt=datetime.strptime(main,'%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    return int(dt.timestamp())*1000000000+int((fraction+'000000000')[:9])
contradictions=[];captures=[]
for role in ('ingress','planner_1','planner_2','sender'):
    rows=[json.loads(x) for x in (d/(role+'.jsonl')).read_text().splitlines()]
    state=Continuity();failure=None
    for row in rows:
        previous=[state.lo,state.hi]
        try:state.feed(row)
        except ClockInvalid as exc:
            failure=dict(role=role,error=str(exc),seq=row['seq'],monotonic_ns=row['monotonic_ns'],
                db_timestamp=row.get('db_timestamp'),previous_intersection_ns=previous,
                new_offset_ns=[ns(row['db_timestamp'])-row['end_ns'],ns(row['db_timestamp'])-row['start_ns']] if row['event']=='db_clock' else None,
                failed_intersection_ns=[state.lo,state.hi],
                journal=str((d/(role+'.jsonl')).relative_to(OUT)))
            contradictions.append(failure);break
    captures.append(dict(role=role,os_pid=rows[0]['os_pid'],total_rows=len(rows),
        calibrations=sum(r['event']=='db_clock' for r in rows),footer_present=rows[-1]['event']=='capture_end'))
events=[]
for e in read(side/'host-after.json')['events']:
    xml=ET.fromstring(e['xml']);n={'e':'http://schemas.microsoft.com/win/2004/08/events/event'}
    data={x.attrib['Name']:x.text for x in xml.findall('.//e:EventData/e:Data',n)}
    item=dict(provider=e['provider'],id=e['id'],record_id=e['record_id'],data=data)
    if 'OldTime' in data and 'NewTime' in data:
        item['observed_step_ns']=iso_ns(data['NewTime'])-iso_ns(data['OldTime'])
    events.append(item)
contradictions.sort(key=lambda x:x['monotonic_ns'])
r=dict(status='INVALID_RUN',first_observed_clock_contradiction=contradictions[0] if contradictions else None,
    all_participant_contradictions=contradictions,capture_completion=captures,system_events=events,
    source_conclusion='Host clock adjustment is directly recorded by Kernel-General event 1 and Time-Service records. DB/monotonic intersections contradict it in raw journals. No independent PostgreSQL-only or timestamp-replay correction was injected.',
    observed_input_attempts=len((d/'offers.jsonl').read_text().splitlines()),ordinary_offer_window_opened=(d/'observed-window.json').exists(),
    all_raw_samples_preserved=True,samples_excluded=0,segments_created=0,tolerance_added=False,timestamps_rewritten=False,
    base_changed=False,runtime_failure_inferred=False,
    next_requirement='Authorize a controlled evaluation-host time procedure before a new R2-04 repetition, preserving the original clock gate and without changing application runtime.',
    idle_guard='Acquired by conductor; restoration executes in context-manager finally. On the exception path the existing receipt omitted the success flag; do not manufacture it retroactively.')
with (d/'clock-incident-analysis.json').open('x',encoding='utf-8') as f:json.dump(r,f,indent=2)
print(json.dumps(dict(status=r['status'],first=r['first_observed_clock_contradiction'],steps_ns=[e['observed_step_ns'] for e in events if 'observed_step_ns' in e],ordinary_offer_window_opened=r['ordinary_offer_window_opened'])))
