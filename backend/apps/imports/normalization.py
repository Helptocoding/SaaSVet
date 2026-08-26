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
from decimal import Decimal, InvalidOperation

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
# Inventario — categoría, unidad base, decimal y booleanos.
# Deterministas: valor ambiguo NUNCA se convierte silenciosamente en válido
# ("abc" → decimal es error; bool ambiguo es error). El caller decide el default.
# ---------------------------------------------------------------------------
def _canonical_set(choices):
    return {c[0] for c in choices}


def normalize_category(raw):
    """Mapea categoría libre a CATEGORY_CHOICES de Product, o None si no resuelve.

    None ⇒ el caller importa como 'other' con WARNING visible en el preview
    (nunca bloquea: la categoría histórica sucia no debe frenar la migración).
    """
    from apps.inventory.models import Product
    key = normalize_text(raw)
    if not key:
        return None
    if key in _canonical_set(Product.CATEGORY_CHOICES):
        return key
    aliases = {
        'medicamento': 'medication', 'medicamentos': 'medication',
        'medicina': 'medication', 'medicinas': 'medication',
        'remedio': 'medication', 'farmaco': 'medication',
        'alimento': 'food', 'alimentos': 'food', 'comida': 'food',
        'pienso': 'food', 'croquetas': 'food',
        'accesorio': 'accessory', 'accesorios': 'accessory',
        'otro': 'other', 'otros': 'other', 'varios': 'other',
        'general': 'other', 'na': 'other', 'n/a': 'other',
    }
    return aliases.get(key)


_BASE_UNIT_ALIASES = {
    'pieza': 'piece', 'piezas': 'piece', 'pza': 'piece', 'pzas': 'piece',
    'pz': 'piece', 'pc': 'piece',
    'tableta': 'tablet', 'tabletas': 'tablet', 'tabs': 'tablet', 'tab': 'tablet',
    'capsula': 'capsule', 'capsulas': 'capsule', 'cap': 'capsule', 'caps': 'capsule',
    'ampolleta': 'ampoule', 'ampolletas': 'ampoule', 'ampolla': 'ampoule',
    'ampollas': 'ampoule', 'amp': 'ampoule',
    'viales': 'vial',
    'frascos': 'bottle',
    'bolsas': 'bag',
    'tubos': 'tube',
    'kilogramo': 'kg', 'kilogramos': 'kg', 'kilo': 'kg', 'kilos': 'kg',
    'gramo': 'g', 'gramos': 'g', 'gr': 'g',
    'mililitro': 'ml', 'mililitros': 'ml',
    'unidad': 'unit', 'unidades': 'unit', 'u': 'unit',
}


def normalize_base_unit(raw):
    """Mapea unidad libre a BASE_UNIT_CHOICES de Product, o None si no resuelve.

    None ⇒ el caller importa con 'unit' + WARNING (Presentation.base_unit es
    NOT NULL y no existe estado "pendiente"; decisión D4 del plan).
    """
    from apps.inventory.models import Product
    key = normalize_text(raw)
    if not key:
        return None
    if key in _canonical_set(Product.BASE_UNIT_CHOICES):
        return key
    return _BASE_UNIT_ALIASES.get(key)


_CURRENCY_CHARS = '$ \t\xa0\u202f'


def parse_decimal(raw):
    """Parseo ESTRICTO de decimales de Excel/CSV → (Decimal|None, ok).

    - Vacío (None/''/espacios) → (None, True): ausencia legítima; el caller
      aplica su default (stock→0, cf→1…).
    - Válido → (Decimal, True). Acepta '$' y espacios alrededor; separador
      decimal '.' o ',' (uno solo, consistente). Signo negativo parsea; el
      caller aplica su regla de dominio (≥0 / >0).
    - No vacío inválido ("abc", "1.234.56", "1,234.56", "", exponentes) →
      (None, False): el caller lo reporta como ERROR de fila (blocking).
    """
    if raw is None:
        return None, True
    text = str(raw)
    for ch in _CURRENCY_CHARS:
        text = text.replace(ch, '')
    text = text.strip()
    if not text:
        return None, True
    if text.count(',') and text.count('.'):
        # Separadores mezclados: ambiguo sin locale (miles vs decimal). Error.
        return None, False
    normalized = text.replace(',', '.')
    body = normalized[1:] if normalized.startswith('-') else normalized
    if (
        not body
        or not body.replace('.', '', 1).isdigit()
        or normalized.count('.') > 1
        or '+' in normalized or 'e' in normalized.lower()
    ):
        return None, False
    try:
        return Decimal(normalized), True
    except InvalidOperation:
        return None, False


_TRUE_WORDS = {
    'si', 'yes', 'true', 'verdadero', 'v', '1', 'x', 'y',
}
_FALSE_WORDS = {
    'no', 'false', 'falso', 'f', '0', 'n',
}


def parse_bool(raw):
    """Booleano estricto → True | False | None.

    None = vacío o ambiguo. Para campos con implicancia operativa
    (requires_prescription afecta billing/receta) el caller trata None-no-vacío
    como ERROR: nunca False silencioso.
    """
    key = normalize_text(raw)
    if not key:
        return None
    if key in _TRUE_WORDS:
        return True
    if key in _FALSE_WORDS:
        return False
    return None


# ---------------------------------------------------------------------------
# Catálogo de campos destino por entity_type (consumido por la UI de mapeo).
# ---------------------------------------------------------------------------
# Labels en lenguaje humano (sin prefijos técnicos tipo "Cliente · Nombre").
# `group` agrupa visualmente. `importance` ∈ {required, recommended, optional}
# para que la UI muestre Obligatorio / Recomendado / Opcional.
# Solo nombre de cliente y nombre de mascota son obligatorios; especie y teléfono
# son recomendados (no bloquean la importación de datos históricos).
FIELD_CATALOG = {
    'owner_pet': [
        {'key': 'owner.name', 'label': 'Nombre del cliente', 'group': 'Cliente', 'importance': 'required'},
        {'key': 'owner.phone', 'label': 'Teléfono del cliente', 'group': 'Cliente', 'importance': 'recommended'},
        {'key': 'owner.legacy_id', 'label': 'Nº de cliente anterior', 'group': 'Cliente', 'importance': 'optional'},
        # Dato histórico del cliente sin campo propio (Fase D). many→1 permitido.
        {'key': 'owner.extra', 'label': 'Dato del cliente', 'group': 'Cliente', 'importance': 'optional', 'is_extra': True},
        {'key': 'pet.name', 'label': 'Nombre de la mascota', 'group': 'Mascota', 'importance': 'required'},
        {'key': 'pet.species', 'label': 'Especie', 'group': 'Mascota', 'importance': 'recommended'},
        {'key': 'pet.breed', 'label': 'Raza', 'group': 'Mascota', 'importance': 'optional'},
        {'key': 'pet.sex', 'label': 'Sexo', 'group': 'Mascota', 'importance': 'optional'},
        {'key': 'pet.birth_date', 'label': 'Fecha de nacimiento', 'group': 'Mascota', 'importance': 'optional'},
        {'key': 'pet.color', 'label': 'Color', 'group': 'Mascota', 'importance': 'optional'},
        {'key': 'pet.legacy_id', 'label': 'Nº de expediente anterior', 'group': 'Mascota', 'importance': 'optional'},
        # Dato histórico de la mascota sin campo propio (Fase D). many→1 permitido.
        {'key': 'pet.extra', 'label': 'Dato de la mascota', 'group': 'Mascota', 'importance': 'optional', 'is_extra': True},
    ],
    # Importador de inventario (plan PLAN-importador-inventario.md §4).
    # sale_price required: CHECK DB presentation_sale_price_positive (>0) y billing
    # lo exige — sin precio válido la fila es bloqueante (nunca se inventa dinero).
    'inventory': [
        {'key': 'product.name', 'label': 'Nombre del producto', 'group': 'Producto', 'importance': 'required'},
        {'key': 'presentation.sale_price', 'label': 'Precio de venta', 'group': 'Presentación', 'importance': 'required'},
        {'key': 'product.internal_code', 'label': 'Código interno', 'group': 'Producto', 'importance': 'recommended'},
        {'key': 'product.category', 'label': 'Categoría', 'group': 'Producto', 'importance': 'recommended'},
        {'key': 'product.base_unit', 'label': 'Unidad base', 'group': 'Producto', 'importance': 'recommended'},
        {'key': 'product.stock', 'label': 'Existencia inicial', 'group': 'Producto', 'importance': 'recommended'},
        {'key': 'product.min_stock', 'label': 'Stock mínimo', 'group': 'Producto', 'importance': 'optional'},
        {'key': 'presentation.name', 'label': 'Nombre de la presentación', 'group': 'Presentación', 'importance': 'optional'},
        {'key': 'presentation.conversion_factor', 'label': 'Factor de conversión', 'group': 'Presentación', 'importance': 'optional'},
        {'key': 'presentation.barcode', 'label': 'Código de barras', 'group': 'Presentación', 'importance': 'optional'},
        {'key': 'presentation.purchase_price', 'label': 'Precio de compra', 'group': 'Presentación', 'importance': 'optional'},
        {'key': 'product.description', 'label': 'Descripción', 'group': 'Producto', 'importance': 'optional'},
        {'key': 'product.manufacturer', 'label': 'Fabricante', 'group': 'Producto', 'importance': 'optional'},
        {'key': 'product.requires_prescription', 'label': 'Requiere receta', 'group': 'Producto', 'importance': 'optional'},
        # Dato histórico del producto sin campo propio (Product.extra_data, patrón
        # Fase D / ADR p43). many→1 permitido.
        {'key': 'product.extra', 'label': 'Dato del producto', 'group': 'Producto', 'importance': 'optional', 'is_extra': True},
    ],
}


def required_fields(entity_type):
    return [f['key'] for f in FIELD_CATALOG.get(entity_type, []) if f.get('importance') == 'required']


def extra_target_fields(entity_type):
    """Keys destino que aceptan MUCHAS columnas → una lista (exentos del dedup 1:1):
    owner.extra / pet.extra (Fase D, datos del sistema anterior)."""
    return {f['key'] for f in FIELD_CATALOG.get(entity_type, []) if f.get('is_extra')}


def field_label(entity_type, key):
    """Label humano de un campo destino (para mensajes de error legibles)."""
    for f in FIELD_CATALOG.get(entity_type, []):
        if f['key'] == key:
            return f['label']
    return key


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
    # Importador de inventario (plan §4). Claves normalizadas (sin acentos).
    'inventory': {
        'product.name': [
            'producto', 'productos', 'articulo', 'nombre producto',
            'nombre del producto', 'nombre articulo', 'descripcion producto',
        ],
        'product.internal_code': [
            'codigo', 'codigo interno', 'código interno', 'codigo producto',
            'codigo de producto', 'sku', 'clave', 'clave interna', 'id producto',
        ],
        'product.category': [
            'categoria', 'categoria producto', 'tipo', 'rubro', 'linea',
            'familia',
        ],
        'product.base_unit': ['unidad', 'unidad base', 'umedida', 'u de medida'],
        'product.stock': [
            'existencia', 'existencias', 'stock', 'stock actual',
            'existencia inicial', 'inventario', 'cantidad', 'cantidad actual',
        ],
        'product.min_stock': [
            'minimo', 'stock minimo', 'minimo stock', 'punto de reorden',
            'stock min', 'min',
        ],
        'presentation.name': [
            'presentacion', 'presentacion comercial', 'formato', 'formato venta',
        ],
        'presentation.conversion_factor': [
            'factor', 'factor conversion', 'factor de conversion', 'contenido',
            'piezas por caja', 'unidades por caja', 'equivale a',
        ],
        'presentation.barcode': [
            'codigo de barras', 'codigo barras', 'codigobarras', 'barcode',
            'upc', 'ean', 'cbarra',
        ],
        'presentation.sale_price': [
            'precio', 'precio venta', 'precio de venta', 'pvp', 'precio publico',
            'precio unitario',
        ],
        'presentation.purchase_price': [
            'precio compra', 'precio de compra', 'costo', 'costo compra',
            'costo de compra', 'ultimo costo',
        ],
        'product.description': ['descripcion', 'detalle', 'notas'],
        'product.manufacturer': ['fabricante', 'laboratorio', 'marca', 'proveedor marca'],
        'product.requires_prescription': [
            'receta', 'requiere receta', 'requiere receta medica', 'controlado',
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
