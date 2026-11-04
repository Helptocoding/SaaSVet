from django.db import migrations


TABLES = (
    ('billing_invoice', 'owner_id', 'patients_owner', 'invoice_owner_tenant'),
    ('billing_invoice', 'pet_id', 'patients_pet', 'invoice_pet_tenant'),
    ('billing_invoice', 'medical_record_id', 'medical_records_medicalrecord', 'invoice_record_tenant'),
    ('billing_invoice', 'appointment_id', 'appointments_appointment', 'invoice_appointment_tenant'),
    ('billing_invoice', 'checkout_id', 'billing_checkout', 'invoice_checkout_tenant'),
    ('billing_checkout', 'customer_id', 'patients_owner', 'checkout_customer_tenant'),
    ('billing_checkout', 'pet_id', 'patients_pet', 'checkout_pet_tenant'),
    ('billing_checkout', 'medical_record_id', 'medical_records_medicalrecord', 'checkout_record_tenant'),
)


def install(apps, schema_editor):
    # Composite FKs, not a CHECK with a cross-table subquery: PostgreSQL checks
    # both child writes and reparenting/updating a referenced parent.
    with schema_editor.connection.cursor() as cursor:
        for child, field, parent, name in TABLES:
            cursor.execute(
                f'ALTER TABLE {child} ADD CONSTRAINT {name} FOREIGN KEY '
                f'({field}, organization_id) REFERENCES {parent}(id, organization_id) '
                'DEFERRABLE INITIALLY IMMEDIATE'
            )
        cursor.execute("""
            CREATE FUNCTION order2_checkout_active_subjects() RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE owner_row record; pet_row record;
            BEGIN
              PERFORM 1 FROM organizations_organization WHERE id=NEW.organization_id
                AND is_active FOR SHARE;
              IF NOT FOUND THEN RAISE EXCEPTION 'inactive_organization' USING ERRCODE='23514'; END IF;
              SELECT id, is_active INTO owner_row FROM patients_owner
                WHERE id=NEW.customer_id AND organization_id=NEW.organization_id FOR SHARE;
              IF NOT FOUND OR NOT owner_row.is_active THEN
                RAISE EXCEPTION 'inactive_customer' USING ERRCODE='23514';
              END IF;
              IF NEW.pet_id IS NOT NULL THEN
                SELECT id, is_active, owner_id INTO pet_row FROM patients_pet
                  WHERE id=NEW.pet_id AND organization_id=NEW.organization_id FOR SHARE;
                IF NOT FOUND OR NOT pet_row.is_active OR pet_row.owner_id <> NEW.customer_id THEN
                  RAISE EXCEPTION 'inactive_or_foreign_pet' USING ERRCODE='23514';
                END IF;
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER order2_checkout_active_insert BEFORE INSERT ON billing_checkout
                FOR EACH ROW EXECUTE FUNCTION order2_checkout_active_subjects();
            CREATE FUNCTION order2_invoice_new_document() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.checkout_id IS NULL OR NEW.owner_id IS NULL THEN
                RAISE EXCEPTION 'invoice_requires_checkout_and_customer' USING ERRCODE='23514';
              END IF;
              IF NOT EXISTS (SELECT 1 FROM billing_checkout
                  WHERE id=NEW.checkout_id AND organization_id=NEW.organization_id
                    AND customer_id=NEW.owner_id) THEN
                RAISE EXCEPTION 'invoice_checkout_customer_mismatch' USING ERRCODE='23514';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER order2_invoice_insert BEFORE INSERT ON billing_invoice
                FOR EACH ROW EXECUTE FUNCTION order2_invoice_new_document();
        """)


def uninstall(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            DROP TRIGGER order2_invoice_insert ON billing_invoice;
            DROP FUNCTION order2_invoice_new_document();
            DROP TRIGGER order2_checkout_active_insert ON billing_checkout;
            DROP FUNCTION order2_checkout_active_subjects();
        """)
        for child, _, _, name in reversed(TABLES):
            cursor.execute(f'ALTER TABLE {child} DROP CONSTRAINT {name}')


class Migration(migrations.Migration):
    dependencies = [
        ('billing', '0037_checkout_tenant_reference_key'),
        ('patients', '0021_tenant_reference_keys'),
        ('appointments', '0019_tenant_reference_key'),
        ('medical_records', '0027_tenant_reference_key'),
        ('organizations', '0015_state_audit'),
    ]
    operations = [migrations.RunPython(install, uninstall)]
