"""Pure interval constraints; no schedule replay and no physical evidence."""
from fractions import Fraction


def feasible_chain(*, ready, cap, old_deadline, prequery, yield_end, correction_commit, corrected_deadline,
                   correction_db_now, miss_poll, corrected_claim, waiter_claim):
    """Arguments are [lo, hi] in a common clock; strict causal ordering only."""
    xs=locals().copy()
    if any(len(v)!=2 or v[0] is None or v[1] is None or v[0]>v[1] for v in xs.values()):
        return {'interval_constraints_satisfied':False,'errors':['UNKNOWN_OR_REVERSED_INTERVAL'],'physical_accreditation':False}
    H=Fraction(1);Q=Fraction(8)
    failures=[]
    def require(condition,code):
        if not condition:failures.append(code)
    require(ready[1]<=prequery[0],'W_NOT_DEFINITELY_READY_BEFORE_QUERY')
    require(prequery[1]<old_deadline[0],'F_NOT_DEFINITELY_FUTURE_AT_QUERY')
    require(old_deadline[1]<=prequery[0]+H,'F_NOT_DEFINITELY_WITHIN_NATIVE_H')
    require(prequery[1]<=yield_end[0],'YIELD_NOT_AFTER_PREQUERY')
    require(yield_end[1]<correction_commit[0],'CORRECTION_NOT_AFTER_YIELD')
    require(yield_end[1]<correction_db_now[0],'CORRECTION_NATIVE_NOW_NOT_AFTER_YIELD')
    require(correction_commit[1]<old_deadline[0],'CORRECTION_NOT_COMMITTED_BEFORE_OLD_DEADLINE')
    require(correction_db_now[1]<=correction_commit[0],'CORRECTION_NATIVE_NOW_AFTER_COMMIT')
    require(correction_db_now[0]+Q>=cap[1],'NATIVE_QUIET_WINDOW_DOES_NOT_REACH_CAP')
    require(corrected_deadline==cap,'CORRECTED_DEADLINE_NOT_NATIVE_CAP')
    require(old_deadline[1]<corrected_deadline[0],'OLD_FORECAST_NOT_DEFINITELY_SUPERSEDED')
    require(old_deadline[1]<=miss_poll[0] and miss_poll[1]<cap[0],'OLD_FORECAST_MISS_NOT_OBSERVED_BEFORE_CAP')
    require(corrected_deadline[1]<=miss_poll[0]+H,'CORRECTED_FORECAST_NOT_WITHIN_H_AT_MISS_POLL')
    require(ready[0]>=cap[1]-H,'CORRECTED_FORECAST_CAN_LEAVE_H_AFTER_W_READY')
    require(corrected_deadline[1]<=corrected_claim[0],'CLAIM_BEFORE_NEW_NATURAL_ELIGIBILITY')
    require(waiter_claim[0]>=corrected_claim[1],'WAITER_CLAIM_BEFORE_PEER_CLAIM_IN_PROPOSED_CHAIN')
    require(waiter_claim[1]-ready[0]<=120,'WAITER_BOUND_NOT_DEMONSTRATED')
    return {'interval_constraints_satisfied':not failures,'errors':failures,
            'physical_accreditation':False,'meaning':'Conditional geometry only; inputs are not observed evidence'}


def analysis():
    return {'status':'PENDING_NO_DEMONSTRABLE_PHYSICAL_WINDOW','source_kind':'OFFLINE_CODE_AND_INTERVAL_ANALYSIS',
            'native_constants':{'QUIET_WINDOW_seconds':8,'MAX_WAIT_seconds':25,'H_seconds':1,'planner_pause_seconds':1},
            'inequalities':['rW >= T-H','rW <= p < d1 < T','d1 <= p+H','yield_end < correction_native_now <= correction_commit < d1',
                            'd1 <= miss_poll < T; actual prequery/selection, never a later census',
                            'correction_native_now + QUIET_WINDOW >= T','d2=T','d2 <= claimF <= claimW','claimW-rW <=120'],
            'available_window':'d1 - max(rW, T-H); strictly less than H=1s, before any observation/commit uncertainty',
            'missing_evidence':['bounded poll phase for both already-free planners','yield-observation latency upper bound',
                                'ordinary correction transaction latency upper bound','pre-query and commit clock brackets',
                                'no competing selection/early claim during correction','pre-query native forecast/history witness'],
            'finding':'Nonempty symbolic intervals exist. The existing receipts do not establish the physical latency/phase bounds required to close them. A 1s pause does not guarantee a poll in a window shorter than 1s.',
            'no_absolute_impossibility_claim':True,'nominal_offsets_not_evidence':True,
            'recipe_execution_ready':False,'branch_stopped_before_fixture_or_probe':True,'population_increase':False,
            'runtime_changes':False,'clock_or_bound_relaxation':False}
