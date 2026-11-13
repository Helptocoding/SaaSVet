from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0011_user_is_service_account_alter_user_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='license_number',
            field=models.CharField(blank=True, db_default='', default='', max_length=10),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(('license_number', ''), ('license_number__regex', '^[0-9]{5,10}$'), _connector='OR'),
                name='user_license_number_digits',
            ),
        ),
    ]
