"""Read retained one-second observations within actual command intervals."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
GIB=1024**3

def main():
    target=HERE/'resource-observation-validation.json'
    assert not target.exists()
    raw=(HERE/'resource-observer/samples.jsonl').read_bytes()
    complete=raw.rsplit(b'\n',1)[0]+b'\n'
    samples=[json.loads(line) for line in complete.splitlines()]
    commands={};violations={}
    for path in sorted((HERE/'blocks').glob('*.command.json')):
        command=json.loads(path.read_text());assert command['state']=='COMPLETED'
        start=command['resources_before']['host']['utc_epoch_seconds']
        end=command['resources_after']['host']['utc_epoch_seconds']
        observed=[s for s in samples if start<=s['utc_epoch_seconds']<=end]
        assert observed,path.name
        label=command['label']
        monitor=json.loads((HERE/('monitor-'+label+'.json')).read_text())
        low=[s for s in observed if s['physical_available']<2*GIB]
        commands[label]={'utc_epoch_start':start,'utc_epoch_end':end,'host_samples':len(observed),
            'minimum_host_available_bytes':min(s['physical_available'] for s in observed),
            'host_samples_below_execution_reserve':len(low),
            'minimum_controller_cached_host_bytes':min(s['host']['physical_available'] for s in monitor),
            'minimum_guest_available_bytes':min(s['guest']['physical_available'] for s in monitor),
            'minimum_backing_disk_available_bytes':min(s['guest']['disk_available'] for s in monitor),
            'maximum_absolute_clock_skew_seconds':max(abs(s['wall_minus_monotonic_seconds']) for s in monitor)}
        if low:violations[label]=low
    first=min(c['utc_epoch_start'] for c in commands.values())
    last=max(c['utc_epoch_end'] for c in commands.values())
    before=[s for s in samples if s['utc_epoch_seconds']<first]
    after=[s for s in samples if s['utc_epoch_seconds']>last]
    data={'state':'PENDING_RESOURCE_RESERVE_BREACH' if violations else 'PASS_AS_SAMPLED',
        'commands':commands,'execution_reserve_violations':violations,
        'observation_frequency_seconds':1,'memory_reserve_bytes':2*GIB,'disk_reserve_bytes':GIB,
        'clock_limit_seconds':1,'observed_complete_prefix_bytes':len(complete),
        'observed_complete_prefix_sha256':hashlib.sha256(complete).hexdigest(),
        'pre_execution_low_samples':sum(s['physical_available']<2*GIB for s in before),
        'pre_execution_minimum_host_bytes':min(s['physical_available'] for s in before),
        'post_execution_low_samples':sum(s['physical_available']<2*GIB for s in after),
        'post_execution_minimum_host_bytes':min(s['physical_available'] for s in after) if after else None,
        'limits':'Sampled execution intervals only; preparatory/post-execution lows disclosed separately; no continuous millisecond guarantee'}
    target.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'state':data['state'],'commands_checked':len(commands),
        'execution_violation_labels':list(violations),
        'minimum_execution_host_GiB':min(c['minimum_host_available_bytes'] for c in commands.values())/GIB,
        'pre_execution_low_samples':data['pre_execution_low_samples'],
        'post_execution_low_samples':data['post_execution_low_samples']}))

if __name__=='__main__':main()
