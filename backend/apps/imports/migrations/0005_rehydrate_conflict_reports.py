from uuid import uuid4

from django.db import migrations


def rehydrate(apps, schema_editor):
    Job = apps.get_model('imports', 'ImportJob')
    Detail = apps.get_model('imports', 'ImportConflict')
    db = schema_editor.connection.alias
    for job in Job._base_manager.using(db).all().iterator(chunk_size=100):
        result = dict(job.result or {})
        meta = result.get('conflict_report') or {}
        if not meta or meta.get('invalidated'):
            continue
        available = meta.get('available')
        count = Detail.objects.using(db).filter(job_id=job.pk).count()
        if count == available:
            continue
        legacy = result.get('conflicts') or []
        # Only the rollback bridge retains the complete available detail in JSON.
        # A partial table or sample is never treated as authoritative evidence.
        if count != 0 or not isinstance(available, int) or len(legacy) != available:
            raise RuntimeError('Rehidratación detenida: detalle de conflictos no recuperable desde JSON.')
        pending = []
        for ordinal, item in enumerate(legacy, 1):
            pending.append(Detail(job_id=job.pk, row=item['row'], ordinal=ordinal, payload=item))
            if len(pending) == 100:
                Detail.objects.using(db).bulk_create(pending, batch_size=100)
                pending.clear()
        if pending:
            Detail.objects.using(db).bulk_create(pending, batch_size=100)
        result['conflicts'] = legacy[:100]
        meta = dict(meta)
        meta.update(version=str(uuid4()), sample_size=len(result['conflicts']),
                    truncated=meta.get('total', available) > len(result['conflicts']))
        result['conflict_report'] = meta
        Job._base_manager.using(db).filter(pk=job.pk).update(result=result)


class Migration(migrations.Migration):
    dependencies = [('imports', '0004_conflict_rollback_bridge')]
    operations = [migrations.RunPython(rehydrate, migrations.RunPython.noop)]
