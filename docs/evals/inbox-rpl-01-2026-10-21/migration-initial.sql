BEGIN;
--
-- Add field reply_to to message
--
ALTER TABLE "channels_message" ADD COLUMN "reply_to_id" bigint NULL CONSTRAINT "channels_message_reply_to_id_0380ee1c_fk_channels_message_id" REFERENCES "channels_message"("id") DEFERRABLE INITIALLY DEFERRED; SET CONSTRAINTS "channels_message_reply_to_id_0380ee1c_fk_channels_message_id" IMMEDIATE;
--
-- Create index message_reply_target on field(s) reply_to of model message
--
CREATE INDEX "message_reply_target" ON "channels_message" ("reply_to_id");
COMMIT;
