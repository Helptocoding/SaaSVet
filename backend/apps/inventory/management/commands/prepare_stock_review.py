import json

from django.core.management.base import BaseCommand, CommandError

from apps.inventory.models import Product
from apps.inventory.stock_diagnostics import diagnose_product


class Command(BaseCommand):
    help = 'Diagnóstico de un producto, sin escrituras ni regularización.'

    def add_arguments(self, parser):
        parser.add_argument('--organization-public-id', required=True)
        parser.add_argument('--product-public-id', required=True)

    def handle(self, *args, **options):
        try:
            product = Product.all_objects.select_related('organization').get(
                organization__public_id=options['organization_public_id'],
                public_id=options['product_public_id'],
            )
        except (Product.DoesNotExist, ValueError):
            raise CommandError('Producto u organización no encontrados.')
        self.stdout.write(json.dumps(diagnose_product(product), ensure_ascii=False))
