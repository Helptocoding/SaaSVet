from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('imports', '0002_alter_importjob_entity_type')]
    operations = [
        migrations.CreateModel(
            name='ImportConflict',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('row', models.PositiveIntegerField()),
                ('ordinal', models.PositiveIntegerField()),
                ('payload', models.JSONField()),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='conflict_details', to='imports.importjob')),
            ],
            options={
                'ordering': ['row', 'ordinal'],
                'indexes': [models.Index(fields=['job', 'row', 'ordinal'], name='import_conflict_order_idx')],
                'constraints': [models.UniqueConstraint(fields=('job', 'ordinal'), name='import_conflict_job_ordinal_uniq')],
            },
        ),
    ]
