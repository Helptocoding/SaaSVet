"""Orden 4, I03: comprobación visual del reporte de conflictos en la vista previa y el resultado.

Chromium recorre el asistente real con un CSV de inventario que choca con 130 productos
existentes (110 coincidencias altas y 20 por revisar) y trae 5 nuevos. En la vista previa y
en el resultado se recorre el detalle página a página, sin huecos ni duplicados, y se guardan
capturas junto a la build. Se ejecuta igual que el navegador de I01:

    ORDEN4_BROWSER_DIST=<dir> python scripts/orden4_isolated.py test <este módulo> --keepdb --noinput
"""
import importlib.util
import os
import re
from decimal import Decimal
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest import skipUnless

from django.core.cache import caches
from django.test import LiveServerTestCase, override_settings

from apps.core.models import UserRole
from apps.imports.models import ImportJob
from apps.imports.tests.test_owner_pet_import import _seed_roles
from apps.inventory.models import Product
from apps.inventory.tests.test_order4_reception_browser import (
    API_PORT, DIST, FRONTEND, FRONTEND_PORT, PASSWORD, WAIT_MS, SinglePageHandler,
)
from apps.organizations.models import Organization
from apps.users.models import User

HIGH, UNCERTAIN, NEW = 110, 20, 5
CONFLICTS = HIGH + UNCERTAIN


def _csv():
    lines = ['Producto,Código,Unidad,Existencia,Precio']
    for i in range(1, CONFLICTS + 1):
        name = f'Producto {i:03d}' if i <= HIGH else f'Otro nombre {i:03d}'
        lines.append(f'{name},I03-{i:03d},pieza,1,10.00')
    lines += [f'Nuevo {i},I03-N{i},pieza,2,15.00' for i in range(1, NEW + 1)]
    return ('\n'.join(lines) + '\n').encode('utf-8')


@skipUnless(importlib.util.find_spec('playwright') and DIST, 'Requiere Playwright y ORDEN4_BROWSER_DIST.')
@override_settings(CORS_ALLOWED_ORIGINS=[FRONTEND])
class ConflictReportBrowserTests(LiveServerTestCase):
    host = '127.0.0.1'
    port = API_PORT

    @classmethod
    def setUpClass(cls):
        # Igual que en I01: Playwright deja un event loop en este hilo.
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
        self.org = Organization.objects.create(name='Clínica conflictos', timezone='UTC', tax_rate=Decimal('0'))
        roles = _seed_roles(self.org)
        self.user = User.objects.create_user(
            username='browser_i03', password=PASSWORD, organization=self.org, role='ADMIN',
        )
        UserRole.objects.get_or_create(user=self.user, role=roles['ADMIN'])
        Product.objects.bulk_create([
            Product(organization=self.org, name=f'Producto {i:03d}', internal_code=f'I03-{i:03d}', base_unit='piece')
            for i in range(1, CONFLICTS + 1)
        ])
        self.context = self.browser.new_context(viewport={'width': 1360, 'height': 900})
        self.addCleanup(self.context.close)

    def _shot(self, page, name, locator=None):
        """Captura de la pantalla visible (legible), con `locator` desplazado a la vista."""
        if locator is not None:
            locator.scroll_into_view_if_needed()
        page.screenshot(path=str(Path(DIST).parent / f'{name}.png'))

    def _walk_detail(self, page, prefix):
        """Recorre las tres páginas del detalle y devuelve las filas vistas, en orden."""
        detail = page.get_by_role('region', name='Detalle de conflictos')
        detail.get_by_text(f'Coincidencias altas: {HIGH} · Por revisar: {UNCERTAIN}').wait_for()
        detail.get_by_role('button', name='Ver detalle').click()
        seen = []
        for number, size in ((1, 50), (2, 50), (3, 30)):
            showing = detail.get_by_text(f'Mostrando {size} de {CONFLICTS} · Página {number}')
            showing.wait_for()
            rows = [int(re.search(r'\d+', text).group()) for text in
                    detail.get_by_text(re.compile(r'^Fila #\d+$')).all_inner_texts()]
            self.assertEqual(len(rows), size, f'{prefix} página {number}')
            seen.extend(rows)
            # Las mismas tarjetas que la muestra: nada de claves internas en pantalla.
            self.assertEqual(detail.get_by_text('En tu archivo', exact=True).count(), size)
            self.assertEqual(detail.get_by_text('Ya registrado', exact=True).count(), size)
            self.assertEqual(detail.get_by_text(re.compile(r'internal_code:|name:|public_id')).count(), 0)
            self._shot(page, f'{prefix}-detalle-pagina-{number}', showing)
            self._shot(page, f'{prefix}-detalle-pagina-{number}-final',
                       detail.get_by_role('button', name='Siguiente'))
            if number < 3:
                detail.get_by_role('button', name='Siguiente').click()
        # Las 20 por revisar caen en la última página y dicen por qué: código con otro nombre.
        self.assertEqual(
            detail.get_by_text('Ya existe un producto con este código interno.', exact=True).count(), UNCERTAIN)
        self.assertTrue(detail.get_by_role('button', name='Siguiente').is_disabled())
        detail.get_by_role('button', name='Anterior').click()
        detail.get_by_text(f'Mostrando 50 de {CONFLICTS} · Página 2').wait_for()
        return seen

    def test_preview_and_result_show_the_full_report_page_by_page(self):
        page = self.context.new_page()
        page.set_default_timeout(WAIT_MS)
        page.goto(f'{FRONTEND}/login')
        page.get_by_placeholder('correo@clinica.com o usuario').fill(self.user.username)
        page.locator('input[type="password"]').fill(PASSWORD)
        page.locator('button[type="submit"]').click()
        page.wait_for_url(lambda url: '/login' not in url)

        page.goto(f'{FRONTEND}/imports')
        page.get_by_role('button', name='Productos / Inventario').click()
        page.locator('input[type="file"]').set_input_files(
            {'name': 'conflictos-i03.csv', 'mimeType': 'text/csv', 'buffer': _csv()})
        page.get_by_role('button', name='Subir y continuar').click()
        page.get_by_role('button', name='Continuar').click()

        page.get_by_role('heading', name='Detalle completo de conflictos').wait_for()
        self._shot(page, 'i03-vista-previa')
        # La muestra no atribuye a «nombre» conflictos que son por código.
        uncertain_title = page.get_by_text(f'Posibles duplicados por revisar ({UNCERTAIN})')
        self.assertEqual(uncertain_title.count(), 1)
        self._shot(page, 'i03-vista-previa-por-revisar', uncertain_title)
        preview_rows = self._walk_detail(page, 'i03-vista-previa')
        self.assertEqual(len(preview_rows), CONFLICTS)
        self.assertEqual(len(set(preview_rows)), CONFLICTS)

        page.get_by_role('button', name='Confirmar importación').click()
        page.get_by_role('button', name='Importar', exact=True).click()
        page.get_by_role('button', name='Importar otro archivo').wait_for()
        omitted_card = page.get_by_text('Posibles duplicados omitidos', exact=True).locator('..')
        self.assertIn(str(CONFLICTS), omitted_card.inner_text())
        self._shot(page, 'i03-resultado')
        result_rows = self._walk_detail(page, 'i03-resultado')
        self.assertEqual(sorted(result_rows), sorted(preview_rows))

        job = ImportJob.objects.get(organization=self.org)
        self.assertEqual(job.status, ImportJob.STATUS_COMMITTED)
        self.assertEqual(job.result['conflicts_high'], HIGH)
        self.assertEqual(job.result['conflicts_uncertain'], UNCERTAIN)
        self.assertEqual(Product.objects.filter(organization=self.org).count(), CONFLICTS + NEW)
        self.assertEqual(Product.objects.get(internal_code='I03-111').name, 'Producto 111')
