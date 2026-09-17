"""B5 bounded conversational escalation, NOT clinical triage.

Versioned technical rules awaiting veterinary review. No LLM, diagnosis,
binary interpretation, network, clinical score or business capability.
"""
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta

CATALOG_VERSION = 'b5-safety-v1'
REVIEW_STATUS = 'VETERINARY_REVIEW_REQUIRED'
NO_SIGNAL = 'NO_SIGNAL'
POSSIBLE_URGENT = 'POSSIBLE_URGENT'
URGENT = 'URGENT'
logger = logging.getLogger('agent.events')


@dataclass(frozen=True, slots=True)
class SignalEvidence:
    code: str
    message_ids: tuple[int, ...]
    negated: bool
    temporality: str
    subject: str
    basis: str
    classification: str


@dataclass(frozen=True, slots=True)
class SafetyAssessment:
    classification: str
    evidence: tuple[SignalEvidence, ...] = ()
    media_uninterpreted: bool = False
    catalog_version: str = CATALOG_VERSION

    @property
    def matched_signals(self):
        return tuple(sorted({e.code for e in self.evidence if e.classification != NO_SIGNAL}))

    @property
    def recommended_action(self):
        return 'CONTINUE' if self.classification == NO_SIGNAL else 'GUIDANCE_HANDOFF'


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower())
                   if not unicodedata.combining(c))


# Catalog is deliberately finite. No fuzzy search or medical knowledge expansion.
SIGNALS = (
    ('RESPIRATORY', URGENT, r'\b(?:no respira|no (?:puede|pueda|logra|consigue) respirar|(?:dificultad|dificultades) (?:para |al )?respirar|cuesta(?: un buen| mucho| demasiado)? respirar|respiracion (?:muy )?trabajosa|ahogandose|se (?:esta )?ahogando)\b'),
    ('OPEN_MOUTH', POSSIBLE_URGENT, r'\b(?:respira\w* (?:con )?(?:la )?boca abierta|(?:esta|anda) con la boca abierta)\b'),
    ('RESPIRATORY_CONTEXT', POSSIBLE_URGENT, r'\b(?:respira raro|mira como esta respirando)\b'),
    ('URINARY', URGENT, r'\b(?:no (?:puede|pueda|logra|consigue) (?:orinar|hacer pipi)|no (?:hace|ase) pipi|no (?:le )?sale (?:la )?orina|(?:intent\w*|esfuer\w*)[^.!?\n]{0,90}(?:orinar|hacer pipi)[^.!?\n]{0,70}(?:no sale|no puede|sin orina))\b'),
    ('NEUROLOGICAL', URGENT, r'\b(?:convulsion\w*|se (?:me )?desmayo|se desplomo|inconsciente|perdio (?:el conocimiento|la consciencia|la conciencia)|no responde)\b'),
    ('REPORTED_DISTRESS', POSSIBLE_URGENT, r'\bse esta muriendo\b'),
    ('TRAUMA', URGENT, r'\b(?:atropell\w*|trauma severo|(?:se cayo|caida)[^.!?\n]{0,65}(?:no responde|no se mueve|esta muy mal))\b'),
    ('BLEEDING', URGENT, r'\b(?:sangr\w* (?:mucho|abundante\w*)|sangr\w*[^.!?\n]{0,35}no para|no (?:deja|para) de sangrar|hemorragia)\b'),
    ('TOXIC_EXPOSURE', URGENT, r'\b(?:comio|comer|come|ingirio|ingerido|trago|lamio|tomo|bebio)[^.!?\n]{0,65}(?:veneno|chocolate|anticongelante|sustancia toxica|algo toxico)\b'),
)
_HISTORICAL = re.compile(r'\b(?:el ano pasado|cuando era cachorro|antes|en 20\d\d|hace (?:\w+ ){1,3}(?:anos?|meses?|semanas?))\b')
_HYPOTHETICAL = re.compile(r'\b(?:si (?:un dia|algun dia|un perro)|algun dia|que (?:pasa|pasaria|hago) si|siempre es emergencia|como reconocer|es peligroso que|en caso de que)\b')
_REFERENCE = re.compile(r'\b(?:folleto|lei que|en internet|ejemplo|pelicula|factura|curso)\b')
_PRICE_REFERENCE = re.compile(r'\b(?:precio|costo|cuanto cuesta)\b')
_CURRENT_REPORT = re.compile(r'\b(?:ahorita|ahora|acaba|no puede|no respira|esta (?:convulsion\w*|sangr\w*|inconsciente))\b')
_SERVICE_SUBJECT = re.compile(r'\b(?:la clinica|el veterinario|el doctor|la recepcion|el chat|la app|el sistema)\s*$')
_HUMAN = re.compile(r'\b(?:mi (?:papa|mama|hermano|hijo|abuelo)|yo (?:no )?puedo)\b')
_NEGATION = re.compile(r'\b(?:no (?:esta|esta\w*|tiene|ha|le cuesta|parece|fue|comio|ingirio|convulsion\w*|presenta|sangr\w*|tuvo|se esta)|nunca|sin dificultad|no es que|ya (?:no|puede))\b')


def _context(clause):
    temporal = ('HISTORICAL' if _HISTORICAL.search(clause) else
                'HYPOTHETICAL' if _HYPOTHETICAL.search(clause) else
                'RECENT' if re.search(r'\b(?:ayer|hoy|acaba|hace .*minutos?)\b', clause) else 'CURRENT')
    subject = 'HUMAN' if _HUMAN.search(clause) else 'REPORTED_ANIMAL_OR_UNSPECIFIED'
    # A negative finding is scoped to this clause, never to another symptom.
    negated = bool(_NEGATION.search(clause))
    reference = bool(_REFERENCE.search(clause) or (
        _PRICE_REFERENCE.search(clause) and not _CURRENT_REPORT.search(clause)))
    return temporal, subject, negated, reference


def assess_texts(texts, *, message_ids=(), current_count=1, media_uninterpreted=False):
    """Pure corpus adapter. Older input is usable only by an explicit continuation.

    Production supplies the complete fixed burst as current_count, plus the
    bounded C1 history. No previous standalone positive is replayed as new.
    """
    texts = tuple(normalize(t or '') for t in texts)
    ids = tuple(message_ids) if message_ids else (None,) * len(texts)
    evidence = []
    first_current = max(0, len(texts) - current_count)
    for index in range(first_current, len(texts)):
        text = texts[index]
        previous = texts[index - 1] if index else ''
        refs = tuple(i for i in (ids[index],) if i is not None)
        # Only two bounded conceptual joins; never concatenate arbitrary history.
        previous_context = _context(previous)
        joins = []
        if (previous and previous_context[0] in ('CURRENT', 'RECENT')
                and previous_context[1:] == ('REPORTED_ANIMAL_OR_UNSPECIFIED', False, False)):
            if (re.search(r'\b(?:intent\w*|esfuer\w*)[^.!?]{0,65}(?:orinar|hacer pipi)', previous)
                    and re.search(r'\bno sale (?:nada|ni una gota|orina)\b', text)):
                joins.append(('URINARY', URGENT))
            if re.search(r'\brespir\w*', previous) and re.search(r'\bboca abierta\b', text):
                joins.append(('RESPIRATORY', URGENT))
        if joins:
            temporal, subject, negated, reference = _context(text)
            for code, level in joins:
                active = not negated and not reference and temporal in ('CURRENT', 'RECENT') and subject != 'HUMAN'
                evidence.append(SignalEvidence(code, tuple(i for i in ids[max(0,index-1):index+1] if i is not None),
                    negated, temporal, subject, 'CAUSAL_CONTINUATION', level if active else NO_SIGNAL))
        for clause in re.split(r'[.!;\n]|\b(?:pero|aunque|tambien)\b|\by (?=(?:no )?(?:esta|puede|le|se|tiene)\b)', text):
            temporal, subject, negated, reference = _context(clause)
            for code, level, pattern in SIGNALS:
                for match in re.finditer(pattern, clause):
                    signal_subject = subject
                    if match.group() == 'no responde' and _SERVICE_SUBJECT.search(clause[:match.start()]):
                        signal_subject = 'SERVICE'
                    if code == 'OPEN_MOUTH' and re.search(r'\bgat[oa]\b', text):
                        level = URGENT
                    if code == 'RESPIRATORY' and re.search(r'\b(?:creo|quizas|tal vez)\b', clause):
                        level = POSSIBLE_URGENT
                    if code == 'TOXIC_EXPOSURE' and 'algo toxico' in clause:
                        level = POSSIBLE_URGENT
                    active = (not negated and not reference and temporal in ('CURRENT', 'RECENT')
                              and signal_subject == 'REPORTED_ANIMAL_OR_UNSPECIFIED')
                    evidence.append(SignalEvidence(code, refs, negated, temporal, signal_subject,
                        'REFERENCE' if reference else 'DETERMINISTIC_GROUP', level if active else NO_SIGNAL))
    classification = (URGENT if any(e.classification == URGENT for e in evidence) else
                      POSSIBLE_URGENT if any(e.classification == POSSIBLE_URGENT for e in evidence) else NO_SIGNAL)
    return SafetyAssessment(classification, tuple(evidence), media_uninterpreted)


def assess_context(conversation, turn_context):
    """Only C1's scope/cursor can select prior textual evidence."""
    from apps.channels.events import event_from_message
    from apps.channels.models import Message
    from apps.channels.selectors import prior_messages
    turn_context.assert_scope(conversation)
    history = list(prior_messages(Message.objects.for_organization(turn_context.organization_id).filter(
        conversation_id=turn_context.conversation_id, channel_account_id=turn_context.channel_account_id,
        contact_id=turn_context.contact_id, direction='in',
        created_at__gte=turn_context.clinic_now - timedelta(minutes=15)),
        turn_context.history_before).order_by('-created_at', '-id')[:2])
    events = tuple(event_from_message(m) for m in reversed(history)) + turn_context.events
    assessment = assess_texts(tuple(e.text for e in events), message_ids=tuple(e.message_id for e in events),
        current_count=len(turn_context.events), media_uninterpreted=bool(turn_context.media_kinds))
    logger.info('AGENT_SAFETY_ASSESSMENT', extra={'event': 'AGENT_SAFETY_ASSESSMENT',
        'classification': assessment.classification, 'catalog_version': CATALOG_VERSION,
        'human_owned': bool(conversation.claimed_by_id or conversation.state == 'human_active'),
        'media_uninterpreted': assessment.media_uninterpreted})
    return assessment
