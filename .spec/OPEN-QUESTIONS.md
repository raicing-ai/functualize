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
