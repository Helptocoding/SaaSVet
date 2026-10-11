"""Strict interface repairs around the preserved offline adapter.

No raw record, bound, savepoint decision, or acceptance rule is changed.
The original savepoint helper takes (transaction, bound), while the offline
adapter calls (bound, transaction). Timestamp comparison uses the same instant
in UTC; the independent psycopg census uses the connection's -06:00 timezone.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch
import r106_verifier
from apps.agent.claim_diagnostic_report import _savepoint_rolled_back


def canonical_works(works):
    result = []
    for work in works:
        row = dict(work)
        value = row.get('anchor_created_at')
        if value is not None:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError('ANCHOR_TIMEZONE_MISSING')
            row['anchor_created_at'] = parsed.astimezone(timezone.utc).isoformat()
        result.append(row)
    return result


@contextmanager
def installed():
    native_reconcile = r106_verifier.reconcile
    def reconcile(report,census,works,*args,**kwargs):
        return native_reconcile(report,census,canonical_works(works),*args,**kwargs)
    def savepoint(bound, transaction):
        return _savepoint_rolled_back(transaction,bound)
    with patch.object(r106_verifier,'_savepoint_rolled_back',savepoint), \
            patch.object(r106_verifier,'reconcile',reconcile):
        yield
