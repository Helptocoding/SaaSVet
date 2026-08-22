"""
test_prompts.py — Ensamblado de contexto del LLM.

Bug real de piloto: el modelo alucinaba la fecha ("este viernes 21 de marzo"
en julio) porque el contexto no incluía la fecha de hoy. Estos tests anclan
que la fecha actual (en la zona de la org) SIEMPRE viaja al LLM.

É-F4 Fase 2 añade dos anclas más, ambas nacidas de la conv 13: el modelo debe
poder distinguir lo que escribió él de lo que escribió el router (§2.1), y no
puede perder un hecho solo porque el mensaje que lo dijo salió de la ventana
(§2.2).
"""
import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.agent import prompts
from apps.agent.models import ContactIdentity, Conversation
from apps.channels.models import ChannelAccount, Message
from apps.organizations.models import Organization


class PromptsTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Fecha Org", timezone="America/Mexico_City")
        self.channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="990990990")
        self.contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500000000")
        self.conv = Conversation.objects.create(
            organization=self.org, channel_account=self.channel,
            contact=self.contact)

    def _inbound(self, body, available_at=None):
        return Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, direction=Message.DIRECTION_IN,
            author_type=Message.AUTHOR_CLIENT, body=body,
            status=Message.STATUS_PROCESSED, available_at=available_at,
        )

    def _outbound(self, body, author_type=Message.AUTHOR_AGENT,
                  semantic_type='', operation_key=''):
        return Message.objects.create(
            organization=self.org, channel_account=self.channel,
            conversation=self.conv, direction=Message.DIRECTION_OUT,
            author_type=author_type, semantic_type=semantic_type,
            operation_key=operation_key, body=body,
            status=Message.STATUS_SENT,
        )

    def _context_block(self):
        messages = prompts.assemble_messages(self.conv)
        self.assertEqual(messages[0]["role"], "system")
        # El primer bloque de sistema es el JSON de contexto.
        payload = messages[0]["content"].split("\n", 1)[1]
        return json.loads(payload)


class AssembleMessagesDateTests(PromptsTestCase):

    def test_context_includes_today(self):
        ctx = self._context_block()
        for key in ("fecha_hoy", "dia_semana", "hoy_legible", "hora_actual"):
            self.assertIn(key, ctx)

    def test_today_matches_org_timezone(self):
        from zoneinfo import ZoneInfo
        expected = timezone.now().astimezone(
            ZoneInfo(self.org.timezone)).date().isoformat()
        self.assertEqual(self._context_block()["fecha_hoy"], expected)

    def test_bad_timezone_does_not_crash(self):
        # Zona inválida → cae a localtime, nunca lanza (defensivo).
        Organization.objects.filter(pk=self.org.pk).update(timezone="Marte/Nada")
        self.conv.refresh_from_db()
        ctx = self._context_block()
        self.assertIn("fecha_hoy", ctx)


class AuthorshipTests(PromptsTestCase):
    """Fase 2 §2.1 (R11) — conv 13 / CR-6: el modelo veía como suyas las
    plantillas que escribió el router y llegó a disculparse por ellas."""

    def test_system_template_is_not_presented_as_the_agents_voice(self):
        self._outbound("Ahorita estamos fuera de horario",
                       author_type=Message.AUTHOR_SYSTEM)
        messages = prompts.assemble_messages(self.conv)
        rendered = messages[1:]
        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0]["role"], "system")
        self.assertIn("no lo redactaste", rendered[0]["content"].lower())
        # El texto sigue disponible (el cliente SÍ lo recibió: no repetirlo).
        self.assertIn("fuera de horario", rendered[0]["content"])
        # …pero ningún turno de assistant lo reclama como propio.
        self.assertEqual(
            [m for m in rendered if m["role"] == "assistant"], [])

    def test_agent_text_stays_the_agents_voice(self):
        self._outbound("La consulta cuesta *$350* 🐾")
        rendered = prompts.assemble_messages(self.conv)[1:]
        self.assertEqual(rendered, [
            {"role": "assistant", "content": "La consulta cuesta *$350* 🐾"},
        ])

    def test_human_staff_message_is_kept_but_distinguished(self):
        """Se CONSERVA como assistant (ignorarlo hacía que el agente
        contradijera a su compañero) — solo se distingue."""
        self._outbound("ok", author_type=Message.AUTHOR_HUMAN)
        rendered = prompts.assemble_messages(self.conv)[1:]
        self.assertEqual(len(rendered), 2)
        self.assertEqual(rendered[0]["role"], "system")
        self.assertIn("persona del equipo", rendered[0]["content"])
        self.assertEqual(rendered[1],
                         {"role": "assistant", "content": "ok"})




class OperationReceiptTests(PromptsTestCase):
    def test_receipt_enters_context_as_fact_not_as_copy_to_repeat(self):
        body = 'Tu cita para Luna quedó creada el viernes a las 12:30.'
        self._outbound(
            body, author_type=Message.AUTHOR_SYSTEM,
            semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
            operation_key='create-luna-1',
        )

        messages = prompts.assemble_messages(self.conv)

        self.assertTrue(self._context_block()['ultimo_recibo_operacion']
                        ['notificado_al_cliente'])
        rendered = messages[1:]
        self.assertEqual(len(rendered), 1)
        self.assertIn('ya notificó', rendered[0]['content'])
        self.assertNotIn(body, rendered[0]['content'])

    def test_same_operation_receipt_is_enqueued_once(self):
        from apps.agent.outbound import enqueue_outbound

        first = enqueue_outbound(
            self.conv, 'Cita creada', author='system',
            semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
            operation_key='create-luna-2',
        )
        second = enqueue_outbound(
            self.conv, 'Cita creada de nuevo', author='system',
            semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
            operation_key='create-luna-2',
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Message.objects.filter(
            conversation=self.conv,
            semantic_type=Message.SEMANTIC_OPERATION_RECEIPT,
            operation_key='create-luna-2',
        ).count(), 1)
class TurnWindowTests(PromptsTestCase):
    """Fase 2 §2.2 (R2) — CR-3: la ventana contaba MENSAJES y una ráfaga de
    WhatsApp se comía medio contexto."""

    def test_a_burst_of_seven_is_one_turn(self):
        stamp = timezone.now()
        burst = [self._inbound(f"parte {i}", available_at=stamp)
                 for i in range(7)]
        turns = prompts._group_into_turns(burst)
        self.assertEqual(len(turns), 1)
        self.assertEqual(len(turns[0]), 7)

    def test_separate_bursts_are_separate_turns(self):
        first = timezone.now()
        second = first + timedelta(minutes=5)
        messages = [
            self._inbound("hola", available_at=first),
            self._inbound("buenas", available_at=first),
            self._inbound("sigo aquí", available_at=second),
        ]
        turns = prompts._group_into_turns(messages)
        self.assertEqual([len(t) for t in turns], [2, 1])

    def test_inbound_without_available_at_never_groups(self):
        """Fixtures y filas legacy no traen `available_at`: agrupar por la
        AUSENCIA del dato inventaría turnos que nadie registró."""
        messages = [self._inbound("uno"), self._inbound("dos")]
        self.assertEqual(len(prompts._group_into_turns(messages)), 2)

    def test_burst_survives_a_history_that_message_counting_would_have_cut(self):
        """El contraste exacto de CR-3: 17 mensajes en 11 turnos.

        Contando MENSAJES (12) la ráfaga quedaba partida — se perdían sus
        primeros 5. Contando TURNOS (12) entra completa, que es lo que el
        cliente escribió: un solo pensamiento.
        """
        stamp = timezone.now()
        for i in range(7):
            self._inbound(f"ráfaga {i}", available_at=stamp)
        for i in range(5):                    # 5 × (saliente + entrante) = 10 turnos
            self._outbound(f"respuesta {i}")
            self._inbound(f"seguimiento {i}",
                          available_at=stamp + timedelta(minutes=i + 1))

        total_messages = Message.objects.filter(conversation=self.conv).count()
        self.assertEqual(total_messages, 17)
        self.assertLessEqual(
            len(prompts._group_into_turns(
                list(Message.objects.filter(conversation=self.conv)
                     .order_by('created_at', 'id')))),
            prompts.HISTORY_TURNS,
        )

        contents = [m["content"] for m in prompts.assemble_messages(self.conv)]
        for i in range(7):
            self.assertIn(f"ráfaga {i}", contents)

    def test_oldest_turns_still_fall_out_of_the_window(self):
        """La ventana sigue siendo una ventana: turnos ≠ historial infinito."""
        stamp = timezone.now()
        for i in range(prompts.HISTORY_TURNS + 3):
            self._inbound(f"turno {i}", available_at=stamp + timedelta(minutes=i))
        contents = [m["content"] for m in prompts.assemble_messages(self.conv)]
        self.assertNotIn("turno 0", contents)
        self.assertIn(f"turno {prompts.HISTORY_TURNS + 2}", contents)


class AnchoredIdentityFactsTests(PromptsTestCase):
    """Fase 2 §2.2 (R2) — el caso EXACTO de la conv 13: el cliente dijo "ya he
    ido varias veces", el router lo clasificó bien y nunca se lo pasó al
    modelo; al salir de la ventana el agente contestó "no me lo dijiste aún"."""

    def _fill_the_window(self):
        stamp = timezone.now()
        for i in range(prompts.HISTORY_MESSAGE_CAP + 5):
            self._inbound(f"relleno {i}",
                          available_at=stamp + timedelta(minutes=i))

    def test_lo_que_el_cliente_aporto_sobrevive_a_la_ventana(self):
        """R2 · salir de la ventana pierde el FRASEO, nunca el HECHO.

        Reescrito en É-F5 Fase 2. Antes el hecho anclado era el VEREDICTO de
        un tamiz determinista (`identity_triage_done='returning'` → «ya dijo
        que es cliente»); ahora es el DATO que el cliente aportó, que es lo
        que de verdad hacía falta: la conv 13 clasificó bien y aun así perdió
        el nombre.

        Reescrito otra vez en F0 del plan de continuidad: el dato viaja **con su
        procedencia**. Sin ella no se publica (D15), porque un valor suelto puede
        ser el nombre que el modelo copió de una fuga — que es exactamente cómo
        se verificó a sí mismo el sistema en la conv 18 de producción.
        """
        from apps.agent.identity_evidence import FLOW_KEY
        message = self._inbound("cita para Luna")
        self.conv.flow[FLOW_KEY] = {'pet_name': {
            'value': 'Luna', 'from_message': message.pk,
            'match_mode': 'passive_free_text',
            'captured_at': timezone.now().isoformat(),
        }}
        self.conv.save(update_fields=['flow'])
        self._fill_the_window()
        ctx = self._context_block()
        self.assertEqual(ctx["identidad"]["dijo_que_su_mascota_se_llama"],
                         "Luna")

    def test_an_unsourced_fact_never_travels(self):
        """D15 · el punto de control está en el ESCRITOR, pero el lector también
        se protege de las filas escritas antes del gate."""
        from apps.agent.identity_evidence import FLOW_KEY
        self.conv.flow[FLOW_KEY] = {'owner_name': 'Ana Cruz'}   # forma vieja
        self.conv.save(update_fields=['flow'])
        self.assertNotIn("identidad", self._context_block())

    def test_declared_titular_and_pending_factor_travel_too(self):
        from apps.agent import goals
        message = self._inbound("soy Ana")
        commitment = goals.start_identity(
            self.conv, goals.FAMILY, first_factor='digits',
            working_state={'candidate_ids': [1]})
        goals.satisfy(commitment, 'titular', 'Ana',
                      provenance={'from_message': message.pk,
                                  'match_mode': 'challenge_response'})
        ctx = self._context_block()
        self.assertEqual(ctx["identidad"]["titular_declarado"], "Ana")
        self.assertIn("4 dígitos", ctx["identidad"]["verificacion_pendiente"])

    def test_satisfy_refuses_an_identity_value_without_provenance(self):
        """El choke point (D15): bloquear en el escritor hace la regla cierta
        para cualquier vía futura de publicación."""
        from apps.agent import goals
        commitment = goals.start_identity(
            self.conv, goals.FAMILY, first_factor='digits')
        with self.assertRaises(ValueError):
            goals.satisfy(commitment, 'titular', 'Ana')

    def test_parked_challenge_still_counts_as_a_fact(self):
        """Apartado ≠ inexistente: para el modelo el hecho es el mismo — hay
        una verificación a medias con un titular declarado."""
        from apps.agent import goals
        message = self._inbound("soy Ana")
        commitment = goals.start_identity(
            self.conv, goals.FAMILY, first_factor='digits')
        goals.satisfy(commitment, 'titular', 'Ana',
                      provenance={'from_message': message.pk,
                                  'match_mode': 'challenge_response'})
        goals.park_identity(self.conv, commitment, going_to_human=True)
        ctx = self._context_block()
        self.assertEqual(ctx["identidad"]["titular_declarado"], "Ana")

    def test_no_identity_block_when_there_is_nothing_to_say(self):
        self.assertNotIn("identidad", self._context_block())


class VerifiedBehaviourPromptTests(PromptsTestCase):
    """F1a · el prompt tiene conducta para el caso VERIFICADO.

    En producción (conv 20) un contacto ya `confirmed_in_chat` recibió «Todavía
    no [sé quién eres], Andrés»: el modelo tenía el nombre en los DATOS y el
    bloque IDENTIDAD dedicaba ~30 líneas a pedir datos sin una sola regla para
    cuando el sistema ya sabe quién escribe.

    **Lo que estos tests NO prueban**: que el modelo obedezca. Eso no lo decide
    un `assertIn` sobre una plantilla — hace falta un eval contra el proveedor
    real. Lo que sí anclan es que las reglas y los ejemplos siguen ahí, que la
    prohibición no volvió a su forma absoluta, y que el dato que las activa
    (`verificado`) llega al modelo.
    """

    def _owner_contact(self, *, verified):
        from apps.patients.models import Owner
        owner = Owner.objects.create(
            organization=self.org, name="Andrés Ruiz", phone="5511667788")
        self.contact.owner = owner
        self.contact.verification_level = (
            ContactIdentity.VERIFICATION_CONFIRMED if verified
            else ContactIdentity.VERIFICATION_PHONE_MATCH)
        self.contact.verified_at = timezone.now() if verified else None
        self.contact.save(update_fields=[
            'owner', 'verification_level', 'verified_at'])
        self.conv.contact = self.contact
        return owner

    def test_the_prompt_has_a_rule_for_the_verified_case(self):
        prompt = prompts.SYSTEM_PROMPT
        self.assertIn('CUANDO `verificado` ES TRUE', prompt)
        self.assertIn('no le pidas que se identifique otra vez',
                      prompt.lower())

    def test_the_ban_stopped_being_absolute(self):
        """Antes: «Nunca digas ni des por hecho que alguien quedó verificado»,
        que empujaba al modelo a desconfiar de un dato que el sistema le daba
        como cierto. Sigue prohibido AFIRMARLO por su cuenta; usarlo, no."""
        prompt = prompts.SYSTEM_PROMPT
        self.assertNotIn('Nunca digas ni des por hecho que alguien quedó '
                         'verificado', prompt)
        self.assertIn('úsalo con naturalidad', prompt)

    def test_the_prompt_no_longer_enumerates_retired_factors(self):
        """v10 pedía «su nombre, el de su mascota o los últimos 4 dígitos». Los
        dos primeros ya no verifican (D4b) y pedirlos manda al cliente a dar un
        dato que no sirve."""
        self.assertNotIn('o los\núltimos 4 dígitos del teléfono con el que está '
                         'registrado', prompts.SYSTEM_PROMPT)

    def test_the_prompt_explains_the_expiry_instead_of_pretending(self):
        self.assertIn('la\nverificación caduca', prompts.SYSTEM_PROMPT)

    def test_both_cases_have_a_worked_example(self):
        prompt = prompts.SYSTEM_PROMPT
        self.assertIn('(`verificado: true`, cliente Andrés)', prompt)
        self.assertIn('(`verificado: false`, `numero_registrado: true`)', prompt)

    def test_the_verified_flag_reaches_the_model_with_the_name(self):
        self._owner_contact(verified=True)
        ctx = self._context_block()
        self.assertTrue(ctx['verificado'])
        self.assertEqual(ctx['cliente'], "Andrés Ruiz")

    def test_an_unverified_contact_gets_the_flag_without_the_name(self):
        """La otra mitad: la regla del caso false solo es honesta si el nombre
        de verdad no viaja."""
        self._owner_contact(verified=False)
        ctx = self._context_block()
        self.assertFalse(ctx['verificado'])
        self.assertTrue(ctx['numero_registrado'])
        self.assertIsNone(ctx['cliente'])

    def test_prompt_version_was_bumped(self):
        """`PROMPT_VERSION` viaja en cada `LLMCall`: sin bumpearlo no se puede
        correlacionar calidad con versión, que es para lo que existe."""
        self.assertEqual(prompts.PROMPT_VERSION, 'reception-f5-v12')
