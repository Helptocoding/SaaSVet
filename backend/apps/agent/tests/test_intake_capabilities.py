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


class PostReceiptOperationAuthorityTests(AgentFixture):
    """Un recibo cierra la capacidad anterior, no inicia otra agenda.

    Estas pruebas no dependen de cómo el cliente redacte un agradecimiento. El
    caso de producción se representa con una llamada de agenda que el modelo
    intentaría hacer sin una autorización nueva: el catálogo la oculta y
    ``run_tool`` la rechaza aunque llegue desde un output viejo o defectuoso.
    """

    account_id = '900000313'

    def _receipt(self):
        return Message.objects.create(
            organization=self.org,
            channel_account=self.channel,
            conversation=self.conv,
            direction=Message.DIRECTION_OUT,
            author_type=Message.AUTHOR_SYSTEM,
            semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
            operation_key='operation-already-completed',
            body='Tu cita quedó agendada.',
            status=Message.STATUS_DELIVERED,
        )

    def _inbound(self, body):
        return Message.objects.create(
            organization=self.org,
            channel_account=self.channel,
            conversation=self.conv,
            direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT,
            body=body,
            status=Message.STATUS_PROCESSED,
        )

    def _tool_names(self):
        return {
            item['function']['name']
            for item in tools.as_openai_tools(self.conv)
        }

    def test_completed_operation_hides_unscoped_scheduling_tools(self):
        self._receipt()

        names = self._tool_names()

        self.assertIn(tools.BEGIN_OPERATION_TOOL, names)
        self.assertNotIn('create_appointment', names)
        self.assertNotIn('find_available_slots', names)
        self.assertNotIn('check_appointment_slot', names)

    def test_direct_scheduling_after_receipt_is_denied_without_pending(self):
        self._receipt()
        thanks = self._inbound('muchas gracias')

        outcome = tools.run_tool(
            'create_appointment',
            {'pet_handle': 'mascota_1', 'date': '2026-09-01',
             'time': '10:00', 'reason': 'Revisión'},
            conversation=self.conv, executor=self.executor(),
            triggered_by=thanks,
        )

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.client_error, 'operation_authorization_required')
        self.assertIsNone(goals.get_open_goal(self.conv))
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_new_operation_is_explicit_and_keeps_its_causal_message(self):
        self._receipt()
        request = self._inbound('Quiero otra cita para Luna el viernes.')

        outcome = tools.run_tool(
            tools.BEGIN_OPERATION_TOOL,
            {'operation': 'new_appointment'},
            conversation=self.conv, executor=self.executor(),
            triggered_by=request,
        )

        self.assertTrue(outcome.ok, outcome.client_error)
        goal = goals.get_open_goal(self.conv)
        self.assertEqual(goal.name, goals.SCHEDULE)
        self.assertEqual(goal.authorization_message_id, request.pk)
        names = self._tool_names()
        self.assertIn('create_appointment', names)
        self.assertIn('find_available_slots', names)
        self.assertNotIn('cancel_appointment', names)

    def test_errant_planner_call_after_receipt_cannot_emit_confirmation(self):
        self._receipt()
        thanks = self._inbound('Gracias, nos vemos mañana.')
        stub = StubLLMClient(scripted=[
            LLMResult(
                kind='tool_call', tool_name='create_appointment',
                tool_args={'pet_handle': 'mascota_1', 'date': '2026-09-01',
                           'time': '10:00', 'reason': 'Revisión'},
                tool_call_id='bad_schedule',
            ),
            LLMResult(kind='text', text='¡De nada! 😊 Aquí estoy si necesitas algo más.'),
        ])

        result = planner.handle_inbound(
            self.conv, agent_settings=self.settings, llm_client=stub,
            executor=self.executor(), triggered_by=thanks,
        )

        self.assertEqual(result['decision'], 'planner_reply')
        self.assertIsNone(confirmations.get_pending(self.conv))
        self.assertFalse(Message.objects.filter(
            conversation=self.conv,
            semantic_type=Message.SEMANTIC_CONFIRMATION,
        ).exists())
