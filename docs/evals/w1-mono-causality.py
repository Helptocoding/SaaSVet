"""Read-only causal proof from the completed blocked-LLM fixture database."""
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'docs/evals/w1-mono'
receipt = json.loads((OUT/'diagnostic-blocked.json').read_text(encoding='utf-8'))
start, end = receipt['window_utc']
org = receipt['fixture_organization_ids'][1]
with psycopg.connect('postgresql://w1mono@127.0.0.1:35442/test_b8b_w1_mono_diag_blocked',
                     row_factory=dict_row) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    joined = conn.execute("SELECT id, created_at, available_at, turn_work_id, conversation_id, organization_id "
        "FROM channels_message WHERE organization_id=%s AND direction='in' "
        "AND semantic_type<>'safety_signal' AND created_at>=%s AND created_at<%s "
        "AND available_at<created_at AND turn_work_id IS NOT NULL ORDER BY created_at,id",
        (org, start, end)).fetchall()
    cases = []
    for inbound in joined:
        work = conn.execute("SELECT id, organization_id, conversation_id, claimed_at, "
            "anchor_message_id, anchor_created_at, cursor_message_id, cursor_created_at "
            "FROM agent_turnwork WHERE id=%s", (inbound['turn_work_id'],)).fetchone()
        members = conn.execute("SELECT id, created_at, available_at, organization_id, conversation_id "
            "FROM channels_message WHERE turn_work_id=%s AND direction='in' ORDER BY created_at,id",
            (work['id'],)).fetchall()
        assert len(members) >= 2
        assert members[0]['created_at'] < inbound['created_at']
        assert all(m['available_at'] == inbound['available_at'] for m in members)
        assert all((m['organization_id'], m['conversation_id']) ==
            (work['organization_id'], work['conversation_id']) for m in members)
        assert ((work['anchor_created_at'], work['anchor_message_id']) ==
            (members[-1]['created_at'], members[-1]['id']))
        assert ((work['cursor_created_at'], work['cursor_message_id']) ==
            (members[0]['created_at'], members[0]['id']))
        assert work['claimed_at'] >= members[-1]['created_at']
        assert inbound['available_at'] < inbound['created_at'] <= work['claimed_at']
        cases.append(dict(inbound=inbound, work=work, members=members,
            second_quiet_window=False, common_expired_deadline=True,
            exact_scope=True, last_anchor=True, first_cursor=True))
    expected = receipt['monotonic_diagnostic']['organizations'][1]['joined_ready_inbounds']
    assert len(cases) == expected == 7
    result = dict(classification='DIAGNOSTIC_ONLY', source='diagnostic-blocked.json',
        read_only=True, window_utc=[start,end], organization_index=1, joined_ready=len(cases),
        proof='Earlier A and later B share an expired deadline and the same frozen work; no second quiet window.',
        cases=cases, retained_fields='Technical IDs/timestamps only; no payload or identity fields.')
    (OUT/'ready-profile-causality.json').write_text(json.dumps(result, indent=2, default=str)+'\n', encoding='utf-8')
    print(json.dumps(dict(joined_ready=len(cases), second_quiet_window=False, exact_scope=True)))
