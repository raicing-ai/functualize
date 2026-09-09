# Feature — surface-request-parity

Implements **F4** of `contributor/architecture/run-model/13-roadmap.md`: the audit's step 9
(the seal) plus D-4, D-5 and D-6 — every door gets the *syntax* to fill the request F1 gave it,
and the parity matrix becomes a test.

**Depends on:** `run-request-entry` (F1), `engine-sealed-construction` (F3).
**Blocks:** nothing.

---

## 1. The problem

F1 gives every door a `RunRequest` with a `group_option_values` field on it. **It does not
give three doors a way for a caller to fill that field**, and it leaves one door class with an
accidental way to fill fields nobody meant to expose.

### 1.1 `rc.invoke` cannot pass group options (D-4, STATUS #17)

`Invoke.__call__` and `RunContext.invoke` have no `group_option_values` parameter. A nested
job runs with whatever its parent's configuration resolved to, and cannot be told otherwise.

`docs/guides/group-options.md` records this as **deliberate**.

### 1.2 MCP answers the same question three ways (D-5)

```
plugins/functualize-mcp/src/functualize_mcp/_server.py:278   passes group_option_values
plugins/functualize-mcp/src/functualize_mcp/_tools.py        zero occurrences
```

The per-job tool path passes it; the generic `run_job` and the async worker do not. **One
adapter, three answers** — and the MCP translator merges group fields into tool schemas, so an
agent is shown flags it then cannot pass through `run_job`.

### 1.3 HTTP and Lambda have no designed channel (D-6)

Neither plugin exposes group options or a resume channel. A gated workflow reached through
Lambda cannot be resumed through Lambda.

### 1.4 …except they do, by accident, and so does MCP

`FunctualizeApp.execute` declares its control inputs as keywords, and four doors splat a
caller-controlled dictionary into it:

```python
result = await asyncio.to_thread(self._app.execute, job_name, **kwargs)   # HTTP:177
```

A payload key named `scope_id` binds to the **control parameter**, not to the job. So doors
documented as having *no* resume channel have an unvalidated one that appears in no schema.

> This is D-6 seen from the other side, and it means F4 is not merely additive. **Giving these
> doors a real channel and closing the accidental one is the same change.** Doing only the
> first leaves the second.

*(F1 stops the splat at each door; this feature makes the shape unrepresentable and pins it.)*

### 1.5 Adapters still reach into the kernel

Five imports across three files:

```
app/adapters/lazy_command.py:87    _engine.capabilities.tty.terminal_available
app/adapters/surface_gate.py:37    _engine.ambient.has_eligible_ambient
app/adapters/click_params.py:1064  _engine.executor
app/adapters/click_params.py:1069  _engine.capabilities.tty.terminal_available
app/adapters/click_params.py:1230  _engine.missing_value.MissingValueError
```

Note `terminal_available` is imported **twice**, in two adapters, to answer one question — the
TTY pre-flight is decided in two files.

While these imports exist, an adapter *can* reach the engine to re-derive something, and the
guarantee this document set claims is a convention rather than a structure.

### 1.6 The parity matrix is hand-maintained, and was wrong when written

The coverage audit's §B matrix is 16 feature rows × 8 surface columns. It placed D-13's
failure in the `rc.invoke` column — and `rc.invoke` is one of the doors that gets scope
propagation *right* (`_engine/capabilities/invoke.py:398,406`).

A table nobody can check drifts in both directions: it under-reports real gaps and invents
fake ones.

---

## 2. User stories

- **US-1** As an agent driving functualize over MCP, every tool that runs a job accepts the
  same inputs — I do not have to know which door I came through.
- **US-2** As someone triggering a job over HTTP, I can pass group options and resume a
  blocked workflow, through a documented parameter that appears in the schema.
- **US-3** As a job author calling `rc.invoke`, I can override a group option for one nested
  call, and inheritance stays the default when I do not.
- **US-4** As an operator, a job argument named `scope_id` reaches my job as an argument — it
  does not silently address someone else's workflow.
- **US-5** As a maintainer adding a door, the parity suite tells me which rows I did not wire.

---

## 3. Behaviour

### 3.1 Every executing door can carry every request field

The three doors without a channel get one, in their own idiom: a schema field for MCP, a
documented body key for HTTP and Lambda, a keyword for `Invoke`.

### 3.2 STATUS #17's boundary moves, and the reason is recorded

`Invoke` gains `group_option_values`. **Inheritance stays the default**: `rc.invoke(job)`
inherits the parent's values exactly as today; `rc.invoke(job, group_option_values=…)`
overrides.

> The old reasoning — a nested call should not re-negotiate its parent's configuration — was
> sound when the alternative was a twelfth parameter. Under `RunRequest` it inverts:
> *withholding* the field now costs a deliberate erasure, code that builds a request and blanks
> a field. A boundary that costs code needs a stronger reason than "it was free".

`parallel` is untouched: items still run with `parent_scope=None`
(`_engine/capabilities/invoke.py:603`, *"Independent — no shared scope"*). A parallel batch is
not a nested walk.

### 3.3 Control inputs are unrepresentable as job arguments

No door splats a caller-controlled dictionary into a function whose keyword parameters are
control inputs. A payload key named `scope_id` reaches the job as an argument named
`scope_id`.

### 3.4 The seal

No module under `app/adapters/` imports from `_engine`. After this, an adapter **cannot** reach
the engine to re-derive a rule — the import fails `lint-imports`, which runs in CI as its own
job.

The doubly-imported `terminal_available` gets one home on the way through.

### 3.5 The matrix becomes a test

Every feature row of the coverage audit's §B table becomes a case in the dual-surface
`cli_run` harness (`tests/conftest.py:454`), which is already parameterised over `func` | `app`
and already earned its keep — it caught the epilog and capability-leak defects (ADR-010 §5).

> **A row that cannot be expressed as a test is a row that was never true.** Any row that
> resists is reported as a finding, not quietly dropped.

### 3.6 What must not change

- `parallel`'s `parent_scope=None`.
- Any existing flag or parameter spelling.
- Inheritance as `rc.invoke`'s default.
- The six import-linter contracts, which must be **greener**, not merely as green.

---

## 4. Acceptance criteria

- **AC-1** `rg 'from functualize\._engine' src/functualize/app/adapters/` returns **zero**.
- **AC-2** `terminal_available` is reached through one route, from one place.
- **AC-3** `uv run lint-imports` passes, and the `_cli`/adapters contracts are tightened to
  forbid what this feature removed.
- **AC-4** MCP's three executing doors accept `group_option_values`; a schema-driven per-job
  tool, the generic `run_job`, and the async worker behave identically for the same inputs.
- **AC-5** HTTP and Lambda accept group options and a scope id as **documented, schema-visible**
  inputs.
- **AC-6** A gated workflow started over Lambda can be resumed over Lambda.
- **AC-7** `rc.invoke(job, group_option_values=…)` overrides; `rc.invoke(job)` inherits.
- **AC-8** `rc.invoke_parallel` items still run with `parent_scope=None`.
- **AC-9** A job argument named `scope_id` or `group_option_values` reaches the job as an
  argument on every door, and addresses nothing.
- **AC-10** Every feature row of coverage §B is a case in the `cli_run` harness, passing
  identically on both surfaces — or is recorded as a finding with the reason it cannot be.
- **AC-11** `docs/guides/group-options.md` records that #17's boundary moved, and why.
- **AC-12** A new door added without wiring a field fails the parity suite rather than
  shipping.

---

## 5. Out of scope

- Reducing the door count — **N4**. A tenth door should be cheap, not forbidden.
- The `app/utils.py` corridor — **N3**.
- Pre-boot-only flags. Aliases, `--exclude` and `--perf-report`'s lookahead are about
  *reaching the program*, not about the run, and stay `func`-only.

> The test for whether something belongs in the request: **does a job author's declaration
> depend on it?** `--prompt-gates` changes how a declared `Gate` behaves — request.
> `--exclude` changes which modules are scanned before any declaration is read — pre-boot.

## 6. Prior art

- **ADR-020** consequence: *"a job-author-declared feature works on every surface by
  construction"* — this feature is where that stops being aspirational.
- **ADR-010 §5** — the dual-surface harness and the two defects it caught.
- **`pitfalls.md` §19** — a rule that cannot be shared needs a parity test, not a comment.
- **`surface-boundary.md` §4** — the worked example this feature makes structural.
