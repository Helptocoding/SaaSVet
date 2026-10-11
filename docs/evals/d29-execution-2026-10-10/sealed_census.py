"""An exact read interface over the independently captured final outbox."""
from datetime import datetime
from types import SimpleNamespace


def output_row(census,*,pk):
    matches=[m for m in census['messages'] if m['id']==pk and m['direction']=='out']
    if len(matches)!=1:raise ValueError('SEALED_OUTPUT_ID_MISSING_OR_DUPLICATED')
    row=matches[0]
    at=datetime.fromisoformat(row['send_admitted_at'])
    if at.tzinfo is None:raise ValueError('SEALED_ADMISSION_TIMEZONE_MISSING')
    return SimpleNamespace(pk=row['id'],status=row['status'],send_admitted_at=at)
