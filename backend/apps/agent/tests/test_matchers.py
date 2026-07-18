"""
test_matchers.py — É-F1 PR-11: clasificadores deterministas es-MX.
"""
from django.test import SimpleTestCase

from apps.agent import matchers


class EmergencyTests(SimpleTestCase):
    def test_detects_lemmas(self):
        for text in ["mi perro está convulsionando", "LO ATROPELLARON",
                     "no respira!!", "se comió veneno", "está sangrando mucho"]:
            self.assertTrue(matchers.is_emergency(text), text)

    def test_no_false_positive_on_normal(self):
        for text in ["quiero una cita", "cuánto cuesta la consulta",
                     "a qué hora abren"]:
            self.assertFalse(matchers.is_emergency(text), text)


class HumanAndOptoutTests(SimpleTestCase):
    def test_wants_human(self):
        for t in ["quiero hablar con una persona", "me atienda alguien del equipo",
                  "puedo hablar con un humano?"]:
            self.assertTrue(matchers.wants_human(t), t)

    def test_optout(self):
        for t in ["ya no me escriban", "STOP", "quiero darme de baja"]:
            self.assertTrue(matchers.wants_optout(t), t)
        self.assertFalse(matchers.wants_optout("no tengo cita"))


class BotQuestionTests(SimpleTestCase):
    def test_detects(self):
        for t in ["eres un robot?", "con quién hablo", "eres una persona real"]:
            self.assertTrue(matchers.is_bot_question(t), t)


class ConfirmationTests(SimpleTestCase):
    def test_affirmatives(self):
        for t in ["sí", "sale", "va", "simón", "claro que sí", "ok", "dale",
                  "está bien", "👍"]:
            self.assertEqual(matchers.classify_confirmation(t), 'affirmative', t)

    def test_negatives(self):
        for t in ["no", "mejor no", "cancela", "no gracias"]:
            self.assertEqual(matchers.classify_confirmation(t), 'negative', t)

    def test_false_affirmatives_are_defer(self):
        """El caso peligroso: NUNCA ejecutan ni cierran (UX-02)."""
        for t in ["ahorita", "déjame ver", "luego te digo", "yo te aviso",
                  "al rato", "déjame checar"]:
            self.assertEqual(matchers.classify_confirmation(t), 'defer', t)

    def test_unclear_goes_to_planner(self):
        for t in ["y más tarde no tienes?", "mejor el jueves", "cuánto queda"]:
            self.assertEqual(matchers.classify_confirmation(t), 'unclear', t)


class GreetingTests(SimpleTestCase):
    def test_bare_greeting(self):
        for t in ["hola", "buenas tardes", "qué tal"]:
            self.assertTrue(matchers.is_bare_greeting(t), t)

    def test_greeting_with_intent_is_not_bare(self):
        self.assertFalse(matchers.is_bare_greeting("hola quiero una cita"))

    def test_thanks(self):
        self.assertTrue(matchers.is_thanks("muchas gracias"))
        self.assertFalse(matchers.is_thanks("gracias, y una duda más"))
