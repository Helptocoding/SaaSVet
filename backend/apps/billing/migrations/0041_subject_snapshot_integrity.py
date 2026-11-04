from django.db import migrations


TABLES = ('billing_invoice', 'billing_checkout',
          'medical_records_medicalrecord', 'prescriptions_prescription')


def install(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
          CREATE FUNCTION order2_validate_subject_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
          DECLARE org_uuid text;
          BEGIN
            IF TG_OP='UPDATE' AND OLD.subject_snapshot <> '{}'::jsonb
               AND NEW.subject_snapshot IS DISTINCT FROM OLD.subject_snapshot THEN
              RAISE EXCEPTION 'immutable_subject_snapshot' USING ERRCODE='23514';
            END IF;
            IF NEW.subject_snapshot='{}'::jsonb THEN
              IF TG_OP='INSERT' THEN
                RAISE EXCEPTION 'missing_subject_snapshot' USING ERRCODE='23514';
              END IF;
              RETURN NEW;
            END IF;
            SELECT public_id::text INTO org_uuid FROM organizations_organization WHERE id=NEW.organization_id;
            IF NEW.subject_snapshot->>'organization' IS DISTINCT FROM org_uuid THEN
              RAISE EXCEPTION 'snapshot_tenant_mismatch' USING ERRCODE='23514';
            END IF;
            IF TG_TABLE_NAME='billing_invoice' AND (to_jsonb(NEW)->>'owner_id') IS NOT NULL THEN
              IF NEW.subject_snapshot->'owner'->>'uuid' IS DISTINCT FROM
                 (SELECT public_id::text FROM patients_owner WHERE id=NEW.owner_id) THEN
                RAISE EXCEPTION 'snapshot_owner_mismatch' USING ERRCODE='23514';
              END IF;
            ELSIF TG_TABLE_NAME='billing_checkout' AND (to_jsonb(NEW)->>'customer_id') IS NOT NULL THEN
              IF NEW.subject_snapshot->'owner'->>'uuid' IS DISTINCT FROM
                 (SELECT public_id::text FROM patients_owner WHERE id=NEW.customer_id) THEN
                RAISE EXCEPTION 'snapshot_customer_mismatch' USING ERRCODE='23514';
              END IF;
            END IF;
            IF NEW.subject_snapshot->>'source' NOT IN ('captured', 'reconstructed', 'unknown')
               OR NEW.subject_snapshot->>'recorded_at' IS NULL THEN
              RAISE EXCEPTION 'invalid_subject_provenance' USING ERRCODE='23514';
            END IF;
            IF TG_TABLE_NAME='billing_invoice' AND NEW.pet_id IS NOT NULL THEN
              IF NEW.subject_snapshot->'pet'->>'uuid' IS DISTINCT FROM
                 (SELECT public_id::text FROM patients_pet WHERE id=NEW.pet_id) THEN
                RAISE EXCEPTION 'snapshot_pet_mismatch' USING ERRCODE='23514';
              END IF;
            ELSIF TG_TABLE_NAME='billing_checkout' AND NEW.pet_id IS NOT NULL THEN
              IF NEW.subject_snapshot->'pet'->>'uuid' IS DISTINCT FROM
                 (SELECT public_id::text FROM patients_pet WHERE id=NEW.pet_id) THEN
                RAISE EXCEPTION 'snapshot_pet_mismatch' USING ERRCODE='23514';
              END IF;
            ELSIF TG_TABLE_NAME='medical_records_medicalrecord' AND NEW.pet_id IS NOT NULL THEN
              IF NEW.subject_snapshot->'pet'->>'uuid' IS DISTINCT FROM
                 (SELECT public_id::text FROM patients_pet WHERE id=NEW.pet_id) THEN
                RAISE EXCEPTION 'snapshot_pet_mismatch' USING ERRCODE='23514';
              END IF;
            ELSIF TG_TABLE_NAME='prescriptions_prescription' AND NEW.pet_id IS NOT NULL THEN
              IF NEW.subject_snapshot->'pet'->>'uuid' IS DISTINCT FROM
                 (SELECT public_id::text FROM patients_pet WHERE id=NEW.pet_id) THEN
                RAISE EXCEPTION 'snapshot_pet_mismatch' USING ERRCODE='23514';
              END IF;
            END IF;
            RETURN NEW;
          END $$;
          CREATE FUNCTION order2_preserve_public_uuid() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN
            IF NEW.public_id IS DISTINCT FROM OLD.public_id THEN
              RAISE EXCEPTION 'immutable_public_uuid' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
          END $$;
        """)
        for table in TABLES:
            cursor.execute(f'CREATE TRIGGER order2_subject_snapshot BEFORE INSERT OR UPDATE '
                           f'ON {table} FOR EACH ROW EXECUTE FUNCTION order2_validate_subject_snapshot()')
        for table in ('organizations_organization', 'patients_owner', 'patients_pet'):
            cursor.execute(f'CREATE TRIGGER order2_public_uuid BEFORE UPDATE OF public_id '
                           f'ON {table} FOR EACH ROW EXECUTE FUNCTION order2_preserve_public_uuid()')


def uninstall(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DROP TRIGGER order2_subject_snapshot ON {table}')
        for table in ('organizations_organization', 'patients_owner', 'patients_pet'):
            cursor.execute(f'DROP TRIGGER order2_public_uuid ON {table}')
        cursor.execute('DROP FUNCTION order2_validate_subject_snapshot()')
        cursor.execute('DROP FUNCTION order2_preserve_public_uuid()')


class Migration(migrations.Migration):
    dependencies = [('billing', '0040_detachable_billed_subjects'),
                    ('platform', '0001_physical_deletion_receipt')]
    operations = [migrations.RunPython(install, uninstall)]
