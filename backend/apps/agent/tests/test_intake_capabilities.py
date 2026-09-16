"""Triaje semántico de contactos sin expediente vinculado.

No se prueban frases del cliente: el modelo entrega el enum tipado mediante
``set_client_path``. Lo que estas pruebas aseguran es la parte vinculante: qué
capacidades llegan al modelo y qué rechaza el servidor si intenta saltarlas.
"""
from apps.agent import confirmations, goals, planner, tools
from apps.agent.llm import LLMError, LLMResult, StubLLMClient
from apps.agent.models import (
    ContactIdentity, ConversationGoal, TurnOperationAssessment,
)
from apps.agent.tests.test_w0_hardening import AgentFixture
from apps.channels.models import Message

# The confirmed B2 contract permits these six public reads before onboarding.
B2_PUBLIC_TOOLS = {
    'get_clinic_info', 'get_service_catalog', 'get_offered_specialties',
    'check_product_availability', 'find_available_slots', 'check_appointment_slot',
}


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

    def test_unknown_contact_keeps_public_reads_without_personal_access(self):
        self.assertEqual(
            self._tool_names(),
            B2_PUBLIC_TOOLS | {'set_client_path', tools.REPLY_TOOL_NAME},
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
        self.assertNotIn('register_new_client_and_pet', names)  # B0: WRITE cerrado
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
        self.assertEqual(denied.client_error, 'autonomous_writes_paused')

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
                         B2_PUBLIC_TOOLS | {'set_client_path', tools.REPLY_TOOL_NAME})
        self.assertNotIn('register_new_client_and_pet', second_names)
        self.assertIn('get_clinic_info', second_names)
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

    def test_completed_operation_keeps_public_reads_and_hides_writes(self):
        self._receipt()

        names = self._tool_names()

        self.assertNotIn(tools.BEGIN_OPERATION_TOOL, names)
        self.assertNotIn('create_appointment', names)
        self.assertTrue(B2_PUBLIC_TOOLS.issubset(names))
        self.assertNotIn('cancel_appointment', names)
        self.assertNotIn('reschedule_appointment', names)

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
        self.assertEqual(outcome.client_error, 'autonomous_writes_paused')
        self.assertIsNone(goals.get_open_goal(self.conv))
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_new_operation_is_authorized_from_the_current_turn(self):
        self._receipt()
        old_operation_data = self._inbound(
            'La cita anterior de Luna era a las nueve.',
        )
        request = self._inbound('Quiero otra cita para Luna el viernes.')
        authorizer = StubLLMClient(scripted=[
            LLMResult(
                kind='tool_call', tool_name='classify_turn_operation',
                tool_args={
                    'verdict': 'operation',
                    'operation': 'new_appointment',
                },
                tool_call_id='authorize_1',
            ),
        ])
        verifier = StubLLMClient(scripted=[
            LLMResult(
                kind='tool_call', tool_name='verify_turn_operation',
                tool_args={'verdict': 'accept'}, tool_call_id='verify_1',
            ),
        ])
        agent = StubLLMClient(scripted=[
            LLMResult(kind='text', text='Claro, ¿qué horario prefieres?'),
        ])

        planner.handle_inbound(
            self.conv, agent_settings=self.settings, llm_client=agent,
            operation_authorizer=authorizer, operation_verifier=verifier,
            executor=self.executor(), triggered_by=request,
            burst_messages=[request],
        )

        goal = goals.get_open_goal(self.conv)
        self.assertEqual(goal.name, goals.SCHEDULE)
        self.assertEqual(goal.authorization_message_id, request.pk)
        self.assertEqual(
            goal.operation_assessment.verdict,
            TurnOperationAssessment.VERDICT_AUTHORIZED,
        )
        self.assertEqual(
            list(goal.operation_assessment.source_messages.values_list('pk', flat=True)),
            [request.pk],
        )
        planner_context = '\n'.join(
            message['content'] for message in agent.calls[0]['messages']
        )
        self.assertIn(request.body, planner_context)
        self.assertNotIn(old_operation_data.body, planner_context)
        names = self._tool_names()
        self.assertNotIn('create_appointment', names)  # Interpretación no reabre B0.
        self.assertIn('find_available_slots', names)
        self.assertNotIn('cancel_appointment', names)

    def test_fragmented_thanks_remains_conversational(self):
        self._receipt()
        fragments = [
            self._inbound('muchas'),
            self._inbound('gracias'),
            self._inbound('por su atención'),
        ]
        authorizer = StubLLMClient(scripted=[
            LLMResult(
                kind='tool_call', tool_name='classify_turn_operation',
                tool_args={'verdict': 'conversational'},
                tool_call_id='authorize_1',
            ),
        ])
        agent = StubLLMClient(scripted=[
            LLMResult(kind='text', text='¡Con gusto! Que estén muy bien.'),
        ])

        planner.handle_inbound(
            self.conv, agent_settings=self.settings, llm_client=agent,
            operation_authorizer=authorizer, executor=self.executor(),
            triggered_by=fragments[-1], burst_messages=fragments,
        )

        assessment = TurnOperationAssessment.objects.get(
            conversation=self.conv, anchor_message=fragments[-1],
        )
        self.assertEqual(
            assessment.verdict,
            TurnOperationAssessment.VERDICT_CONVERSATIONAL,
        )
        self.assertEqual(
            list(assessment.source_messages.values_list('pk', flat=True)),
            [message.pk for message in fragments],
        )
        self.assertIsNone(goals.get_open_goal(self.conv))
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_verifier_rejects_a_hallucinated_new_appointment(self):
        self._receipt()
        social_message = self._inbound('Excepcional.')
        authorizer = StubLLMClient(scripted=[
            LLMResult(
                kind='tool_call', tool_name='classify_turn_operation',
                tool_args={
                    'verdict': 'operation',
                    'operation': 'new_appointment',
                },
                tool_call_id='authorize_1',
            ),
        ])
        verifier = StubLLMClient(scripted=[
            LLMResult(
                kind='tool_call', tool_name='verify_turn_operation',
                tool_args={'verdict': 'reject'}, tool_call_id='verify_1',
            ),
        ])
        agent = StubLLMClient(scripted=[
            LLMResult(
                kind='text', text='Qué bueno saberlo. ¿Te ayudo en algo más?'),
        ])

        planner.handle_inbound(
            self.conv, agent_settings=self.settings, llm_client=agent,
            operation_authorizer=authorizer, operation_verifier=verifier,
            executor=self.executor(), triggered_by=social_message,
            burst_messages=[social_message],
        )

        assessment = TurnOperationAssessment.objects.get(
            conversation=self.conv, anchor_message=social_message,
        )
        self.assertEqual(
            assessment.verdict,
            TurnOperationAssessment.VERDICT_REJECTED,
        )
        self.assertEqual(assessment.operation, 'new_appointment')
        self.assertIsNone(goals.get_open_goal(self.conv))
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_authorizer_failure_fails_closed(self):
        self._receipt()
        request = self._inbound('Quiero agendar otra cita para Luna.')
        authorizer = StubLLMClient(scripted=[
            LLMError('proveedor no disponible', retryable=True),
        ])
        agent = StubLLMClient(scripted=[
            LLMResult(kind='text', text='¿Me indicas qué necesitas?'),
        ])

        planner.handle_inbound(
            self.conv, agent_settings=self.settings, llm_client=agent,
            operation_authorizer=authorizer, executor=self.executor(),
            triggered_by=request, burst_messages=[request],
        )

        assessment = TurnOperationAssessment.objects.get(
            conversation=self.conv, anchor_message=request,
        )
        self.assertEqual(
            assessment.verdict,
            TurnOperationAssessment.VERDICT_UNAVAILABLE,
        )
        self.assertEqual(assessment.failure_code, 'llm_retryable_failure')
        self.assertNotIn(
            'create_appointment',
            {item['function']['name'] for item in agent.calls[0]['tools']},
        )
        self.assertIsNone(goals.get_open_goal(self.conv))
        self.assertIsNone(confirmations.get_pending(self.conv))

    def test_begin_operation_is_never_a_model_authority(self):
        self._receipt()
        request = self._inbound('Quiero otra cita para Luna.')

        outcome = tools.run_tool(
            tools.BEGIN_OPERATION_TOOL,
            {'operation': 'new_appointment'}, conversation=self.conv,
            executor=self.executor(), triggered_by=request,
        )

        self.assertFalse(outcome.ok)
        self.assertEqual(
            outcome.client_error,
            'operation_authorization_managed_by_orchestrator',
        )
        self.assertIsNone(goals.get_open_goal(self.conv))

    def test_errant_planner_call_after_receipt_cannot_emit_confirmation(self):
        self._receipt()
        thanks = self._inbound('Gracias, nos vemos mañana.')
        authorizer = StubLLMClient(scripted=[
            LLMResult(
                kind='tool_call', tool_name='classify_turn_operation',
                tool_args={'verdict': 'conversational'},
                tool_call_id='authorize_1',
            ),
        ])
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
            operation_authorizer=authorizer, executor=self.executor(),
            triggered_by=thanks, burst_messages=[thanks],
        )

        self.assertEqual(result['decision'], 'autonomous_writes_paused')
        self.assertIsNone(confirmations.get_pending(self.conv))
        self.assertFalse(Message.objects.filter(
            conversation=self.conv,
            semantic_type=Message.SEMANTIC_CONFIRMATION,
        ).exists())
