"""El vínculo de identidad no sobrevive a su premisa (bug de piloto 2026-08-12).

Reportado depurando con un número real: se crea un cliente por WhatsApp, se le
cambia el teléfono en la ficha de la mascota, y **el agente sigue tratando a
quien escribe como el cliente original** — lo saluda con su nombre y le ofrece
sus mascotas.

La causa: `ContactIdentity.owner` es una FK que se resolvía la primera vez y no
se volvía a mirar nunca. `patients` no conoce `ContactIdentity`, así que
cambiar `Owner.phone` no avisaba a nadie.

En producción es peor que un incordio de depuración: las operadoras **reciclan
números**. El cliente A cambia de número, la clínica actualiza su ficha, y quien
herede ese número acaba viendo las mascotas de A y gestionando sus citas. Y ahí
nadie tiene un botón de reset — el de la bandeja es herramienta de depuración,
no producto.
"""
from django.test import TestCase

from apps.agent import identity
from apps.agent.models import ContactIdentity
from apps.agent.signals import unlink_stale_phone_identities
from apps.channels.models import ChannelAccount
from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.patients.services import change_owner_phone

WA = '5219371651868'
PHONE = '9371651868'
OTHER = '5500000001'


class StalePhoneIdentityTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Stale", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="stale-770")
        self.owner = Owner.objects.create(
            organization=self.org, name="Andres", phone=PHONE)
        Pet.objects.create(organization=self.org, owner=self.owner,
                           name="Luna", species="canino", birth_date="2021-01-01")

    def _contact(self, linked_via, level):
        contact = ContactIdentity.objects.create(
            organization=self.org, external_id=WA, phone_normalized=PHONE,
            owner=self.owner, verification_level=level, linked_via=linked_via)
        return contact

    # -- lo que se rompe ---------------------------------------------------
    def test_self_register_link_dies_when_the_phone_changes(self):
        """El caso exacto del reporte."""
        contact = self._contact(ContactIdentity.LINKED_SELF_REGISTER,
                                ContactIdentity.VERIFICATION_CONFIRMED)

        change_owner_phone(self.owner, OTHER)

        contact.refresh_from_db()
        self.assertIsNone(contact.owner_id)
        self.assertEqual(contact.verification_level,
                         ContactIdentity.VERIFICATION_UNKNOWN)
        self.assertEqual(contact.linked_via, '')

    def test_implicit_phone_match_link_dies_too(self):
        """El caso MÁS COMÚN: `linked_via=''` — "phone_match implícito".

        El sistema dedujo el vínculo del número y no dejó marca de procedencia.
        Enumerar "lo que se rompe" dejaba fuera justo este; por eso el criterio
        es la lista blanca de lo que sobrevive.
        """
        contact = self._contact('', ContactIdentity.VERIFICATION_PHONE_MATCH)
        change_owner_phone(self.owner, OTHER)
        contact.refresh_from_db()
        self.assertIsNone(contact.owner_id)

    def test_a_chat_confirmed_link_over_a_phone_match_also_dies(self):
        """Confirmar en chat sobre un vínculo telefónico no lo independiza.

        El cliente nombró su mascota y subió a `confirmed_in_chat`, pero la
        premisa original seguía siendo el número: nombró la mascota del
        expediente al que YA estaba vinculado por teléfono.
        """
        contact = self._contact('', ContactIdentity.VERIFICATION_CONFIRMED)
        change_owner_phone(self.owner, OTHER)
        contact.refresh_from_db()
        self.assertIsNone(contact.owner_id)

    def test_recycled_number_does_not_inherit_the_previous_client(self):
        """El caso grave de producción, y el que nadie puede arreglar a mano."""
        contact = self._contact(ContactIdentity.LINKED_SELF_REGISTER,
                                ContactIdentity.VERIFICATION_CONFIRMED)
        # El cliente A cambia de número; la clínica actualiza su ficha.
        change_owner_phone(self.owner, OTHER)
        # Quien herede el número escribe: mismo wa_id, mismo ContactIdentity.
        contact.refresh_from_db()
        self.assertIsNone(
            contact.owner_id,
            "Un número reciclado no puede heredar el expediente de su dueño anterior.")

    # -- lo que NO se rompe ------------------------------------------------
    def test_a_staff_verified_link_survives(self):
        """Lo verificó una persona con evidencia EXTERNA al teléfono (FLUJO-C).

        Corregir un typo en el teléfono del expediente no puede destruir el
        trabajo de quien identificó al cliente en mostrador.
        """
        contact = self._contact(ContactIdentity.LINKED_STAFF,
                                ContactIdentity.VERIFICATION_STAFF)
        change_owner_phone(self.owner, OTHER)
        contact.refresh_from_db()
        self.assertEqual(contact.owner_id, self.owner.pk)
        self.assertEqual(contact.verification_level,
                         ContactIdentity.VERIFICATION_STAFF)

    def test_a_family_link_survives(self):
        """El reto de tres factores no se fundaba en el número de quien escribe."""
        contact = self._contact(ContactIdentity.LINKED_FAMILY,
                                ContactIdentity.VERIFICATION_CONFIRMED)
        change_owner_phone(self.owner, OTHER)
        contact.refresh_from_db()
        self.assertEqual(contact.owner_id, self.owner.pk)

    def test_reformatting_the_same_number_changes_nothing(self):
        """La clave no se mueve: es una edición cosmética, no de identidad."""
        contact = self._contact(ContactIdentity.LINKED_SELF_REGISTER,
                                ContactIdentity.VERIFICATION_CONFIRMED)
        change_owner_phone(self.owner, '93 7165 1868')
        contact.refresh_from_db()
        self.assertEqual(contact.owner_id, self.owner.pk)

    def test_editing_the_name_does_not_touch_the_link(self):
        contact = self._contact(ContactIdentity.LINKED_SELF_REGISTER,
                                ContactIdentity.VERIFICATION_CONFIRMED)
        self.owner.name = "Andres Corregido"
        self.owner.save()
        contact.refresh_from_db()
        self.assertEqual(contact.owner_id, self.owner.pk)

    def test_other_contacts_of_the_same_owner_are_untouched(self):
        """Solo cae quien colgaba del teléfono que cambió."""
        mine = self._contact(ContactIdentity.LINKED_SELF_REGISTER,
                             ContactIdentity.VERIFICATION_CONFIRMED)
        # Un familiar, con su propio número, vinculado por el reto triple.
        relative = ContactIdentity.objects.create(
            organization=self.org, external_id='5215544443333',
            phone_normalized='5544443333', owner=self.owner,
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            linked_via=ContactIdentity.LINKED_FAMILY)

        change_owner_phone(self.owner, OTHER)

        mine.refresh_from_db()
        relative.refresh_from_db()
        self.assertIsNone(mine.owner_id)
        self.assertEqual(relative.owner_id, self.owner.pk)

    # -- después del desvínculo -------------------------------------------
    def test_the_contact_can_be_matched_again_by_its_own_number(self):
        """No se bloquea nada: si el número vuelve a resolver, se vincula.

        Desvincular no es castigar al contacto — es dejar de afirmar algo que
        ya no consta. Si más tarde ese mismo número tiene un expediente propio,
        el rematch normal lo vincula.
        """
        contact = self._contact(ContactIdentity.LINKED_SELF_REGISTER,
                                ContactIdentity.VERIFICATION_CONFIRMED)
        change_owner_phone(self.owner, OTHER)
        contact.refresh_from_db()
        self.assertFalse(contact.auto_rematch_blocked)

        propio = Owner.objects.create(
            organization=self.org, name="Felipe", phone=PHONE)
        from apps.agent.services import _rematch_owner
        _rematch_owner(contact)
        contact.refresh_from_db()
        self.assertEqual(contact.owner_id, propio.pk)

    def test_the_helper_is_idempotent(self):
        contact = self._contact(ContactIdentity.LINKED_SELF_REGISTER,
                                ContactIdentity.VERIFICATION_CONFIRMED)
        change_owner_phone(self.owner, OTHER)
        # Correrlo de nuevo no encuentra nada que desvincular ni rompe nada.
        self.assertEqual(unlink_stale_phone_identities(self.owner), 0)
        contact.refresh_from_db()
        self.assertIsNone(contact.owner_id)

    def test_a_link_whose_phone_still_matches_is_never_touched(self):
        """Guardar el expediente por cualquier motivo no desvincula a nadie."""
        contact = self._contact(ContactIdentity.LINKED_SELF_REGISTER,
                                ContactIdentity.VERIFICATION_CONFIRMED)
        self.owner.save()
        self.owner.save()
        contact.refresh_from_db()
        self.assertEqual(contact.owner_id, self.owner.pk)

    def test_tenant_isolation(self):
        """Un expediente de otra clínica no puede desvincular contactos ajenos."""
        other_org = Organization.objects.create(name="Ajena", timezone="UTC")
        foreign_owner = Owner.objects.create(
            organization=other_org, name="Ajeno", phone=PHONE)
        contact = self._contact(ContactIdentity.LINKED_SELF_REGISTER,
                                ContactIdentity.VERIFICATION_CONFIRMED)

        change_owner_phone(foreign_owner, OTHER)

        contact.refresh_from_db()
        self.assertEqual(contact.owner_id, self.owner.pk)


class IdentityVerificationAfterUnlinkTests(TestCase):
    """Y el bucle de verificación que esto causaba, cerrado por la raíz."""

    def setUp(self):
        self.org = Organization.objects.create(name="Bucle", timezone="UTC")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="bucle-770")
        self.andres = Owner.objects.create(
            organization=self.org, name="Andres", phone=PHONE)
        Pet.objects.create(organization=self.org, owner=self.andres,
                           name="Luna", species="canino", birth_date="2021-01-01")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id=WA, phone_normalized=PHONE,
            owner=self.andres,
            verification_level=ContactIdentity.VERIFICATION_CONFIRMED,
            linked_via=ContactIdentity.LINKED_SELF_REGISTER)

    def test_before_the_fix_no_answer_of_the_real_person_could_verify(self):
        """La trampa: quien escribe dice ser Felipe; el sistema espera Andres.

        Ningún dato suyo iba a coincidir jamás — por eso el bot preguntaba una
        y otra vez hasta escalar. No era un fallo de redacción: era un bucle
        sin salida por construcción.

        Se comprueba sobre el matcher (D4b retiró la vía que promovía con el
        nombre del titular): lo que se protege es que un nombre ajeno no case
        con el expediente vinculado, no cuál era la función que lo usaba.
        """
        self.assertFalse(identity._name_matches("Felipe", self.andres.name))

    def test_after_the_phone_changes_the_contact_starts_clean(self):
        change_owner_phone(self.andres, OTHER)
        self.contact.refresh_from_db()
        # Ya no se le compara contra un expediente que no es suyo.
        self.assertIsNone(self.contact.owner_id)
