"""Publicación atómica de la versión vigente del reporte de conflictos."""
from contextvars import ContextVar
from uuid import uuid4

from .models import ImportConflict

SAMPLE_LIMIT = 100
BATCH_SIZE = 100
_collector = ContextVar('import_conflict_collector', default=None)


class ConflictCollector:
    def __init__(self, job):
        self.job = job
        self.version = str(uuid4())
        self.buffer = []
        self.count = 0

    def add(self, conflict):
        self.count += 1
        self.buffer.append(ImportConflict(job=self.job, row=conflict['row'], ordinal=self.count, payload=conflict))
        if len(self.buffer) >= BATCH_SIZE:
            self.flush()

    def flush(self):
        if self.buffer:
            ImportConflict.objects.bulk_create(self.buffer, batch_size=BATCH_SIZE)
            self.buffer.clear()

    def finish(self, result, *, complete=True):
        self.flush()
        result['conflict_report'] = {
            'version': self.version,
            'total': result.get('skipped_conflicts', self.count),
            'sample_size': len(result.get('conflicts', [])),
            'truncated': result.get('skipped_conflicts', self.count) > len(result.get('conflicts', [])),
            'available': self.count,
            'complete': complete,
        }
        return result


def append_conflict(result, conflict):
    collector = _collector.get()
    if collector is None:
        result['conflicts'].append(conflict)
        return
    collector.add(conflict)
    if len(result['conflicts']) < SAMPLE_LIMIT:
        result['conflicts'].append(conflict)


def collect(job, callback):
    """Caller holds job row lock and transaction; failure rolls back publication."""
    ImportConflict.objects.filter(job=job).delete()
    collector = ConflictCollector(job)
    token = _collector.set(collector)
    try:
        result = callback()
        return collector.finish(result)
    finally:
        _collector.reset(token)


def convert_legacy(job):
    """Never recalculate historical results against the current catalogue."""
    result = dict(job.result or {})
    if result.get('conflict_report'):
        return result
    legacy = result.get('conflicts') or []
    ImportConflict.objects.filter(job=job).delete()
    collector = ConflictCollector(job)
    for conflict in legacy:
        collector.add(conflict)
    result['conflicts'] = legacy[:SAMPLE_LIMIT]
    total = result.get('skipped_conflicts', len(legacy))
    collector.finish(result, complete=total == len(legacy))
    return result
