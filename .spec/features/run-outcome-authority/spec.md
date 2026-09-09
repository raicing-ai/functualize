# Feature — run-outcome-authority

Implements **F2** of `contributor/architecture/run-model/13-roadmap.md`: the audit's steps 4
and 5 — one home for what a `RunStatus` *means*, and one home for the flag vocabulary.

**Depends on:** nothing. Runs in parallel with `run-request-entry` (F1).
**Blocks:** `engine-sealed-construction` (F3).

---

## 1. The problem

**The tables are shared; the rules are not.** Two number tables are genuine single
authorities and they work. What has no home is *"which statuses are failures"* and *"what does
a blocked run say before it exits"* — and those are re-decided at five sites, two of which
were added in the last release.

### 1.1 Nine translation sites, and the count is growing

| # | Site | Decides |
|---|---|---|
| 1 | `_types/exit_codes.py:50-68` | the process numbers — **authority** |
| 2 | `_types/http_status.py:53-75` | the wire numbers — **authority** |
| 3 | `app/adapters/click_params.py:1271-1276` | the failure set **and** the BLOCKED/REFUSED report line, for two click surfaces only |
| 4 | `_cli/tui/job_execution.py:274` | its own success set |
| 5 | `_cli/builtins.py:598, 608` | `func builtin parallel`'s own success set, first-failure rule |
| 6 | `_cli/builtins.py:1354-1367` | `_resume_exit()` — **new in 0.3.0** |
| 7 | `plugins/functualize-mcp/.../_tools.py:35-48` | `wire_status()` — **new in 0.3.0** |
| 8 | `plugins/functualize-http/.../__init__.py:193` | family choice — correct |
| 9 | `plugins/functualize-lambda/.../__init__.py:65` | family choice — correct |

Sites 8 and 9 choose a family and render, which is right. Sites 3–7 **decide**.

### 1.2 The rule is coordinated by comments

`_cli/tui/job_execution.py:269-274`:

> *"SKIPPED/BLOCKED are not failures (a blocked workflow did what it was asked and is
> resumable), **matching `func builtin parallel`'s rule**."*

```python
if status in (RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED):
    return_code = 0
else:
    return_code = int(exit_code_for_status(status)) if status is not None else 1
```

The table is consulted **for failures** and overridden **for BLOCKED**, and the citation is to
another hand-written site rather than to an authority.

### 1.3 `_resume_exit` invented a tenth vocabulary because it could not reach the ninth

`_cli/builtins.py:1354-1367` reverse-looks-up a status **string** into a `RunStatus`, and when
the lookup misses:

```python
return 0 if status in {"answered", "drafted"} else 1
```

A hand-rolled mapping, written because the resume verb receives a status as a string and has
no way back to the enum.

### 1.4 `wire_status()` proves the thesis in the codebase's own words

`plugins/functualize-mcp/.../_tools.py:35-48` did not exist at `c0c921f`. It was written in
0.3.0 because MCP's execution doors disagreed about how a status reaches the wire. **Its
docstring says "Three doors disagreed."** The correct local fix produced a ninth global site,
because there was no global one to join.

### 1.5 The TUI is now the only surface calling a blocked run a success

0.3.0 changed `workflow resume` from always-exit-0 to 5-when-blocked, **deliberately breaking
compatibility**. Its docstring (`builtins.py:1354-1358`):

> *"A still-blocked run exits 5, the same code the job itself uses. This is a breaking change
> from the deposit-only verb, which always exited 0 — and it is the point: a script that
> resumes in a loop needs to know whether it finished."*

After that change the inline TUI is the last surface reporting a blocked run as success. This
is no longer two defensible opinions; it is one surface left behind by a decision taken.

### 1.6 One flag rule, seven call sites, no test

`negative_flag_for` (`_types/naming.py:100`) is the precedent that proves the move works — one
rule, so `--no-cache` means the same thing on both surfaces. Its consumers:
`app/adapters/click_params.py` (4), `_cli/tui/bar.py`, `_cli/tui/sync.py`, `_cli/dispatch.py`.

The finding is not that seven is too many. It is that **the plan which produced this rule
counted five sites and the test found a sixth** (`.spec/STATUS.md`: *"five flag-rendering
sites, not the four the plan named"*). Counting re-derivations is not a mechanism, and the
count is pinned by no test today.

The rest of the vocabulary — which flags take values, which take optional values, which are
bool (`_cli/dispatch.py:81-121`), and the group-flag alias matchers (`:703-767`) — has no home
at all.

---

## 2. User stories

- **US-1** As someone wrapping functualize in a script, a paused workflow reports the same
  exit code whichever surface I ran it from.
- **US-2** As a maintainer adding a `RunStatus`, I edit one module and every surface's
  behaviour follows.
- **US-3** As a maintainer changing a flag rule, I edit one file, and a test tells me if a new
  consumer appeared that I did not update.
- **US-4** As a TUI user, a paused workflow still reads as `✓ Done` in the panel — because
  in a shell it genuinely is not an error.

---

## 3. Behaviour

### 3.1 One outcome module owns four things

> `RunStatus → family` has one home. Delivery surfaces choose a family and render, and stop
> deciding.

| | Owns | Today |
|---|---|---|
| a | the exit table | exists |
| b | the HTTP table | exists, in a sibling |
| c | **the failure-set rule** — `is_failure(status, family)` | spelled three times |
| d | **the report line** for BLOCKED/REFUSED | click-only |
| e | the **string ↔ status** mapping | hand-rolled in `_resume_exit` |

### 3.2 Family choice is the only per-surface decision

Four families: `process`, `panel`, `tool`, `wire`. Each surface names its family in one
greppable word. The mechanism does **not** forbid a surface differing — it makes the
difference visible and reviewable instead of a comment citing a sibling.

### 3.3 The inline TUI exits 5 when a gate blocks

Audit decision **D3**, resolved (`14-decisions.md` **J3**). The *process* exit becomes 5,
matching every other surface.

> **The panel keeps rendering `✓ Done`.** Family choice and render are different questions,
> and separating them is the whole point of §3.2. The `panel` family may report a blocked run
> as complete for display; the `process` family, which is what the shell sees, says 5.

### 3.4 One flag grammar

`_types/flag_grammar.py` holds the whole vocabulary, not one rule of it: value-taking flags,
optional-value flags, bool flags, the negative spelling, and the group-flag alias matchers.

**Two parsers remain, deliberately.** Pre-boot exists so `func` can route without importing
job modules — a ~3 ms zero-import budget. They share a vocabulary, not a syntax.
`--perf-report`'s optional-value lookahead stays `func`-only, and the grammar module says so
in a comment, so the exclusion is a decision rather than an omission.

### 3.5 What must not change

- The two number tables' contents. This feature gives them company, not new values.
- The three plugin `test_status_codes.py` suites, already parametrized over every terminal
  status, stay green throughout.
- `--no-cache` and every existing flag spelling.

---

## 4. Acceptance criteria

- **AC-1** One `_types` module exports the exit table, the HTTP table, `is_failure`, the
  report line, and the string ↔ status mapping.
- **AC-2** No surface defines its own success or failure set.
  `rg 'RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED'` over `src/` returns **0**.
- **AC-3** Each delivery surface names its family in one place, and the name is greppable.
- **AC-4** `_resume_exit`'s hand-rolled `{"answered", "drafted"}` fallback is gone; the
  string ↔ status mapping comes from the module.
- **AC-5** `wire_status()` reads the module rather than deciding.
- **AC-6** The inline TUI's **process** exit is 5 when a gate blocks, and its **panel** still
  renders the run as done.
- **AC-7** A panel ≡ table parity test derives its expectations **from the module**, never
  from a second list.
- **AC-8** The three plugin `test_status_codes.py` suites pass unchanged.
- **AC-9** `_types/flag_grammar.py` holds the value/optional-value/bool tables, the negative
  spelling, and the alias matchers; `_cli/dispatch.py` holds none of them.
- **AC-10** Every `negative_flag_for` consumer reads it through the grammar module, and a test
  pins the consumer count so an eighth fails the suite.
- **AC-11** `emit(resolve(text)) == text` round-trips across every consumer.
- **AC-12** `--perf-report`'s lookahead is still `func`-only, and `flag_grammar` carries a
  comment saying why.

---

## 5. Out of scope

- Anything needing a `RunRequest` — F1. This feature touches no door's inputs.
- The `--output` and `--prompt-gates` parity gaps — F1.
- Adding or removing a `RunStatus` member.

## 6. Prior art

- **`pitfalls.md` §19** — *a rule that cannot be shared needs a parity test, not a comment*.
  §1.2 is the comment; AC-7 is the test.
- **`pitfalls.md` §6** — *a list hardcoded in five places has already drifted*. AC-10 is the
  registry-plus-test shape.
- **`_engine/explain.py:105-126`** — the precedent inside the engine: `explain_exit_code` maps
  a pre-flight verdict to the exit table's numbers rather than inventing a second vocabulary,
  and its docstring says why. It also records that `ExitCode.STALE` sat in the table with **no
  producer** until `why` grew one. *The failure-set rule is the STALE of today.*
