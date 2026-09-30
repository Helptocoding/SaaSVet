"""Consolidate E4 diagnostic receipts and selection decisions, readonly."""
import argparse
import json
import hashlib
from collections import Counter, defaultdict
from pathlib import Path
import psycopg


def summarize(root, output, port=35440):
    variants = ('baseline', 'baseline-120', 'no-noisy', 'fast-provider', 'batch-3', 'poll-01', 'efficient', 'fair')
    result = dict(schema='e4-summary-v1', classification='DIAGNOSTIC_ONLY', variants={})
    for variant in variants:
        stem = 'e4-diagnostic-' + variant
        path = root / (stem + '.analysis.json')
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        receipt = json.loads((root / (stem + '.json')).read_text(encoding='utf-8'))
        organizations = receipt['fixture_organization_ids']
        with psycopg.connect(host='127.0.0.1', port=port, dbname='test_e4_' + variant.replace('-', '_'),
                user='e4', autocommit=True) as conn:
            mapping = dict(conn.execute('SELECT id, organization_id FROM agent_conversation').fetchall())
            scopes = conn.execute('SELECT count(*) FROM agent_turnwork w JOIN agent_conversation c ON c.id=w.conversation_id WHERE w.organization_id<>c.organization_id').fetchone()[0]
        decisions = []
        for role in ('planner-1', 'planner-2'):
            journal = root / (stem + '-' + role + '.timing.json')
            events = json.loads(journal.read_text(encoding='utf-8'))['events']
            polls = [e for e in events if e['event'] == 'poll']
            for i, poll in enumerate(polls):
                after = polls[i+1]['time'] if i+1 < len(polls) else float('inf')
                ce = [e for e in events if poll['time'] <= e['time'] < after]
                candidates = [organizations.index(mapping[e['conversation']]) for e in ce
                    if e['event'] == 'candidate_selected']
                claimable_healthy = sum(poll['queue'].get(str(org), {}).get('claimable', 0)
                    for org in organizations[:2])
                processed = next((e['processed'] for e in ce if e['event'] == 'poll_end'), None)
                decisions.append(dict(time=poll['time'], role=role, healthy_claimable=claimable_healthy,
                    candidate_organizations=candidates, processed=processed,
                    misses=sum(e['event'] == 'claim_miss' for e in ce)))
        eligible = [d for d in decisions if d['healthy_claimable']]
        queue_max = defaultdict(Counter)
        for item in data['queue_timeline']:
            for org, counts in item['queue'].items():
                role = organizations.index(int(org))
                for metric, value in counts.items():
                    queue_max[role][metric] = max(queue_max[role][metric], value)
        result['variants'][variant] = dict(claim=data['distributions']['persisted_to_claim'],
            eligible_delay=data['distributions'].get('eligible_delay'), service=data['service'],
            polling=data['polling'], critical=dict(data['critical'], cross_tenant_work=scopes),
            profile_overrides=receipt['e4_overrides'], measurement_seconds=receipt['measurement_seconds'],
            query_execution_ms=data['query_plan'][0]['Execution Time'],
            eligibility_extensions=sum(s.get('eligibility_extended_after_observation', False)
                for s in data['timing_samples'] if s['ordinary'] and s['organization'] < 2),
            selection=dict(polls_with_healthy_claimable=len(eligible),
                noisy_selected_while_healthy_claimable=sum(2 in d['candidate_organizations'] for d in eligible),
                zero_progress_with_healthy_claimable=sum(d['processed'] == 0 for d in eligible),
                misses=sum(d['misses'] for d in decisions)),
            queue_max=dict(queue_max), decisions=decisions)
    files = sorted(p for p in root.glob('e4-*') if p.is_file() and p != output)
    result['sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({v: dict(claim=d['claim'], selection=d['selection'],
        extensions=d['eligibility_extensions']) for v,d in result['variants'].items()}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=35440)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError('Refusing to overwrite evidence')
    summarize(args.directory, args.output, args.port)


if __name__ == '__main__':
    main()
