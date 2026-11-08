"""I01 acceptance in a real browser: real API, real PostgreSQL, no shared client state.

Every recovery starts from a brand new browser context: no storage, no cookies, nothing
from the sending session. Tests never read an operation id, so the only way the page can
reach one is by asking the server. Needs a frontend build pointed at the live server:

    VITE_API_URL=http://127.0.0.1:49936/api/ pnpm exec vite build --outDir <dir>
    ORDEN4_BROWSER_DIST=<dir> python scripts/orden4_isolated.py test <this module> --keepdb --noinput
"""
import importlib.util
import os
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest import skipUnless
from unittest.mock import patch

from django.test import LiveServerTestCase, override_settings
from django.core.cache import caches

from apps.core.models import UserRole
from apps.inventory.models import Presentation, Product, StockLot, StockMovement, StockReceptionReceipt
from apps.inventory.tests.test_order4_reception_recovery_races import HeldExecution
from apps.inventory.tests.test_stock_reception import _seed_roles
from apps.organizations.models import Organization
from apps.users.models import User

API_PORT = 49936
FRONTEND_PORT = 49937
FRONTEND = f'http://127.0.0.1:{FRONTEND_PORT}'
DIST = os.environ.get('ORDEN4_BROWSER_DIST', '')
PASSWORD = 'pass1234!'
COMPLETE_ROUTE = '**/api/inventory/receptions/*/complete/'
PREPARE_ROUTE = '**/api/inventory/presentations/*/receptions/'
WAIT_MS = 30_000


class SinglePageHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        requested = Path(self.directory) / self.path.split('?')[0].lstrip('/')
        if not requested.is_file():
            self.path = '/index.html'
        return super().do_GET()

    def log_message(self, *args):
        pass


@skipUnless(importlib.util.find_spec('playwright') and DIST, 'Requiere Playwright y ORDEN4_BROWSER_DIST.')
@override_settings(CORS_ALLOWED_ORIGINS=[FRONTEND])
class ReceptionRecoveryBrowserTests(LiveServerTestCase):
    host = '127.0.0.1'
    port = API_PORT

    @classmethod
    def setUpClass(cls):
        # Playwright's sync API keeps an event loop on this thread, which Django's ORM
        # guard mistakes for async code. These tests only touch the ORM between steps.
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
        super().setUpClass()
        from playwright.sync_api import sync_playwright
        handler = partial(SinglePageHandler, directory=DIST)
        cls.frontend = ThreadingHTTPServer(('127.0.0.1', FRONTEND_PORT), handler)
        Thread(target=cls.frontend.serve_forever, daemon=True).start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.frontend.shutdown()
        cls.frontend.server_close()
        os.environ.pop('DJANGO_ALLOW_ASYNC_UNSAFE', None)
        super().tearDownClass()

    def setUp(self):
        caches['throttle_login'].clear()
        self.org = Organization.objects.create(name='Clínica navegador', timezone='UTC', tax_rate=Decimal('0'))
        roles = _seed_roles(self.org)
        self.user = User.objects.create_user(
            username='browser_i01', password=PASSWORD, organization=self.org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.user, role=roles['ADMIN'])
        self.product, self.presentation = self._lot_product('Vacuna Rabia', 'VAC-E2E')
        self.addCleanup(self._close_contexts)
        self.contexts = []

    def _close_contexts(self):
        for context in self.contexts:
            context.close()

    def _lot_product(self, name, code):
        product = Product.objects.create(
            name=name, internal_code=code, organization=self.org, base_unit='vial', tracks_lots=True,
        )
        presentation = Presentation.objects.create(
            product=product, name='Vial', base_unit='vial', quantity=Decimal('1'),
            conversion_factor=Decimal('1'), sale_price=Decimal('120'), stock=Decimal('0'), organization=self.org,
        )
        return product, presentation

    def _clean_session(self):
        """A browser that remembers nothing, signing in with real credentials."""
        context = self.browser.new_context(viewport={'width': 1360, 'height': 900})
        self.contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(WAIT_MS)
        page.goto(f'{FRONTEND}/login')
        self.assertEqual(page.evaluate('localStorage.length + sessionStorage.length'), 0)
        self.assertEqual(context.cookies(), [])
        page.get_by_placeholder('correo@clinica.com o usuario').fill(self.user.username)
        page.locator('input[type="password"]').fill(PASSWORD)
        page.locator('button[type="submit"]').click()
        page.wait_for_url(lambda url: '/login' not in url)
        page.goto(f'{FRONTEND}/inventory')
        page.get_by_role('heading', name='Inventario').wait_for()
        return context, page

    def _record_writes(self, page):
        writes = []

        def remember(request):
            if request.method not in ('GET', 'OPTIONS', 'HEAD') and 'token' not in request.url:
                writes.append(request.url)

        page.on('request', remember)
        return writes

    def _destroy(self, context):
        context.close()
        self.contexts.remove(context)

    def _fill_stock_entry(self, page, code='VAC-E2E', lot='E2E-1', quantity='2'):
        page.get_by_role('button', name='Entrada de stock').click()
        search = page.get_by_placeholder('Escanea código de barras o escribe código interno')
        search.fill(code)
        search.press('Enter')
        page.get_by_placeholder('A123').fill(lot)
        page.locator('.modal input[type="number"]').first.fill(quantity)

    def _submit_stock_entry(self, page):
        page.get_by_role('button', name='Registrar recepción').click()

    def _lose_response_after_commit(self, page, route_pattern):
        reached = []

        def forward_then_lose(route):
            reached.append(route.fetch().status)
            route.abort('connectionreset')

        page.route(route_pattern, forward_then_lose)
        return reached

    def _never_reach_server(self, page, route_pattern):
        page.route(route_pattern, lambda route: route.abort('connectionreset'))

    def _open_receptions(self, page):
        page.get_by_role('button', name='Recepciones', exact=True).click()
        return page.get_by_role('dialog', name='Recepciones')

    def _confirm_dialog(self, page, text):
        page.locator('.modal-overlay').last.get_by_role('button', name=text, exact=True).click()

    def _counts(self, product=None):
        product = product or self.product
        return {
            'products': Product.objects.filter(organization=self.org).count(),
            'lots': StockLot.objects.filter(product=product).count(),
            'movements': StockMovement.objects.filter(product=product).count(),
            'stock': Product.objects.get(pk=product.pk).stock_quantity,
            'operations': StockReceptionReceipt.objects.filter(product=product).count(),
        }

    def _screenshot(self, page, name):
        page.screenshot(path=str(Path(DIST).parent / f'{name}.png'))

    def test_committed_reception_with_lost_response_is_recovered_in_a_clean_browser(self):
        context, page = self._clean_session()
        reached = self._lose_response_after_commit(page, COMPLETE_ROUTE)
        self._fill_stock_entry(page)
        self._submit_stock_entry(page)
        page.get_by_role('dialog', name='Recepciones').wait_for()
        self.assertEqual(reached, [200])
        committed = self._counts()
        self.assertEqual(committed['movements'], 1)
        self._destroy(context)

        context, page = self._clean_session()
        writes = self._record_writes(page)
        dialog = self._open_receptions(page)
        dialog.get_by_role('button', name='Vacuna Rabia').click()
        dialog.get_by_text('ya sumó stock').wait_for()
        dialog.get_by_text('libro de movimientos registró').wait_for()
        dialog.get_by_text('no es la cantidad de esta operación').wait_for()
        self._screenshot(page, 'i01-confirmada-navegador-limpio')

        self.assertEqual(writes, [])
        self.assertNotIn(str(StockReceptionReceipt.objects.get().operation_id), page.url)
        self.assertEqual(self._counts(), committed)
        self.assertEqual(committed['stock'], Decimal('2'))
        self.assertEqual(committed['products'], 1)

    def test_execution_that_never_arrived_is_completed_once_and_a_new_entry_stays_legitimate(self):
        context, page = self._clean_session()
        self._never_reach_server(page, COMPLETE_ROUTE)
        self._fill_stock_entry(page)
        self._submit_stock_entry(page)
        page.get_by_role('dialog', name='Recepciones').wait_for()
        self.assertEqual(self._counts()['movements'], 0)
        self.assertEqual(StockReceptionReceipt.objects.get().status, 'pending')
        self._destroy(context)

        context, page = self._clean_session()
        writes = self._record_writes(page)
        page.get_by_text('Tienes 1 recepción sin resolver').wait_for()
        self.assertEqual(writes, [])
        self.assertEqual(self._counts()['movements'], 0)
        page.get_by_role('button', name='Revisar recepciones').click()
        dialog = page.get_by_role('dialog', name='Recepciones')
        dialog.get_by_role('button', name='Vacuna Rabia').click()
        dialog.get_by_text('todavía no ha sumado stock').wait_for()
        self._screenshot(page, 'i01-sin-confirmar-navegador-limpio')
        self.assertEqual(writes, [])
        dialog.get_by_role('button', name='Completar esta recepción').click()
        self._confirm_dialog(page, 'Completar recepción')
        dialog.get_by_text('ya sumó stock').wait_for()

        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].endswith('/complete/'))
        self.assertEqual(self._counts()['movements'], 1)
        self.assertEqual(self._counts()['stock'], Decimal('2'))

        # Same lot and quantity, explicitly requested: a second legitimate entry.
        dialog.get_by_role('button', name='Registrar una recepción nueva').click()
        search = page.get_by_placeholder('Escanea código de barras o escribe código interno')
        search.fill('VAC-E2E')
        search.press('Enter')
        page.get_by_placeholder('A123').fill('E2E-1')
        page.locator('.modal input[type="number"]').first.fill('2')
        self._submit_stock_entry(page)
        page.get_by_text('Recepción registrada').wait_for()

        counts = self._counts()
        self.assertEqual(counts['operations'], 2)
        self.assertEqual(counts['movements'], 2)
        self.assertEqual(counts['stock'], Decimal('4'))
        self.assertEqual(counts['lots'], 1)
        self.assertEqual(counts['products'], 1)

    def test_lost_intent_response_is_closed_without_touching_stock(self):
        context, page = self._clean_session()
        reached = self._lose_response_after_commit(page, PREPARE_ROUTE)
        self._fill_stock_entry(page)
        self._submit_stock_entry(page)
        page.get_by_role('dialog', name='Recepciones').wait_for()
        self.assertEqual(reached, [201])
        self._destroy(context)

        context, page = self._clean_session()
        page.get_by_role('button', name='Revisar recepciones').click()
        dialog = page.get_by_role('dialog', name='Recepciones')
        dialog.get_by_role('button', name='Vacuna Rabia').click()
        dialog.get_by_label('Motivo para descartar').select_option('not_received')
        dialog.get_by_role('button', name='Descartar esta operación').click()
        self._confirm_dialog(page, 'Descartar operación')
        dialog.get_by_text('No sumó stock').wait_for()
        page.get_by_text('Tienes 1 recepción sin resolver').wait_for(state='detached')

        operation = StockReceptionReceipt.objects.get()
        self.assertEqual(operation.status, 'discarded')
        self.assertEqual(operation.discard_reason, 'not_received')
        self.assertEqual(operation.resolved_by, self.user)
        self.assertEqual(self._counts()['movements'], 0)
        self.assertEqual(self._counts()['stock'], Decimal('0'))

    def test_intent_that_never_arrived_leaves_nothing_and_a_new_entry_is_free(self):
        context, page = self._clean_session()
        self._never_reach_server(page, PREPARE_ROUTE)
        self._fill_stock_entry(page)
        self._submit_stock_entry(page)
        page.get_by_role('dialog', name='Recepciones').wait_for()
        self.assertEqual(StockReceptionReceipt.objects.count(), 0)
        self._destroy(context)

        context, page = self._clean_session()
        dialog = self._open_receptions(page)
        dialog.get_by_text('No hay operaciones en esta vista').wait_for()
        self.assertEqual(page.get_by_text('recepción sin resolver').count(), 0)
        dialog.get_by_role('button', name='Cerrar', exact=True).first.click()
        self._fill_stock_entry(page)
        self._submit_stock_entry(page)
        page.get_by_text('Recepción registrada').wait_for()
        self.assertEqual(self._counts()['movements'], 1)
        self.assertEqual(self._counts()['stock'], Decimal('2'))

    def test_identical_candidates_need_an_explicit_choice(self):
        other, _ = self._lot_product('Vacuna Parvo', 'PAR-E2E')
        context, page = self._clean_session()
        self._never_reach_server(page, COMPLETE_ROUTE)
        for code in ('VAC-E2E', 'PAR-E2E'):
            self._fill_stock_entry(page, code=code)
            self._submit_stock_entry(page)
            page.get_by_role('dialog', name='Recepciones').wait_for()
            page.get_by_role('dialog', name='Recepciones').get_by_role('button', name='Cerrar', exact=True).first.click()
        self._destroy(context)

        context, page = self._clean_session()
        writes = self._record_writes(page)
        page.get_by_text('Tienes 2 recepciones sin resolver').wait_for()
        page.get_by_role('button', name='Revisar recepciones').click()
        dialog = page.get_by_role('dialog', name='Recepciones')
        dialog.get_by_role('button', name='Vacuna Parvo').wait_for()
        dialog.get_by_text('Selecciona una operación').wait_for()
        self.assertEqual(dialog.get_by_role('button', name='Completar esta recepción').count(), 0)
        self._screenshot(page, 'i01-candidatas-sin-seleccion')
        self.assertEqual(writes, [])

        dialog.get_by_role('button', name='Vacuna Parvo').click()
        dialog.get_by_role('button', name='Completar esta recepción').click()
        self._confirm_dialog(page, 'Completar recepción')
        dialog.get_by_text('ya sumó stock').wait_for()

        self.assertEqual(self._counts(other)['movements'], 1)
        self.assertEqual(self._counts()['movements'], 0)
        self.assertEqual(StockReceptionReceipt.objects.get(product=self.product).status, 'pending')
        page.get_by_text('Tienes 1 recepción sin resolver').wait_for(state='attached')

    def test_execution_in_flight_cannot_become_a_second_entry_from_a_clean_browser(self):
        held = HeldExecution()
        with patch('apps.inventory.services.receive_stock', held):
            context, page = self._clean_session()
            self._fill_stock_entry(page)
            self._submit_stock_entry(page)
            self.assertTrue(held.entered.wait(WAIT_MS / 1000))
            self._destroy(context)  # The request is still running on the server.

            context, page = self._clean_session()
            page.get_by_text('Tienes 1 recepción sin resolver').wait_for()
            self.assertEqual(self._counts()['movements'], 0)

            # Registering the delivery again is refused and leads back to the review.
            page.get_by_role('button', name='Revisar recepciones').click()
            dialog = page.get_by_role('dialog', name='Recepciones')
            dialog.get_by_role('button', name='Registrar una recepción nueva').click()
            search = page.get_by_placeholder('Escanea código de barras o escribe código interno')
            search.fill('VAC-E2E')
            search.press('Enter')
            page.get_by_placeholder('A123').fill('E2E-1')
            page.locator('.modal input[type="number"]').first.fill('2')
            self._submit_stock_entry(page)
            dialog = page.get_by_role('dialog', name='Recepciones')
            dialog.wait_for()
            self.assertEqual(self._counts()['movements'], 0)

            # Completing the same operation waits for the one in flight and replays it.
            dialog.get_by_role('button', name='Vacuna Rabia').click()
            dialog.get_by_role('button', name='Completar esta recepción').click()
            self._confirm_dialog(page, 'Completar recepción')
            held.release.set()
            dialog.get_by_text('ya sumó stock').wait_for()

        counts = self._counts()
        self.assertEqual(counts['operations'], 1)
        self.assertEqual(counts['movements'], 1)
        self.assertEqual(counts['stock'], Decimal('2'))

    def test_new_product_from_the_wizard_is_not_created_again(self):
        context, page = self._clean_session()
        reached = self._lose_response_after_commit(page, COMPLETE_ROUTE)
        page.evaluate("localStorage.setItem('inventory_product_tutorial_seen', 'true')")
        page.get_by_role('button', name='Nuevo producto').click()
        page.locator('[data-demo="mode-simple"]').click()
        page.locator('[data-demo="product-name"] input').fill('Producto Asistente')
        page.get_by_role('button', name='Descripción y receta médica').click()
        page.get_by_label('Requiere control de lotes y caducidad').check()
        page.get_by_placeholder('A123').fill('WIZ-1')
        page.locator('.modal input[type="number"][min="1"]').first.fill('3')
        page.locator('[data-demo="sale-0"] input[placeholder="0.00"]').first.fill('50')
        page.get_by_role('button', name='Crear producto').click()
        page.get_by_role('button', name='Confirmar y crear').click()
        page.get_by_role('dialog', name='Recepciones').wait_for()
        self.assertEqual(reached, [200])
        self._destroy(context)

        created = Product.objects.get(organization=self.org, name='Producto Asistente')
        committed = self._counts(created)

        context, page = self._clean_session()
        writes = self._record_writes(page)
        dialog = self._open_receptions(page)
        dialog.get_by_role('button', name='Producto Asistente').click()
        dialog.get_by_text('ya sumó stock').wait_for()

        self.assertEqual(writes, [])
        self.assertEqual(self._counts(created), committed)
        self.assertEqual(committed['movements'], 1)
        self.assertEqual(committed['stock'], Decimal('3'))
        self.assertEqual(Product.objects.filter(organization=self.org, name='Producto Asistente').count(), 1)
