from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('appointments', '0018_confirm_attendance_effect')]
    operations = [migrations.AddConstraint('appointment', models.UniqueConstraint(
        fields=['id', 'organization'], name='appointment_id_org_ref'))]
