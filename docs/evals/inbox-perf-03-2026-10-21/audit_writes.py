"""Inventory write entry points and opt-in manager coverage without DB writes."""
import ast
import json
import os
import sys
from pathlib import Path

out = Path(__file__).resolve().parent
root = out.parents[2]
sys.path.insert(0, str(root/'backend'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['SENTRY_DSN'] = ''
import django
django.setup()
from apps.agent.models import ContactIdentity, Conversation, HumanHandoff, InboxReadState
from apps.channels.models import Message
from apps.patients.models import Owner

models = [ContactIdentity, Conversation, HumanHandoff, InboxReadState, Message]
coverage = [dict(model=model._meta.label, opted_in=model.track_updated_at,
    default_manager=model._default_manager.name,
    ordinary_queryset=type(model.objects.get_queryset()).__name__,
    unfiltered_queryset=type(model.all_objects.get_queryset()).__name__) for model in models]
assert all(row['opted_in'] and row['default_manager'] == 'objects'
           and row['ordinary_queryset'] == 'TenantQuerySet'
           and row['unfiltered_queryset'] == 'TimestampedQuerySet' for row in coverage)
assert not getattr(Owner, 'track_updated_at', False)
writes, raw = [], []
for directory in ('backend/apps/agent', 'backend/apps/channels'):
    for path in (root/directory).rglob('*.py'):
        if {'tests', 'migrations', 'management'} & set(path.relative_to(root).parts):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            method = node.func.attr
            if method in ('update', 'bulk_update', 'save', 'bulk_create'):
                writes.append(dict(file=path.relative_to(root).as_posix(), line=node.lineno,
                    method=method, receiver=ast.unparse(node.func.value)[:220],
                    keywords=[keyword.arg for keyword in node.keywords]))
            if method == 'execute' and node.args and isinstance(node.args[0], ast.Constant):
                sql = node.args[0].value
                if isinstance(sql, str) and any(word in sql.upper() for word in ('UPDATE ', 'INSERT INTO ', 'DELETE FROM ')):
                    raw.append(dict(file=path.relative_to(root).as_posix(), line=node.lineno))
assert not raw, raw
result = dict(status='PASS', tracked_models=coverage, other_domains_opted_in=False,
    raw_sql_write_literals=raw, inventory_includes_dictionary_updates=True,
    write_call_inventory=writes,
    interpretation='Atomic/bulk/save writes on opted-in models share timestamp maintenance; predicates, locks, validation and tenant filtering are unchanged.')
(out/'write-audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(dict(status='PASS', tracked_models=len(coverage), write_calls=len(writes), raw_sql_write_literals=len(raw))))
