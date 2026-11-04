"""Relink de la identidad genérica en consultas abiertas (audit run-1, 8.4).

`0041` hace inmutable `subject_snapshot` y exige que el paciente de la fila
coincida con él. Juntas, esas reglas impedían que `assign-patient` moviera una
consulta ABIERTA del paciente genérico de una atención sin cita al paciente
real: la escritura fallaba con `snapshot_pet_mismatch` (500), aunque el
contrato documentado es que la consulta abierta sigue a la cita.

Se reemplaza solo la función; los triggers de `0041` no cambian. La excepción
exige que la identidad congelada ANTERIOR sea el genérico de la misma
organización y que la consulta esté abierta (para la receta, su consulta). Toda
identidad real conserva la inmutabilidad, y el snapshot nuevo sigue pasando
tenant, procedencia y coincidencia con el paciente. Addendum en
docs/remediaciones/orden-2/ADR-001-conservacion.md.

La reversa restaura literalmente la función de `0041`.
"""
from django.db import migrations


RELAXED = """
CREATE OR REPLACE FUNCTION order2_validate_subject_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
          DECLARE org_uuid text;
          DECLARE generic_relink boolean := FALSE;
          BEGIN
            -- Excepción única (audit run-1, hallazgo 8.4): una consulta ABIERTA,
            -- o la receta de una consulta abierta, cuya identidad congelada es
            -- el paciente GENÉRICO de su organización puede pasar al paciente
            -- real. El genérico no es la identidad de nadie: es el marcador de
            -- «aún sin vincular». Toda identidad real sigue siendo inmutable, y
            -- el snapshot nuevo pasa por todas las validaciones de abajo.
            IF TG_OP='UPDATE' AND OLD.subject_snapshot <> '{}'::jsonb
               AND NEW.subject_snapshot IS DISTINCT FROM OLD.subject_snapshot
               AND TG_TABLE_NAME IN ('medical_records_medicalrecord', 'prescriptions_prescription')
               AND NEW.organization_id = OLD.organization_id
               AND EXISTS (SELECT 1 FROM patients_pet
                           WHERE organization_id = OLD.organization_id AND is_generic
                             AND public_id::text = OLD.subject_snapshot->'pet'->>'uuid') THEN
              IF TG_TABLE_NAME='medical_records_medicalrecord' THEN
                generic_relink := (to_jsonb(OLD)->>'status') = 'open'
                                  AND (to_jsonb(NEW)->>'status') = 'open';
              ELSE
                generic_relink := EXISTS (
                  SELECT 1 FROM medical_records_medicalrecord
                  WHERE id = (to_jsonb(NEW)->>'medical_record_id')::bigint
                    AND organization_id = NEW.organization_id AND status = 'open');
              END IF;
            END IF;
            IF TG_OP='UPDATE' AND OLD.subject_snapshot <> '{}'::jsonb
               AND NEW.subject_snapshot IS DISTINCT FROM OLD.subject_snapshot
               AND NOT generic_relink THEN
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
"""

ORIGINAL = """
CREATE OR REPLACE FUNCTION order2_validate_subject_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
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
"""


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(RELAXED)


def backwards(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(ORIGINAL)


class Migration(migrations.Migration):
    dependencies = [('billing', '0042_invoice_audit_identity_required')]
    operations = [migrations.RunPython(forwards, backwards)]
