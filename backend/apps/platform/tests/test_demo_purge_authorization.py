"""La exención de preservación se abre SOLO para una organización demo.

Origen: la política de preservación de documentos (`deletion_guards`) y el reset
automático de la demo (ADR p49) se contradecían de frente. `_protect_document`
prohibía todo borrado físico de Invoice/Prescription sin excepción, y el reset
existe justamente para borrarlos cada media hora — así que la demo dejó de poder
resetearse (`test_demo_reset::PurgeP0Tests` falló con
`ProtectedError: Documento conservado`).

La preservación existe por retención legal de documentos REALES
(NOM-007/NOM-046, cinco años). Una demo no tiene ese deber. Así que la política
no se debilitó: se delimitó.

Lo que estas pruebas protegen es la frontera de esa delimitación. Si alguna vez
la autorización se pudiera abrir para un tenant real, la preservación habría
dejado de existir en silencio — y eso es exactamente lo que no debe poder pasar.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Checkout, Invoice
from apps.organizations.models import Organization
from apps.patients.models import Owner
from apps.platform.deletion_guards import (
    authorize_demo_purge,
    authorize_physical_deletion,
    demo_purge_authorized,
)


def _refuses_delete(case, obj):
    """Afirma que el guard rechaza borrar `obj`, y deja seguir consultando.

    `Collector.delete()` abre su atomic con `savepoint=False`: un ProtectedError
    desde `pre_delete` marca la transacción del test y toda consulta posterior
    muere con TransactionManagementError. Este envoltorio aporta el savepoint
    que falta, y por eso se puede comprobar después que la fila sobrevivió.
    """
    with case.assertRaises(ProtectedError):
        with transaction.atomic():
            obj.delete()


def _invoice_for(org):
    owner = Owner.objects.create(organization=org, name="Cliente", phone="5512345678")
    checkout = Checkout.objects.create(
        organization=org, origin='direct_sale', kind='direct_sale',
        lifecycle='completed', completion_kind='posted_unpaid', customer=owner,
        completed_at=timezone.now(),
    )
    return Invoice.objects.create(
        checkout=checkout, organization=org, invoice_type="direct_sale", owner=owner,
        status="posted", posted_at=timezone.now(), tax_rate=Decimal("0"),
    )


class DemoPurgeAuthorizationBoundaryTests(TestCase):
    def setUp(self):
        self.demo = Organization.objects.create(name="Demo", is_demo=True)
        self.real = Organization.objects.create(name="Clínica real", timezone="UTC")

    def test_a_real_organization_cannot_be_authorized(self):
        """La garantía central: la puerta se niega a abrirse para un tenant."""
        with self.assertRaises(ValueError):
            with authorize_demo_purge(self.real):
                pass  # pragma: no cover — no debe llegar aquí

    def test_authorizing_the_demo_allows_deleting_its_documents(self):
        invoice = _invoice_for(self.demo)
        with authorize_demo_purge(self.demo):
            invoice.delete()
        self.assertFalse(Invoice.all_objects.filter(pk=invoice.pk).exists())

    def test_a_real_invoice_is_preserved_even_while_the_demo_is_authorized(self):
        """La autorización es por organización, no un interruptor global."""
        real_invoice = _invoice_for(self.real)
        with authorize_demo_purge(self.demo):
            _refuses_delete(self, real_invoice)
        self.assertTrue(Invoice.all_objects.filter(pk=real_invoice.pk).exists())

    def test_documents_are_preserved_outside_any_authorization(self):
        """Sin autorización el guard sigue cerrado, también para la demo."""
        invoice = _invoice_for(self.demo)
        _refuses_delete(self, invoice)
        self.assertTrue(Invoice.all_objects.filter(pk=invoice.pk).exists())

    def test_the_authorization_does_not_leak_past_its_block(self):
        first = _invoice_for(self.demo)
        with authorize_demo_purge(self.demo):
            first.delete()
        second = _invoice_for(self.demo)
        with self.assertRaises(ProtectedError):
            second.delete()

    def test_a_failing_purge_still_closes_the_authorization(self):
        """El `finally` del context manager no es decorativo."""
        with self.assertRaises(RuntimeError):
            with authorize_demo_purge(self.demo):
                raise RuntimeError('purga interrumpida')
        invoice = _invoice_for(self.demo)
        with self.assertRaises(ProtectedError):
            invoice.delete()

    def test_the_demo_organization_row_itself_is_authorized(self):
        """`full=True` borra la propia Organization; el guard la cubre aparte."""
        with authorize_demo_purge(self.demo):
            # No se borra de verdad (arrastraría settings y roles del tenant);
            # basta comprobar que el guard de Organization no la rechaza.
            from apps.platform.deletion_guards import _demo_purge_authorized
            self.assertTrue(_demo_purge_authorized(Organization, self.demo))
            self.assertFalse(_demo_purge_authorized(Organization, self.real))


class DemoPurgeDecoratorTests(TestCase):
    """El decorador no debe cambiar la semántica de error de quien decora."""

    def setUp(self):
        self.demo = Organization.objects.create(name="Demo dec", is_demo=True)
        self.real = Organization.objects.create(name="Real dec", timezone="UTC")

    def test_a_non_demo_organization_reaches_the_wrapped_guard(self):
        """No autoriza nada y DEJA PASAR: el guard del comando debe explicar.

        Si el decorador lanzase su propio ValueError aquí, el `CommandError`
        de `seed_demo_clinic._purge` —que es el que dice qué pasó y por qué—
        nunca llegaría a verse.
        """
        seen = {}

        @demo_purge_authorized
        def _fake_purge(self_, organization):
            seen['called_with'] = organization.pk
            raise AssertionError('guard del comando')

        with self.assertRaises(AssertionError):
            _fake_purge(None, self.real)
        self.assertEqual(seen['called_with'], self.real.pk)

    def test_a_demo_organization_runs_inside_the_authorization(self):
        invoice = _invoice_for(self.demo)

        @demo_purge_authorized
        def _fake_purge(self_, organization):
            invoice.delete()

        _fake_purge(None, self.demo)
        self.assertFalse(Invoice.all_objects.filter(pk=invoice.pk).exists())


class PhysicalDeletionAuthorizationTests(TestCase):
    """La otra puerta: `authorize_physical_deletion`, por fila."""

    def test_it_authorizes_exactly_one_row(self):
        org = Organization.objects.create(name="Org fila", timezone="UTC")
        a = Owner.objects.create(organization=org, name="A", phone="5512345678")
        b = Owner.objects.create(organization=org, name="B", phone="5512345679")
        with authorize_physical_deletion(a):
            _refuses_delete(self, b)
            a.delete()
        self.assertFalse(Owner.objects.filter(pk=a.pk).exists())
        self.assertTrue(Owner.objects.filter(pk=b.pk).exists())

    def test_it_does_not_authorize_documents(self):
        """Owner/Pet/Organization sí; Invoice/Prescription NO tienen esta vía.

        Un documento solo se borra físicamente dentro de una purga de demo. Que
        esta puerta no lo abra es deliberado: si lo abriera, la retención legal
        dependería de que nadie la invocara.
        """
        org = Organization.objects.create(name="Org doc", timezone="UTC")
        invoice = _invoice_for(org)
        with authorize_physical_deletion(invoice):
            _refuses_delete(self, invoice)
        self.assertTrue(Invoice.all_objects.filter(pk=invoice.pk).exists())
