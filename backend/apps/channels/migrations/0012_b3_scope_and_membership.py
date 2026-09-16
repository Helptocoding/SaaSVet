"""PostgreSQL relational tenant and immutable causal membership enforcement."""
from django.db import migrations


FORWARD = """
CREATE FUNCTION b3_check_turnwork() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c agent_conversation; a channels_message; first_message channels_message;
BEGIN
    SELECT * INTO c FROM agent_conversation WHERE id = NEW.conversation_id;
    SELECT * INTO a FROM channels_message WHERE id = NEW.anchor_message_id;
    SELECT * INTO first_message FROM channels_message WHERE id = NEW.cursor_message_id;
    IF c.id IS NULL OR a.id IS NULL OR first_message.id IS NULL
       OR c.organization_id <> NEW.organization_id
       OR a.organization_id <> NEW.organization_id
       OR a.conversation_id IS DISTINCT FROM c.id OR a.direction <> 'in'
       OR a.channel_account_id <> c.channel_account_id
       OR first_message.organization_id <> NEW.organization_id
       OR first_message.conversation_id IS DISTINCT FROM c.id OR first_message.direction <> 'in'
       OR a.created_at <> NEW.anchor_created_at
       OR first_message.created_at <> NEW.cursor_created_at
       OR (first_message.created_at, first_message.id) > (a.created_at, a.id)
    THEN RAISE EXCEPTION 'B3 TurnWork scope/cursor mismatch' USING ERRCODE = '23514'; END IF;
    IF TG_OP = 'UPDATE' AND
       (OLD.organization_id, OLD.conversation_id, OLD.anchor_message_id, OLD.anchor_created_at,
        OLD.cursor_message_id, OLD.cursor_created_at, OLD.context_at, OLD.clinic_timezone,
        OLD.ownership_epoch) IS DISTINCT FROM
       (NEW.organization_id, NEW.conversation_id, NEW.anchor_message_id, NEW.anchor_created_at,
        NEW.cursor_message_id, NEW.cursor_created_at, NEW.context_at, NEW.clinic_timezone,
        NEW.ownership_epoch)
    THEN RAISE EXCEPTION 'B3 TurnWork causal identity is immutable' USING ERRCODE = '23514'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER b3_turnwork_scope BEFORE INSERT OR UPDATE ON agent_turnwork
    FOR EACH ROW EXECUTE FUNCTION b3_check_turnwork();

CREATE FUNCTION b3_check_message() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE w agent_turnwork; c agent_conversation;
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.turn_work_id IS NOT NULL AND
       (OLD.turn_work_id, OLD.organization_id, OLD.conversation_id, OLD.channel_account_id,
        OLD.contact_id, OLD.direction, OLD.created_at, OLD.body, OLD.raw_metadata,
        OLD.output_ordinal, OLD.origin_epoch, OLD.payload_type, OLD.is_active) IS DISTINCT FROM
       (NEW.turn_work_id, NEW.organization_id, NEW.conversation_id, NEW.channel_account_id,
        NEW.contact_id, NEW.direction, NEW.created_at, NEW.body, NEW.raw_metadata,
        NEW.output_ordinal, NEW.origin_epoch, NEW.payload_type, NEW.is_active)
    THEN RAISE EXCEPTION 'B3 Message causal evidence is immutable' USING ERRCODE = '23514'; END IF;
    IF NEW.turn_work_id IS NULL THEN RETURN NEW; END IF;
    SELECT * INTO w FROM agent_turnwork WHERE id = NEW.turn_work_id;
    SELECT * INTO c FROM agent_conversation WHERE id = NEW.conversation_id;
    IF NEW.direction = 'in' AND w.attempts > 0
       AND (TG_OP = 'INSERT' OR OLD.turn_work_id IS NULL) THEN
        RAISE EXCEPTION 'B3 claimed membership is frozen' USING ERRCODE = '23514';
    END IF;
    IF w.id IS NULL OR c.id IS NULL OR w.organization_id <> NEW.organization_id
       OR c.organization_id <> NEW.organization_id
       OR w.conversation_id IS DISTINCT FROM NEW.conversation_id
       OR c.channel_account_id <> NEW.channel_account_id
       OR (NEW.contact_id IS NOT NULL AND c.contact_id <> NEW.contact_id)
       OR (NEW.direction = 'out' AND NEW.origin_epoch IS DISTINCT FROM w.ownership_epoch)
       OR (NEW.direction = 'in' AND (
           (NEW.created_at, NEW.id) < (w.cursor_created_at, w.cursor_message_id) OR
           (NEW.created_at, NEW.id) > (w.anchor_created_at, w.anchor_message_id)))
    THEN RAISE EXCEPTION 'B3 Message/TurnWork scope mismatch' USING ERRCODE = '23514'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER b3_message_scope BEFORE INSERT OR UPDATE ON channels_message
    FOR EACH ROW EXECUTE FUNCTION b3_check_message();

CREATE FUNCTION b3_check_epoch() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.ownership_epoch < OLD.ownership_epoch THEN
        RAISE EXCEPTION 'B3 ownership epoch cannot decrease' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM agent_turnwork WHERE conversation_id = OLD.id) AND
       (NEW.organization_id, NEW.contact_id, NEW.channel_account_id) IS DISTINCT FROM
       (OLD.organization_id, OLD.contact_id, OLD.channel_account_id) THEN
        RAISE EXCEPTION 'B3 conversation scope is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER b3_conversation_epoch BEFORE UPDATE ON agent_conversation
    FOR EACH ROW EXECUTE FUNCTION b3_check_epoch();
"""

REVERSE = """
DROP TRIGGER b3_conversation_epoch ON agent_conversation;
DROP FUNCTION b3_check_epoch();
DROP TRIGGER b3_message_scope ON channels_message;
DROP FUNCTION b3_check_message();
DROP TRIGGER b3_turnwork_scope ON agent_turnwork;
DROP FUNCTION b3_check_turnwork();
"""


class Migration(migrations.Migration):
    dependencies = [('channels', '0011_message_origin_epoch_message_output_ordinal_and_more')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
