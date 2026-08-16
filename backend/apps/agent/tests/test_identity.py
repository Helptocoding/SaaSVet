"""
test_identity.py — É-F1 PR-11: verificación de identidad tolerante (UX-03).
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.agent import identity
from apps.agent.models import ContactIdentity
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet


class IdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Id Org", timezone="UTC")
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Ana Torres", phone="5511223344",
        )
        Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Kira",
            species="perro", birth_date="2021-01-01",
        )

    def _contact(self, level=ContactIdentity.VERIFICATION_PHONE_MATCH):
        return ContactIdentity.objects.create(
            organization=self.org, external_id="5215511223344",
            owner=self.owner, verification_level=level,
        )

    # Los matchers son PUROS desde el plan de continuidad (D28): devuelven un
    # booleano y no tocan estado. `_promote` tiene un solo llamador, el servicio
    # de evidencia — ver `test_identity_evidence.py`.

    def test_exact_matcher_accepts_the_registered_name(self):
        self.assertTrue(identity.matches_pet_name_exact("Kira", "Kira"))

    def test_exact_matcher_accepts_a_complete_token_of_a_compound_name(self):
        # «cita para Luna» con «Luna Bella» registrada tiene que funcionar: el
        # subconjunto de tokens existe porque el reto rechazaba el nombre de pila
        # y mandaba a handoff a clientes legítimos.
        self.assertTrue(identity.matches_pet_name_exact("Luna", "Luna Bella"))

    def test_exact_matcher_rejects_a_typo(self):
        # Lo que se elimina del modo pasivo es la distancia de edición: de ahí
        # salían los falsos positivos en texto libre.
        self.assertFalse(identity.matches_pet_name_exact("Kyra", "Kira"))

    def test_tolerant_matcher_accepts_a_typo(self):
        # Legítimo solo cuando el cliente RESPONDE a la pregunta por el nombre.
        self.assertTrue(identity.matches_pet_name_tolerant("Kyra", "Kira"))

    def test_matchers_never_touch_state(self):
        contact = self._contact()
        identity.matches_pet_name_tolerant("Kira", "Kira")
        identity.matches_pet_name_exact("Kira", "Kira")
        contact.refresh_from_db()
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_PHONE_MATCH,
        )

    def test_owner_name_is_no_longer_a_verification_factor(self):
        # D4b · el sistema conoce ese nombre y se lo enseña al staff en la
        # bandeja, así que no prueba nada sobre quien escribe. La función se
        # eliminó para que un cambio futuro no reabra el factor por accidente.
        self.assertFalse(hasattr(identity, 'try_verify_by_owner_name'))

    def test_punctuation_is_a_token_boundary(self):
        # «cita para Kira, por favor» dejaba el token `kira,`, que no es igual a
        # `kira` — y el modo pasivo exige igualdad de token completo.
        self.assertEqual(identity._norm("cita para Kira, por favor"),
                         "cita para kira por favor")

    def test_verification_expiry(self):
        contact = self._contact(ContactIdentity.VERIFICATION_CONFIRMED)
        contact.verified_at = timezone.now()
        contact.save(update_fields=["verified_at"])
        self.assertTrue(identity.is_verification_current(contact))

        contact.verified_at = timezone.now() - timedelta(days=200)
        contact.save(update_fields=["verified_at"])
        self.assertFalse(identity.is_verification_current(contact))

    def test_levenshtein_helper(self):
        self.assertTrue(identity._levenshtein_le_1("kira", "kyra"))   # sub
        self.assertTrue(identity._levenshtein_le_1("kira", "kir"))    # del
        self.assertTrue(identity._levenshtein_le_1("kira", "kiraa"))  # ins
        self.assertFalse(identity._levenshtein_le_1("kira", "milo"))  # lejos


class RematchBlockedClearingTests(TestCase):
    """`auto_rematch_blocked` (levantado por `reset_contact_identity`) solo debe
    bajarse por una vía confiable: verificación completa o vinculación
    manual — nunca porque el contacto volvió a escribir."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Clear Flag Org", timezone="UTC")
        cls.owner = Owner.objects.create(
            organization=cls.org, name="Ana Torres", phone="5511229900",
        )
        Pet.objects.create(
            organization=cls.org, owner=cls.owner, name="Kira",
            species="perro", birth_date="2021-01-01",
        )

    def _blocked_contact(self, **extra):
        return ContactIdentity.objects.create(
            organization=self.org, external_id="5215511229900",
            verification_level=ContactIdentity.VERIFICATION_PHONE_MATCH,
            auto_rematch_blocked=True, **extra,
        )

    def test_promote_clears_the_flag_on_full_verification(self):
        contact = self._blocked_contact(owner=self.owner)
        identity._promote(contact)
        contact.refresh_from_db()
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_CONFIRMED,
        )
        self.assertFalse(contact.auto_rematch_blocked)

    def test_link_self_registered_clears_the_flag(self):
        contact = self._blocked_contact()
        identity.link_self_registered(contact, self.owner)
        contact.refresh_from_db()
        self.assertEqual(contact.owner_id, self.owner.pk)
        self.assertFalse(contact.auto_rematch_blocked)

    def test_link_family_clears_the_flag(self):
        contact = self._blocked_contact()
        identity.link_family(contact, self.owner)
        contact.refresh_from_db()
        self.assertEqual(contact.owner_id, self.owner.pk)
        self.assertFalse(contact.auto_rematch_blocked)
