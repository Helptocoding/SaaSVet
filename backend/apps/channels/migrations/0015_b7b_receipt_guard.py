"""B7B reception evidence is immutable from INSERT, before B3 membership too."""
from django.db import migrations

FORWARD = """
CREATE FUNCTION b7b_check_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (OLD.raw_metadata->'_b7b_receipt') IS DISTINCT FROM
       (NEW.raw_metadata->'_b7b_receipt') THEN
        RAISE EXCEPTION 'B7B reception evidence is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.raw_metadata ? '_b7b_receipt' AND
       (OLD.organization_id, OLD.conversation_id, OLD.contact_id, OLD.channel_account_id,
        OLD.direction, OLD.author_type, OLD.external_message_id,
        OLD.raw_metadata->'_channel_event', OLD.body, OLD.payload_type, OLD.created_at)
       IS DISTINCT FROM
       (NEW.organization_id, NEW.conversation_id, NEW.contact_id, NEW.channel_account_id,
        NEW.direction, NEW.author_type, NEW.external_message_id,
        NEW.raw_metadata->'_channel_event', NEW.body, NEW.payload_type, NEW.created_at) THEN
        RAISE EXCEPTION 'B7B inbound evidence is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER b7b_receipt_guard BEFORE UPDATE ON channels_message
    FOR EACH ROW EXECUTE FUNCTION b7b_check_receipt();
"""


class Migration(migrations.Migration):
    dependencies = [('channels', '0014_alter_message_semantic_type'), ('agent', '0026_b7b_consent_evidence')]
    operations = [migrations.RunSQL(FORWARD,
        'DROP TRIGGER b7b_receipt_guard ON channels_message; DROP FUNCTION b7b_check_receipt();')]
