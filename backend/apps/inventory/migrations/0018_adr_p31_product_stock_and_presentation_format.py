"""
ADR p31 — Product-level stock + Presentation como formato comercial.

Schema additions (non-breaking, todos con defaults):
  Product: base_unit, stock_quantity, min_stock
  Presentation: conversion_factor, barcode, purchase_price
  StockMovement: product FK (nullable), quantity_unit discriminator

Data migration:
  1. conversion_factor = quantity (mismo dato, semántica explícita)
  2. Product.base_unit desde primera Presentation
  3. Product.stock_quantity = Σ(p.stock * p.quantity) por producto
  4. Product.min_stock = max(p.min_stock * p.quantity) por producto
  5. Crear StockMovement baseline (adjustment, quantity_unit='base') por Product

⚠️  RESTRICCIÓN: correr esta migration cuando no hay Invoices en estado
    'confirmed' pendientes (sin pagar/cancelar). Facturas confirmadas pre-ADR p31
    que se cancelen después tendrán reversión en base_units correcta por la
    migración del baseline.
"""
from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


def populate_product_stock(apps, schema_editor):
    """
    Pobla Product.base_unit, stock_quantity, min_stock desde las Presentations,
    y crea StockMovement baseline en base_units por producto.
    """
    Product = apps.get_model('inventory', 'Product')
    Presentation = apps.get_model('inventory', 'Presentation')
    StockMovement = apps.get_model('inventory', 'StockMovement')
    import logging
    logger = logging.getLogger(__name__)

    for product in Product.objects.all().prefetch_related('presentations'):
        presentations = list(product.presentations.all())
        if not presentations:
            continue

        # Poblar conversion_factor desde quantity (mismo dato)
        for p in presentations:
            if p.conversion_factor == Decimal('1') and p.quantity != Decimal('1'):
                p.conversion_factor = p.quantity
                p.save(update_fields=['conversion_factor'])

        # base_unit desde primera presentación
        first = presentations[0]
        product.base_unit = first.base_unit or ''

        # stock_quantity = Σ(p.stock * p.quantity) — total en unidades base
        total_base = sum(
            p.stock * (p.quantity if p.quantity else Decimal('1'))
            for p in presentations
        )
        product.stock_quantity = total_base

        # min_stock = max(p.min_stock * p.quantity) — threshold más estricto
        max_min = max(
            (p.min_stock * (p.quantity if p.quantity else Decimal('1')))
            for p in presentations
        ) if any(p.min_stock > 0 for p in presentations) else Decimal('0')
        product.min_stock = max_min

        product.save(update_fields=['base_unit', 'stock_quantity', 'min_stock'])

        # Crear StockMovement baseline en base_units
        # Usa la primera presentación como contexto de audit trail
        StockMovement.objects.create(
            presentation=first,
            product=product,
            organization=product.organization,
            movement_type='adjustment',
            quantity=total_base,
            quantity_unit='base',
            reason='migration_baseline_adr_p31',
        )
        logger.info(
            "ADR p31 baseline | product=%s stock_quantity=%s org=%s",
            product.pk, total_base, product.organization_id,
        )


def reverse_product_stock(apps, schema_editor):
    """
    Reversa la data migration: borra movimientos de baseline y resetea campos.
    NO restaura Presentation.stock (se asume que los valores siguen igual).
    """
    Product = apps.get_model('inventory', 'Product')
    StockMovement = apps.get_model('inventory', 'StockMovement')

    StockMovement.objects.filter(reason='migration_baseline_adr_p31').delete()
    Product.objects.all().update(base_unit='', stock_quantity=0, min_stock=0)


class Migration(migrations.Migration):
    # atomic=False: PostgreSQL no permite CREATE INDEX en inventory_stockmovement
    # dentro de la misma transacción donde se altera quantity (deferred trigger events
    # del CASCADE FK de presentation bloquean el CREATE INDEX del nuevo product FK).
    # Cada operación corre en su propia transacción. Si falla a mitad, re-correr
    # la migration aplica solo las operaciones pendientes (Django trackea por operación).
    atomic = False

    dependencies = [
        ('inventory', '0017_medicalrecordproduct_cost_behavior'),
    ]

    operations = [
        # ── Product: campos ADR p31 ──────────────────────────────────────────
        migrations.AddField(
            model_name='product',
            name='base_unit',
            field=models.CharField(
                blank=True, default='',
                choices=[
                    ('tablet', 'Tableta'), ('capsule', 'Cápsula'), ('ml', 'ml'),
                    ('vial', 'Vial'), ('ampoule', 'Ampolleta'), ('piece', 'Pieza'),
                    ('bag', 'Bolsa'), ('bottle', 'Frasco'), ('tube', 'Tubo'),
                    ('kg', 'kg'), ('g', 'g'), ('unit', 'Unidad'),
                ],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='stock_quantity',
            field=models.DecimalField(decimal_places=4, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name='product',
            name='min_stock',
            field=models.DecimalField(decimal_places=4, default=0, max_digits=14),
        ),
        migrations.AddConstraint(
            model_name='product',
            constraint=models.CheckConstraint(
                condition=models.Q(stock_quantity__gte=0),
                name='product_stock_quantity_non_negative',
            ),
        ),

        # ── Presentation: campos ADR p31 ─────────────────────────────────────
        migrations.AddField(
            model_name='presentation',
            name='conversion_factor',
            field=models.DecimalField(decimal_places=4, default=1, max_digits=10),
        ),
        migrations.AddField(
            model_name='presentation',
            name='barcode',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='presentation',
            name='purchase_price',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=10, null=True,
            ),
        ),

        # ── StockMovement: campos ADR p31 ────────────────────────────────────
        migrations.AddField(
            model_name='stockmovement',
            name='product',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='stock_movements',
                to='inventory.product',
            ),
        ),
        migrations.AddField(
            model_name='stockmovement',
            name='quantity_unit',
            field=models.CharField(
                choices=[
                    ('presentation', 'Unidades de presentación (legacy)'),
                    ('base', 'Unidades base (ADR p31)'),
                ],
                default='presentation',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='stockmovement',
            name='quantity',
            field=models.DecimalField(decimal_places=4, max_digits=14),
        ),

        # ── Data migration ───────────────────────────────────────────────────
        migrations.RunPython(
            populate_product_stock,
            reverse_code=reverse_product_stock,
        ),
    ]
