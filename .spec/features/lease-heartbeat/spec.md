# Lease heartbeat during workflow steps

## Problem

A workflow walk renews its lease after a node returns. A node that runs longer
than the lease can therefore leave a still-working scope claimable. Another
runner may claim it and repeat effects before the first runner reaches a fenced
write. The lease documentation promises renewal during long work, while the
current walker does not provide it.

The current renewal call was verified with `rg -n '\.renew\(' src/functualize`:
`workflow_walker.py:550` is the one production call. The earlier timeout decision
in `contributor/architecture/run-model/08-durable-runs.md` §D rejects pretending
that a Python thread has been interrupted. This change preserves that decision.

## Intended behavior

- A runner that holds a workflow scope continues renewing it while a node is
  executing, including a node that runs longer than `DEFAULT_LEASE_SECONDS`.
  The normal heartbeat interval is 60 seconds, one fifth of the current 300
  second lease. It does not depend on a node boundary or produce a busy loop.
  The walk also renews once when it starts, on the walking thread and before
  its first step, so time spent by the claim itself cannot leave that step on
  a lapsed lease; a walk that learns there that the scope was taken runs
  nothing.
- A second ordinary runner attempting the same scope during a live step is
  refused. The running step is not interrupted or reported as timed out merely
  because it has taken longer than one lease period.
- Renewal preserves the held generation. A forced claim, cancellation, or
  another legitimate takeover still fences the former runner's writes. A
  renewal refused with `StaleGenerationError` is treated as lost ownership even
  if the old expiry has passed. Other renewal errors are recorded as errors and
  retried at the next interval; they are not described as proof of takeover.
- When the walk exits, whether by completion, a raised exception, a failed
  step, or a superseding claim, its heartbeat stops. A stopped runner does not
  keep a lease alive. Expiry after its last successful renewal makes the scope
  claimable under the existing lease rules.
- Lease expiry is a measure of missed renewal, not a step execution budget.
  Existing explicit reclaim and fencing rules continue to apply. No running
  Python step is forcibly stopped by this change.

## Acceptance criteria

1. A step can run past one full lease period while its scope remains unclaimable
   to a second ordinary runner if successful renewals finish before expiry. A
   renewal whose own durable write outlasts the lease can land already expired,
   allowing an ordinary second walker to claim while the first step still runs.
   One measured renewal write took 0.418 seconds against a compressed
   0.3-second lease; with a 300-second lease and 60-second interval, the write
   would have to stall for more than 240 seconds. The generation fence rejects
   the old runner's stored writes, but effects outside the store can repeat.
2. A two-runner test observes the refusal during the live step and verifies
   that the first runner's generation remains current until a legitimate
   takeover or release.
3. A test observes renewal from the walk during the step without calling
   `renew()` in the test. It also verifies that renewal continues without a
   node boundary and stops on completion and on an exception.
4. A refused renewal distinguishes stale generation from a transient renewal
   error. A forced takeover still produces a superseded result through the
   existing fence; an expired but unchanged generation can still be renewed.
5. Heartbeat timing is testable without a 300 second wait. A bounded interval
   and stop mechanism prevent repeated immediate wakeups and leave no active
   heartbeat after the walk returns.
6. `lease.py`, `frontier.py`, the timeout tests, and the user-facing workflow
   documentation agree on what lease expiry means during long work.

## Outside scope

The claim algorithm, generation-fence semantics, non-interruptible step policy,
and the default lease duration remain as they are.
