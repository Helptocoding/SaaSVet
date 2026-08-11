"""patients/services.py — Identidad de expediente por teléfono (INV-C).

Fuente **única** de la pregunta «¿este teléfono ya tiene expediente en esta
organización?». Antes había cuatro respuestas distintas para la misma pregunta
—`create-with-patient` deduplicaba por teléfono, `/api/pets/` por
`(nombre, teléfono)`, el importador tomaba `.first()` sobre los duplicados, y
los lectores del agente comparaban un valor normalizado contra la columna
cruda— y cada una podía **elegir** entre expedientes históricos duplicados.

> **INV-C** — Un teléfono normalizado identifica *como máximo* un expediente
> dentro de una organización. Si hay más de uno, el resultado es
> `owner_ambiguous` y el caso escala a una persona. El sistema NUNCA fusiona
> registros ni elige uno automáticamente.

> **INV-B** — El teléfono **localiza**, no autoriza. Que un número coincida no
> habilita escribir sobre el expediente que encontró.

Tres operaciones, una sola verdad (decisión §4.7.3):

  `lookup_owner_by_phone`   modo LECTURA — sin lock, sin escribir. Lo usan los
                            lectores de identidad del agente y las pasadas de
                            preview/dry-run del importador.
  `resolve_owner_for_phone` resolver para ESCRIBIR — toma el lock de
                            deduplicación y cuenta bajo él.
  `change_owner_phone`      mover la clave — bloquea la anterior y la nueva en
                            orden total, comprueba y guarda sin ventana.

Las tres comparten normalización, conteo, exclusión del genérico y desenlaces.
Separarlas volvería a producir dos verdades.

Por qué un lock de aviso y no un `UNIQUE (organization, phone)`: la restricción
única exigiría limpiar o fusionar los duplicados históricos, y eso es
justamente lo que INV-C prohíbe (§4.7.1). El lock cubre además el caso que un
lock de fila no puede cubrir: **la fila todavía no existe**.
"""
import unicodedata

from django.db import connection
from rest_framework.exceptions import APIException

from apps.core.db_locks import advisory_xact_lock
from apps.core.validators import phone_key

from .models import Owner

# Namespace del lock de deduplicación. Va en la clave para que un hash no pueda
# colisionar con el de otro dominio que use `advisory_xact_lock`.
_LOCK_NAMESPACE = 'patients.owner.phone'


# ---------------------------------------------------------------------------
# Desenlaces de negocio (409). NO son errores técnicos: son resultados.
# ---------------------------------------------------------------------------
class OwnerIdentityConflict(APIException):
    """Base de los conflictos de identidad de expediente.

    Existe para que un llamador que no es una vista DRF —el importador— pueda
    capturarlos como una familia y convertirlos en error de fila, sin atrapar
    a ciegas cualquier `Exception`.
    """
    status_code = 409


class OwnerExists(OwnerIdentityConflict):
    """409 — el teléfono ya tiene expediente y este camino no puede reutilizarlo.

    Dos situaciones lo producen, y las dos son INV-B:
      · quien escribe pidió expresamente un expediente nuevo
        (`require_new=True`), porque su identidad no está verificada;
      · el alta trae un nombre distinto al del expediente que ya tiene ese
        número: crear un segundo sería fabricar el duplicado que INV-C obliga
        a tratar como ambiguo (§4.9).

    El cuerpo lleva el **candidato** para que la UI pueda preguntar «¿es este
    cliente?» en vez de decidir por el usuario.
    """
    default_detail = 'Ya existe un cliente con ese teléfono.'
    default_code = 'owner_exists'

    def __init__(self, candidate, detail=None):
        super().__init__(detail)
        self.candidate = candidate
        self.error_payload = {'candidate': owner_candidate(candidate)}


class OwnerAmbiguous(OwnerIdentityConflict):
    """409 — dos o más expedientes comparten ese teléfono normalizado (INV-C).

    Cero escrituras y **ningún** candidato en el cuerpo: publicar uno sería
    sugerir la elección que el invariante prohíbe. Se ordena el dato primero
    (`audit_owner_phone_duplicates` lo lista).

    No es opt-in: si el dominio no sabe cuál es el expediente, ningún actor
    —tampoco recepción— puede fingir que sí.
    """
    default_detail = (
        'Hay más de un cliente con ese teléfono. Revisa los expedientes '
        'duplicados antes de continuar.'
    )
    default_code = 'owner_ambiguous'

    def __init__(self, count, detail=None):
        super().__init__(detail)
        self.count = count
        self.error_payload = {'candidate_count': count}


def owner_candidate(owner):
    """Proyección mínima de un expediente candidato para el cuerpo de un 409.

    `public_id` + nombre: lo justo para que la UI pregunte. Nunca el PK ni el
    resto del expediente.
    """
    return {'public_id': str(owner.public_id), 'name': owner.name}


# ---------------------------------------------------------------------------
# Modo LECTURA — sin lock, sin escribir
# ---------------------------------------------------------------------------
NO_KEY = 'no_key'
NONE = 'none'
UNIQUE = 'unique'
AMBIGUOUS = 'ambiguous'


class PhoneLookup:
    """Resultado del modo lectura. `outcome` es exhaustivo, no hay «otro»."""

    __slots__ = ('key', 'outcome', 'owner', 'count')

    def __init__(self, key, outcome, owner=None, count=0):
        self.key = key
        self.outcome = outcome
        self.owner = owner
        self.count = count

    @property
    def is_ambiguous(self):
        return self.outcome == AMBIGUOUS

    def __repr__(self):  # pragma: no cover - ayuda de depuración
        return f'<PhoneLookup {self.outcome} key={self.key} count={self.count}>'


def identity_queryset(organization):
    """Los `Owner` que pueden ser identidad de un teléfono en esta organización.

    Dos filtros, ambos parte del contrato:
      · `for_organization()` **primero** (invariante tenant del proyecto);
      · `is_generic=False` — el genérico nace con teléfono de relleno
        `'0000000000'` y ese número no es de nadie (§4.12). Su
        `phone_normalized` ya es NULL, así que el filtro es cinturón y
        tirantes: sobrevive a un dato histórico mal derivado.
    """
    return Owner.objects.for_organization(organization).filter(is_generic=False)


def lookup_owner_by_phone(organization, phone):
    """¿Qué expediente(s) tiene este teléfono? **No** bloquea ni escribe.

    Para quien necesita *saber* sin *decidir*: los lectores de identidad del
    agente (`agent/services.py`) y las pasadas de preview y dry-run del
    importador. El contrato es el mismo que el de escritura, y esa paridad es
    el punto: el preview no puede mostrar una reutilización que el commit
    rechazaría (§4.8).

    No toma el lock porque no lo necesita — no crea ni mueve claves. Su peor
    caso es un resultado que envejece (un alta concurrente vuelve ambiguo lo
    que se leyó único); se corrige solo en la lectura siguiente. Lo que este
    modo cierra no es la carrera, es la **elección** entre duplicados
    (§4.11).
    """
    key = phone_key(phone)
    if key is None:
        return PhoneLookup(None, NO_KEY)
    # [:2] basta para distinguir 0 / 1 / ≥2 sin contar toda la tabla. Nunca
    # `.first()`: elegir es exactamente lo prohibido.
    candidates = list(identity_queryset(organization).filter(phone_normalized=key)[:2])
    if not candidates:
        return PhoneLookup(key, NONE, count=0)
    if len(candidates) == 1:
        return PhoneLookup(key, UNIQUE, owner=candidates[0], count=1)
    return PhoneLookup(key, AMBIGUOUS, count=len(candidates))


# ---------------------------------------------------------------------------
# Modo ESCRITURA — bajo el lock de deduplicación
# ---------------------------------------------------------------------------
def _lock_dedup_key(organization_id, key):
    """Serializa a todos los que resuelvan `(organización, clave)`.

    Es un lock de aviso a nivel de transacción sobre un entero derivado por
    hash estable del par. Una colisión de hash solo produce serialización de
    más entre dos claves distintas; jamás incorrección.

    El nombre de la base entra en la clave porque los locks de aviso de
    PostgreSQL son de **cluster**, no de base: sin él, dos bases del mismo
    servidor con los mismos PK de organización se bloquearían entre sí. En
    producción hay una sola base y esto no cambia nada; en la suite en paralelo
    —cada worker sobre su clon— evita una contención entre pruebas que no
    comparten ningún dato.

    No altera el orden global de locks del proyecto
    (`CashSession → MedicalRecord → Invoice → …`): se toma antes de cualquier
    lock de fila del alta y se libera con el commit.
    """
    return advisory_xact_lock(
        _LOCK_NAMESPACE,
        connection.settings_dict['NAME'],
        organization_id,
        key,
    )


def normalize_owner_name(value):
    """Nombre comparable: sin acentos, sin mayúsculas, sin espacios de sobra.

    Solo se usa para decidir si un alta se refiere al MISMO cliente que el
    expediente que ya tiene ese teléfono ("Ana Lopez" == "Ana López"). Nunca
    para deduplicar por sí solo: el nombre no es identidad.
    """
    text = unicodedata.normalize('NFKD', (value or '').strip())
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return ' '.join(text.casefold().split())


def resolve_owner_for_phone(
    organization,
    *,
    phone,
    name,
    require_new=False,
    match_name=False,
    defaults=None,
):
    """Resuelve —creando o reutilizando— el expediente de un teléfono.

    **Debe llamarse dentro de la transacción que escribe.** El lock se libera
    con el commit; comprobar fuera de la transacción sería TOCTOU otra vez.

    Devuelve `(owner, 'created' | 'reused')`. Los otros dos desenlaces son
    excepciones porque son negativas: `OwnerExists` y `OwnerAmbiguous`, ambas
    con **cero escrituras**.

    | Expedientes con la clave | `require_new` | `match_name` | Resultado |
    |---|---|---|---|
    | sin clave (teléfono vacío o < 10 dígitos) | — | — | `created` |
    | 0 | cualquiera | — | `created` |
    | 1 | `False` | nombre coincide o `False` | `reused` |
    | 1 | `False` | nombre distinto | `OwnerExists` |
    | 1 | `True` | — | `OwnerExists` |
    | ≥ 2 | cualquiera | — | `OwnerAmbiguous` |

    `require_new=True` es INV-B aplicado: quien no tiene identidad verificada
    no puede colgar nada de un expediente ajeno. Hoy nadie lo envía —el agente
    lo hará en F2—; se implementa aquí porque el desenlace es del dominio.

    `match_name=True` es el contrato del alta de cliente y del alta de mascota
    (§4.9): un teléfono conocido con OTRO nombre pregunta en vez de fabricar un
    segundo expediente. El importador NO lo usa: su regla documentada es dedup
    por teléfono, y cambiarla partiría archivos que hoy importan bien.

    Sin clave normalizable no hay deduplicación posible: se crea siempre. Es el
    comportamiento vigente del importador (única vía que admite cliente sin
    teléfono) y `require_new` queda satisfecho por construcción.
    """
    key = phone_key(phone)
    if key is None:
        return _create_owner(organization, name=name, phone=phone, defaults=defaults), 'created'

    _lock_dedup_key(organization.pk, key)

    candidates = list(identity_queryset(organization).filter(phone_normalized=key)[:2])
    if len(candidates) > 1:
        raise OwnerAmbiguous(len(candidates))
    if candidates:
        existing = candidates[0]
        if require_new:
            raise OwnerExists(existing)
        if match_name and normalize_owner_name(name) != normalize_owner_name(existing.name):
            raise OwnerExists(existing)
        return existing, 'reused'

    return _create_owner(organization, name=name, phone=phone, defaults=defaults), 'created'


def change_owner_phone(owner, new_phone):
    """Mueve la clave de deduplicación de un expediente. Devuelve el `Owner`.

    Cambiar el teléfono de un cliente **libera una clave y ocupa otra**: es una
    operación de identidad, aunque se lance desde una pantalla que parece de
    mascota (`PATCH /api/pets/`, la vía menos evidente y la más peligrosa).

    Bloquea **ambas** claves en **orden total** por su valor normalizado. El
    orden fijo no es cosmético: sin él, dos cambios cruzados (A→B y B→A a la
    vez) se bloquean mutuamente y PostgreSQL aborta uno por deadlock.

    Comprueba y escribe **en el mismo bloque**, bajo los locks. La comprobación
    NO puede vivir en `Serializer.validate`: DRF valida y guarda en pasos
    separados, y esa separación es justo la ventana que esto elimina.

    | Expedientes con la clave nueva (excluyendo el propio) | Resultado |
    |---|---|
    | 0 | se escribe |
    | 1 | `OwnerExists` — moverlo ahí fabricaría un duplicado nuevo |
    | ≥ 2 | `OwnerAmbiguous` — duplicado histórico, se ordena primero |

    Los atributos que el llamador ya haya asignado sobre `owner` se persisten
    en el mismo `save()`: la operación entera es una transacción, así que un
    409 no deja nada a medias.
    """
    owner.phone = new_phone

    if owner.is_generic:
        # El genérico no tiene identidad por teléfono (§4.12): sin clave, no
        # hay nada que serializar ni contra qué chocar.
        owner.save()
        return owner

    old_key = owner.phone_normalized
    new_key = phone_key(new_phone)

    if old_key == new_key:
        # La clave no se mueve: es una edición corriente (corregir el formato,
        # cambiar el nombre). Nada que deduplicar.
        owner.save()
        return owner

    for key in sorted(k for k in {old_key, new_key} if k):
        _lock_dedup_key(owner.organization_id, key)

    if new_key is not None:
        others = list(
            identity_queryset(owner.organization)
            .filter(phone_normalized=new_key)
            .exclude(pk=owner.pk)[:2]
        )
        if len(others) > 1:
            raise OwnerAmbiguous(len(others))
        if others:
            raise OwnerExists(others[0])

    owner.save()
    return owner


def _create_owner(organization, *, name, phone, defaults=None):
    owner = Owner(organization=organization, name=name, phone=phone, **(defaults or {}))
    owner.save()  # OrganizationalModel.save() → full_clean(); deriva la clave
    return owner
