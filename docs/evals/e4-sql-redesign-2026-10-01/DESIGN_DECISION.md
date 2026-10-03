# DESIGN_DECISION — E4 forecast SQL

Recorded before any production runtime edit, 2026-10-01 (America/Mexico_City).
Baseline HEAD: `1d04e72f69e9c1576ac1be901624db127b879bf4`.
Old runtime: `83ee3b24c84b170e22e401cb09a34da5320ae0a3`.

Decision: **implement alternative A only, subject to post-fix regression and concurrency gates**.
This is a query rewrite without schema or persistence changes. Migration count: 0.

## Alternatives measured

**A — uncorrelated future organization relation in one statement.** Select distinct
organization IDs from ordinary, unbound, inbound pending Messages in `(clock,
clock + 1 second]`. Test the existing idle and recency predicates against
Organization rows whose IDs are in that relation. The outer Conversation
selection, safety exemption, never-claimed exemption, partition ranking,
ordering, exclusions and limit remain identical. Message scans execute once;
the residual correlation visits the small organization relation.

**B — materialize the same organization IDs in a separate query.** Evaluate the
future Message relation first, then pass its IDs to the same organization
predicate. This uses two statements and a Python list proportional to future
organization cardinality. It removes the repeated Message scan too. Two
autocommit statements can observe different committed states; a repeatable-read
wrapper would add complexity. Advisory selection and transactional claim would
still fence admission, but A avoids the extra observation interval altogether.

Both alternatives were measured at all seven Messages points (8 controlled
Conversations) and all seven Conversations points (2000 pending Messages), using
PostgreSQL 16.15 with fsync/synchronous_commit on, the same migrated empty
template, synthetic fixture proportions, five warmups and 30 repetitions.
The metric is PostgreSQL EXPLAIN ANALYZE execution time, excluding network and
planning time. B sums execution times of its two statements. No OS cache flush.
The interrupted initial full run produced no matrix receipts; its migrated
template was recovered and reused, with receipts preserved.

| Conversations | OLD p95 ms | A p95 ms | B p95 ms |
|---:|---:|---:|---:|
| 10 | 27.515 | 6.012 | 7.033 |
| 25 | 90.887 | 8.722 | 9.524 |
| 50 | 224.300 | 13.184 | 6.762 |
| 100 | 398.106 | 10.272 | 27.779 |
| 250 | 952.656 | 26.203 | 31.628 |
| 500 | 2679.216 | 118.551 | 69.651 |
| 1000 | 5336.076 | 159.084 | 156.077 |

At B=1000, OLD dominant Message loops=1003 and root shared hits=215477.
A and B each execute three Message scans with loops=1 and 39 shared hits per
scan. A root shared hits=7867, shared reads=0. A planning time=4.815 ms.
Full distributions, removed rows, temp buffers, sorts, and individual plans are
in `matrix-full-*.json` and `explain/full/`. Host scheduling noise is visible in
the tails; the decision relies on the plan shape and material improvement, with
no artificial SLO introduced.

## Equivalence

`oracle.json`: seed 20261001, 20 named states + 300 generated states, 640
alternative evaluations, **decision_mismatches=0**. Comparisons include ordered
Conversation IDs and corresponding ordered organization IDs, yield/no-yield,
busy/never-claimed/recency boundaries, safety presence, disappeared candidates,
multiple Conversations per organization, and deadline observations.

The relational identity is: `exists qualifying Message m with organization
predicates P(m.organization)` equals `exists Organization o in distinct
qualifying Message organization IDs with P(o)`. Message eligibility conditions
stay in the uncorrelated relation. The current-org exclusion, durable last
claim comparison and active-org-work condition depend only on organization.
Foreign keys guarantee the organization row exists. A executes all predicates
in one PostgreSQL statement snapshot, including the existing Now expressions.
No candidate filter moves across the window ranking or limit.

The frozen old selector in `backend/apps/agent/tests/e4_sql_oracle.py` is for
tests only. Production claim and admission code remain the authority. The
post-fix tests will cover fallback exclusions, retries/expired leases, B5 after
W1, monotonic READY and races from independent processes.

## Other alternatives considered

- A raw MATERIALIZED CTE could force relation reuse, but adds SQL and ORM
  integration complexity. STOP_NOT_NEEDED: A already demonstrates scan reuse.
- Selecting <=3 candidates and then applying forecast in a second query risks
  changing the current filtering-before-ranking behavior and losing fallback
  candidates. Making it exact requires additional selection rounds or a larger
  relation. STOP_NOT_SELECTED: A keeps the original ordering and limit placement.
- An index on future ordinary Message eligibility could lower each old scan's
  cost while leaving the correlated loop count. STOP_NOT_NEEDED: no new index
  was created; the rewrite passes the structural gate with existing indexes.
- New derived persistence/state: STOP_DESIGN_ESCALATION if ever required; no
  such alternative is implemented or needed here.

## Choice, risks and boundaries

A is preferred because both measured rewrites eliminate the structural cause
and have comparable sufficient performance, while A uses the existing lazy
QuerySet interface and one statement snapshot. B is STOP_ALTERNATIVE_NOT_SELECTED.
Only A will enter runtime. No second tuning is authorized in this experiment.

Residual work still scales with Conversation cardinality and durable history:
organization/claim checks and ranking are not constant-time. The measured
Message relation is independent of Conversation count. PostgreSQL planner
choices can vary with data and statistics; a real plan regression test and the
post-fix matrices guard the diagnosed shape. No claim revalidation is weakened.

No new index, migration, counter, cursor, derived state, high-cardinality
instrumentation, release grant or deployment. B0 closed; B7B=False; flags={};
release grants=[]; active clinics=0; PENDING_ACTIVATION_REQUIREMENTS.
PROFILE-BETA-1 and B9E are not run in this task.
