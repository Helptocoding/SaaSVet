import json

from django.core.management.base import BaseCommand, CommandError

from apps.billing.schema_contract import collect_billing_schema_drift


class Command(BaseCommand):
    help = 'Compara Invoice/Billing model state con el schema PostgreSQL físico.'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        errors = collect_billing_schema_drift()
        report = {
            'schema_version': 1,
            'contract': 'checkout-billing-v1',
            'violations': len(errors),
            'errors': errors,
            'ok': not errors,
        }
        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        elif errors:
            self.stdout.write(self.style.ERROR('Billing schema drift detectado:'))
            for error in errors:
                self.stdout.write(f'  - {error}')
        else:
            self.stdout.write(self.style.SUCCESS(
                'Billing model state y PostgreSQL cumplen checkout-billing-v1.'
            ))
        if errors:
            raise CommandError(f'Billing schema drift: {len(errors)} violaciones.')
