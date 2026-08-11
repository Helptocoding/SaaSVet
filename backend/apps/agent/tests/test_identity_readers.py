"""P0-26 — Los *lectores* de identidad del agente resuelven por clave normalizada.

Bloqueador de la revisión OCR (decisión §4.11, familia E del inventario §4.7.4).

El inventario original cubría **escrituras**. El punto ciego era de categoría:
`agent/services.py` tiene dos lecturas de producción que resuelven identidad por
teléfono, y ambas comparaban un valor **normalizado** (el del `wa_id`) contra
`Owner.phone` **en crudo**.

Un expediente guardado como ``"55 1234 5678"`` y otro como ``"5512345678"``
normalizan a la misma clave: INV-C dice **ambiguo**. La igualdad cruda solo
encontraba el segundo → el lector veía **una** coincidencia y vinculaba el
contacto a esa fila. Una elección automática entre duplicados históricos.

Que el nivel resultante sea `phone_match` (que no autoriza nada por sí solo) no
lo hace inocuo: ese vínculo es el punto de partida de la promoción a
`confirmed_in_chat`, y arrastra el expediente equivocado.

`TestCase` (rollback) y no `TransactionTestCase`: estas vías son **lecturas**
—no toman lock ni necesitan commits reales— y `ChannelAccount.external_account_id`
es único globalmente, así que depender del truncado entre pruebas las volvía
sensibles al orden.
"""
from django.test import TestCase

from apps.agent.models import ContactIdentity
from apps.agent.services import resolve_contact_identity
from apps.channels.models import ChannelAccount
from apps.organizations.models import Organization
from apps.patients.models import Owner

WA_ID = '5215512345678'
PHONE_KEY = '5512345678'


class IdentityReaderTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Lectores", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="999000111",
        )

    def contact(self):
        return resolve_contact_identity(self.channel, WA_ID)

    # --- E1: creación de ContactIdentity (primer mensaje del número) --------
    def test_single_candidate_in_another_format_still_matches(self):
        """Sin cambio de comportamiento donde el dato está limpio…

        …salvo que ahora también encuentra al expediente guardado con espacios,
        que la igualdad cruda se perdía en silencio (falso «no registrado» que
        empujaba al cliente a un alta duplicada).
        """
        owner = Owner.objects.create(
            organization=self.org, name="Ana López", phone='55 1234 5678',
        )
        contact = self.contact()
        self.assertEqual(contact.owner_id, owner.pk)
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_PHONE_MATCH,
        )
        self.assertFalse(contact.is_ambiguous)

    def test_no_candidate_stays_unknown(self):
        contact = self.contact()
        self.assertIsNone(contact.owner_id)
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_UNKNOWN,
        )
        self.assertFalse(contact.is_ambiguous)

    def test_duplicate_visible_only_after_normalizing_is_ambiguous(self):
        """El caso exacto del bloqueador: crudo veía uno, normalizado ve dos."""
        Owner.objects.create(
            organization=self.org, name="Ana López", phone='55 1234 5678',
        )
        Owner.objects.create(
            organization=self.org, name="Ana Lopez", phone=PHONE_KEY,
        )
        contact = self.contact()
        self.assertIsNone(contact.owner_id, "No se vincula ningún expediente.")
        self.assertTrue(contact.is_ambiguous)
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_UNKNOWN,
            "El nivel NO sube ante ambigüedad.",
        )

    def test_generic_owner_is_never_a_candidate(self):
        generic = Owner.objects.for_organization(self.org).get(is_generic=True)
        generic.phone = PHONE_KEY
        generic.save()
        contact = self.contact()
        self.assertIsNone(contact.owner_id)
        self.assertFalse(contact.is_ambiguous)

    def test_foreign_organization_record_is_invisible(self):
        other = Organization.objects.create(name="Ajena", timezone="UTC")
        Owner.objects.create(organization=other, name="Ajeno", phone=PHONE_KEY)
        contact = self.contact()
        self.assertIsNone(contact.owner_id)
        self.assertFalse(contact.is_ambiguous)

    # --- E2: _rematch_owner (cada mensaje posterior) -----------------------
    def test_rematch_links_when_the_record_appears(self):
        contact = self.contact()
        self.assertIsNone(contact.owner_id)
        owner = Owner.objects.create(
            organization=self.org, name="Ana", phone='55 1234 5678',
        )
        contact = self.contact()  # segundo mensaje
        self.assertEqual(contact.owner_id, owner.pk)

    def test_rematch_marks_ambiguous_without_linking(self):
        contact = self.contact()
        Owner.objects.create(organization=self.org, name="Ana López", phone='55 1234 5678')
        Owner.objects.create(organization=self.org, name="Ana Lopez", phone=PHONE_KEY)

        contact = self.contact()
        self.assertIsNone(contact.owner_id)
        self.assertTrue(contact.is_ambiguous)
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_UNKNOWN,
        )

    def test_ambiguity_never_clears_auto_rematch_blocked(self):
        """Ese flag solo lo limpia una vía de promoción auditada; un lector no lo es."""
        contact = self.contact()
        contact.auto_rematch_blocked = True
        contact.save(update_fields=['auto_rematch_blocked'])

        Owner.objects.create(organization=self.org, name="Ana López", phone='55 1234 5678')
        Owner.objects.create(organization=self.org, name="Ana Lopez", phone=PHONE_KEY)

        contact = self.contact()
        self.assertTrue(contact.auto_rematch_blocked)
        self.assertIsNone(contact.owner_id)

    def test_blocked_contact_is_not_rematched_even_with_one_candidate(self):
        contact = self.contact()
        contact.auto_rematch_blocked = True
        contact.save(update_fields=['auto_rematch_blocked'])
        Owner.objects.create(organization=self.org, name="Ana", phone=PHONE_KEY)

        contact = self.contact()
        self.assertIsNone(contact.owner_id)
        self.assertTrue(contact.auto_rematch_blocked)

    def test_ambiguous_contact_links_once_the_data_is_ordered(self):
        """Un contacto ambiguo no se «desambigua» solo, pero tampoco queda preso.

        Que el conteo cambie es información del dominio, no una decisión del
        lector: cuando alguien ordena el duplicado y queda un solo candidato,
        el siguiente mensaje sí vincula.
        """
        dup = Owner.objects.create(
            organization=self.org, name="Ana López", phone='55 1234 5678',
        )
        keeper = Owner.objects.create(
            organization=self.org, name="Ana Lopez", phone=PHONE_KEY,
        )
        contact = self.contact()
        self.assertTrue(contact.is_ambiguous)

        # Una persona ordena el dato: corrige el teléfono del duplicado.
        dup.phone = '5599999999'
        dup.save()

        contact = self.contact()
        self.assertEqual(contact.owner_id, keeper.pk)
        self.assertFalse(contact.is_ambiguous)
        self.assertEqual(
            contact.verification_level, ContactIdentity.VERIFICATION_PHONE_MATCH,
        )
