"""
audit_payment_ledger_integrity — verifica la consistencia entre el estado de la
factura y el ledger de pagos (ADR p27 / docs/financial-event-model-contract.md §8).

Invariante real: `Invoice.status` es una PROYECCIÓN del ledger, no un flag
arbitrario. `remaining_balance = total − Σ(Payment.amount)`.

Reglas verificadas (por factura):
  - status='paid'      ⇒ remaining_balance == 0   (Σ pagos == total)
  - status='posted'    ⇒ remaining_balance >  0   (Σ pagos < total; si == total
                         debería estar 'paid' → violación)
  - status='voided'    ⇒ Σ pagos == 0             (void con pagos está bloqueado;
                         la devolución va por nota de crédito, ADR p29)

Es el ratchet que atrapa la regresión "alguien dejó status='paid' sin que el
dinero cuadre" (o un partial mal proyectado). Hermano de audit_anchor_integrity
y audit_stock_integrity.

Seguridad de producción
------------------------
- Solo lectura. Sin locks, sin transaction.atomic.
- Una sola query anotada (Coalesce(Sum)) con .iterator(); no scans repetidos.
- Scope opcional por --org para fan-out por tenant en cron.

Exit codes:
  0  sin violaciones
  1  violación de invariante detectada
  2  error interno

Usage:
  python manage.py audit_payment_ledger_integrity
  python manage.py audit_payment_ledger_integrity --org=12 --verbose
  python manage.py audit_payment_ledger_integrity --json
"""
import json
import sys
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

# Esta salida alimenta un gate de CI/cron (exit code). Es API interna:
# versionar el shape del reporte. Bump al cambiar la semántica de un campo.
REPORT_SCHEMA_VERSION = 1
SAMPLE_SIZE = 20
ZERO = Decimal('0.00')


class Command(BaseCommand):
    help = "Verifica consistencia entre Invoice.status y el ledger de Payment (ADR p27)."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None,
                            help="Restringe a una organizacion id.")
        parser.add_argument('--verbose', action='store_true',
                            help="Imprime detalle de cada violacion (sin cap de sample).")
        parser.add_argument('--json', action='store_true',
                            help="Emite un unico objeto JSON en vez de salida humana.")

    def handle(self, *args, **options):
        from apps.billing.models import Invoice

        org_filter = Q(organization_id=options['org']) if options['org'] else Q()

        invoices = (
            Invoice.all_objects.filter(org_filter)
            .annotate(paid_sum=Coalesce(
                Sum('payments__amount'),
                Value(ZERO),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ))
            .values('pk', 'public_id', 'organization_id', 'status', 'total', 'paid_sum')
            .order_by('pk')
        )

        checked = 0
        violations = 0
        sample = []

        for inv in invoices.iterator(chunk_size=500):
            checked += 1
            total = inv['total']
            paid = inv['paid_sum']
            remaining = total - paid
            status = inv['status']
            kind = None

            if status == 'paid' and remaining != ZERO:
                kind = 'paid_remaining_nonzero'
            elif status == 'posted' and total > ZERO and paid >= total:
                kind = 'posted_fully_paid_not_marked'
            elif status == 'voided' and paid > ZERO:
                kind = 'voided_with_payments'

            if kind:
                violations += 1
                if options['verbose'] or len(sample) < SAMPLE_SIZE:
                    sample.append({
                        'invoice_id': inv['pk'],
                        'public_id': str(inv['public_id']),
                        'organization_id': inv['organization_id'],
                        'status': status,
                        'total': str(total),
                        'paid_sum': str(paid),
                        'remaining_balance': str(remaining),
                        'kind': kind,
                    })

        exit_code = 1 if violations > 0 else 0
        report = {
            'schema_version': REPORT_SCHEMA_VERSION,
            'checked_invoices': checked,
            'violations': violations,
            'violation_sample': sample,
            'exit_code': exit_code,
        }

        if options['json']:
            self.stdout.write(json.dumps(report, default=str, indent=2))
        else:
            self._print_human(report)

        sys.exit(exit_code)

    def _print_human(self, report):
        self.stdout.write(self.style.MIGRATE_HEADING("Payment ledger integrity audit"))
        self.stdout.write("")
        self.stdout.write(f"  Facturas revisadas : {report['checked_invoices']}")
        if report['violations'] == 0:
            self.stdout.write(self.style.SUCCESS(
                "  OK status consistente con el ledger de pagos."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"  X {report['violations']} facturas violan el invariante status↔ledger"
            ))
            for row in report['violation_sample']:
                self.stdout.write(
                    f"      - inv={row['invoice_id']} org={row['organization_id']} "
                    f"status={row['status']} total={row['total']} pagado={row['paid_sum']} "
                    f"remaining={row['remaining_balance']} [{row['kind']}]"
                )
        self.stdout.write("")
        self.stdout.write(f"Exit code: {report['exit_code']}")
