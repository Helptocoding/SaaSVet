"""
ADR p49 — reset del tenant demo.

Cubre las dos garantías de mayor valor sin correr el seed completo (lento):

1. P0 — `_purge` borra `MetricAdjustment` ANTES que `Invoice`. Sin el fix, el
   FK PROTECT `MetricAdjustment.source_invoice` hace que el DELETE de Invoice
   lance `ProtectedError` (una devolución de un visitante dejaba la demo sin
   poder resetearse). El test crea ese escenario y prueba que el purge no falla.

2. Ventana de mantenimiento — `DemoResetGate` / `_demo_reset_blocks` y el
   embedding en `HybridPermission`: escritura de la org demo durante un reset →
   503; lectura demo, escritura de tenant real, y demo sin flag → no se bloquea.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from apps.analytics.models import MetricAdjustment
from apps.billing.models import Invoice
from apps.core.demo_reset import DEMO_RESET_FLAG_KEY
from apps.core.management.commands.seed_demo_clinic import Command
from apps.core.permissions import (
    DemoResetGate,
    DemoResetInProgress,
    HybridPermission,
    _demo_reset_blocks,
)
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet

User = get_user_model()


class PurgeP0Tests(TestCase):
    """El purge no debe romperse por el FK PROTECT de MetricAdjustment→Invoice."""

    def setUp(self):
        # Organization.objects.create dispara initialize_organization →
        # OrganizationSettings + Owner/Pet genéricos + roles RBAC del sistema.
        self.org = Organization.objects.create(name="Demo", is_demo=True)

    def test_purge_after_refund_metric_adjustment_no_protected_error(self):
        owner = Owner.objects.create(
            organization=self.org, name="Cliente Real", phone="5512345678",
        )
        invoice = Invoice.objects.create(
            organization=self.org, invoice_type="direct_sale", owner=owner,
            status="draft", tax_rate=Decimal("0"),
        )
        # Lo que crea process_refund: ajuste con source_invoice PROTECT.
        MetricAdjustment.objects.create(
            organization=self.org, date=timezone.localdate(),
            metric_name="revenue_paid", delta=Decimal("-10.00"),
            source_invoice=invoice, reason="test refund",
        )

        # No debe lanzar ProtectedError (ese era el P0).
        Command()._purge(self.org, full=False)

        self.assertEqual(Invoice.all_objects.filter(organization=self.org).count(), 0)
        self.assertEqual(MetricAdjustment.all_objects.filter(organization=self.org).count(), 0)
        # El cliente real se borra…
        self.assertEqual(
            Owner.all_objects.filter(organization=self.org, is_generic=False).count(), 0
        )
        # …pero los genéricos se conservan (reset, no delete).
        self.assertTrue(
            Owner.all_objects.filter(organization=self.org, is_generic=True).exists()
        )
        self.assertTrue(
            Pet.all_objects.filter(organization=self.org, is_generic=True).exists()
        )


class DemoResetGateTests(TestCase):
    """La ventana de mantenimiento: 503 solo en escrituras de la org demo activa."""

    def setUp(self):
        cache.delete(DEMO_RESET_FLAG_KEY)
        self.factory = APIRequestFactory()
        self.demo_org = Organization.objects.create(name="Demo", is_demo=True)
        self.real_org = Organization.objects.create(name="Real")  # is_demo=False
        self.demo_user = User.objects.create_user(
            username="demo1", email="demo1@x.com", password="Pass1234!",
            role="ADMIN", organization=self.demo_org,
        )
        self.real_user = User.objects.create_user(
            username="real1", email="real1@x.com", password="Pass1234!",
            role="ADMIN", organization=self.real_org,
        )

    def tearDown(self):
        cache.delete(DEMO_RESET_FLAG_KEY)

    def _req(self, method, user):
        req = getattr(self.factory, method)("/x/")
        req.user = user
        return req

    # ---- _demo_reset_blocks matrix ----------------------------------------
    def test_demo_write_with_flag_blocks(self):
        cache.set(DEMO_RESET_FLAG_KEY, True, timeout=60)
        self.assertTrue(_demo_reset_blocks(self._req("post", self.demo_user)))

    def test_demo_read_with_flag_does_not_block(self):
        cache.set(DEMO_RESET_FLAG_KEY, True, timeout=60)
        self.assertFalse(_demo_reset_blocks(self._req("get", self.demo_user)))

    def test_demo_write_without_flag_does_not_block(self):
        self.assertFalse(_demo_reset_blocks(self._req("post", self.demo_user)))

    def test_real_tenant_write_with_flag_does_not_block(self):
        cache.set(DEMO_RESET_FLAG_KEY, True, timeout=60)
        self.assertFalse(_demo_reset_blocks(self._req("post", self.real_user)))

    # ---- gate + embedding -------------------------------------------------
    def test_gate_raises_503_for_demo_write_during_reset(self):
        cache.set(DEMO_RESET_FLAG_KEY, True, timeout=60)
        with self.assertRaises(DemoResetInProgress) as ctx:
            DemoResetGate().has_permission(self._req("post", self.demo_user), view=None)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.default_code, "demo_resetting")

    def test_gate_allows_demo_read_during_reset(self):
        cache.set(DEMO_RESET_FLAG_KEY, True, timeout=60)
        self.assertTrue(
            DemoResetGate().has_permission(self._req("get", self.demo_user), view=None)
        )

    def test_hybrid_permission_embeds_gate(self):
        """Las views RBAC pisan el DEFAULT; el check va embebido en HybridPermission."""
        cache.set(DEMO_RESET_FLAG_KEY, True, timeout=60)
        with self.assertRaises(DemoResetInProgress):
            HybridPermission().has_permission(self._req("post", self.demo_user), view=None)
