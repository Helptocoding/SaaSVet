from django.db import migrations, models


def reconstruct_known_vets(apps, schema_editor):
    Record = apps.get_model('medical_records', 'MedicalRecord')
    for record in Record.objects.filter(status='closed', vet_snapshot_source='unknown').select_related('veterinarian').iterator(chunk_size=500):
        vet = record.veterinarian
        if vet is None or vet.organization_id != record.organization_id:
            continue
        name = f'{vet.first_name} {vet.last_name}'.strip()
        if not name:
            continue
        # Timestamp de reconstrucción, nunca la fecha histórica de cierre.
        from django.utils import timezone
        Record.objects.filter(pk=record.pk, vet_snapshot_source='unknown').update(
            vet_public_id_at_close=vet.public_id, vet_name_at_close=name,
            # `specialty` era texto libre en este punto del historial; desde
            # users.0017 (ADR p68) no existe y una prueba invoca esta función
            # con los modelos actuales.
            vet_specialty_at_close=getattr(vet, 'specialty', '') or '',
            vet_snapshot_source='reconstructed', vet_snapshot_recorded_at=timezone.now(),
        )


class Migration(migrations.Migration):
    dependencies = [('medical_records', '0025_preserve_record_evidence'),
                    ('users', '0007_day6_add_public_id')]
    operations = [
        migrations.AddField(model_name='medicalrecord', name='vet_public_id_at_close',
                            field=models.UUIDField(blank=True, null=True, editable=False)),
        migrations.AddField(model_name='medicalrecord', name='vet_name_at_close',
                            field=models.CharField(max_length=255, blank=True, default='', editable=False)),
        migrations.AddField(model_name='medicalrecord', name='vet_specialty_at_close',
                            field=models.CharField(max_length=100, blank=True, default='', editable=False)),
        migrations.AddField(model_name='medicalrecord', name='vet_snapshot_source',
                            field=models.CharField(max_length=16, default='unknown', editable=False,
                                                   choices=[('captured', 'Capturado al cierre'),
                                                            ('reconstructed', 'Reconstruido desde usuario actual'),
                                                            ('unknown', 'Sin fuente')])),
        migrations.AddField(model_name='medicalrecord', name='vet_snapshot_recorded_at',
                            field=models.DateTimeField(blank=True, null=True, editable=False)),
        migrations.RunPython(reconstruct_known_vets, migrations.RunPython.noop),
    ]
