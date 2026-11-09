"""
audit_stock_integrity — reconcilia stock contra el ledger de StockMovement.

ADR p31: el algoritmo opera a nivel de Product (base_units).

Modelo de reconciliacion
------------------------
  Se recorre el libro del producto en orden (`replay_ledger`):
    - sin ningun adjustment de producto el saldo parte de 0, porque todo stock
      entra por `apply_stock_movement` (orden 4, 09-11);
    - un adjustment de producto fija el saldo (absoluto);
    - un adjustment de lote mueve el agregado por su diferencia con ese lote;
    - 'in' suma y 'out' resta.
  El resultado se compara con Product.stock_quantity.

Un movimiento legacy (sin producto o con quantity_unit='presentation') no se puede
sumar. Deja el producto como 'no_baseline' (informativo, no drift) hasta su
siguiente adjustment de producto.

Exit codes:
  0  sin drift
  1  drift detectado
  2  error interno
"""
import json
import sys
from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum


SAMPLE_SIZE = 20
ZERO = Decimal('0.0000')

LEDGER_FIELDS = ('pk', 'product_id', 'movement_type', 'quantity', 'quantity_unit', 'lot_id', 'lot_number')


def replay_ledger(movements):
    """Recorre movimientos (filas de LEDGER_FIELDS, en orden de pk).

    Devuelve (saldo esperado, pk del ultimo adjustment de producto). El saldo es None si
    un movimiento legacy lo deja sin reconstruir; el pk es None si se partio de 0.
    """
    expected = ZERO
    known = True
    baseline_pk = None
    lots = defaultdict(lambda: ZERO)
    for pk, product_id, movement_type, quantity, unit, lot_id, lot_number in movements:
        if product_id is None or unit != 'base':
            known = False
            continue
        lot = (lot_id, lot_number) if lot_id is not None or lot_number else None
        if movement_type == 'adjustment':
            if lot is None:
                expected, known, baseline_pk = quantity, True, pk
            else:
                expected += quantity - lots[lot]
                lots[lot] = quantity
            continue
        signed = quantity if movement_type == 'in' else -quantity
        expected += signed
        if lot is not None:
            lots[lot] += signed
    return (expected if known else None), baseline_pk


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
        reconciled_from_zero = 0
        no_baseline = 0
        drift_count = 0
        drift_sample = []

        for p in products.iterator(chunk_size=500):
            checked += 1

            movements = (
                StockMovement.all_objects
                .filter(Q(product_id=p['pk']) | Q(product__isnull=True, presentation__product_id=p['pk']))
                .order_by('pk')
                .values_list(*LEDGER_FIELDS)
            )
            expected, baseline_pk = replay_ledger(movements.iterator(chunk_size=500))

            if expected is None:
                no_baseline += 1
                continue

            reconciled += 1
            if baseline_pk is None:
                reconciled_from_zero += 1

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
                        'baseline_adjustment_pk': baseline_pk,
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
            'reconciled_from_zero': reconciled_from_zero,
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
        self.stdout.write(f"  Reconciliados            : {report['reconciled']}")
        self.stdout.write(f"    de ellos, desde 0      : {report['reconciled_from_zero']}")
        self.stdout.write(self.style.WARNING(
            f"  No reconstruibles (legacy): {report['no_baseline']}"
        ) if report['no_baseline'] else
            f"  No reconstruibles (legacy): 0")
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
                    f"diff={row['diff']} (baseline adj pk={row['baseline_adjustment_pk'] or 'ninguno, desde 0'})"
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
