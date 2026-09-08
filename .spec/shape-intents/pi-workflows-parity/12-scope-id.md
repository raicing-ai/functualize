# 12 · Removing `--scope-id`

Audited empirically across every dispatch mode, cold cache and warm, at `78d9ff4`. The
replacement is [05 §2.2](05-target-surface.md) — `--wf-resume [id]`.

---

## 1. The two claims, tested

### 1.1 "Redundant with `builtin workflow`" — false

`func builtin workflow` has **no verb that advances a walk** today. `list` and `state`
read, `cancel` marks, and `resume` deposits — *"Accepting input does not run the
workflow"* (`builtins.py:914-918`). So `--scope-id` duplicates nothing there; it **is**
the advance surface, in its entirety.

That is the same finding as [01 §C.6](01-current-state.md): the advance operation has one
spelling and no name.

### 1.2 "Redundant with the per-command option" — true, and proven

Every dispatch mode that receives `scope_id` (`main.py:2001-2091` — SINGLE_FILE, JOB,
GROUP, UNKNOWN; BARE and BUILTIN run no job) plus the embedded-app path, tested for the
**post-command** option:

| Mode | How exercised | Cold | Warm |
|---|---|---|---|
| JOB | `func trip-planner --help` (ungrouped `@workflow`) | ✅ | ✅ |
| GROUP | `func lab release --help` | ✅ | ✅ |
| UNKNOWN | job name ≠ file stem, cheap enumeration misses it | ✅ | ✅ |
| SINGLE_FILE | `func ../sf/weather.py trip_planner --help` | ✅ | ✅ |
| Embedded app | `python main.py lab release --help` | ✅ | ✅ |

Warm caches were populated with a real run first (`--help` writes no cache). Sample:

```
$ func lab release --help
Options:
  --scope-id TEXT  Resume the named workflow scope instead of starting a fresh one.
```

Gating holds — a plain `@job` does not carry it:

```
$ func forecast --help
Options:
  --city TEXT     City to check
  --days INTEGER  Days to forecast
  --help                            ← no --scope-id
```

**Per-command coverage is complete.**

## 2. Why the "keep it" case does not survive

The prior study's doc 07 gave four arguments. Tested, three dissolve.

| Argument | Audited |
|---|---|
| *"the only spelling guaranteed on all dispatch modes"* | **False** — §1.2 |
| *"positional ergonomics: `func --scope-id X release-pipeline` reads as operate-on-scope-X"* | Taste, and the weaker placement. `_scope_id_option`'s own docstring picks post-command deliberately: *"that is where a reader looks: the audit that found this got the pre-command position wrong twice."* |
| *"script stability: every deposit result, doc page and skill teaches `--scope-id`"* | **True about the flag, false about the position** — §2.1 |
| *"zero plumbing risk"* | **Inverted.** The cold-cache bug at `main.py:2075-2081` was a defect in the **global's** threading through UNKNOWN mode: *"Omitting them made `--scope-id` silently ignored on a cold discovery cache."* The global is the thing with a history of vanishing. |

### 2.1 Nothing that is taught would change

Exhaustive grep over `docs/`, `skills/` and both hint-emitting modules. Every taught
spelling is **post-command**:

| Site | Emits |
|---|---|
| `app/_workflow_resume.py:95-101` | `<entry> <workflow> --scope-id <scope>` |
| `app/adapters/click_params.py:956` | `{program} {command_path} --scope-id {scope}` |
| `docs/cli/workflow.md:72` | `func release --scope-id rel-1` |
| `docs/guides/composition.md:211` | `func lab release --scope-id f81eb2d5` |

The pre-command form appears in exactly **one** place in the repository: the
`_scope_id_option()` docstring noting that `func --scope-id X walk` "still works"
(`click_params.py:67`).

### 2.2 What removal simplifies

- `_GLOBAL_OPTIONS_ALWAYS_VALUE` loses its only member that addresses **persisted state**
  rather than discovery/config/perf — a category error a new user cannot see, since
  `func --help` lists it among global config flags where it silently does nothing on a
  non-workflow job.
- Four handler signatures and four call sites lose a parameter
  (`main.py:1160, 1258, 1469, 1536, 1654` and `:2009, 2032, 2052, 2091`).
- `click_params.py:1095` — `scope_id = kwargs.pop(_SCOPE_ID_PARAM, None) or workflow_scope_id`
  — loses its precedence rule, and with it the documented "per-command wins over
  pre-command" interaction that has to be explained and tested.

## 3. Deletion, not a refusal

`detect_mode`'s scan (`dispatch.py:199-235`) skips boolean flags, always-value flags,
optional-value flags, `--opt=value` forms and short options. A bare `--unknown-flag`
matches **none** of those and falls through to the `break` at `:253` — so **the flag
itself becomes the first positional** and its value is never examined:

```
$ func --not-a-flag somevalue trip-planner --help
Error: Unknown command 'not-a-flag'.
Run 'func' to see all available commands.
$ echo $?
1
```

Applied to the real flag: `Error: Unknown command 'scope-id'`, exit 1. Confusing, but
**loud, non-zero, and incapable of running the wrong thing** — the stray scope id can
never be mistaken for a job name because the scan stops before it.

A refusal branch (keep the flag recognised, answer with exit 2 and the corrected form)
would produce a better message. Its only justification is courtesy to muscle memory, and
with no users to spare it is not worth the code: `_GLOBAL_OPTIONS_ALWAYS_VALUE` exists so
`detect_mode` can skip a flag *and its value* while hunting the first positional, and the
correct spelling is post-command, where the scan stops before reaching the flag. **The
recognition set only matters for the invocation that is now invalid.**

## 4. A prerequisite defect

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

Directory discovery registers `forecast` from `weather.py`, then
`_register_single_file_peers` (`main.py:1524`) registers it again and
`register_dynamic_job` (`_app/impl.py:700`) refuses. The common case — `cd` into a
project and run a file in it — raises an unhandled `ValueError` with a traceback rather
than an error envelope.

It matters here because SINGLE_FILE is the mode whose replacement coverage is hardest to
claim, and it is the mode that is broken. **Fix it before removing the per-command
option**, or scope this change to exclude it and file it separately.

## 5. The removal, step by step

**Step 0 — prerequisite.** Fix §4, or file it and exclude SINGLE_FILE from this change.

**Step 1 — delete the early-parse flag.** Remove `"--scope-id"` from
`_GLOBAL_OPTIONS_ALWAYS_VALUE` (`dispatch.py:79`); drop `scope_id` from `GlobalOptions`
(`:320`, `:524`, `:547`) and `_assign_option` (`:624-625`); drop it from the four handler
signatures and call sites in `main.py`.

**Step 2 — decide the programmatic seam.** `create_job_click_command`'s
`workflow_scope_id` parameter and the `app_ref._workflow_scope_id` fallback
(`click_params.py:1095-1097`) become dead. Decide deliberately whether the app-level
attribute stays as an entry point for embedded hosts; if it does, document it as API-only
with no CLI spelling.

**Step 3 — replace the per-command option with `--wf-resume`.** Per
[05 §2.1-2.2](05-target-surface.md). `_scope_id_option()` is retired; the `--wf-*` family
takes its two injection points (`click_params.py:1289`, `lazy_command.py:168`).

**Step 4 — reclaim the docstring.** `_scope_id_option()`'s *"`func --scope-id X walk`
still works"* becomes false. Replace it with the reason the flags are per-command only.

**Step 5 — tests, one per dispatch mode.** The guardrail the repo already demands for
state-addressing flags (`main.py:2075-2081`):

- post-command `--wf-resume` is honoured in JOB, GROUP, UNKNOWN, SINGLE_FILE and the
  embedded-app path, **cold cache and warm** — a resumed scope must replay, not mint a
  new id, which is the exact regression that comment describes;
- pre-command `--scope-id` exits non-zero and does **not** consume the job name as its
  value;
- `--wf-resume` with an unknown id **errors** rather than creating a scope
  ([05 §2.2](05-target-surface.md));
- a plain `@job` carries no `--wf-*` flags on `--help`.

**Step 6 — docs.** Nothing changes in examples (§2.1 — they all teach post-command); the
flag name changes. One line in `docs/cli/workflow.md` stating the flags are per-command.

**Cost:** four signatures, one docstring, the `--wf-*` family from
[05](05-target-surface.md), and the per-mode test matrix. No engine change, no state
change, no format change.
