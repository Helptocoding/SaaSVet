"""
Unique index parcial sobre Presentation.barcode por organización.
WHERE barcode != '' permite múltiples presentaciones sin barcode.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0018_adr_p31_product_stock_and_presentation_format'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX presentation_barcode_org_uniq
                ON inventory_presentation (organization_id, barcode)
                WHERE barcode IS NOT NULL AND barcode <> '';
            """,
            reverse_sql="DROP INDEX IF EXISTS presentation_barcode_org_uniq;",
        ),
    ]
