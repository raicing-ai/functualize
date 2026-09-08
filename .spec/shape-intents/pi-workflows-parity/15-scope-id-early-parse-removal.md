# 15 · Audit: removing `--scope-id` from the early-parse layer

The question put to this audit: *"What can we do to remove `--scope-id` from the
early-parse flag idiomatically? It's redundant with what we have for `builtin workflow`
and the workflow job's options."*

Audited empirically, not by reading. Every dispatch mode was exercised against the
installed CLI at `78d9ff4`, cold cache and warm.

**Verdict: half the premise is false, the other half is true and now proven — and I have
to retract my own earlier argument against removal.** Removal is correct and cheaper than
this folder previously claimed, but a naive removal produces a bad error and there is a
prerequisite bug in the way.

---

## 1. The premise, audited

### 1.1 "Redundant with `builtin workflow`" — **FALSE**

`func builtin workflow` has **no verb that advances a walk**. `list` and `state` read,
`cancel` marks, and `resume` deposits — *"Accepting input does not run the workflow"*
(`builtins.py:913-917`). There is nothing in that group `--scope-id` duplicates; the
group cannot do what `--scope-id` does.

This matters beyond pedantry: it is the same finding as
[14 §1.3](14-resume-deposit-collisions.md) — **the advance operation has exactly one
surface today, and `--scope-id` is it.** So the flag is not redundant with the record
layer; it *is* the invocation layer, in its entirety.

### 1.2 "Redundant with the workflow job's options" — **TRUE, and now proven**

Every dispatch mode that receives `scope_id` (`main.py:2001-2091` — SINGLE_FILE, JOB,
GROUP, UNKNOWN; BARE and BUILTIN run no job) plus the embedded-app path, tested for the
**post-command** option:

| Mode | How exercised | Cold cache | Warm cache |
|---|---|---|---|
| JOB | `func trip-planner --help` (ungrouped `@workflow`) | ✅ | ✅ |
| GROUP | `func lab release --help` | ✅ | ✅ |
| UNKNOWN | job name ≠ file stem, cheap enumeration misses it | ✅ | ✅ |
| SINGLE_FILE | `func ../sf/weather.py trip_planner --help` | ✅ | ✅ |
| Embedded app | `python main.py lab release --help` | ✅ | ✅ |

Warm caches were populated with a real run first, not a `--help` (which writes no cache).
Sample output:

```
$ func lab release --help
Options:
  --scope-id TEXT  Resume the named workflow scope instead of starting a fresh one.
```

And the gating holds — a plain `@job` does **not** carry it:

```
$ func forecast --help
Options:
  --city TEXT     City to check
  --days INTEGER  Days to forecast
  --help                            ← no --scope-id
```

**Per-command coverage is complete.** The premise's second half is correct.

---

## 2. Retraction: my own argument against removal does not survive testing

[01 §A.3](01-surface-inventory.md), [07 item 5](07-roadmap.md) and my answer in
conversation all said:

> *"the warm path is gated on `descriptor.workflow` being present in the discovery cache
> — which is the documented cold-cache hazard (`main.py:2075-2081`). The global is the
> only spelling guaranteed on every dispatch mode."*

Both halves are wrong.

1. **The warm path works.** The discovery cache records `@workflow` topology (the
   `lazy_command.py:164-167` comment says so: *"The cached descriptor already records the
   `@workflow` topology (v10)"*), and the table above confirms it at runtime.
2. **The cold-cache bug was the *global's* bug, not the option's.** Read
   `main.py:2075-2085` again:

   > *"`scope_id`/`prompt_gates` must be forwarded here exactly as Mode.JOB forwards
   > them… Omitting them made `--scope-id` silently ignored on a cold discovery cache and
   > honoured on every warm run afterwards, so a workflow minted a generated scope id on
   > its first invocation and the caller's id addressed nothing."*

   That is a defect in threading **the early-parse global** through UNKNOWN mode. It is
   evidence *against* keeping the global — the global is the thing with a history of
   silently vanishing — and I repeated it as evidence *for*. I inherited the framing from
   the prior study's doc 07 and did not test it. Corrected here.

---

## 3. What removal actually costs — the real list

The prior study's doc 07 gave four arguments for keeping the global. Tested, three of
them dissolve.

| Doc 07's argument | Audited |
|---|---|
| *"the only resume spelling guaranteed on all dispatch modes"* | **False** — §1.2 |
| *"positional ergonomics: `func --scope-id X release-pipeline` reads as operate-on-scope-X"* | **Taste, and the weaker placement.** `_scope_id_option`'s own docstring picks post-command deliberately: *"Post-command… because that is where a reader looks: the audit that found this got the pre-command position wrong twice."* |
| *"script stability: every deposit result, doc page, and skill teaches `--scope-id`"* | **True about the flag, false about the position.** Every generated hint and every doc teaches **post-command** — see §3.1. |
| *"zero plumbing risk"* | **Inverted** — the plumbing is what broke once (§2). |

### 3.1 Nothing that is taught would change

Exhaustive grep over `docs/`, `skills/` and the two hint-emitting modules. Every taught
spelling is post-command:

| Site | Emits |
|---|---|
| `app/_workflow_resume.py:95-101` | `<entry> <workflow> --scope-id <scope>` |
| `app/adapters/click_params.py:956` | `{program} {command_path} --scope-id {scope}` |
| `docs/cli/workflow.md:72` | `func release --scope-id rel-1` |
| `docs/guides/composition.md:211` | `func lab release --scope-id f81eb2d5` |

The pre-command form appears in exactly **one** place in the whole repository: the
`_scope_id_option()` docstring noting that `func --scope-id X walk` "still works"
(`click_params.py:66`).

**So removal touches no generated text, no doc example, and no skill.** That is the
decisive fact, and it is the opposite of what doc 07 asserted.

### 3.2 What removal actually simplifies

- `_GLOBAL_OPTIONS_ALWAYS_VALUE` loses its only member that addresses **persisted state**
  rather than discovery/config/perf — the category error doc 07 identified and then
  declined to act on.
- `detect_mode` stops needing to skip a flag-plus-value pair while hunting the first
  positional for this flag.
- Four handler signatures and four call sites lose a parameter
  (`main.py:1160, 1258, 1469, 1536, 1654` and `:2009, 2032, 2052, 2091`).
- `click_params.py:1040` — `scope_id = kwargs.pop(_SCOPE_ID_PARAM, None) or workflow_scope_id`
  — loses its precedence rule, and with it the documented "per-command wins over
  pre-command" interaction that has to be tested and explained.

---

## 4. The two things a naive removal gets wrong

### 4.1 The error message becomes actively misleading

Tested with an unrecognised value-taking pre-command flag, which is what `--scope-id`
becomes after removal:

```
$ func --not-a-flag somevalue trip-planner --help
Error: Unknown command 'not-a-flag'.
Run 'func' to see all available commands.
$ echo $?
1
```

Applied to the real flag, a user with muscle memory gets **`Error: Unknown command
'scope-id'.`** — which names neither the problem (wrong position) nor the fix (move it
after the job), and misattributes it to the command layer. The stray value is silently
dropped.

**This is the whole "idiomatically" part of the question.** Removal must be a *rejection*,
not a deletion:

```
$ func --scope-id a3f9c2 release-pipeline
Error: --scope-id is a per-command option, not a global one.
       Move it after the job:  func release-pipeline --scope-id a3f9c2
```
exit 2 (usage), per `_types/exit_codes.py`.

Implement it by keeping `--scope-id` in the early-parse **recognition** set — so the
value is still consumed and `detect_mode` is unaffected — while replacing its assignment
with a hard refusal. That preserves the one thing the early-parse layer was good at
(knowing the flag takes a value) and removes the thing it was bad at (silently owning
persisted state). The repo has no backward-compat obligation
(`CONSTITUTION.md:176-179`), so this is a courtesy, not a shim — but it is the difference
between a rename users can follow and one they file bugs about.

### 4.2 A prerequisite bug: SINGLE_FILE mode crashes when the file is in the cwd

Found while exercising the modes. **Unconditional, and unrelated to `--scope-id`:**

```
$ cd /tmp/sf && ls
weather.py
$ func weather.py trip_planner --help
Traceback (most recent call last):
  ...
  File ".../_cli/main.py", line 1524, in _register_single_file_peers
    app.register_dynamic_job(
  File ".../_app/impl.py", line 700, in register_dynamic_job
    raise ValueError(
ValueError: Cannot register dynamic job 'forecast': a job with this name already exists
```

Mechanism confirmed by contrast — the same file **outside** the cwd works:

```
$ cd /tmp/outside && func ../sf/weather.py trip_planner --help
Usage: trip_planner [OPTIONS]     ← works, --scope-id present
```

So directory discovery registers `forecast` from `weather.py`, then
`_register_single_file_peers` (`main.py:1524`) registers it again and
`register_dynamic_job` (`_app/impl.py:700`) refuses. The common case —
`cd` into a project and run a file in it — raises an unhandled `ValueError` with a
traceback rather than an error envelope.

This matters to the question because **SINGLE_FILE is the mode whose per-command coverage
is hardest to claim**, and it is currently the mode that is broken. Fix it first, or at
minimum land the removal's per-mode tests against the working invocation form and record
the crash as a known separate defect.

---

## 5. The idiomatic removal, concretely

Ordered, each step independently reviewable.

**Step 0 — prerequisite.** Fix the SINGLE_FILE cwd collision (§4.2), or file it and scope
this change to exclude it. Do not remove a global whose replacement cannot be exercised
in one of the four modes.

**Step 1 — turn the global into a refusal.** `_cli/dispatch.py`:
- keep `"--scope-id"` in `_GLOBAL_OPTIONS_ALWAYS_VALUE` (`:79`) so the value is still
  consumed and `detect_mode` is untouched;
- in `_assign_option` (`:624-625`), replace `state.scope_id = value` with the usage
  error from §4.1.

**Step 2 — delete the plumbing.** Remove `scope_id` from `GlobalOptions` (`:320`, `:524`,
`:547`), from the four handler signatures and the four call sites in `main.py`, and from
`_handle_single_file`/`_handle_job`/`_handle_group`'s bodies. `create_job_click_command`'s
`workflow_scope_id` parameter and the `app_ref._workflow_scope_id` fallback
(`click_params.py:1040-1042`) become dead — decide deliberately whether the app-level
attribute stays as a programmatic entry point for embedded hosts, and if it does, document
that it is API-only with no CLI spelling.

**Step 3 — reclaim the docstring.** `_scope_id_option()`'s *"`func --scope-id X walk`
still works"* (`click_params.py:66`) becomes false. Replace it with the reason the option
is per-command only, and cite the category-error argument rather than restating history.

**Step 4 — tests, one per dispatch mode.** This is the guardrail the repo already demands
for state-addressing flags (`main.py:2075-2081`):
- post-command `--scope-id` is honoured in JOB, GROUP, UNKNOWN, SINGLE_FILE and the
  embedded-app path, **cold cache and warm** — a resumed scope must replay, not mint a new
  id (the exact regression the comment describes);
- pre-command `--scope-id` exits 2 with the move-it message, and does **not** consume the
  job name as its value;
- a plain `@job` still has no `--scope-id` on `--help`.

**Step 5 — docs.** Nothing to change in examples (§3.1). One line in
`docs/cli/workflow.md` stating the flag is per-command, and remove the
`--scope-id` mention from `docs/guides/composition.md:230`'s history note if it implies a
global.

**Cost:** one refusal branch, four signatures, one docstring, five tests. No engine
change, no state change, no format change.

---

## 6. Interaction with the rest of the plan

- **This makes [14](14-resume-deposit-collisions.md)'s D1b easier, not harder.** Once the
  early-parse global is gone, the invocation layer has exactly one spelling family, and
  `--wf-continue` joins `--scope-id` there with no pre-command sibling to explain.
- **It does not conflict with D1.** `resume`/`deposit` stay on the record layer; this
  change is entirely within the invocation layer.
- **It closes the category error doc 07 named and declined.** `_GLOBAL_OPTIONS_ALWAYS_VALUE`
  becomes uniformly about discovery, config and perf — no member touches persisted state.
- **Sequencing:** it belongs with [07 item 5](07-roadmap.md) (`--wf-continue`), not before
  it — ship one invocation-layer change, one set of per-mode tests, one docs pass.

## 7. Answer to the question, in one paragraph

`--scope-id` is **not** redundant with `builtin workflow` — that group cannot advance a
walk at all — but it **is** redundant with the per-command option, which this audit
verified across all five invocation paths, cold and warm. Removal is cheaper than this
folder previously claimed: every generated hint and every doc already teaches the
post-command spelling, so nothing taught changes, and the one historical bug in this area
was the global's own plumbing. Do it as a *refusal* rather than a deletion — keep the flag
recognised so its value is still consumed, and answer it with `exit 2` and the corrected
command — and fix the SINGLE_FILE cwd crash first so all four dispatch modes can actually
be tested.
