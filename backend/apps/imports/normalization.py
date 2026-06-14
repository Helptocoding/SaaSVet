"""
imports/normalization.py — Normalización de datos sucios de Excel + auto-mapeo.

Los archivos reales de clínicas vienen inconsistentes: "Perro"/"PERRO"/"canino",
"Max"/"MAX", encabezados "Dueño"/"Cliente"/"Propietario". Este módulo:

  1. normalize_text  — clave de comparación (lower, sin acentos, espacios colapsados).
  2. normalize_species / normalize_sex — mapean valores libres al catálogo cerrado.
  3. suggest_mapping — heurística de auto-mapeo columna→campo (NO IA, solo alias).
  4. FIELD_CATALOG — campos destino por entity_type (lo consume la UI de mapeo).
"""
import unicodedata

from apps.patients.models import SPECIES_CHOICES


def _strip_accents(text):
    return ''.join(
        c for c in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(c)
    )


def normalize_text(value):
    """Clave de comparación canónica: lower + sin acentos + espacios colapsados.

    "Juan  Pérez " == "JUAN PEREZ" == "juan perez" → "juan perez".
    Usada para dedup por nombre y para matchear alias de columnas/valores.
    """
    if value is None:
        return ''
    text = _strip_accents(str(value)).lower().strip()
    return ' '.join(text.split())


# ---------------------------------------------------------------------------
# Especie — catálogo cerrado SPECIES_CHOICES; lo demás es alias o desconocido.
# ---------------------------------------------------------------------------
# Canónicos válidos (con acento donde aplica): canino felino equino ave reptil
# exótico otro. El alias se resuelve por normalize_text (sin acentos).
_SPECIES_ALIASES = {
    'perro': 'canino', 'perros': 'canino', 'can': 'canino', 'canino': 'canino',
    'cachorro': 'canino', 'dog': 'canino',
    'gato': 'felino', 'gatos': 'felino', 'felino': 'felino', 'minino': 'felino',
    'cat': 'felino',
    'caballo': 'equino', 'yegua': 'equino', 'equino': 'equino', 'potro': 'equino',
    'ave': 'ave', 'pajaro': 'ave', 'loro': 'ave', 'perico': 'ave',
    'canario': 'ave', 'bird': 'ave',
    'reptil': 'reptil', 'serpiente': 'reptil', 'iguana': 'reptil',
    'tortuga': 'reptil', 'lagarto': 'reptil',
    'exotico': 'exótico', 'huron': 'exótico', 'conejo': 'exótico',
    'hamster': 'exótico', 'cuyo': 'exótico', 'cobayo': 'exótico',
    'otro': 'otro', 'otros': 'otro', 'na': 'otro', 'n/a': 'otro',
}


def normalize_species(raw):
    """Devuelve la especie canónica (∈ SPECIES_CHOICES) o None si no se resuelve.

    None ⇒ el caller reporta error de fila (no se inventa 'otro' silenciosamente;
    el usuario decide corregir el archivo).
    """
    key = normalize_text(raw)
    if not key:
        return None
    if key in SPECIES_CHOICES:
        return key
    return _SPECIES_ALIASES.get(key)


_SEX_ALIASES = {
    'male': 'male', 'macho': 'male', 'm': 'male', 'masculino': 'male',
    'female': 'female', 'hembra': 'female', 'h': 'female', 'f': 'female',
    'femenino': 'female',
}


def normalize_sex(raw):
    """Mapea sexo libre a {male, female, unknown}. Default unknown (campo opcional)."""
    return _SEX_ALIASES.get(normalize_text(raw), 'unknown')


# ---------------------------------------------------------------------------
# Catálogo de campos destino por entity_type (consumido por la UI de mapeo).
# ---------------------------------------------------------------------------
FIELD_CATALOG = {
    'owner_pet': [
        {'key': 'owner.name', 'label': 'Cliente · Nombre', 'group': 'Cliente', 'required': True},
        {'key': 'owner.phone', 'label': 'Cliente · Teléfono', 'group': 'Cliente', 'required': False},
        {'key': 'owner.legacy_id', 'label': 'Cliente · Nº de cliente anterior', 'group': 'Cliente', 'required': False},
        {'key': 'pet.name', 'label': 'Mascota · Nombre', 'group': 'Mascota', 'required': True},
        {'key': 'pet.species', 'label': 'Mascota · Especie', 'group': 'Mascota', 'required': True},
        {'key': 'pet.breed', 'label': 'Mascota · Raza', 'group': 'Mascota', 'required': False},
        {'key': 'pet.sex', 'label': 'Mascota · Sexo', 'group': 'Mascota', 'required': False},
        {'key': 'pet.birth_date', 'label': 'Mascota · Fecha de nacimiento', 'group': 'Mascota', 'required': False},
        {'key': 'pet.color', 'label': 'Mascota · Color', 'group': 'Mascota', 'required': False},
        {'key': 'pet.legacy_id', 'label': 'Mascota · Nº de expediente anterior', 'group': 'Mascota', 'required': False},
    ],
}


def required_fields(entity_type):
    return [f['key'] for f in FIELD_CATALOG.get(entity_type, []) if f['required']]


def valid_target_fields(entity_type):
    return {f['key'] for f in FIELD_CATALOG.get(entity_type, [])}


# Alias de encabezados → campo destino. Clave = normalize_text(header).
# "Número de expediente anterior" se ofrece como label en UI; el archivo viejo
# trae "Expediente", "Folio", "No. Cliente", etc.
_COLUMN_ALIASES = {
    'owner_pet': {
        'owner.name': [
            'dueño', 'dueno', 'cliente', 'propietario', 'nombre dueño',
            'nombre del dueño', 'nombre cliente', 'nombre del cliente', 'tutor',
            'responsable',
        ],
        'owner.phone': [
            'telefono', 'teléfono', 'tel', 'cel', 'celular', 'movil', 'móvil',
            'whatsapp', 'whats', 'contacto', 'numero', 'número', 'telefono cliente',
        ],
        'owner.legacy_id': [
            'no cliente', 'no. cliente', 'numero cliente', 'codigo cliente',
            'codigo de cliente', 'id cliente', 'clave cliente',
        ],
        'pet.name': [
            'mascota', 'paciente', 'nombre mascota', 'nombre del paciente',
            'nombre paciente', 'animal',
        ],
        'pet.species': [
            'especie', 'tipo', 'tipo animal', 'tipo de animal', 'tipo de mascota',
            'especie mascota',
        ],
        'pet.breed': ['raza', 'breed'],
        'pet.sex': ['sexo', 'genero', 'género', 'sex'],
        'pet.birth_date': [
            'fecha nacimiento', 'fecha de nacimiento', 'nacimiento', 'f. nacimiento',
            'fec nacimiento', 'birth date',
        ],
        'pet.color': ['color', 'capa'],
        'pet.legacy_id': [
            'expediente', 'no expediente', 'no. expediente', 'numero expediente',
            'folio', 'codigo', 'código', 'clave', 'id', 'historia clinica',
            'historia clínica', 'hc',
        ],
    },
}


def suggest_mapping(columns, entity_type):
    """Heurística de auto-mapeo: { header_original: campo_destino }.

    Match por alias exacto sobre normalize_text(header). Sin coincidencia ⇒ la
    columna queda sin mapear (la UI permite asignarla a mano). El usuario SIEMPRE
    confirma — la sugerencia no escribe nada.
    """
    aliases = _COLUMN_ALIASES.get(entity_type, {})
    # Invertir a { alias_normalizado: campo_destino } para lookup O(1).
    lookup = {}
    for field, names in aliases.items():
        for name in names:
            lookup[normalize_text(name)] = field

    suggestion = {}
    used_fields = set()
    for header in columns:
        field = lookup.get(normalize_text(header))
        # No sugerir el mismo campo para dos columnas distintas (1ª gana).
        if field and field not in used_fields:
            suggestion[header] = field
            used_fields.add(field)
    return suggestion
