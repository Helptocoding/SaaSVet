from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('patients', '0018_owner_phone_normalized'),
        ('agent', '0027_attendance_consent_policy'),
        ('organizations', '0012_remove_organizationsettings_auto_create_invoice_on_done_and_more'),
    ]

    operations = [
        migrations.CreateModel(name='PetRegistrationEffect', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('parameters_digest', models.CharField(max_length=64)),
            ('definition', models.JSONField()),
            ('committed_at', models.DateTimeField()),
            ('operation', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                related_name='pet_registration_effect', to='agent.conversationoperation', to_field='operation_key')),
            ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='organizations.organization')),
            ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='patients.owner')),
            ('pet', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                related_name='registration_effect', to='patients.pet')),
        ]),
        migrations.RunSQL(sql='''
            CREATE FUNCTION pet_registration_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP <> 'INSERT' THEN
                    RAISE EXCEPTION 'Pet registration evidence is immutable';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM agent_conversationoperation o
                    JOIN patients_pet p ON p.id = NEW.pet_id
                    JOIN patients_owner w ON w.id = NEW.owner_id
                    WHERE o.operation_key = NEW.operation_id
                    AND o.operation_kind = 'REGISTER_PET' AND o.consent_state = 'AUTHORIZED'
                    AND o.organization_id = NEW.organization_id AND p.organization_id = NEW.organization_id
                    AND w.organization_id = NEW.organization_id
                    AND o.owner_id = NEW.owner_id AND p.owner_id = NEW.owner_id
                    AND o.pet_id IS NULL AND o.appointment_id IS NULL
                    AND o.parameters_digest = NEW.parameters_digest
                    AND NEW.parameters_digest ~ '^[0-9a-f]{64}$'
                    AND o.parameters->>'owner_id' = NEW.owner_id::text
                    AND o.preconditions->>'schema' = '4'
                    AND o.preconditions->>'registration_contract' = '1'
                    AND NEW.committed_at >= o.authorized_at AND NEW.committed_at <= clock_timestamp()
                    AND p.created_at >= o.authorized_at
                    AND NEW.definition = jsonb_build_object(
                        'name', o.parameters->>'name', 'species', COALESCE(o.parameters->>'species', ''),
                        'birth_date', o.parameters->>'birth_date', 'sex', 'unknown',
                        'breed', '', 'color', '', 'legacy_id', '', 'extra_data', '[]'::jsonb,
                        'is_generic', false, 'is_active', true)
                    AND NEW.definition = jsonb_build_object(
                        'name', p.name, 'species', p.species, 'birth_date', p.birth_date::text,
                        'sex', p.sex, 'breed', p.breed, 'color', p.color, 'legacy_id', p.legacy_id,
                        'extra_data', p.extra_data, 'is_generic', p.is_generic, 'is_active', p.is_active)
                ) THEN
                    RAISE EXCEPTION 'Pet registration evidence scope mismatch';
                END IF;
                RETURN NEW;
            END $$;
            CREATE TRIGGER pet_registration_evidence_guard
            BEFORE INSERT OR UPDATE OR DELETE ON patients_petregistrationeffect
            FOR EACH ROW EXECUTE FUNCTION pet_registration_evidence_guard();
            ''', reverse_sql='''DROP TRIGGER pet_registration_evidence_guard ON patients_petregistrationeffect;
                DROP FUNCTION pet_registration_evidence_guard();'''),
    ]
