"""agent/signals.py — el vínculo de identidad no sobrevive a su premisa.

**El bug que cierra.** `ContactIdentity.owner` es una FK persistente: se
resuelve la primera vez que un número escribe y ahí se queda. Nadie la volvía a
mirar. Así que si el teléfono del expediente cambiaba —la clínica lo corrige, o
el cliente cambia de número— el contacto **seguía apuntando al mismo expediente
para siempre**.

Dos formas de doler, y la segunda es la grave:

  · *Depurando*: se crea un cliente por WhatsApp, se le edita el teléfono en
    `/pets`, y el agente sigue saludando con el nombre viejo.
  · *En producción*: las operadoras **reciclan números**. El cliente A cambia
    de número, la clínica actualiza su ficha, y meses después otra persona
    hereda ese número y escribe. Mismo `wa_id` ⇒ mismo `ContactIdentity` ⇒
    **ve las mascotas de A y puede gestionar sus citas**. Nadie tiene un botón
    para arreglarlo en producción: pasa solo y en silencio.

**La regla** se deriva de INV-B (ADR p57), no se inventa aquí: *el teléfono
localiza, no autoriza*. Luego, si el vínculo se creó **por** el número, muere
con el número; si se creó por otra cosa, el número es irrelevante.

| `linked_via` | Premisa del vínculo | Al cambiar el teléfono |
|---|---|---|
| `phone_match` | el sistema lo dedujo del número | **se rompe** |
| `self_register` | se auto-registró con ese número | **se rompe** |
| `staff_verified` | una persona lo verificó con evidencia externa (FLUJO-C) | se mantiene |
| `family_challenge` | pasó el reto de tres factores | se mantiene |

Romper siempre destruiría trabajo humano: alguien verifica a un contacto en
mostrador con identificación y después la clínica corrige un typo en el
teléfono. Ese vínculo nunca se fundó en el número.

**Por qué una señal y no una llamada desde `patients`.** La dependencia entre
dominios va en un solo sentido: `agent` conoce a `patients` (ya lo importa) y
`patients` no sabe que el agente existe. Meter la desvinculación dentro de
`patients.services` invertiría esa flecha y ataría el dominio clínico al
subsistema conversacional. El agente escucha; el dominio no se entera.

**Idempotente y sin estado previo**: no necesita saber cuál era el teléfono
anterior. Compara el estado actual —«este contacto dice ser 937…, este
expediente dice 550…»—, así que correrlo de más no hace daño.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger('agent.events')

#: Vínculos que SOBREVIVEN a un cambio de teléfono: los sostiene un acto humano
#: deliberado, no el número.
#:
#: Es una lista blanca a propósito, no la lista contraria. El vínculo más común
#: —el que el sistema deduce del número— se guarda con `linked_via = ''`
#: («phone_match implícito», ver el comentario del modelo), así que enumerar
#: «lo que se rompe» dejaba fuera justo el caso principal. Y a futuro: si
#: aparece una procedencia nueva y nadie actualiza esto, por defecto **se
#: rompe** — que es el lado seguro. Sobrevivir en silencio sería el fail-open.
SURVIVES_PHONE_CHANGE = ('staff', 'family_challenge')


def unlink_stale_phone_identities(owner):
    """Desvincula los contactos cuya premisa telefónica dejó de ser cierta.

    Devuelve cuántos se desvincularon.

    **No** toca `auto_rematch_blocked`: si el contacto vuelve a escribir y su
    número resuelve a un único expediente, `_rematch_owner` lo vinculará de
    nuevo — y es lo correcto, porque esa vez la premisa sí se cumple. Lo que no
    puede seguir pasando es que quede colgado del expediente viejo sin que
    nadie lo compruebe.
    """
    from .models import ContactIdentity

    stale = (
        ContactIdentity.objects
        .for_organization(owner.organization_id)
        .filter(owner=owner)
        .exclude(linked_via__in=SURVIVES_PHONE_CHANGE)
        .exclude(phone_normalized=owner.phone_normalized or '')
    )

    unlinked = 0
    for contact in stale:
        contact.owner = None
        contact.verification_level = ContactIdentity.VERIFICATION_UNKNOWN
        contact.verified_at = None
        contact.linked_via = ''
        contact.save(update_fields=[
            'owner', 'verification_level', 'verified_at', 'linked_via'])
        unlinked += 1
        logger.info("AGENT_IDENTITY_UNLINKED_STALE_PHONE", extra={
            "event": "AGENT_IDENTITY_UNLINKED_STALE_PHONE",
            "organization_id": owner.organization_id,
            "contact_id": contact.pk,
            "owner_id": owner.pk,
        })
    return unlinked


@receiver(post_save, sender='patients.Owner',
          dispatch_uid='agent.unlink_stale_phone_identities')
def _on_owner_saved(sender, instance, **kwargs):
    """Un `Owner` se guardó: ¿algún contacto quedó colgado de su teléfono viejo?

    Se comprueba en TODA escritura del expediente, no solo en las que cambian
    el teléfono: distinguirlas exigiría recordar el valor anterior, y el coste
    de no hacerlo es una consulta indexada por `(organization, owner)`. La
    consistencia no debería depender de que cada vía nueva recuerde avisar.
    """
    if kwargs.get('raw'):
        return          # cargando fixtures: la base no está en estado coherente
    try:
        unlink_stale_phone_identities(instance)
    except Exception:   # noqa: BLE001 — jamás tumbar el guardado del expediente
        logger.exception("AGENT_IDENTITY_UNLINK_FAILED")
