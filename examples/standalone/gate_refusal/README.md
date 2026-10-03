# Gate refusal — answering by the declared name

A gate declared `Gate(name="approve_refund", ...)` parks the walk under its
canonical node name `approve-refund`. The public answer path accepts either
spelling, so the name an author types is the name that works.

This example shows the two halves a caller cares about:

- `answer_gate` with the declared spelling records the answer, and the result
  carries the canonical name.
- A reference that matches nothing **raises** `GateNotFoundError` (from
  `functualize.app.utils`) carrying the reference as typed, the scope id, and
  the gates that scope actually has — a miss the caller cannot ignore, with
  everything needed to correct it.

Run it from an empty directory, with both `uv` and the script pointed at your
checkout of this repository by absolute path:

```console
$ repo=/path/to/functualize   # your checkout of this repository
$ cd "$(mktemp -d)"
$ uv run --project "$repo" python "$repo/examples/standalone/gate_refusal/gate_refusal.py"
answered: approve-refund -> answered
missed:   'nope' in 'rel-1' is not one of: approve-refund
```

The tests beside it drive the same functions against a real app and a real
scope store; `examples/` is collected by pytest, so the example is the
end-to-end test for the API.
