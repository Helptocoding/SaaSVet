from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('appointments', '0017_appointment_mutation_effect')]

    operations = [
        migrations.RemoveConstraint(model_name='appointmentmutationeffect', name='appointment_mutation_kind_valid'),
        migrations.AlterField(model_name='appointmentmutationeffect', name='kind',
            field=models.CharField(max_length=32, choices=[
                ('RESCHEDULE_APPOINTMENT', 'RESCHEDULE_APPOINTMENT'),
                ('CANCEL_APPOINTMENT', 'CANCEL_APPOINTMENT'),
                ('CONFIRM_ATTENDANCE', 'CONFIRM_ATTENDANCE')])),
        migrations.AddField(model_name='appointmentmutationeffect', name='status_change',
            field=models.OneToOneField(blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT, related_name='mutation_effect',
                to='appointments.appointmentstatuschange')),
        migrations.AddConstraint(model_name='appointmentmutationeffect',
            constraint=models.CheckConstraint(condition=models.Q(kind__in=[
                'RESCHEDULE_APPOINTMENT', 'CANCEL_APPOINTMENT', 'CONFIRM_ATTENDANCE']),
                name='appointment_mutation_kind_valid')),
        migrations.RunSQL(sql='''
            CREATE FUNCTION appointment_confirmation_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.kind = 'CONFIRM_ATTENDANCE' AND NOT EXISTS (
                    SELECT 1 FROM appointments_appointmentstatuschange s
                    JOIN agent_conversationoperation o ON o.operation_key = NEW.operation_id
                    WHERE s.id = NEW.status_change_id
                    AND s.organization_id = NEW.organization_id
                    AND s.appointment_id = NEW.appointment_id
                    AND s.from_status = 'scheduled' AND s.to_status = 'confirmed'
                    AND s.changed_by_id IS NULL AND s.reason = ''
                    AND s.created_at >= o.authorized_at AND s.created_at <= NEW.committed_at
                    AND o.preconditions->>'schema' = '3'
                    AND o.preconditions->>'attendance_contract' = '1'
                    AND NEW.before->>'status' = 'scheduled'
                    AND NEW.after = jsonb_set(NEW.before, '{status}', '"confirmed"'::jsonb)
                ) THEN
                    RAISE EXCEPTION 'Incomplete confirmation evidence';
                END IF;
                RETURN NEW;
            END $$;
            CREATE TRIGGER appointment_confirmation_evidence_guard
            BEFORE INSERT ON appointments_appointmentmutationeffect
            FOR EACH ROW EXECUTE FUNCTION appointment_confirmation_evidence_guard();
        ''', reverse_sql='''
            DROP TRIGGER appointment_confirmation_evidence_guard ON appointments_appointmentmutationeffect;
            DROP FUNCTION appointment_confirmation_evidence_guard();
        '''),
    ]
