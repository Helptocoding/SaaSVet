"""Gate: toda vista de escritura de platform declara un throttle con scope propio.

Las cuatro vistas de la orden 2 nacieron solo con el límite global por usuario
(audit run-1, fase 8.1), a diferencia de crear organización y resetear
contraseña. Una vista nueva que escriba sin scope pone esto en rojo.
"""
from django.conf import settings
from django.test import SimpleTestCase
from rest_framework.throttling import ScopedRateThrottle

from apps.platform import urls as platform_urls

READ_ONLY = {'PlatformOrganizationHistoryView'}


class PlatformWriteViewsAreScopedThrottled(SimpleTestCase):
    def test_every_write_view_has_a_configured_scope(self):
        rates = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']
        for pattern in platform_urls.urlpatterns:
            view = pattern.callback.view_class
            if view.__name__ in READ_ONLY:
                continue
            with self.subTest(view=view.__name__):
                self.assertIn(ScopedRateThrottle, view.throttle_classes)
                self.assertIn(getattr(view, 'throttle_scope', None), rates)
