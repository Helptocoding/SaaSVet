"""Block ordinary ORM collector/instance deletes of exceptional physical targets."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete

from apps.organizations.models import Organization
from apps.patients.models import Owner, Pet
from apps.billing.models import Invoice
from apps.prescriptions.models import Prescription
from apps.medical_records.models import MedicalRecord
from apps.medical_records.policies import medical_record_has_clinical_content


_authorized_target = ContextVar('order2_physical_target', default=None)

# Autorización de purga: el PK de la organización demo que se está reseteando.
#
# Existe porque la política de preservación y el reset automático de la demo
# (ADR p49) se contradicen de frente: el reset existe para borrar físicamente
# los datos de la demo cada media hora, y `_protect_document` prohibía todo
# borrado físico de Invoice/Prescription sin excepción alguna. El resultado era
# que la demo dejaba de poder resetearse.
#
# La preservación existe por retención legal de documentos clínicos y
# financieros REALES (NOM-007/NOM-046, cinco años). Una organización demo no
# tiene ese deber: sus datos son sintéticos y su propósito es desaparecer. Así
# que la política no se debilita, se delimita — declara sobre qué datos manda.
#
# Por qué un ContextVar y no un `instance.organization.is_demo` dentro del
# guard: (1) evita una consulta por fila durante una purga de miles de filas,
# porque compara `organization_id`, que ya viene cargado; y (2) exige un acto
# EXPLÍCITO y acotado del camino de reset. Un `.delete()` suelto sobre una
# factura de la demo desde cualquier otro sitio sigue fallando. El guard
# permanece cerrado por defecto.
_purging_demo_organization = ContextVar('order2_purging_demo_org', default=None)


@contextmanager
def authorize_demo_purge(organization):
    """Autoriza el borrado físico de los datos de UNA organización demo.

    Rechaza cualquier organización que no sea demo: la autorización no puede
    abrirse para un tenant real ni por error ni a propósito.
    """
    if not getattr(organization, 'is_demo', False):
        raise ValueError(
            'authorize_demo_purge solo autoriza organizaciones demo; '
            'los documentos de un tenant real se conservan.'
        )
    marker = _purging_demo_organization.set(organization.pk)
    try:
        yield
    finally:
        _purging_demo_organization.reset(marker)


@contextmanager
def authorize_physical_deletion(instance):
    """Autoriza el borrado físico de ESTA instancia, y solo durante el bloque.

    Es la puerta sancionada del guard de Owner/Pet/Organization: la usa
    `platform.services.physical_deletion.execute` tras validar actor, preview y
    digest de impacto. Se expone para que nadie más tenga que tocar
    `_authorized_target` a mano —`physical_deletion` lo importaba en privado— y
    para que una prueba pueda ejercitar «el PROTECT no sobre-bloquea» sin
    arrastrar el protocolo de firma completo.

    No sustituye a esas validaciones: autoriza una fila concreta, nada más.
    """
    marker = _authorized_target.set((type(instance).__name__, instance.pk))
    try:
        yield
    finally:
        _authorized_target.reset(marker)


def demo_purge_authorized(fn):
    """Decorador para una función `(self, organization, ...)` que purga la demo.

    Se usa como decorador y no como `with` dentro del cuerpo por una razón
    práctica: `seed_demo_clinic._purge` son ~130 líneas y envolverlas exigiría
    re-indentarlas enteras, que es mucho riesgo de edición para ninguna
    ganancia.

    Si la organización NO es demo no autoriza nada y deja pasar la llamada tal
    cual: el comando tiene su propio guard y debe ser él quien explique el
    rechazo con su `CommandError`. Así este decorador no cambia la semántica de
    error de quien decora.
    """
    @wraps(fn)
    def wrapper(self, organization, *args, **kwargs):
        if not getattr(organization, 'is_demo', False):
            return fn(self, organization, *args, **kwargs)
        with authorize_demo_purge(organization):
            return fn(self, organization, *args, **kwargs)
    return wrapper


def _demo_purge_authorized(sender, instance):
    """¿Esta fila pertenece a la organización demo que se está purgando?"""
    authorized = _purging_demo_organization.get()
    if authorized is None:
        return False
    if sender is Organization:
        return instance.pk == authorized
    return getattr(instance, 'organization_id', None) == authorized


def _protect(sender, instance, **kwargs):
    if _demo_purge_authorized(sender, instance):
        return
    if _authorized_target.get() != (sender.__name__, instance.pk):
        raise ProtectedError('Borrado físico exclusivo de la API de plataforma.', {instance})


def _protect_document(sender, instance, **kwargs):
    if _demo_purge_authorized(sender, instance):
        return
    raise ProtectedError('Documento conservado; borrado físico no permitido.', {instance})


for target in (Owner, Pet, Organization):
    pre_delete.connect(_protect, sender=target, weak=False,
                       dispatch_uid=f'order2_protect_{target.__name__}')

for document in (Invoice, Prescription):
    pre_delete.connect(_protect_document,
        sender=document, weak=False, dispatch_uid=f'order2_preserve_{document.__name__}')


def _protect_medical_evidence(sender, instance, **kwargs):
    # Misma delimitación que arriba: la evidencia clínica de la demo es
    # sintética y el reset existe para borrarla.
    if _demo_purge_authorized(sender, instance):
        return
    if (instance.status != MedicalRecord.Status.OPEN or
            medical_record_has_clinical_content(instance) or
            instance.invoices.exists()):
        raise ProtectedError('No se elimina un expediente con evidencia durable.', {instance})


pre_delete.connect(_protect_medical_evidence, sender=MedicalRecord,
                   weak=False, dispatch_uid='order2_preserve_medical_record_evidence')
