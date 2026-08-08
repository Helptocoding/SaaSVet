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

    def test_implicit_verification_on_exact_pet_name(self):
        contact = self._contact()
        self.assertTrue(
            identity.try_verify_by_pet_name(contact, "quiero cita para Kira")
        )
        contact.refresh_from_db()
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_CONFIRMED,
        )
        self.assertIsNotNone(contact.verified_at)

    def test_implicit_with_article(self):
        contact = self._contact()
        self.assertTrue(
            identity.try_verify_by_pet_name(contact, "es para la Kira")
        )

    def test_typo_distance_one_matches(self):
        contact = self._contact()
        # "Kyra" ≈ "Kira" (sustitución), nombre ≥4 letras.
        self.assertTrue(
            identity.try_verify_by_pet_answer(contact, "Kyra")
        )

    def test_wrong_name_does_not_verify(self):
        contact = self._contact()
        self.assertFalse(
            identity.try_verify_by_pet_answer(contact, "Firulais")
        )
        contact.refresh_from_db()
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_PHONE_MATCH,
        )

    def test_owner_name_second_factor(self):
        contact = self._contact()
        self.assertTrue(
            identity.try_verify_by_owner_name(contact, "Ana Torres")
        )

    def test_unknown_contact_never_verifies(self):
        contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215599990000",
        )  # sin owner
        self.assertFalse(identity.try_verify_by_pet_name(contact, "Kira"))

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
        self.assertTrue(
            identity.try_verify_by_pet_name(contact, "cita para Kira")
        )
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
