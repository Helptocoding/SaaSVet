from django.db import migrations


def restore_legacy_results(apps, schema_editor):
    """Restore available report details before 0003 can be reversed.

    Run with import writers stopped. The original missing portion of an
    incomplete legacy report is never reconstructed or claimed to exist.
    """
    Job = apps.get_model('imports', 'ImportJob')
    Detail = apps.get_model('imports', 'ImportConflict')
    db = schema_editor.connection.alias
    for job in Job._base_manager.using(db).all().iterator(chunk_size=100):
        result = dict(job.result or {})
        meta = result.get('conflict_report') or {}
        if not meta or meta.get('invalidated'):
            continue
        details = list(Detail.objects.using(db).filter(job_id=job.pk)
                       .order_by('row', 'ordinal').values_list('payload', flat=True))
        if len(details) != meta.get('available'):
            raise RuntimeError('Rollback detenido: detalle de conflictos incompleto respecto al reporte publicado.')
        result['conflicts'] = details
        Job._base_manager.using(db).filter(pk=job.pk).update(result=result)


class Migration(migrations.Migration):
    dependencies = [('imports', '0003_importconflict')]
    operations = [migrations.RunPython(migrations.RunPython.noop, restore_legacy_results)]
