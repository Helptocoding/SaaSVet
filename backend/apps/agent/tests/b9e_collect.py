"""Read-only B9E receipt enrichment from isolated local PostgreSQL fixtures."""
import argparse
import hashlib
import json
from pathlib import Path

import psycopg


DATABASES = {
    'base': 'test_b9e_profile',
    'blocked_llm': 'test_b9e_blocked',
    'meta_slow': 'test_b9e_meta',
    'duplicate': 'test_b9e_duplicate',
    'saturation': 'test_b9e_saturation',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root, port):
    evidence = root / 'docs' / 'evals'
    result = {'schema_version': 'b9e-load-summary-v1', 'postgresql_port': port,
              'profile_sha256': digest(evidence / 'profile-beta-1-v1.json'),
              'scenarios': {}}
    for scenario, database in DATABASES.items():
        # Actual filenames are stable and explicit; no heuristics for a missing receipt.
        receipt_path = evidence / {
            'base': 'b9e-first-base.json',
            'blocked_llm': 'b9e-first-blocked.json',
            'meta_slow': 'b9e-first-meta.json',
            'duplicate': 'b9e-first-duplicate.json',
            'saturation': 'b9e-first-saturation.json',
        }[scenario]
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        org_ids = receipt['fixture_organization_ids']
        with psycopg.connect(f'postgresql://b9e@127.0.0.1:{port}/{database}') as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT current_database(), current_setting(%s), current_setting(%s), version()',
                               ('fsync', 'synchronous_commit'))
                db, fsync, synchronous_commit, version = cursor.fetchone()
                if (db != database or not db.startswith('test_') or
                        (fsync, synchronous_commit) != ('on', 'on')):
                    raise RuntimeError('Unexpected PostgreSQL database or durability settings')
                cursor.execute('''SELECT count(*), count(*) FILTER (WHERE input_tokens IS NULL
                    OR output_tokens IS NULL OR recorded_at IS NULL),
                    count(*) FILTER (WHERE error <> ''),
                    count(*) FILTER (WHERE retry_of_id IS NOT NULL),
                    COALESCE(sum(reserved_output_tokens), 0),
                    COALESCE(sum(output_tokens) FILTER (WHERE output_tokens IS NOT NULL), 0)
                    FROM agent_llmcall WHERE organization_id = ANY(%s)''', (org_ids,))
                calls, unknown, failures, retries, reserved, output_known = cursor.fetchone()
                cursor.execute('''SELECT max(llm_calls_admitted), max(llm_output_tokens_reserved),
                    count(*) FILTER (WHERE llm_calls_admitted > llm_call_limit OR
                    llm_output_tokens_reserved > llm_output_token_limit)
                    FROM agent_turnwork WHERE organization_id = ANY(%s)''', (org_ids,))
                max_calls, max_reserved, budget_violations = cursor.fetchone()
                cursor.execute('''SELECT count(*) FILTER (WHERE attempts > 1), max(attempts),
                    count(*) FILTER (WHERE status='uncertain')
                    FROM channels_message WHERE organization_id = ANY(%s) AND direction='out' ''',
                               (org_ids,))
                repeated, max_attempts, uncertain = cursor.fetchone()
                cursor.execute('''SELECT count(*) FROM channels_message m
                    JOIN agent_conversation c ON c.id=m.conversation_id
                    WHERE m.organization_id=ANY(%s) AND m.organization_id<>c.organization_id''',
                               (org_ids,))
                cross_tenant = cursor.fetchone()[0]
        logs = sorted(evidence.glob(receipt_path.stem + '-*.log'))
        result['scenarios'][scenario] = {
            'receipt': receipt_path.name, 'receipt_sha256': digest(receipt_path),
            'logs_sha256': {p.name: digest(p) for p in logs},
            'postgresql_version': version, 'fsync': fsync,
            'synchronous_commit': synchronous_commit,
            'inbound_count': receipt['inbound_count'],
            'healthy_claim': receipt['healthy_claim'],
            'safety_dispatch': receipt['safety_dispatch'],
            'outbox_dispatch': receipt['outbox_dispatch'],
            'max_pending_inbound_observed': max(
                (sample['pending_inbound'] for sample in receipt['queue_samples']), default=0),
            'max_active_per_org_observed': max(
                (row['count'] for sample in receipt['queue_samples']
                 for row in sample['active_work']), default=0),
            'llm': {'admitted_calls': calls, 'unknown_usage_calls': unknown,
                    'provider_failures': failures, 'retries': retries,
                    'reserved_output_tokens_total': reserved,
                    'known_output_tokens_subtotal': output_known,
                    'max_calls_per_turnwork': max_calls,
                    'max_reserved_tokens_per_turnwork': max_reserved,
                    'budget_violations': budget_violations},
            'outbound': {'attempts_above_one': repeated,
                         'max_attempts': max_attempts, 'uncertain_count': uncertain},
            'cross_tenant_message_rows': cross_tenant,
            'variant_gates': receipt['gates'],
            'variant_gate_pass': receipt['technical_pass'],
            'postgresql_process_ids': receipt['postgresql_process_ids'],
        }
    result['profile_technical_status'] = 'FAIL' if any(
        not row['variant_gate_pass'] for row in result['scenarios'].values()) else 'NOT_YET_COMPLETE'
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.port != 35439 or args.output.exists():
        raise RuntimeError('Use the isolated B9E cluster and a new output path')
    result = collect(args.repository.resolve(), args.port)
    args.output.write_text(json.dumps(result, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'status': result['profile_technical_status']}))


if __name__ == '__main__':
    main()
