"""Regresión audit run-1, hallazgo 8.1: el inspector del borrado físico debe ver
también las FK declaradas con `related_name='+'`.

`_meta.related_objects` las omite, pero el Collector de Django sí aplica su
on_delete. Cinco FK del agente hacia Owner/Pet eran invisibles: el preview daba
la mascota por elegible sin reportarlas y el borrado anulaba en silencio la FK
de una ConversationOperation B7A inmutable, que dejaba de validar contra su
propio digest.
"""
from django.apps import apps
from django.test import SimpleTestCase, TestCase

from apps.agent.models import ConversationGoal, ConversationOperation
from apps.agent.operation_model_contract import validate_operation
from apps.agent.tests.test_b7a_operations import OperationFixtures
from apps.patients.models import Pet
from apps.platform.services.physical_deletion import (TARGETS, PhysicalDeleteConflict,
                                                      _reverse_relations, execute, preview)
from apps.users.models import User


class EveryInboundForeignKeyIsInspectedGate(SimpleTestCase):
    """Gate estático: toda FK de cualquier modelo hacia un tipo borrable debe
    aparecer en lo que el inspector recorre. Si alguien vuelve a usar
    `related_objects`, o Django cambia qué incluye, esto se pone rojo."""

    def test_inspector_sees_every_concrete_fk_into_each_target(self):
        for target_type, target in TARGETS.items():
            inspected = {(r.related_model._meta.label, r.field.name)
                         for r in _reverse_relations(target)}
            for model in apps.get_models(include_auto_created=True):
                for field in model._meta.concrete_fields:
                    remote = getattr(field.remote_field, 'model', None)
                    if field.is_relation and remote is target:
                        with self.subTest(target=target_type, field=f'{model._meta.label}.{field.name}'):
                            self.assertIn((model._meta.label, field.name), inspected)

    def test_the_hidden_agent_references_are_included(self):
        pet_refs = {(r.related_model._meta.label, r.field.name) for r in _reverse_relations(Pet)}
        self.assertIn(('agent.ConversationOperation', 'pet'), pet_refs)
        self.assertIn(('agent.ConversationGoal', 'bound_pet'), pet_refs)


class HiddenReferenceBlocksPhysicalDeletionTests(OperationFixtures, TestCase):
    def _operator(self):
        return User.objects.create(username='hidden-ref-op', role='ADMIN_SAAS',
                                   is_superuser=True, is_staff=True, is_active=True)

    def test_pet_referenced_by_an_operation_is_not_eligible_and_stays_intact(self):
        op = self.prepare()
        self.assertEqual(op.pet_id, self.luna.pk)
        Pet.all_objects.filter(pk=self.luna.pk).update(is_active=False)
        common = dict(actor=self._operator(), organization_id=self.org.public_id,
                      target_type='pet', target_id=self.luna.public_id,
                      reason='prueba de regresion 8.1')

        result = preview(**common)
        self.assertFalse(result['eligible'])
        self.assertIn('unsupported_reference', result['blockers'])

        # Sin elegibilidad no se emite token; un intento forzado se rechaza y
        # nada se borra ni se reescribe.
        self.assertIsNone(result['confirmation'])
        with self.assertRaises(PhysicalDeleteConflict):
            execute(**common, confirmation='token-forzado',
                    idempotency_key='11111111-1111-4111-8111-111111111111')
        self.assertTrue(Pet.all_objects.filter(pk=self.luna.pk).exists())
        after = ConversationOperation.all_objects.get(pk=op.pk)
        self.assertEqual(after.pet_id, self.luna.pk)
        validate_operation(after)
        self.assertEqual(ConversationGoal.all_objects.get(pk=self.goal.pk).bound_pet_id,
                         self.luna.pk)
