"""WA-CTX-01: bounded nonclinical projection from an already linked owner."""
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.appointments.models import Appointment
from apps.core.datetime_utils import org_now_local
from apps.patients.models import Owner, Pet
from apps.patients.serializers import OwnerSerializer, PetSerializer
from .models import Conversation


class ContextOwnerSerializer(OwnerSerializer):
    class Meta(OwnerSerializer.Meta):
        fields = ['public_id', 'name', 'phone']
        read_only_fields = fields


class ContextPetSerializer(PetSerializer):
    class Meta(PetSerializer.Meta):
        fields = ['public_id', 'name', 'species']
        read_only_fields = fields


class ContextAppointmentSerializer(serializers.Serializer):
    date = serializers.DateField(read_only=True)
    status = serializers.CharField(read_only=True)


class ThreadContextSerializer(serializers.Serializer):
    owner = ContextOwnerSerializer(read_only=True, allow_null=True)
    pets = ContextPetSerializer(many=True, read_only=True)
    last_appointment = ContextAppointmentSerializer(read_only=True, allow_null=True)


def thread_context(*, organization, contact, account):
    """Read only. No phone rematch, clinical notes, private IDs or authority changes."""
    if (contact.organization_id != organization.pk or account.organization_id != organization.pk
            or not Conversation.objects.for_organization(organization).filter(
                contact=contact, channel_account=account).exists()):
        raise NotFound()
    if contact.owner_id is None:
        return {'owner': None, 'pets': [], 'last_appointment': None}
    owner = Owner.objects.for_organization(organization).filter(
        pk=contact.owner_id, is_generic=False).only('pk', 'public_id', 'name', 'phone').first()
    if owner is None:
        # Includes broken legacy cross-tenant links; never disclose the joined owner.
        raise NotFound()
    pets = (Pet.objects.for_organization(organization).filter(owner=owner, is_generic=False)
            .only('pk', 'public_id', 'name', 'species').order_by('name', 'pk'))
    now = timezone.now()
    local = org_now_local(organization, now=now)
    # Last appointment whose scheduled time has arrived, irrespective of status.
    # UTC is authoritative; pre-UTC legacy rows use clinic-local date/time.
    past = (Q(start_datetime__lte=now) | (Q(start_datetime__isnull=True) & (
        Q(date__lt=local.date()) | Q(date=local.date(), start_time__lte=local.time()))))
    appointment = (Appointment.objects.for_organization(organization)
        .filter(pet__in=pets.values('pk')).filter(past)
        .order_by('-date', '-start_time', '-pk').values('date', 'status').first())
    return {'owner': owner, 'pets': pets, 'last_appointment': appointment}
