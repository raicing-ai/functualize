# Open questions for the maintainer

Written while executing alone. Each one names what I did in the meantime, so
nothing is blocked waiting for an answer — but each is a decision that could
reasonably go the other way, and I would rather you saw them than not.

Format: **Q-n · question** → *what I did* → *what would change if you say
otherwise*.

## Q-1 · Should `invoke_parallel` items share the run's state, or get their own?

**What I did:** they share it. `capability-duality`/T2 changed
`invoke.parallel` to pass the scope *object* (state) while `nested_request`
still withholds the scope *id* (step records, gates). So batch items write into
the run's store and the parent can read what they produced.

**What this overturns.** Two tests in
`tests/context/test_parallel_and_log_properties.py` asserted the opposite,
citing *"Requirements 21.5 — independent RunContexts with no shared mutable
state"*. That requirement is cited **only** in that file — no spec, ADR or doc
in the repo defines it, so its source was cleared at some earlier merge. I
rewrote both tests to the new contract rather than reverting the change.

**The honest tradeoff.**

*For sharing (what I did):* your stated model is "state between jobs of the
same run", and a batch item is part of the run. With isolation, a parallel item
can compute something and has nowhere to put it that anyone reads — which is
what `invoke_parallel` is usually for.

*For isolation (what 21.5 said):* N identical jobs running concurrently will
pick the same key name by default, not by mistake. Under isolation that was
harmless. Under sharing it is a silent last-write-wins race. The old tests
demonstrate exactly this: N items write one key and each expects its own value
back.

**What changes if you disagree:** one line in
`_engine/capabilities/invoke.py` — `parent_scope=self._workflow_scope` back to
`parent_scope=None` — plus reverting the two tests. I kept the hazard pinned by
a test (`test_two_items_writing_one_key_race`) so the behaviour is asserted
either way rather than implied.

**A third option I did not take:** give each batch item an automatic per-item
key prefix. It solves both, but you rejected framework namespacing for the
general case ("a user could easily add namespacing themselves"), and a special
rule for parallel only would be a second namespacing concept.


## Q-2 · `WorkflowScope.close()` has no production caller — wire it, or delete it?

**What I did:** nothing yet, deliberately. An external review found that
`git grep "\.close()" -- src/` has no hit on a scope anywhere in production, so
`ScopeBackedStateStore._check_open`'s promise — *"once a scope is finished, a
late write from a straggling thread must fail loudly rather than mutate a record
something already read as final"* — is reachable only from tests.

**Why it needs you.** This is a **fourth** instance of the shape
`contributor/guides/wiring-discipline.md` exists for (built, tested, connected
to nothing), and I added to it this week: `_check_open` is mine. The guide's own
rule says a capability with no production call path is not done. But the two
answers differ a lot:

- *Wire it* — somebody has to decide **when** a scope is finished. A workflow
  scope ends when the walk reaches END; a plain job's scope has no such moment,
  which is the same gap as F1's "nothing marks a non-workflow scope terminal".
- *Delete it* — then a late write from a straggler silently mutates a finished
  record, which is what the guarantee was for.

They are the same question as `scope-record-lifecycle`, so that is where it
should be answered.

## Q-3 · `Prompt` and `Sources` bypass the capability map — exempt, or fix?

**What I did:** left them, and left them undeclared, because the new
registry-driven test only checks capabilities that declare an `rc_accessor` and
neither does.

`prompt_facade.py:58-66` and `discovery_facade.py:47-48,71-76` resolve through
`self._rc._execution_engine.host` rather than `_cap_or_none`. The reviewer
looked for observable divergence and found none — the injected `Prompt` also
resolves its collector from the surface stack at call time, so both doors end at
the same object.

**Why it needs you.** ADR-021 lists five classes that may be exempt and neither
of these is one, so today they are an undeclared third state: not shared, not
exempt, just unexamined. Either declare `shared_with_rc=False` with a reason, or
give them an `rc_accessor` and let the tripwire hold them. One line either way;
I would rather not pick the reason for you.

## Q-4 · Delete `get_job_state` / `list_job_namespaces`?

**What I did:** left them.

ADR-021 §B records your decision that the `"fetch.count"` convention is
*documented rather than built*, "because a framework namespace is a second
concept for something a string prefix already does". But
`get_job_state("fetch", "rows")` **is** a framework namespace accessor, and
`list_job_namespaces()` exists to enumerate namespaces. Neither is called
anywhere in `src/` or `examples/`; only a protocol-conformance test touches
them.

**Why it needs you.** They are on `StateStoreProtocol`, so deleting them is a
plugin-contract change — `functualize-state-sqlite` implements both. It is not a
local cleanup, and it interacts with `store-substrate`, which retires that
protocol anyway. If the substrate work goes ahead, this deletes itself; if it
does not, this is a small separate decision.
