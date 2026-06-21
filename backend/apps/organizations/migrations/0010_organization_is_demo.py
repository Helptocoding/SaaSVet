from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0009_organizationsettings_require_open_cash_session'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='is_demo',
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
