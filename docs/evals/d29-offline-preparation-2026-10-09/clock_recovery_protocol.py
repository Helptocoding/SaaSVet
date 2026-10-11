"""Inactive safety protocol model. No Windows service API or executor."""


def safe_start(before, helper):
    required=('own_restore_access_verified','separate_process','ready_ack','durable_lease',
              'parent_pid_creation_time_verified','restore_deadline_registered','state_readable',
              'outside_main_kill_job_verified')
    errors=[k for k in required if helper.get(k) is not True]
    if before.get('state') not in ('RUNNING','STOPPED'):
        errors.append('ORIGINAL_SERVICE_STATE_NOT_STABLE')
    if before.get('start_type') not in ('AUTOMATIC','MANUAL','DISABLED'):
        errors.append('ORIGINAL_START_TYPE_UNKNOWN')
    if before.get('host_scope_authorized') is not True:
        errors.append('EXPLICIT_HOST_W32TIME_AUTHORIZATION_MISSING')
    if before.get('main_restore_access_verified') is not True:
        errors.append('MAIN_CANNOT_RESTORE')
    return {'may_start':not errors,'errors':errors,'service_action_executed':False}


def recovery_action(before, *, reason, currently, same_parent_identity=True):
    """Idempotent restore intent, exercised only with fake states offline."""
    if reason not in ('NORMAL','ERROR','INTERRUPTION','PARENT_DIED','DEADLINE_EXCEEDED'):
        raise ValueError('Unknown recovery trigger')
    if before.get('state') not in ('RUNNING','STOPPED'):
        raise ValueError('Unknown original state; refuse mutation')
    if currently not in ('RUNNING','STOPPED'):
        return {'action':'WAIT_FOR_STABLE_STATE_OR_REPORT_RECOVERY_FAILURE','restored':False}
    if currently==before['state']:
        return {'action':'VERIFY_AND_RECEIPT_ONLY','restored':True}
    return {'action':'RESTORE_'+before['state'],'restored':False,'start_type_mutation':False,
            'reason':reason,'parent_pid_reuse_not_used_as_liveness':not same_parent_identity}
