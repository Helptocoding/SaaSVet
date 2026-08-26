"""Triaje semántico de contactos sin expediente vinculado.

No se prueban frases del cliente: el modelo entrega el enum tipado mediante
``set_client_path``. Lo que estas pruebas aseguran es la parte vinculante: qué
capacidades llegan al modelo y qué rechaza el servidor si intenta saltarlas.
"""
from apps.agent import confirmations, goals, planner, tools
from apps.agent.llm import LLMResult, StubLLMClient
from apps.agent.models import ContactIdentity, ConversationGoal
from apps.agent.tests.test_w0_hardening import AgentFixture
from apps.channels.models import Message


class IntakeCapabilityTests(AgentFixture):
    account_id = '900000311'

    def setUp(self):
        super().setUp()
        self.contact.owner = None
        self.contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        self.contact.verified_at = None
        self.contact.save(update_fields=['owner', 'verification_level',
                                         'verified_at'])
        self.conv.intake_path = ''
        self.conv.save(update_fields=['intake_path'])

    def _tool_names(self):
        return {
            item['function']['name']
            for item in tools.as_openai_tools(self.conv)
        }

    def _select(self, path):
        return tools.run_tool(
            'set_client_path', {'path': path}, conversation=self.conv,
            executor=self.executor(),
        )

    def test_unknown_contact_can_only_classify_or_reply(self):
        self.assertEqual(
            self._tool_names(),
            {'set_client_path', tools.REPLY_TOOL_NAME},
        )
        outcome = tools.run_tool(
            'identify_client', {'pet_name': 'Kiko'}, conversation=self.conv,
            executor=self.executor(),
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.client_error, 'intake_required')
        self.assertNotIn('aportado', self.conv.flow)

    def test_first_visit_never_exposes_identification(self):
        outcome = self._select('new_client')
        self.assertTrue(outcome.ok, outcome.client_error)
        self.conv.refresh_from_db()

        names = self._tool_names()
        self.assertIn('register_new_client_and_pet', names)
        self.assertNotIn('identify_client', names)

        denied = tools.run_tool(
            'identify_client', {'pet_name': 'Kiko'}, conversation=self.conv,
            executor=self.executor(),
        )
        self.assertFalse(denied.ok)
        self.assertEqual(denied.client_error, 'intake_path_conflict')

    def test_existing_client_never_exposes_new_registration(self):
        outcome = self._select('existing_client')
        self.assertTrue(outcome.ok, outcome.client_error)

        names = self._tool_names()
        self.assertIn('identify_client', names)
        self.assertNotIn('register_new_client_and_pet', names)

        denied = tools.run_tool(
            'register_new_client_and_pet',
            {'owner_name': 'Luis', 'pet_name': 'Kiko'},
            conversation=self.conv, executor=self.executor(),
        )
        self.assertFalse(denied.ok)
        self.assertEqual(denied.client_error, 'intake_path_conflict')

    def test_reclassification_invalidates_pending_and_old_goal(self):
        self.assertTrue(self._select('new_client').ok)
        goal = goals.open_goal(self.conv, goals.REGISTER)
        confirmations.stage_pending(
            self.conv,
            tool='register_new_client_and_pet',
            args={'idempotency_key': 'test-intake-reclassification'},
            paraphrase='propuesta de prueba',
        )
        self.conv.flow['aportado'] = {'pet_name': 'Kiko'}
        self.conv.save(update_fields=['flow'])

        self.assertTrue(self._select('existing_client').ok)
        self.conv.refresh_from_db()
        goal.refresh_from_db()

        self.assertIsNone(confirmations.get_pending(self.conv))
        self.assertEqual(goal.status, ConversationGoal.STATUS_ABANDONED)
        self.assertNotIn('aportado', self.conv.flow)


class IntakePlannerCapabilitiesTests(AgentFixture):
    account_id = '900000312'

    def setUp(self):
        super().setUp()
        self.contact.owner = None
        self.contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        self.contact.verified_at = None
        self.contact.save(update_fields=['owner', 'verification_level',
                                         'verified_at'])

    def test_classification_refreshes_the_catalogue_in_the_same_turn(self):
        inbound = Message.objects.create(
            organization=self.org,
            channel_account=self.channel,
            conversation=self.conv,
            direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT,
            body='Nunca había venido; quiero una cita para Kiko.',
            status=Message.STATUS_PROCESSED,
        )
        stub = StubLLMClient(scripted=[
            LLMResult(
                kind='tool_call', tool_name='set_client_path',
                tool_args={'path': 'new_client'}, tool_call_id='path_1',
            ),
            LLMResult(
                kind='text',
                text='¡Claro! ¿Me dices tu nombre completo para darlo de alta?',
            ),
        ])

        planner.handle_inbound(
            self.conv, agent_settings=self.settings, llm_client=stub,
            executor=self.executor(), triggered_by=inbound,
        )

        first_names = {
            item['function']['name'] for item in stub.calls[0]['tools']
        }
        second_names = {
            item['function']['name'] for item in stub.calls[1]['tools']
        }
        self.assertEqual(first_names,
                         {'set_client_path', tools.REPLY_TOOL_NAME})
        self.assertIn('register_new_client_and_pet', second_names)
        self.assertNotIn('identify_client', second_names)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.intake_path, 'new_client')
