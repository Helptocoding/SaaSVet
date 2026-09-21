"""
harness.py — Motor de la suite de regresión conversacional (É-F1 PR-13).

Conduce un turno completo (entrante → policy/planner → salientes) con un
StubLLMClient determinista y aplica las ASERCIONES PROHIBIDAS GLOBALES de la
spec §9.2 a CADA saliente: ningún mensaje del agente puede contener UUIDs/
PKs, cifras de stock, consejo médico, jerga interna, ni datos de otro tenant.

Filosofía (spec §1.3/§9.1): plantillas tier-0 = igualdad literal; texto del
LLM = elementos obligatorios/prohibidos, jamás igualdad. Tools y efectos de
dominio = exactos. La suite CI corre contra el stub (bloqueante); el eval
con LLM real es nightly (comando agent_eval).
"""
from functools import wraps
from unittest.mock import patch

from django.test import tag
from django.test.runner import DiscoverRunner
from rest_framework.test import APIClient

from apps.agent import guards, planner
from apps.agent.executor import ToolExecutor
from apps.channels.models import Message

_UUID_RE = guards.UUID_RE

# Fuente única: las listas vinculantes viven en `guards.py` y corren en
# PRODUCCIÓN (É-F3 W1-1). Aquí solo se añade severidad extra de test —
# patrones demasiado ambiguos para bloquear en vivo pero útiles para detectar
# derivas de tono en la suite ('dale ' es un sí mexicano, no una posología).
FORBIDDEN_JARGON = guards.FORBIDDEN_JARGON + ('conversation',)
FORBIDDEN_MEDICAL = guards.MEDICAL_ADVICE_PATTERNS + ('dale ', 'administra ')


def set_schedule_day(organization, weekday_index, opens="09:00",
                     closes="13:00"):
    """Fija el horario de UN día (0=lunes) en la fuente única (ADR p53).

    El alta de organización siembra 7 filas por defecto; los tests que dependen
    de un horario concreto lo sobreescriben aquí. Sustituye al difunto
    `AgentSettings.business_hours`, que era una segunda fuente de verdad.
    """
    from apps.organizations.models import OrganizationSchedule
    OrganizationSchedule.objects.update_or_create(
        organization=organization, weekday=weekday_index + 1,
        defaults={'opens_at': opens, 'closes_at': closes, 'is_closed': False,
                  'has_break': False, 'break_start': None, 'break_end': None},
    )


def identity_commitment(conversation, *, parked=False):
    """El reto de identidad AL FRENTE (o el apartado, con `parked=True`).

    Desde É-F4 Fase 3 (R7) los retos son compromisos, no dicts en
    `Conversation.flow`. Los tests preguntan por su etapa a través de aquí
    para no volver a acoplarse al contenedor.
    """
    from apps.agent import goals
    from apps.agent.models import ConversationGoal
    statuses = ((ConversationGoal.STATUS_SUSPENDED,) if parked
                else ConversationGoal.FOREGROUND_STATUSES)
    return ConversationGoal.objects.filter(
        conversation=conversation, name__in=goals.IDENTITY_GOALS,
        status__in=statuses,
    ).first()


def close_all_days(organization):
    """Clínica cerrada toda la semana (para probar el aviso de fuera de horario)."""
    from apps.organizations.models import OrganizationSchedule
    OrganizationSchedule.objects.filter(
        organization=organization).update(is_closed=True)


class RealApiTransport:
    """Loopback por el Django test client con el JWT del AGENT (API+RBAC reales).

    Reenvía el body `json` en escrituras (POST/PATCH, F2) y `params` en lecturas
    (GET, F1). Los headers extra (X-Idempotency-Key, X-Request-ID) van como META
    para que el loopback se comporte como en producción."""

    def __call__(self, method, path, *, headers, params=None, json=None):
        client = APIClient()
        extra = {}
        for key, value in (headers or {}).items():
            if key.lower() == 'authorization':
                extra['HTTP_AUTHORIZATION'] = value
            else:
                extra['HTTP_' + key.upper().replace('-', '_')] = value
        if json is not None:
            response = getattr(client, method.lower())(
                path, data=json, format='json', **extra)
        else:
            response = getattr(client, method.lower())(
                path, data=params or {}, **extra)
        from apps.agent.executor import TransportResponse
        return TransportResponse.from_http(response)


def assert_no_forbidden(testcase, text, *, decoy_terms=()):
    """Aserciones prohibidas globales sobre UN saliente."""
    low = (text or '').lower()
    testcase.assertIsNone(_UUID_RE.search(text or ''),
                          f"UUID filtrado: {text}")
    for jargon in FORBIDDEN_JARGON:
        testcase.assertNotIn(jargon, low, f"jerga '{jargon}' en: {text}")
    for term in decoy_terms:
        testcase.assertNotIn(term.lower(), low,
                             f"FUGA CROSS-TENANT '{term}' en: {text}")


def run_turn(testcase, conversation, agent_user, text=None, *, scripted_llm,
             decoy_terms=(), assert_clean=True, burst=None):
    """Persiste el entrante, corre el pipeline y devuelve la lista de cuerpos
    salientes producidos en el turno (en orden). Aplica las aserciones
    prohibidas a cada saliente si assert_clean.

    `burst` = varios mensajes del cliente en UN solo turno, como los agrupa el
    worker (`drain-on-pickup`, §7-C9). En WhatsApp-MX el cliente escribe en
    ráfagas de 1-4 palabras y hay defectos que **solo** aparecen así: el nombre
    que llega en el mismo grupo que la respuesta al tamiz y se descarta. Sin
    esto, el corpus de É-F5 no puede reproducir la conversación que lo motivó.
    `text` sigue siendo la forma corta de `burst=[text]`.
    """
    from apps.agent.llm import StubLLMClient
    from apps.agent.models import AgentSettings, TurnDecision

    bodies_in = list(burst) if burst is not None else [text]

    before_ids = set(
        Message.objects.filter(
            conversation=conversation, direction=Message.DIRECTION_OUT,
        ).values_list('id', flat=True)
    )
    turn_decisions_before = TurnDecision.objects.filter(
        conversation=conversation).count()

    for body in bodies_in:
        Message.objects.create(
            organization=conversation.organization,
            channel_account=conversation.channel_account,
            conversation=conversation, direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT, body=body,
            status=Message.STATUS_PROCESSED,
        )

    agent_settings = AgentSettings.objects.filter(
        organization=conversation.organization,
    ).first()
    stub = StubLLMClient(scripted=scripted_llm)
    executor = ToolExecutor(conversation, agent_user,
                            transport=RealApiTransport())
    # `burst` solo viaja cuando el caller lo pidió: con un único mensaje se
    # conserva el camino de siempre (`_last_inbound_text`). Pasarlo siempre
    # sería equivalente EXCEPTO con texto vacío, donde `policy` paso 2b lo
    # leería como adjunto sin texto — un cambio de conducta encubierto en un
    # helper de tests.
    extra = {'burst': bodies_in} if burst is not None else {}
    result = planner.handle_inbound(
        conversation, agent_settings=agent_settings,
        llm_client=stub, executor=executor, **extra,
    )

    # Exhaustividad de TurnDecision, Capa 2 (§9.2 del plan de gobernanza):
    # todo turno del harness compartido deja EXACTAMENTE una fila, incluidos
    # los que responden SILENT (no mandan mensaje pero sí deciden algo).
    testcase.assertEqual(
        TurnDecision.objects.filter(conversation=conversation).count(),
        turn_decisions_before + 1,
        "cada turno debe dejar exactamente 1 TurnDecision (R12)",
    )

    new_outbound = list(
        Message.objects.filter(
            conversation=conversation, direction=Message.DIRECTION_OUT,
        ).exclude(id__in=before_ids).order_by('id')
    )
    bodies = [m.body for m in new_outbound]
    if assert_clean:
        for body in bodies:
            assert_no_forbidden(testcase, body, decoy_terms=decoy_terms)
    return bodies, result, stub


def legacy_write_component(target):
    """Ejercita componentes inactivos, NO autonomía ni aceptación de B0.

    Opt-in explícito por clase/método para conservar pruebas de precondiciones,
    slots y handlers mientras el release deniega WRITE. Solo sustituye la
    frontera temporal B0 y la precondición B6 para fixtures SIN versión de
    binding; mantiene identidad, permisos y validaciones internas. Los casos
    B6 no usan este decorador y ejercitan ambas fronteras de producción.
    No es un flag de aplicación ni afecta tests que no llevan este decorador.
    El corpus crítico debe ejecutarse sin esta sustitución.
    """
    from apps.agent import confirmations, matter_binding
    from .legacy_pending import seed_pending, legacy_is_confirmable
    binding_check = confirmations.binding_is_current

    def component_binding_check(conversation, pending):
        goal = matter_binding.current_goal(conversation)
        if ((pending or {}).get('binding') or (goal and
                (goal.working_state or {}).get('binding'))):
            return binding_check(conversation, pending)
        return True

    if isinstance(target, type):
        setup = target.setUp

        @wraps(setup)
        def component_setup(self):
            boundary = patch('apps.agent.intake.CONTAINED_WRITES', frozenset())
            boundary.start()
            self.addCleanup(boundary.stop)
            # Historical inactive components only; B8A acceptance never uses
            # this decorator. No runtime setting can reopen either boundary.
            for boundary_name in ('legacy_write_denied', 'agent_api_write_denied'):
                guard_boundary = patch('apps.agent.operation_execution.' + boundary_name, return_value=False)
                guard_boundary.start()
                self.addCleanup(guard_boundary.stop)
            semantic_boundary = patch('apps.agent.confirmations.binding_is_current',
                                      side_effect=component_binding_check)
            semantic_boundary.start()
            self.addCleanup(semantic_boundary.stop)
            legacy_writer = patch('apps.agent.confirmations.stage_pending', side_effect=seed_pending)
            legacy_writer.start()
            self.addCleanup(legacy_writer.stop)
            legacy_reader = patch('apps.agent.confirmations.is_confirmable', side_effect=legacy_is_confirmable)
            legacy_reader.start()
            self.addCleanup(legacy_reader.stop)
            setup(self)

        target.setUp = component_setup
        return tag('legacy_write_component')(target)

    @wraps(target)
    def component_test(*args, **kwargs):
        with patch('apps.agent.operation_execution.legacy_write_denied', return_value=False), patch(
                'apps.agent.operation_execution.agent_api_write_denied', return_value=False), patch(
                'apps.agent.intake.CONTAINED_WRITES', frozenset()), patch(
                'apps.agent.confirmations.binding_is_current',
                side_effect=component_binding_check), patch(
                'apps.agent.confirmations.stage_pending', side_effect=seed_pending), patch(
                'apps.agent.confirmations.is_confirmable', side_effect=legacy_is_confirmable):
            return target(*args, **kwargs)

    return tag('legacy_write_component')(component_test)


# B0: pruebas de planner con eventos persistidos; NO simula completion, claim
# ni entrega. B3/B4 integrarán sus fronteras reales sin sustituir run_turn.
class InjectedFailure(RuntimeError):
    pass


class FailureBarrier:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.events = []

    def reach(self, name):
        self.events.append(name)
        if name == self.fail_at:
            raise InjectedFailure(name)


class ControlledTransport:
    """Proveedor sin red, con respuestas explícitas y fallos antes/después."""

    def __init__(self, responses=(), barrier=None):
        self.responses = iter(responses)
        self.calls = []
        self.barrier = barrier or FailureBarrier()

    def __call__(self, method, path, *, headers, params=None, json=None):
        self.calls.append((method.upper(), path))
        self.barrier.reach('before_provider')
        response = next(self.responses)  # Una llamada inesperada falla el test.
        if isinstance(response, Exception):
            raise response
        self.barrier.reach('after_provider')
        return response


def business_snapshot():
    from apps.appointments.models import Appointment
    from apps.patients.models import Owner, Pet
    # Incluye filas de otros tenants y valores: detecta updates además de altas.
    return {
        model._meta.label: list(model.objects.order_by('pk').values())
        for model in (Owner, Pet, Appointment)
    }


class PersistedTurnHarness:
    def __init__(self, testcase, conversation, agent_user, *, transport=None,
                 barrier=None):
        self.testcase = testcase
        self.conversation = conversation
        self.agent_user = agent_user
        self.transport = transport or ControlledTransport()
        self.barrier = barrier or FailureBarrier()
        self.before_business = business_snapshot()
        self.inbounds = []
        self.outbounds = []

    def run(self, burst, *, scripted_llm):
        from apps.agent.llm import StubLLMClient
        from apps.agent.models import AgentSettings

        conv = self.conversation
        before_outbound = set(Message.objects.filter(
            conversation=conv, direction=Message.DIRECTION_OUT,
        ).values_list('pk', flat=True))
        self.inbounds = [
            Message.objects.create(
                organization=conv.organization,
                channel_account=conv.channel_account, conversation=conv,
                direction=Message.DIRECTION_IN, author_type=Message.AUTHOR_CLIENT,
                body=body, status=Message.STATUS_PENDING,
            ) for body in burst
        ]
        self.barrier.reach('inbound_persisted')
        self.barrier.reach('before_planner')
        result = planner.handle_inbound(
            conv, agent_settings=AgentSettings.objects.get(
                organization=conv.organization),
            llm_client=StubLLMClient(scripted=scripted_llm),
            executor=ToolExecutor(conv, self.agent_user,
                                  transport=self.transport),
            burst=list(burst), triggered_by=self.inbounds[-1],
        )
        self.outbounds = list(Message.objects.filter(
            conversation=conv, direction=Message.DIRECTION_OUT,
        ).exclude(pk__in=before_outbound).order_by('pk'))
        self.barrier.reach('after_planner')
        return result

    def assert_zero_business_effects(self):
        self.testcase.assertEqual(self.before_business, business_snapshot())
        self.testcase.assertFalse([
            call for call in self.transport.calls
            if call[0] not in ('GET', 'HEAD', 'OPTIONS')
        ], 'La contención debe impedir incluso el intento HTTP de WRITE')


class CriticalB0Runner(DiscoverRunner):
    """Exige los escenarios B0: ni omitir una clase ni skip cuenta como verde."""

    REQUIRED = {
        'B0ContainmentTests': (
            'test_registry_covers_every_current_write',
            'test_forced_dispatch_cannot_invoke_any_write_handler',
            'test_forced_planner_write_is_handed_off',
            'test_legacy_pending_cannot_authorize_any_reply',
            'test_direct_pending_commit_is_contained',
            'test_unsafe_output_corpus_is_replaced_without_retry',
            'test_read_result_does_not_prove_write_or_price',
            'test_public_read_and_explicit_human_remain_available',
            'test_personal_read_needs_current_identity',
            'test_pending_events_and_queued_outbound_do_not_mean_delivery',
            'test_failure_after_persistence_leaves_pending_event',
            'test_llm_timeout_yields_honest_fallback',
            'test_emergency_copy_uses_only_configured_phone',
        ),
        'B0CorpusGateTests': (
            'test_fixture_is_required_and_complete',
            'test_failed_empty_skipped_or_expected_failure_cannot_pass_gate',
            'test_controlled_provider_failure_boundaries',
            'test_alert_acceptance_failure_and_no_free_text_export',
        ),
    }

    def build_suite(self, test_labels=None, **kwargs):
        suite = super().build_suite(test_labels, **kwargs)

        def ids(items):
            for case in items:
                if hasattr(case, 'id'):
                    yield case.id()
                else:
                    yield from ids(case)

        expected = {
            f'apps.agent.tests.test_b0_containment.{group}.{method}'
            for group, methods in self.REQUIRED.items() for method in methods
        }
        missing = expected - set(ids(suite))
        if missing:
            raise RuntimeError(f'Escenarios críticos B0 ausentes: {sorted(missing)}')
        self._planned_count = suite.countTestCases()
        return suite

    def suite_result(self, suite, result, **kwargs):
        failures = super().suite_result(suite, result, **kwargs)
        if (result.testsRun == 0 or result.skipped or result.expectedFailures
                or result.unexpectedSuccesses
                or result.testsRun != getattr(self, '_planned_count', result.testsRun)):
            return failures + 1
        return failures


class CriticalB3Runner(CriticalB0Runner):
    """B3 gate: real PostgreSQL corpus, including isolated process boundaries."""

    def build_suite(self, test_labels=None, **kwargs):
        suite = DiscoverRunner.build_suite(self, test_labels, **kwargs)

        def ids(items):
            for case in items:
                if hasattr(case, 'id'):
                    yield case.id()
                else:
                    yield from ids(case)

        required = {
            'test_b3_durable.DurableTurnTests.test_dur_01_reclaims_same_work_context_and_fences_old_token',
            'test_b3_durable.DurableTurnTests.test_dup_01_live_lease_and_partial_unique_constraint',
            'test_b3_durable.B3LocalIntegrationTests.test_real_postgres_error_after_outbound_insert_rolls_back_final_commit',
            'test_b3_durable.B3LocalIntegrationTests.test_takeover_api_and_return_advance_epoch_and_fence_old_worker',
            'test_b3_durable.B3LocalIntegrationTests.test_starve_01_repeated_new_input_finishes_each_fixed_work',
            'test_b3_processes.B3ProcessTests.test_dup_01_two_processes_compete_for_one_lease',
            'test_b3_processes.B3ProcessTests.test_dur_01_killed_process_restarted_worker_recovers_same_work',
            'test_b3_processes.B3ProcessTests.test_llm_timeout_runs_outside_transaction_and_commits_fallback',
        }
        missing = {'apps.agent.tests.' + name for name in required} - set(ids(suite))
        if missing:
            raise RuntimeError(f'Escenarios críticos B3 ausentes: {sorted(missing)}')
        self._planned_count = suite.countTestCases()
        return suite


class CriticalB4Runner(CriticalB0Runner):
    """Reject absent B4 process boundaries, skips, xfails and partial runs."""

    def build_suite(self, test_labels=None, **kwargs):
        suite = DiscoverRunner.build_suite(self, test_labels, **kwargs)
        def ids(items):
            for case in items:
                if hasattr(case, 'id'):
                    yield case.id()
                else:
                    yield from ids(case)
        required = {
            'apps.agent.tests.test_b4_processes.B4ProcessTests.test_send_fi_12_two_processes_one_claim_one_http',
            'apps.agent.tests.test_b4_processes.B4ProcessTests.test_send_fi_03_process_killed_after_meta_acceptance',
            'apps.agent.tests.test_b4_processes.B4ProcessTests.test_send_fi_08_other_transaction_progresses_while_http_blocked',
            'apps.agent.tests.test_b4_sender.B4SenderTests.test_send_fi_02_takeover_after_claim_before_http',
            'apps.agent.tests.test_b4_sender.B4StatusTests.test_send_fi_10_webhook_reconciles_uncertain_preserves_history',
            'apps.channels.tests.test_b4_transport.B4TransportTests.test_send_fi_05_2xx_without_wamid_is_uncertain',
            'apps.channels.tests.test_b4_webhook.B4WebhookTests.test_other_org_correct_wamid_cannot_update',
            'apps.channels.tests.test_b4_migration.B4MigrationTests.test_legacy_rows_keep_states_ids_and_null_evidence',
        }
        missing = required - set(ids(suite))
        if missing:
            raise RuntimeError(f'Escenarios críticos B4 ausentes: {sorted(missing)}')
        self._planned_count = suite.countTestCases()
        return suite


class CriticalB5Runner(CriticalB0Runner):
    """B5 corpus + real process/ownership boundaries, no skips or partial pass."""

    def build_suite(self, test_labels=None, **kwargs):
        suite = DiscoverRunner.build_suite(self, test_labels, **kwargs)
        def ids(items):
            for case in items:
                if hasattr(case, 'id'):
                    yield case.id()
                else:
                    yield from ids(case)
        required = {
            'test_b5_corpus.B5CorpusTests.test_safe_02_versioned_adversarial_corpus',
            'test_b5_processes.B5ProcessTests.test_safe_fi_01_process_killed_after_detection',
            'test_b5_processes.B5ProcessTests.test_safe_fi_02_process_killed_after_case_before_output',
            'test_b5_processes.B5ProcessTests.test_safe_fi_05_safety_worker_vs_human_takeover',
            'test_b5_processes.B5ProcessTests.test_safe_dup_01_two_inbound_processes_one_handoff',
            'test_b5_processes.B5ProcessTests.test_own_04_two_safety_workers_one_epoch_and_case',
            'test_b5_safety.B5SafetyTests.test_safe_race_01_new_safety_fixed_membership_defers_normal',
            'test_b5_safety.B5SafetyTests.test_safe_race_03_admitted_commercial_reality_survives',
        }
        missing = {'apps.agent.tests.' + name for name in required} - set(ids(suite))
        if missing:
            raise RuntimeError(f'Escenarios críticos B5 ausentes: {sorted(missing)}')
        self._planned_count = suite.countTestCases()
        return suite


class CriticalB6Runner(CriticalB0Runner):
    """B6 requires corpus, actual process CAS/crashes and no skips/xfail."""

    def build_suite(self, test_labels=None, **kwargs):
        suite = DiscoverRunner.build_suite(self, test_labels, **kwargs)
        def ids(items):
            for case in items:
                if hasattr(case, 'id'):
                    yield case.id()
                else:
                    yield from ids(case)
        required = {
            'test_b6_corpus.B6CorpusTests.test_versioned_multi_turn_corpus',
            'test_b6_processes.B6ProcessTests.test_race_02_two_processes_one_revision_winner',
            'test_b6_processes.B6ProcessTests.test_fi_01_process_killed_before_commit_no_partial_invalidation',
            'test_b6_processes.B6ProcessTests.test_fi_02_process_killed_after_commit_recovery_complete',
            'test_b6_binding.B6BindingTests.test_bind_01_pet_correction_selective',
            'test_b6_binding.B6BindingTests.test_bind_03_appointment_correction_and_pending',
            'test_b6_binding.B6BindingTests.test_bind_05_late_outcome_cannot_revive',
            'test_b6_binding.B6BindingTests.test_fi_01_and_05_db_failure_rolls_back_revision_and_pending',
            'test_b6_binding.B6BindingTests.test_race_01_new_inbound_defers_b3_output',
        }
        missing = {'apps.agent.tests.' + name for name in required} - set(ids(suite))
        if missing:
            raise RuntimeError(f'Escenarios críticos B6 ausentes: {sorted(missing)}')
        self._planned_count = suite.countTestCases()
        return suite


class CriticalB7ARunner(CriticalB0Runner):
    """B7A required boundaries; never pass absent, skipped or expected failures."""
    def build_suite(self, test_labels=None, **kwargs):
        suite = DiscoverRunner.build_suite(self, test_labels, **kwargs)
        def ids(items):
            for case in items:
                if hasattr(case, 'id'):
                    yield case.id()
                else:
                    yield from ids(case)
        required = {
            'test_b7a_operations.ConversationOperationTests.test_b7a_cannot_authorize_reject_or_execute',
            'test_b7a_operations.ConversationOperationTests.test_pending_does_not_open_any_write',
            'test_b7a_operations.ConversationOperationTests.test_fi03_postgresql_replacement_failure_is_atomic',
            'test_b7a_operations.ConversationOperationTests.test_permission_04_family_read_does_not_grant_cancel',
            'test_b7a_processes.B7AProcessTests.test_duplicate_preparation_two_processes_one_operation',
            'test_b7a_processes.B7AProcessTests.test_concurrent_replacement_two_processes_one_current',
            'test_b7a_processes.B7AProcessTests.test_fi01_kill_after_validation_before_persistence',
            'test_b7a_processes.B7AProcessTests.test_fi02_kill_after_persistence_before_output',
            'test_b7a_processes.B7AProcessTests.test_fi05_identity_change_during_preparation_invalidates',
            'test_b7a_processes.B7AProcessTests.test_fi06_takeover_during_preparation_no_proposal_or_authorization',
            'test_b7a_migration.B7AMigrationTests.test_no_backfill_of_legacy_proposals',
        }
        missing = {'apps.agent.tests.' + name for name in required} - set(ids(suite))
        if missing:
            raise RuntimeError(f'Missing B7A boundaries: {sorted(missing)}')
        self._planned_count = suite.countTestCases()
        return suite
