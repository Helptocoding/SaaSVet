"""
audit_stock_integrity — reconcilia stock contra el ledger de StockMovement.

ADR p31: el algoritmo opera ahora a nivel de Product (base_units). Los
movimientos legacy (quantity_unit='presentation') se ignoran en el cálculo
nuevo; el baseline de cada producto es el último StockMovement(adjustment,
quantity_unit='base') creado por la migration 0018.

Modelo de reconciliacion (modo Product, ADR p31)
-------------------------------------------------
  baseline = último StockMovement(adjustment, quantity_unit='base') para ese Product.
  expected = baseline.quantity
           + SUM('in', quantity_unit='base', pk > baseline.pk)
           - SUM('out', quantity_unit='base', pk > baseline.pk)
  compare expected vs Product.stock_quantity

Modo legacy (Presentation)
--------------------------
Se mantiene el algoritmo original para productos sin baseline en base_units,
reportados como 'no_baseline_product' (informativo, no drift).

Exit codes:
  0  sin drift
  1  drift detectado
  2  error interno
"""
import json
import sys
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum


SAMPLE_SIZE = 20


class Command(BaseCommand):
    help = "Reconcilia Product.stock_quantity contra el ledger de StockMovement (ADR p31)."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None,
                            help="Restringe a una organizacion id.")
        parser.add_argument('--verbose', action='store_true',
                            help="Imprime detalle de cada producto con drift.")
        parser.add_argument('--json', action='store_true',
                            help="Emite un unico objeto JSON en vez de salida humana.")

    def handle(self, *args, **options):
        from apps.inventory.models import Product, StockLot, StockMovement

        org_filter = Q(organization_id=options['org']) if options['org'] else Q()

        products = (
            Product.all_objects.filter(org_filter)
            .values('pk', 'organization_id', 'stock_quantity', 'name')
            .order_by('pk')
        )

        checked = 0
        reconciled = 0
        no_baseline = 0
        drift_count = 0
        drift_sample = []

        for p in products.iterator(chunk_size=500):
            checked += 1

            # Baseline: último adjustment en base_units para este producto
            last_adj = (
                StockMovement.all_objects
                .filter(
                    product_id=p['pk'],
                    movement_type='adjustment',
                    quantity_unit='base',
                )
                .order_by('-pk')
                .values('pk', 'quantity')
                .first()
            )

            if last_adj is None:
                no_baseline += 1
                continue

            net = Decimal('0')
            after = (
                StockMovement.all_objects
                .filter(
                    product_id=p['pk'],
                    pk__gt=last_adj['pk'],
                    quantity_unit='base',
                )
                .values('movement_type')
                .annotate(total=Sum('quantity'))
            )
            for row in after:
                if row['movement_type'] == 'in':
                    net += row['total']
                elif row['movement_type'] == 'out':
                    net -= row['total']

            expected = last_adj['quantity'] + net
            reconciled += 1

            if expected != p['stock_quantity']:
                drift_count += 1
                if options['verbose'] or len(drift_sample) < SAMPLE_SIZE:
                    drift_sample.append({
                        'product_id': p['pk'],
                        'product_name': p['name'],
                        'organization_id': p['organization_id'],
                        'stock_actual': str(p['stock_quantity']),
                        'stock_esperado': str(expected),
                        'diff': str(p['stock_quantity'] - expected),
                        'baseline_adjustment_pk': last_adj['pk'],
                    })

        # Invariante de lotes (spec 2026-07-10): para productos con tracks_lots,
        # Σ StockLot.quantity_on_hand == Product.stock_quantity.
        lot_drift_count = 0
        lot_drift_sample = []
        lot_products = (
            Product.all_objects.filter(org_filter, tracks_lots=True)
            .values('pk', 'organization_id', 'name', 'stock_quantity')
            .order_by('pk')
        )
        for p in lot_products.iterator(chunk_size=500):
            agg = StockLot.all_objects.filter(product_id=p['pk']).aggregate(
                total=Sum('quantity_on_hand')
            )
            lot_total = agg['total'] or Decimal('0')
            if lot_total != p['stock_quantity']:
                lot_drift_count += 1
                if len(lot_drift_sample) < SAMPLE_SIZE:
                    lot_drift_sample.append({
                        'product_id': p['pk'],
                        'product_name': p['name'],
                        'organization_id': p['organization_id'],
                        'stock_quantity': str(p['stock_quantity']),
                        'sum_lots': str(lot_total),
                        'diff': str(p['stock_quantity'] - lot_total),
                    })

        exit_code = 1 if (drift_count > 0 or lot_drift_count > 0) else 0

        report = {
            'checked_products': checked,
            'reconciled': reconciled,
            'no_baseline': no_baseline,
            'drift_count': drift_count,
            'drift_sample': drift_sample,
            'lot_drift_count': lot_drift_count,
            'lot_drift_sample': lot_drift_sample,
            'exit_code': exit_code,
        }

        if options['json']:
            self.stdout.write(json.dumps(report, default=str, indent=2))
        else:
            self._print_human(report)

        sys.exit(exit_code)

    def _print_human(self, report):
        self.stdout.write(self.style.MIGRATE_HEADING("Stock integrity audit (ADR p31)"))
        self.stdout.write("")
        self.stdout.write(f"  Productos revisados      : {report['checked_products']}")
        self.stdout.write(f"  Reconciliados (baseline) : {report['reconciled']}")
        self.stdout.write(self.style.WARNING(
            f"  Sin baseline base_units  : {report['no_baseline']}"
        ) if report['no_baseline'] else
            f"  Sin baseline base_units  : 0")
        self.stdout.write("")

        if report['drift_count'] == 0:
            self.stdout.write(self.style.SUCCESS("  OK Sin drift en productos reconciliables."))
        else:
            self.stdout.write(self.style.ERROR(
                f"  X DRIFT: {report['drift_count']} productos divergen del ledger"
            ))
            for row in report['drift_sample']:
                self.stdout.write(
                    f"      - product={row['product_id']} ({row['product_name']}) "
                    f"org={row['organization_id']} "
                    f"actual={row['stock_actual']} esperado={row['stock_esperado']} "
                    f"diff={row['diff']} (baseline adj pk={row['baseline_adjustment_pk']})"
                )

        self.stdout.write("")
        if report['lot_drift_count'] == 0:
            self.stdout.write(self.style.SUCCESS(
                "  OK Invariante de lotes (Σ lotes == stock) sin drift."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"  X DRIFT DE LOTES: {report['lot_drift_count']} productos con "
                f"Σ lotes != Product.stock_quantity"
            ))
            for row in report['lot_drift_sample']:
                self.stdout.write(
                    f"      - product={row['product_id']} ({row['product_name']}) "
                    f"org={row['organization_id']} "
                    f"stock={row['stock_quantity']} sum_lotes={row['sum_lots']} "
                    f"diff={row['diff']}"
                )

        self.stdout.write("")
        self.stdout.write(f"Exit code: {report['exit_code']}")
