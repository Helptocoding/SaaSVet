"""
audit_stock_integrity — reconcilia Presentation.stock contra el ledger de StockMovement.

Detecta drift: stock que divergio del ledger de movimientos. El caso que importa
es una escritura directa a Presentation.stock que salto apply_stock_movement (el
unico writer autorizado, ver apps/inventory/services.py).

Modelo de reconciliacion
-------------------------
'adjustment' es un RESET ABSOLUTO: fija stock = quantity. Por eso la
reconciliacion parte del ULTIMO adjustment de cada presentacion:

    expected = ultimo_adjustment.quantity
             + SUM(movimientos 'in'  posteriores)
             - SUM(movimientos 'out' posteriores)

Los movimientos "posteriores" son los de PK mayor al del ultimo adjustment
(StockMovement es append-only y PK es serial). No puede haber otro 'adjustment'
posterior por definicion (seria el ultimo). Comparacion final: expected vs stock.

Limitacion de cobertura (honesta)
---------------------------------
Crear una Presentation NO emite un movimiento de apertura: el stock inicial se
fija directo en el campo (apps/inventory/views.py). Una presentacion SIN ningun
'adjustment' no tiene baseline en el ledger -> su stock NO es verificable por
replay. Se reporta como 'no_baseline' (informativo), NO como drift, para no
generar falsos positivos masivos. Para cobertura total, registrar el stock de
apertura como un movimiento al crear la presentacion.

Seguridad de produccion
------------------------
- Solo lectura. Sin select_for_update, sin transaction.atomic, sin locks.
- Dos queries pequenas por presentacion, ambas acotadas a la particion de una
  presentacion (no scans de tabla completa). Itera con .iterator() para no
  cargar todo en memoria.
- Scope opcional por --org para fan-out por tenant en cron.

Exit codes:
  0  sin drift (presentaciones reconciliables coinciden; 'no_baseline' es informativo)
  1  drift detectado (al menos una presentacion reconciliable no coincide)
  2  error interno

Usage:
  python manage.py audit_stock_integrity
  python manage.py audit_stock_integrity --org=12
  python manage.py audit_stock_integrity --verbose      # detalle de cada drift
  python manage.py audit_stock_integrity --json         # machine-readable (cron/monitoring)
"""
import json
import sys
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum


SAMPLE_SIZE = 20


class Command(BaseCommand):
    help = "Reconcilia Presentation.stock contra el ledger de StockMovement (drift detection)."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None,
                            help="Restringe a una organizacion id.")
        parser.add_argument('--verbose', action='store_true',
                            help="Imprime detalle de cada presentacion con drift (sin cap de sample).")
        parser.add_argument('--json', action='store_true',
                            help="Emite un unico objeto JSON en vez de salida humana.")

    def handle(self, *args, **options):
        from apps.inventory.models import Presentation, StockMovement

        org_filter = Q(organization_id=options['org']) if options['org'] else Q()

        presentations = (
            Presentation.all_objects.filter(org_filter)
            .values('pk', 'organization_id', 'stock')
            .order_by('pk')
        )

        checked = 0
        reconciled = 0
        no_baseline = 0
        drift_count = 0
        drift_sample = []

        for p in presentations.iterator(chunk_size=500):
            checked += 1

            last_adj = (
                StockMovement.all_objects
                .filter(presentation_id=p['pk'], movement_type='adjustment')
                .order_by('-pk')
                .values('pk', 'quantity')
                .first()
            )
            if last_adj is None:
                # Sin adjustment no hay baseline en el ledger: el stock de
                # apertura no se registra como movimiento. No verificable.
                no_baseline += 1
                continue

            net = Decimal('0')
            after = (
                StockMovement.all_objects
                .filter(presentation_id=p['pk'], pk__gt=last_adj['pk'])
                .values('movement_type')
                .annotate(total=Sum('quantity'))
            )
            for row in after:
                if row['movement_type'] == 'in':
                    net += row['total']
                elif row['movement_type'] == 'out':
                    net -= row['total']
                # 'adjustment' posterior imposible: last_adj es el de mayor PK.

            expected = last_adj['quantity'] + net
            reconciled += 1

            if expected != p['stock']:
                drift_count += 1
                if options['verbose'] or len(drift_sample) < SAMPLE_SIZE:
                    drift_sample.append({
                        'presentation_id': p['pk'],
                        'organization_id': p['organization_id'],
                        'stock_actual': str(p['stock']),
                        'stock_esperado': str(expected),
                        'diff': str(p['stock'] - expected),
                        'baseline_adjustment_pk': last_adj['pk'],
                    })

        exit_code = 1 if drift_count > 0 else 0

        report = {
            'checked_presentations': checked,
            'reconciled': reconciled,
            'no_baseline': no_baseline,
            'drift_count': drift_count,
            'drift_sample': drift_sample,
            'exit_code': exit_code,
        }

        if options['json']:
            self.stdout.write(json.dumps(report, default=str, indent=2))
        else:
            self._print_human(report)

        sys.exit(exit_code)

    def _print_human(self, report):
        self.stdout.write(self.style.MIGRATE_HEADING("Stock integrity audit"))
        self.stdout.write("")
        self.stdout.write(f"  Presentaciones revisadas : {report['checked_presentations']}")
        self.stdout.write(f"  Reconciliadas (con baseline): {report['reconciled']}")
        self.stdout.write(self.style.WARNING(
            f"  Sin baseline (no verificable): {report['no_baseline']}"
        ) if report['no_baseline'] else
            f"  Sin baseline (no verificable): 0")
        self.stdout.write("")

        if report['drift_count'] == 0:
            self.stdout.write(self.style.SUCCESS("  OK Sin drift en presentaciones reconciliables."))
        else:
            self.stdout.write(self.style.ERROR(
                f"  X DRIFT: {report['drift_count']} presentaciones divergen del ledger"
            ))
            for row in report['drift_sample']:
                self.stdout.write(
                    f"      - pres={row['presentation_id']} org={row['organization_id']} "
                    f"actual={row['stock_actual']} esperado={row['stock_esperado']} "
                    f"diff={row['diff']} (baseline adj pk={row['baseline_adjustment_pk']})"
                )

        self.stdout.write("")
        self.stdout.write(f"Exit code: {report['exit_code']}")
