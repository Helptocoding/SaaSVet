"""
test_f5_fase5.py — É-F5 Fase 5: qué plantillas sobreviven, y por qué.

La fase no se define por cuántas plantillas quedan sino por **qué tienen en
común las que quedan**. El criterio, y es el que hay que defender:

    Sobrevive la plantilla solo donde llamar al modelo es IMPOSIBLE, está
    PROHIBIDO, o se CONTRADICE a sí mismo.

Aplicado una por una:

    T0_DISABLED       el buzón está apagado — no hay modelo al que preguntar
    T0_EMERGENCY      G2 prohíbe que el modelo valore un cuadro clínico
    T0_PRIVACY        texto legal (LFPDPPP): tiene que salir literal
    T0_TECH_PROBLEM   el modelo está caído — es el propio fallo
    T0_GUARD_BLOCKED  acaban de bloquear su salida; volver a pedírsela es absurdo
    T0_BUDGET         no quedan llamadas: gastar una contradice el motivo
    T0_BOTQ           la respuesta es una obligación de transparencia (ver abajo)
    T0_HANDOFF·*      promesas de escalada (ver abajo)
    T0_GOAL_STALLED   la conversación no avanza; el modelo ya falló tres veces
    T0_DEFER          acuse de una promesa que el recordatorio no debe contradecir

Las tres últimas familias NO son conveniencias y por eso no cayeron con el
resto; sobre `T0_BOTQ` y las escaladas, ver las notas del commit y de
`policy.evaluate`.

Lo que este archivo impide es la regresión silenciosa: que alguien vuelva a
meter una constante para "ahorrar una llamada" en un turno que el modelo debía
haber leído. Añadir una plantilla nueva obliga a tocar este test y, por tanto,
a justificar bajo cuál de los tres supuestos cae.
"""
from django.test import SimpleTestCase

from apps.agent import matchers, policy, situation, tier0

# El inventario vivo. Crece SOLO con justificación explícita.
SALVAGUARDAS = {
    'T0_DISABLED',
    'T0_EMERGENCY',
    'T0_EMERGENCY_NO_PHONE',
    'T0_PRIVACY',
    'T0_TECH_PROBLEM',
    'T0_GUARD_BLOCKED',
    'T0_BUDGET',
    'T0_BOTQ',
    'T0_HANDOFF',
    'T0_HANDOFF_AFTER_HOURS',
    'T0_HANDOFF_WAITING',
    'T0_GOAL_STALLED',
    'T0_DEFER',
    # El saludo del buzón F0 y su sufijo: el camino SIN modelo.
    'T0_GREET',
    'T0_AFTER_HOURS_SUFFIX',
    # Identidad (plan de continuidad, F0). Las dos caen en el supuesto de
    # «llamar al modelo está prohibido», y por el mismo motivo que `T0_PRIVACY`:
    #
    # - `T0_IDENTITY_QUESTION` es la pregunta que SOSTIENE el régimen probatorio.
    #   Si la redactara el modelo, podría preguntar por otra cosa —los últimos 4
    #   dígitos, por ejemplo— y ese saliente quedaría sellado como si fuera el
    #   reto de la mascota: una respuesta «Luna» recibiría el matcher tolerante
    #   sobre una pregunta que nunca se hizo. El modelo redacta el resto del
    #   mensaje; esta línea la pone el sistema.
    # - `T0_IDENTITY_ECHO` sale cuando el dato con el que el cliente intentó
    #   identificarse lo habíamos dicho nosotros primero. Es genérico A
    #   PROPÓSITO: repetir el nombre sería la fuga que este camino cierra, y
    #   dejar al modelo redactarlo es pedirle que hable de un dato que no puede
    #   nombrar.
    'T0_IDENTITY_QUESTION',
    'T0_IDENTITY_ECHO',
    # Un «sí» sin propuesta persistida no tiene una operación que ejecutar.
    # Llamar al modelo aquí sería peligroso: podría inventar o prometer una
    # confirmación no vinculada, recreando la doble confirmación. La respuesta
    # fija obliga a iniciar una solicitud real, que el sistema podrá sellar
    # como Message.SEMANTIC_CONFIRMATION antes de aceptar otro «sí».
    'T0_CONFIRMATION_UNAVAILABLE',
}

# Las que retiró esta fase. Que no vuelvan por la puerta de atrás.
RETIRADAS = {
    'T0_THANKS', 'T0_OUT_PAYMENT', 'T0_OUT_MEDICAL',
    'T0_MEDIA_AUDIO', 'T0_MEDIA_OTHER',
}


class InventarioDePlantillasTests(SimpleTestCase):
    def test_solo_sobreviven_las_salvaguardas_declaradas(self):
        vivas = {n for n in dir(tier0) if n.startswith('T0_')}
        nuevas = vivas - SALVAGUARDAS
        self.assertEqual(
            nuevas, set(),
            f"Plantillas nuevas sin justificar: {sorted(nuevas)}. Una plantilla "
            f"solo se añade si llamar al modelo es imposible, está prohibido o "
            f"se contradice a sí mismo. Si no cae ahí, es un HECHO para "
            f"`situation.read`, no una constante.")

    def test_las_retiradas_no_vuelven(self):
        for nombre in sorted(RETIRADAS):
            with self.subTest(plantilla=nombre):
                self.assertFalse(hasattr(tier0, nombre))

    def test_render_media_reply_ya_no_existe(self):
        self.assertFalse(hasattr(tier0, 'render_media_reply'))


class LosHechosSustituyenALasPlantillasTests(SimpleTestCase):
    """Cada plantilla retirada dejó un hecho en su lugar.

    Retirar sin sustituir no sería 'dejar hablar al modelo': sería quitarle la
    información con la que responder.
    """

    def test_gracias(self):
        self.assertTrue(situation.read(None, "muchas gracias")['agradece'])

    def test_pago(self):
        facts = situation.read(None, "te paso una transferencia?")
        self.assertTrue(facts['quiere_pagar_por_aqui_y_aqui_no_se_cobra'])

    def test_media(self):
        self.assertEqual(
            situation.read(None, "", media_kinds=['audio'])
            ['mando_algo_que_no_puedo_leer'], 'una nota de voz')

    def test_primer_mensaje(self):
        self.assertTrue(
            situation.read(None, "hola", first_contact=True)
            ['es_su_primer_mensaje_con_nosotros'])

    def test_el_matcher_de_pagos_vive_donde_viven_los_matchers(self):
        """Se mudó de `policy` a `matchers` al dejar de alimentar una decisión."""
        self.assertTrue(matchers.mentions_payment("me pasas tu cuenta"))
        self.assertFalse(hasattr(policy, '_mentions_payment'))


class ElErrorEsUnHechoNoUnGuionTests(SimpleTestCase):
    """`_soft_error_hint` → `_error_fact`.

    Antes cada error suave terminaba en una orden ("Ofrécele una fecha
    futura"), y el modelo obedecía la orden en vez de atender al cliente: todos
    los tropiezos de agenda sonaban igual. Ahora dicen qué pasó.
    """

    IMPERATIVOS = ('pregúntale', 'pídesela', 'pídeselo', 'ofrécele',
                   'discúlpate', 'confírmalo', 'revisa', 'trátalo')

    def test_los_hechos_no_dan_ordenes(self):
        from apps.agent.planner import _error_fact
        for code in ('need_data', 'need_date', 'bad_date', 'past_date',
                     'past_appointment',
                     'slot_taken', 'no_vet', 'unknown_handle', 'not_cancelable',
                     'not_reschedulable', 'already_a_client',
                     'ambiguous_identity', 'invalid_data', 'invalid_slot',
                     'confirm_slot', 'out_of_horizon', 'tool_failure'):
            with self.subTest(code=code):
                texto = _error_fact(code).lower()
                for orden in self.IMPERATIVOS:
                    self.assertNotIn(
                        orden, texto,
                        f"'{code}' volvió a ser un guion: dice qué HACER en vez "
                        f"de qué PASÓ.")

    def test_las_correcciones_de_conducta_si_son_imperativas(self):
        """La excepción, y es deliberada: estas dos no describen el mundo,
        corrigen al propio modelo. Ahí el imperativo ES el contenido."""
        from apps.agent.planner import _error_fact
        self.assertIn('no se lo vuelvas a preguntar',
                      _error_fact('change_approach').lower())
        self.assertIn('pídele', _error_fact('verification_required').lower())

    def test_los_limites_del_negocio_siguen_viajando(self):
        """Quitar la orden no puede quitar el dato: '60 días' es verdad del
        negocio, no consejo de redacción."""
        from apps.agent.planner import _error_fact
        self.assertIn('60 días', _error_fact('out_of_horizon'))
