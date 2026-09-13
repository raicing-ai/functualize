# 06 · Outcome authority — the tables are shared, the rule is not

Causes **C-III** (delivery is a per-surface act) and **C-V** (the flag vocabulary has no home).

---

## A. What is already centralized, and why it was not enough

Two number tables are genuine single authorities, and they work:

- `_types/exit_codes.py:50-68` — `_STATUS_EXIT_CODES`, the process family
- `_types/http_status.py:53-75` — `_STATUS_HTTP_CODES`, the wire family, consumed by both
  trigger plugins (`functualize-http/__init__.py:193`, `functualize-lambda/__init__.py:65`)

Three shipped divergences were each fixed by adding one of these tables: cold-boot exit 1 vs
warm-boot exit 0 for the same failure; Lambda answering `{"statusCode": 200}` for every
outcome; HTTP's status line disagreeing with its own body.

**The tables answer "what number".** Nothing answers **"which statuses are failures"**, or
**"what does a blocked run say before it exits"**. Those are re-decided per surface, and that
is the whole of C-III.

## B. Nine translation sites

| # | Site | What it decides |
|---|---|---|
| 1 | `_types/exit_codes.py:50-68` | the process numbers — **authority** |
| 2 | `_types/http_status.py:53-75` | the wire numbers — **authority** |
| 3 | `app/adapters/click_params.py:1271-1276` (`deliver_job_result`, def `:1194`) | the failure set **and** the BLOCKED/REFUSED report line, for the two click surfaces only |
| 4 | `_cli/tui/job_execution.py:274` | its own success set |
| 5 | `_cli/builtins.py:598-608` | `func builtin parallel`'s own success set, first-failure rule |
| 6 | `_cli/builtins.py:1354-1367` | `_resume_exit()` — a string→status reverse lookup **(new in 0.3.0)** |
| 7 | `plugins/functualize-mcp/.../_tools.py:35-48` | `wire_status()` **(new in 0.3.0)** |
| 8 | `plugins/functualize-http/.../__init__.py:193` | family choice |
| 9 | `plugins/functualize-lambda/.../__init__.py:65` | family choice |

Sites 8 and 9 are *correct* — they choose a family and render. Sites 3–7 decide.

### The rule is coordinated by comments

`_cli/tui/job_execution.py:269-274`:

> *"SKIPPED/BLOCKED are not failures (a blocked workflow did what it was asked and is
> resumable), **matching `func builtin parallel`'s rule**."*

```python
if status in (RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED):
    ...
    return_code = 0
else:
    return_code = int(exit_code_for_status(status)) if status is not None else 1
```

Note the shape: the table is consulted **for failures** and overridden **for BLOCKED**. The
citation is to another hand-written site, not to an authority. Three implementations of one
rule, held together by a comment naming a second implementation.

## C. D3 resolved — the TUI exits 5, and the codebase already agreed

The audits left one question to the maintainer: when a gate blocks inside the inline TUI,
should the *process* exit 0 (it is a shell) or 5 (it is the process)?

**Decision: 5.** And the argument was already written, in this codebase, in the same release
that created site 6. `_cli/builtins.py::_resume_exit`'s docstring:

> *"A still-blocked run exits 5, the same code the job itself uses. This is a breaking change
> from the deposit-only verb, which always exited 0 — and it is the point: **a script that
> resumes in a loop needs to know whether it finished.**"*

0.3.0 changed `workflow resume` from always-0 to 5-when-blocked, deliberately, breaking
compatibility to do it. After that change the inline TUI is the **only** surface that reports
a blocked run as success. It is no longer a defensible difference of opinion between two
surfaces; it is one surface left behind by a decision already taken.

What stays per-surface is the **presentation**: the panel may keep saying `✓ Done`, because
in a shell a paused workflow genuinely is not an error. The family choice and the render are
different questions, and separating them is the point of §D.

## D. The target — one module, and family choice as the only per-surface decision

One `_types` module (extend `exit_codes.py` or a sibling `outcome.py`) owns four things:

| | Owns | Today |
|---|---|---|
| a | the exit table | already there |
| b | the HTTP table | already there, in a sibling |
| c | **the failure-set rule** — `is_failure(status, family)` | spelled three times |
| d | **the report line** for BLOCKED/REFUSED | click-only, `click_params.py:1244-1256` |

Delivery surfaces become Adapters: each **chooses a family** and **renders**. Nothing else.

```
                     ┌──────────── _types/outcome.py ────────────┐
                     │  status → family → (number, is_failure,   │
                     │                     report line)          │
                     └───────────────────┬──────────────────────┘
     family="process"   family="panel"   │  family="tool"   family="wire"
            ▼                 ▼          ▼         ▼              ▼
   deliver_job_result     TUI panel          MCP response    HTTP / Lambda
```

The family choice becomes a **one-word, greppable** decision per surface. That is the entire
mechanism: it does not stop a surface differing, it makes the difference visible and
reviewable instead of a comment citing a sibling.

> **Why this is Move Method, not Facade.** No subsystem is being simplified; one concept is
> being given its behaviour. Every mapping changes together — add a `RunStatus` and all
> families change — so they belong beside the data. Today the TUI envies `JobResult`'s status,
> HTTP envies it, Lambda envies it.

Sites 6 and 7 dissolve rather than move. `_resume_exit`'s reverse lookup exists because the
resume verb receives a status **as a string** and has no way back to the enum; once the
outcome module owns the string↔status mapping, the hand-rolled
`0 if status in {"answered", "drafted"} else 1` fallback has nowhere to live. `wire_status`
becomes the tool family's renderer.

## E. The flag vocabulary — one rule, seven consumers, no test

`negative_flag_for` (`_types/naming.py:100`) is the precedent that proves the move works:
one rule, so `--no-cache` means the same thing on both surfaces. It has **seven** consumers,
re-verified at `e57f0c9`:

| Consumer | Site |
|---|---|
| `app/adapters/click_params.py` | `:322`, `:608`, `:675`, `:876` |
| `_cli/tui/bar.py` | `:295` |
| `_cli/tui/sync.py` | `:134` |
| `_cli/dispatch.py` | `:729` |

The audit's finding is not that seven is too many. It is that **the plan that produced this
rule counted five sites, and the test found a sixth** (`.spec/STATUS.md`: *"five
flag-rendering sites, not the four the plan named"*). Counting re-derivation sites is not a
mechanism. The count is pinned by no test today, so an eighth can appear silently.

`_types/flag_grammar.py` takes the whole vocabulary, not one rule of it: which flags take
values, which take optional values, which are bool (`dispatch.py:81-121`), the negative
spelling, and the group-flag alias matchers (`dispatch.py:703-767`).

**Two parsers remain, and that is correct.** The pre-boot tokenizer and click are different
*syntaxes*; pre-boot exists so `func` can route without importing job modules, and that is a
3 ms budget this design must not touch ([12](12-performance.md)). They share a vocabulary,
not a parser. `--perf-report`'s optional-value lookahead stays deliberately `func`-only, and
the grammar module says so in a comment, so the exclusion is a decision rather than an
omission.

## F. Why this feature is independent of F1

F2 touches no door and needs no request. It can be authored and executed in parallel with
F1 — which is why it is the second feature rather than the fourth, despite the entry work
being the headline. It also establishes the pattern (*one authority, parity-tested*) on
low-risk ground before F3 applies it to the engine's construction.

## G. Verification and sabotage

| | |
|---|---|
| **Parity test** | TUI panel ≡ table, in the `TestReadinessAgreesWithClick` style — expectations **derived from the module**, never a second list. This is the pattern `pitfalls.md` §19 prescribes: *a rule that cannot be shared needs a parity test, not a comment.* |
| **Plugin suites** | the three `test_status_codes.py` suites already parametrize over every terminal `RunStatus`; they stay green |
| **Grammar round-trip** | `emit(resolve(text)) == text` across every consumer |
| **Consumer count** | pinned by a test, so an eighth `negative_flag_for` consumer fails the suite rather than appearing silently |

| Break this | This must fail |
|---|---|
| Change the TUI's failure set locally | the panel≡table parity test |
| Diverge one alias in the click builder only | the grammar round-trip test |
| Restore `_resume_exit`'s hand-rolled fallback | the string↔status mapping test |
