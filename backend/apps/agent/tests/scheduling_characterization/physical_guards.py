"""Physical negative B8 guard adapter; WRITE release gates stay closed."""
from datetime import timedelta
from uuid import uuid4

from .evidence import timestamp
from .execution import append
from .physical import contained, wait_db
from .runner import wait_ready, write_json


def inbound(s, text):
    from apps.agent import durable
    from apps.agent.services import ingest_inbound_message
    from apps.channels.events import normalize_whatsapp_event, EVENT_METADATA_KEY
    event=normalize_whatsapp_event({'type':'text','text':{'body':text}})
    before=durable.db_now()
    row=ingest_inbound_message(s.fixtures[0][1],wamid='wamid.d29.guard.'+uuid4().hex,
        wa_id=s.fixtures[0][4].external_id,body=text,raw={EVENT_METADATA_KEY:event.projection()})
    after=durable.db_now()
    if row is None:raise AssertionError('Guard fixture ingress missing')
    attempt=dict(attempt=len(s.recorder.offers)+1,organization_id=row.organization_id,message_id=row.pk,
        offered_db_ns_bounds=[timestamp(before.isoformat()),timestamp(after.isoformat())],outcome='ACCEPTED_DURABLE')
    s.recorder.offers.append(attempt);append(s.directory/'offers.jsonl',attempt)
    return row


def authorized(s):
    from django.utils import timezone
    from apps.agent import durable, operations, goals, matter_binding as binding, operation_consent as consent, sender
    from apps.agent.models import ConversationGoal, Conversation
    row=inbound(s,'Cita sintética para Luna');wait_ready(row);w=s.claim(row)
    conv=Conversation.objects.select_related('contact','organization').get(pk=row.conversation_id)
    ctx=durable.context_for_work(w)
    goal=ConversationGoal.objects.create(organization_id=conv.organization_id,conversation=conv,name=goals.SCHEDULE)
    day=(timezone.now()+timedelta(days=3)).date().isoformat()
    binding.change(goal,conv,{'owner':s.fixtures[0][2].pk,'pet':s.fixtures[0][3].pk,
        'date':day,'time':'10:00','service':'consulta','reason':'consulta'},context=ctx,
        message_id=ctx.anchor.message_id,expected_revision=goal.binding_revision,correction=False)
    binding.record_derived(goal,conv,'selected_slot',{'date':day,'time':'10:00','end_time':'10:30','available':True},
        context=ctx,message_id=ctx.anchor.message_id,expected_snapshot=binding.snapshot(goal),tool='check_appointment_slot',observed_at=timezone.now())
    op=operations.prepare_operation(witness=w,goal_id=goal.pk,capability='create_appointment',
        expected_binding_revision=goal.binding_revision,expected_identity_revision=conv.contact.authorization_revision)
    durable.finalize_turn(w,proposal_operation=op);op.refresh_from_db()
    if op.proposal_message_id is None:raise AssertionError('Real proposal was not published')
    message=op.proposal_message
    claim=sender.claim_message(message.pk,organization_id=conv.organization_id,channel_account_id=conv.channel_account_id)
    # Real admission/finalization with the already-used synthetic Meta provider.
    result=sender.dispatch_claim(claim)
    message.refresh_from_db()
    if message.provider_accepted_at is None:raise AssertionError('Proposal emission unproven')
    response=inbound(s,'CONFIRMAR '+consent.proposal_token(op));wait_ready(response);w=s.claim(response)
    decision=consent.evaluate_turn(w);op.refresh_from_db()
    a,p=s.snap('causal-authorization')
    s.check('real_causal_authorization',decision.decision=='ACCEPT' and op.consent_state=='AUTHORIZED',[p,'service-wire.jsonl'])
    consent.execution_authorization_evidence(op)
    return op,w,response


def r2_10(s):
    from apps.agent import durable, operation_execution as execution, operation_consent as consent
    from apps.agent.models import TurnWork, ToolExecution
    from apps.patients.models import Pet, PetRegistrationEffect
    from django.test import override_settings
    with contained(s,AGENT_B7B_CONSENT_ENABLED=True):
        op,w,row=authorized(s)
        before,p=s.snap('guard-input')
        counts=(Pet.all_objects.count(),PetRegistrationEffect.objects.count(),ToolExecution.objects.filter(policy_decision='confirmed').count())
        s.event('guard_input',[p],operation_id=op.pk,variant=s.variant)
        context=execution.ExecutionContext(w,row.contact_id,'create_appointment')
        if s.variant=='expired_consent':
            # Keep historical authorization, let the real operation TTL expire.
            # A fresh B3 reclaim makes operation expiry the tested guard rather
            # than allowing an earlier expired lease to mask that frontier.
            due=op.expires_at;wait_db(due)
            new=s.claim(row);context=execution.ExecutionContext(new,row.contact_id,'create_appointment')
            op.refresh_from_db();consent.execution_authorization_evidence(op)
            a,p=s.snap('operation-natural-expiry')
            captured=next(o for o in a['operations'] if o['id']==op.pk)
            s.check('actual_operation_ttl_elapsed',a['db_ns']>=timestamp(captured['expires_at']) and timestamp(captured['expires_at'])==timestamp(due.isoformat()),[p],due_db_ns=timestamp(due.isoformat()))
            expected='operation_expired'
        elif s.variant=='expired_authority':
            due=TurnWork.objects.get(pk=w.turn_work_id).lease_expires_at
            wait_db(due);a,p=s.snap('authority-natural-expiry')
            s.check('actual_authority_lease_elapsed',a['db_ns']>=timestamp(due.isoformat()),[p]);expected='ownership_lost'
        elif s.variant=='cross_tenant':
            other=s.offer(org=1);wait_ready(other);foreign=s.claim(other)
            context=execution.ExecutionContext(foreign,other.contact_id,'create_appointment');expected='operation_not_found'
        else:expected='containment_closed'
        result=execution.execute_authorized_operation(op.operation_key,context)
        name='guard-result.json';write_json(s.directory/name,dict(status=result.status,reason=result.reason,
            expected_reason=expected,operation_id=op.pk,context_organization_id=context.witness.organization_id))
        s.check('exact_negative_guard_frontier',result.status=='DENIED' and result.reason==expected,[name])
        s.event('guard_denied',[name])
        after,p=s.snap('no-domain-effect')
        current=(Pet.all_objects.count(),PetRegistrationEffect.objects.count(),ToolExecution.objects.filter(policy_decision='confirmed').count())
        s.check('no_domain_effect',after['domain_counts']==before['domain_counts'] and counts==current,[p,name])
        s.event('no_domain_effect',[p,name],effects=0,external_requests=0)
