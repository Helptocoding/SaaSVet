"""Regresión audit run-1, hallazgo 8.3: restaurar un cliente archivado no debe
fabricar un duplicado de teléfono.

El resolvedor de identidad solo ve clientes activos, así que archivar libera la
clave. Si mientras tanto otro cliente la ocupa, restaurar al archivado dejaba
dos expedientes activos con el mismo teléfono, que INV-C obliga a tratar como
ambiguos en todas las vías de identidad. Restaurar pasa ahora por el mismo
contrato que `change_owner_phone`.
"""
from django.db import transaction
from django.test import TestCase

from apps.organizations.models import Organization
from apps.patients.archive import change_archive_state
from apps.patients.models import Owner
from apps.patients.services import (UNIQUE, OwnerAmbiguous, OwnerExists,
                                    lookup_owner_by_phone, resolve_owner_for_phone)
from apps.users.models import User

PHONE = '5512340000'


class RestorePhoneIdentityTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Restore 8.3', timezone='UTC')
        self.admin = User.objects.create(organization=self.org, username='restore-admin',
                                         role='ADMIN', is_active=True)

    def _new_owner(self, name):
        with transaction.atomic():
            owner, _ = resolve_owner_for_phone(self.org, phone=PHONE, name=name)
        return owner

    def _set_state(self, owner, archive):
        return change_archive_state(actor=self.admin, organization_id=self.org.pk,
                                    kind='owner', public_id=owner.public_id, archive=archive)

    def test_restore_onto_an_occupied_phone_is_refused_with_the_candidate(self):
        original = self._new_owner('Cliente Original')
        self._set_state(original, archive=True)
        newcomer = self._new_owner('Cliente Nuevo')
        self.assertNotEqual(newcomer.pk, original.pk)

        with self.assertRaises(OwnerExists) as ctx:
            self._set_state(original, archive=False)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertFalse(Owner.all_objects.get(pk=original.pk).is_active)
        lookup = lookup_owner_by_phone(self.org, PHONE)
        self.assertEqual((lookup.outcome, lookup.owner.pk), (UNIQUE, newcomer.pk))

    def test_restore_onto_an_already_ambiguous_phone_is_refused(self):
        original = self._new_owner('Cliente Original')
        self._set_state(original, archive=True)
        a = self._new_owner('Cliente A')
        # Duplicado histórico preexistente (anterior a INV-C): se crea por
        # debajo del servicio para reproducir el estado, no como vía soportada.
        Owner.objects.create(organization=self.org, name='Cliente B', phone=PHONE)
        with self.assertRaises(OwnerAmbiguous):
            self._set_state(original, archive=False)
        self.assertFalse(Owner.all_objects.get(pk=original.pk).is_active)
        self.assertTrue(Owner.all_objects.get(pk=a.pk).is_active)

    def test_restore_with_a_free_phone_still_succeeds(self):
        original = self._new_owner('Cliente Original')
        self._set_state(original, archive=True)
        restored = self._set_state(original, archive=False)
        self.assertTrue(restored.is_active)
        lookup = lookup_owner_by_phone(self.org, PHONE)
        self.assertEqual((lookup.outcome, lookup.owner.pk), (UNIQUE, original.pk))
