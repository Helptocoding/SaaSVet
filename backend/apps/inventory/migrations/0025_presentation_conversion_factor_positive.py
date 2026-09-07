from decimal import Decimal

from django.db import migrations, models


def preflight_conversion_factors(apps, schema_editor):
    Presentation = apps.get_model('inventory', 'Presentation')
    invalid = Presentation.objects.exclude(
        conversion_factor__gt=0,
        conversion_factor__lte=Decimal('999999.9999'),
    ).count()
    if invalid:
        raise RuntimeError(
            f'{invalid} presentations have a non-finite, non-positive or '
            'unrepresentable conversion_factor; '
            'correct the catalog explicitly before migrating.'
        )


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0024_product_extra_data'),
    ]

    operations = [
        migrations.RunPython(preflight_conversion_factors, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM pg_constraint
                                WHERE conname = 'presentation_conversion_factor_positive'
                                  AND conrelid = 'inventory_presentation'::regclass
                            ) THEN
                                ALTER TABLE inventory_presentation
                                ADD CONSTRAINT presentation_conversion_factor_positive
                                CHECK (
                                    conversion_factor > 0
                                    AND conversion_factor <= 999999.9999
                                ) NOT VALID;
                            END IF;
                        END
                        $$;
                    """,
                    reverse_sql="""
                        ALTER TABLE inventory_presentation
                        DROP CONSTRAINT IF EXISTS presentation_conversion_factor_positive;
                    """,
                ),
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE inventory_presentation
                        VALIDATE CONSTRAINT presentation_conversion_factor_positive;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name='presentation',
                    constraint=models.CheckConstraint(
                        condition=(
                            models.Q(conversion_factor__gt=0)
                            & models.Q(conversion_factor__lte=Decimal('999999.9999'))
                        ),
                        name='presentation_conversion_factor_positive',
                    ),
                ),
            ],
        ),
    ]
