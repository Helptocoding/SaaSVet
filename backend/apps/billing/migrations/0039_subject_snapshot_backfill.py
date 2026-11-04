from django.db import migrations, models
from django.utils import timezone


def backfill(apps, schema_editor):
    Org = apps.get_model('organizations', 'Organization')
    for label, model_name, owner_field, pet_field in (
        ('medical_records', 'MedicalRecord', None, 'pet'),
        ('prescriptions', 'Prescription', None, 'pet'),
        ('billing', 'Checkout', 'customer', 'pet'),
        ('billing', 'Invoice', 'owner', 'pet'),
    ):
        Model = apps.get_model(label, model_name)
        for doc in Model.objects.filter(subject_snapshot={}).select_related(
            'organization', pet_field, *([owner_field] if owner_field else []),
        ).iterator(chunk_size=500):
            pet = getattr(doc, pet_field)
            owner = getattr(doc, owner_field) if owner_field else pet.owner if pet else None
            if not owner and not pet:
                Model.objects.filter(pk=doc.pk, subject_snapshot={}).update(
                    subject_snapshot={'version': 1, 'organization': str(doc.organization.public_id),
                                      'source': 'unknown', 'recorded_at': timezone.now().isoformat(),
                                      'owner': None, 'pet': None},
                )
                continue
            if (owner and owner.organization_id != doc.organization_id
                    or pet and pet.organization_id != doc.organization_id):
                # No fabricar identidad cross-tenant en datos históricos dañados.
                continue
            payload = {
                'version': 1, 'organization': str(doc.organization.public_id),
                'source': 'reconstructed', 'recorded_at': timezone.now().isoformat(),
                'owner': ({'uuid': str(owner.public_id), 'name': owner.name, 'phone': owner.phone}
                          if owner else None),
                'pet': ({'uuid': str(pet.public_id), 'name': pet.name,
                         'species': pet.species, 'breed': pet.breed,
                         'sex': pet.sex,
                         'birth_date': pet.birth_date.isoformat() if pet.birth_date else None}
                        if pet else None),
            }
            Model.objects.filter(pk=doc.pk, subject_snapshot={}).update(subject_snapshot=payload)


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0038_invoice_checkout_tenant_integrity'),
        ('medical_records', '0028_subject_snapshot_schema'),
        ('prescriptions', '0008_subject_snapshot_schema'),
    ]
    operations = [
        migrations.AddField('invoice', 'subject_snapshot',
                            models.JSONField(blank=True, default=dict, editable=False)),
        migrations.AddField('checkout', 'subject_snapshot',
                            models.JSONField(blank=True, default=dict, editable=False)),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
