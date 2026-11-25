"""Catálogo cerrado de especialidades veterinarias (ADR p68).

Fuente única. Un integrante puede tener varias (``User.specialties``) y un
servicio, una (``Service.specialty``); ambos eligen de esta misma lista, así que
«qué especialidades ofrece la clínica» deja de depender de que dos textos libres
se escriban igual. El frontend tiene una copia en
``frontend/src/features/staff/specialties.json``; una prueba exige que coincidan.

Los códigos son estables (se guardan en la base); las etiquetas son lo que se
muestra y se imprime.
"""
import unicodedata

SPECIALTIES = (
    ('general_medicine', 'Medicina general'),
    ('internal_medicine', 'Medicina interna'),
    ('surgery', 'Cirugía'),
    ('dermatology', 'Dermatología'),
    ('ophthalmology', 'Oftalmología'),
    ('cardiology', 'Cardiología'),
    ('dentistry', 'Odontología'),
    ('orthopedics', 'Ortopedia y traumatología'),
    ('oncology', 'Oncología'),
    ('neurology', 'Neurología'),
    ('imaging', 'Imagenología'),
    ('anesthesiology', 'Anestesiología'),
    ('behavior', 'Etología (comportamiento)'),
    ('exotics', 'Animales exóticos'),
    ('rehabilitation', 'Rehabilitación y fisioterapia'),
    ('nutrition', 'Nutrición'),
)

SPECIALTY_CODES = tuple(code for code, _ in SPECIALTIES)
_LABELS = dict(SPECIALTIES)
_ORDER = {code: index for index, code in enumerate(SPECIALTY_CODES)}


def specialty_label(code):
    return _LABELS.get(code, '')


def normalize_specialties(codes):
    """Códigos válidos, sin repetir y en el orden del catálogo. ``ValueError`` si
    alguno no existe: un código desconocido es un error del llamador, no algo
    que se descarte en silencio."""
    unique = set(codes or ())
    unknown = sorted(code for code in unique if code not in _LABELS)
    if unknown:
        raise ValueError(unknown)
    return sorted(unique, key=_ORDER.__getitem__)


def specialties_display(codes):
    """«Cirugía, Dermatología»: lo que se muestra y se congela en documentos."""
    return ', '.join(_LABELS[code] for code in codes or () if code in _LABELS)


def _fold(text):
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode()
    return ' '.join(text.lower().split())


# Formas habituales de escribir una especialidad a mano (para pasar texto libre
# al catálogo). Solo se usa al migrar el dato anterior.
_FREE_TEXT_ALIASES = {
    'general': 'general_medicine', 'medico general': 'general_medicine',
    'consulta general': 'general_medicine', 'medicina veterinaria': 'general_medicine',
    'interna': 'internal_medicine',
    'cirujano': 'surgery', 'cirujana': 'surgery', 'cirugia general': 'surgery',
    'dermatologo': 'dermatology', 'dermatologa': 'dermatology',
    'oftalmologo': 'ophthalmology', 'oftalmologa': 'ophthalmology',
    'cardiologo': 'cardiology', 'cardiologa': 'cardiology',
    'odontologo': 'dentistry', 'odontologa': 'dentistry', 'dental': 'dentistry',
    'ortopedia': 'orthopedics', 'traumatologia': 'orthopedics', 'ortopedista': 'orthopedics',
    'oncologo': 'oncology', 'oncologa': 'oncology',
    'neurologo': 'neurology', 'neurologa': 'neurology',
    'radiologia': 'imaging', 'ultrasonido': 'imaging',
    'anestesia': 'anesthesiology', 'anestesiologo': 'anesthesiology',
    'etologia': 'behavior', 'comportamiento': 'behavior', 'conducta': 'behavior',
    'exoticos': 'exotics', 'fauna silvestre': 'exotics',
    'rehabilitacion': 'rehabilitation', 'fisioterapia': 'rehabilitation',
    'nutriologa': 'nutrition', 'nutriologo': 'nutrition',
}
_BY_FOLDED_LABEL = {_fold(label): code for code, label in SPECIALTIES}


def specialties_from_free_text(text):
    """Texto libre anterior → códigos del catálogo. Separa por comas, «y» y «/»;
    lo que no reconoce se descarta (ADR p68: no hay datos reales que conservar)."""
    folded = _fold(text)
    if not folded:
        return []
    for separator in (' y ', '/', ';', '|'):
        folded = folded.replace(separator, ',')
    codes = []
    for part in (piece.strip() for piece in folded.split(',')):
        code = _BY_FOLDED_LABEL.get(part) or _FREE_TEXT_ALIASES.get(part)
        if code:
            codes.append(code)
    return normalize_specialties(codes)
