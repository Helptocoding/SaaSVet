"""Una importación confirmada se aplica EXACTAMENTE una vez.

Origen (auditoría run-1, hallazgo
`imports/commit/job-status-toctou-duplicates-inventory-and-initial-stock`):

El estado del job se comprobaba en la vista ANTES de llamar al servicio y se
escribía DESPUÉS, así que los dos quedaban separados por toda la duración de la
importación. Dos peticiones solapadas pasaban ambas el filtro y ejecutaban la
importación entera dos veces. En inventario eso duplicaba el producto y aplicaba
su stock inicial dos veces para las filas **sin** `internal_code`: las que
llevan código están protegidas por el UNIQUE por organización, pero una fila sin
código recibe un código generado desde su propio PK, así que nada en base la
atrapa.

Lo peor era que resultaba invisible: los `StockMovement` y `stock_quantity`
quedaban consistentes entre sí, de modo que `audit_stock_integrity` reconciliaba
limpio. Medido antes del arreglo: 2 productos, 2 movimientos y stock 20 para un
archivo que declaraba 10, con ambos hilos reportando éxito.

El arreglo puso la garantía en `commit_job`, bajo `select_for_update()` de la
fila del job y con la transición de estado dentro de la misma transacción que
escribe. Está en el SERVICIO y no en la vista a propósito: es un cambio de
estado de dominio, así que cualquier llamador futuro lo hereda. Este test llama
al servicio directamente, que es lo que hace esa frontera verificable — contra
la vista pasaría incluso con el arreglo en el lugar equivocado.

Patrón de concurrencia copiado de `apps/billing/tests/test_checkout_concurrency.py`.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from apps.imports.models import ImportJob
from apps.imports.services import ImportAlreadyCommitted, commit_job
from apps.inventory.models import Product, StockMovement
from apps.organizations.models import Organization

COLUMNS = ['nombre', 'precio', 'existencia']
MAPPING = {
    'nombre': 'product.name',
    'precio': 'presentation.sale_price',
    'existencia': 'product.stock',
}


class ImportCommitAppliesOnceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.org = Organization.objects.create(
            name='Import once', timezone='UTC',
        )
        # Fila SIN internal_code a propósito: su unicidad no la respalda la
        # base, así que es el caso que el lock tiene que cubrir.
        job = ImportJob(
            organization=self.org,
            entity_type=ImportJob.ENTITY_INVENTORY,
            status=ImportJob.STATUS_VALIDATED,
            original_filename='once.csv',
            source_columns=COLUMNS,
            rows=[['Jeringa 5ml', '50.00', '10']],
            mapping=MAPPING,
            result={},
        )
        job.save()
        self.job_pk = job.pk

    def _race(self, workers=2):
        barrier = Barrier(workers)

        def run(_n):
            close_old_connections()
            try:
                with connection.cursor() as cur:
                    cur.execute("SET lock_timeout = '5s'")
                    cur.execute("SET statement_timeout = '20s'")
                job = ImportJob.objects.get(pk=self.job_pk)
                barrier.wait(timeout=15)
                commit_job(job, created_by=None)
                return 'committed'
            except ImportAlreadyCommitted:
                return 'rejected'
            except Exception as exc:  # pragma: no cover — diagnóstico
                return f'unexpected:{type(exc).__name__}:{exc}'
            finally:
                # Las conexiones persistentes del worker sobreviven al Future
                # con CONN_MAX_AGE > 0; cerrarlas deja el teardown limpio.
                connection.close()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(run, range(workers)))

    def test_two_overlapping_commits_apply_the_import_once(self):
        outcomes = self._race()

        self.assertEqual(
            sorted(outcomes), ['committed', 'rejected'],
            f"Exactamente un commit debe aplicar y el otro rechazarse; se obtuvo {outcomes}",
        )

        products = Product.objects.filter(organization=self.org, name='Jeringa 5ml')
        self.assertEqual(
            products.count(), 1,
            'Dos commits solapados crearon el producto más de una vez.',
        )
        self.assertEqual(
            StockMovement.objects.filter(
                organization=self.org, presentation__product__in=products,
            ).count(),
            1,
            'El stock inicial se aplicó más de una vez.',
        )
        self.assertEqual(
            products.first().stock_quantity, Decimal('10.0000'),
            'El stock resultante no coincide con lo que declaraba el archivo.',
        )

    def test_sequential_second_commit_is_rejected(self):
        job = ImportJob.objects.get(pk=self.job_pk)
        commit_job(job, created_by=None)

        again = ImportJob.objects.get(pk=self.job_pk)
        self.assertEqual(again.status, ImportJob.STATUS_COMMITTED)
        with self.assertRaises(ImportAlreadyCommitted):
            commit_job(again, created_by=None)

        self.assertEqual(
            Product.objects.filter(organization=self.org, name='Jeringa 5ml').count(), 1,
        )
