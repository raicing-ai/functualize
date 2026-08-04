# Shape Intent: TUI Panel Adjustments for GroupOptions

**Status: specified, not yet implemented**
**Date: 2026-07-23**
**Scope: TUI panels only — GroupOptions data model and CLI parsing are separate work**

## What "GroupOptions" means for the TUI

A `GroupOptions` subclass declares per-group CLI flags that are accepted at a group
level and inherited by every descendant job:

```python
class DeployOptions(GroupOptions, group="deploy"):
    env: Annotated[str, Option("-e", help="Target environment")] = "staging"
    dry_run: Annotated[bool, Option("--dry-run")] = False
```

Invocation places them mid-path: `func deploy --env prod web run --image v1.2`.

Nine fields on a job (`image`, `replicas`) and two group fields on `deploy` (`env`,
`dry_run`) means the job has **11 effective fields**. The TUI treats them as a
unified set — group options are config, not a separate feature.

---

## Core Principle

**Group options ride alongside job config in every panel, distinguished by a
[group] label. They are never segregated into a separate ring, tab, or section.**

The canonical command form is mid-path:

```
func deploy --env prod --dry-run web run --image v1.2
```

The SmartBar must produce, parse, and display this form. Every other panel
derives from the SmartBar's representation.

---

## Implementation directive

**DO NOT immediately edit files.** Instead:

1. Read the current code for each assertion below.
2. Identify which assertions the codebase already satisfies vs. which it does not.
3. Present every **gap** (assertion not satisfied) as a discussion item with the
   exact file, line range, and what would change — wait for approval before editing.
4. Assertions the codebase already satisfies need no edit; just note them as
   pre-existing compliance.

---

## 1. SmartBar — canonical mid-path form (Option 2)

The SmartBar is the source of truth. Every panel reads from or syncs through it.

### 1.1 Render

`_sync_smartbar_from_pending` (and `sync_pending_overrides_to_bar`) must produce
the canonical CLI form with group flags interleaved mid-path, not appended flat
at the end.

| Assertion | Expected behavior |
|---|---|
| `SBR.1` | When a job has group options, the SmartBar text is `deploy --env staging web run --image v1.2`, NOT `deploy.web.run --env staging --image v1.2` |
| `SBR.2` | When no group options are declared for a job's groups, the SmartBar text is unchanged from today (`job.name --flags`) |
| `SBR.3` | Group flags with their default value do not appear in the SmartBar (same rule as job flags — only overrides are rendered) |
| `SBR.4` | Multiple group levels render correctly: `deploy --env prod staging --region us-east-1 web run --image v1.2` |

### 1.2 Parse

`parse_cli_args_to_kwargs` (in `cli_arg_parser.py`) must walk the group trie
(`build_group_option_trie`) to classify tokens — knowing which `--flags` belong
to which group node — and extract group-level values alongside job-level kwargs.

| Assertion | Expected behavior |
|---|---|
| `SBP.1` | `parse_cli_args_to_kwargs` returns both `kwargs` (job-level) and `group_option_values` (group-level) in its result |
| `SBP.2` | `deploy --env prod web run --image v1.2` parses to `kwargs={"image": "v1.2"}`, `group_option_values={"env": "prod"}` |
| `SBP.3` | `deploy --dry-run web run --image v1.2` parses `group_option_values={"dry_run": True}` |
| `SBP.4` | Group flags at wrong positions produce clear errors (e.g. `deploy web run --env prod` when `--env` is a deploy-level flag) |

### 1.3 Reconcile

The overrides round-trip (`sync_bar_to_overrides` / `sync_overrides_to_bar`) must
extract and inject group-level overrides from/to mid-path positions.

| Assertion | Expected behavior |
|---|---|
| `SBO.1` | Editing `[deploy] --env` in the config table → `sync_pending_overrides_to_bar` produces updated text at the correct mid-path position |
| `SBO.2` | Changing SmartBar text → `sync_bar_to_overrides` correctly separates group-level from job-level overrides |
| `SBO.3` | Reset (`r` on a group field row) → the group-level `--flag` is removed from mid-path, not left orphaned |

---

## 2. Config Table — `[group]` prefix, fully editable

Group option fields appear inline in the same DataTable as job fields, with a
`[group_path]` prefix on the name column. They are **fully editable** via `i`
— editing a group field updates the SmartBar at its mid-path position.

### 2.1 Data model

| Assertion | Expected behavior |
|---|---|
| `CTD.1` | `FieldDef` gains an optional `group_path: str | None` attribute (default `None` for job-level fields) |
| `CTD.2` | `build_command_panels` / `build_pending_execution` include group option fields in the unified `FieldDef` list sent to `ConfigTablePanel.set_fields()` |
| `CTD.3` | Group field rows appear AFTER job field rows in the table (group hierarchy above the leaf; leaf fields first is more natural scanning) — OR before, as long as the ordering is consistent and documented |

### 2.2 Display

| Assertion | Expected behavior |
|---|---|
| `CTA.1` | `_format_field_cells` renders a group field's name as `[deploy] --env` when `field.group_path == "deploy"` |
| `CTA.2` | A job-level field's name is unchanged: `--image` |
| `CTA.3` | When a job belongs to multiple nested groups, the prefix shows the full chain: `[deploy.staging] --region` |
| `CTA.4` | The `[group]` prefix is visually distinct from the flag name — dimmed or colored differently, not just concatenated text |

### 2.3 Edit flow

| Assertion | Expected behavior |
|---|---|
| `CTE.1` | Pressing `i` on a `[deploy] --env` row enters INSERT mode (same as any field) |
| `CTE.2` | Committing the edit updates the SmartBar to `deploy --env <new_value> web run --image v1.2` |
| `CTE.3` | Pressing `r` on a `[deploy] --env` row clears the override and removes `--env` from the SmartBar |
| `CTE.4` | `get_available_actions` shows the same hints for group rows as job rows (`i` edit, `r` reset, Enter detail) |

---

## 3. Config Files — zero structural change

Grouped jobs already use the group path as their TOML section. `[deploy]` is
the section for all jobs under `deploy`. Group options declared on `deploy` are
fields in that section, same as job config fields.

| Assertion | Expected behavior |
|---|---|
| `CF.1` | `discover_config_files` receives the unified field list (job + group fields). Group option field names appear in the "Fields" column naturally — no code change needed |
| `CF.2` | The section shown for a file is `[deploy]` (the group path), which is correct — no change needed |
| `CF.3` | Status column is unchanged — a file contributing group fields is still `★ active` |

**Expected outcome:** This panel requires zero code changes. Verify by audit only.

---

## 4. Diff — group entries with `[group]` prefix

### 4.1 Data model

| Assertion | Expected behavior |
|---|---|
| `DFD.1` | `PendingExecution` gains a `group_option_values: dict[str, Any]` field (default `{}`) |
| `DFD.2` | `ConfigSnapshot` records include group option values in their stored field dict |
| `DFD.3` | `compute_config_diff` includes group option value differences as `ConfigDiffEntry` rows with `group_path` set |

### 4.2 Display

| Assertion | Expected behavior |
|---|---|
| `DFA.1` | A group field diff entry renders as `[deploy] --env` in the field name column (same prefix convention as the config table) |
| `DFA.2` | Group diff entries appear alongside job diff entries — they are not segregated into a separate section |
| `DFA.3` | `show_diff` and `refresh_diff_only` accept and render group entries without API changes |

---

## 5. Pre-flight — canonical mid-path command

The pre-flight summary renders the command as the user would type it on the CLI.

### 5.1 Display

| Assertion | Expected behavior |
|---|---|
| `PF.1` | `build_preflight_lines` renders `deploy --env prod --dry-run web run --image v1.2` |
| `PF.2` | Group flags appear at their mid-path position, between their owning group name and the next sub-group/leaf |
| `PF.3` | When no group options are declared, the pre-flight is unchanged from today |
| `PF.4` | The pre-flight walks the same group trie the SmartBar uses — shared logic, not duplicated |

---

## 6. Job Browser — spaces, not dots

The job browser displays fully qualified names with spaces (CLI form), not dots
(internal wire format).

| Assertion | Expected behavior |
|---|---|
| `JB.1` | `_populate_table` renders `deploy web run` instead of `deploy.web.run` |
| `JB.2` | `action_select_job` still posts `JobSelected(job.name)` — the original dotted name. The SmartBar receives the dotted name and resolves it normally. |
| `JB.3` | `apply_filter` normalizes spaces to dots internally: user types `deploy web` → filter matches `deploy.web.run` by substring. Both the query and the target are normalized so `deploy-web` and `deploy.web` also match. |
| `JB.4` | `_derive_source_label` is unchanged — it reads from the descriptor, not the display name |

---

## Cross-cutting invariants

| Invariant | Description |
|---|---|
| `X.1` | The SmartBar text, pre-flight text, and CLI invocation are byte-identical for the same config state |
| `X.2` | The group trie (`build_group_option_trie` in `cli_arg_parser.py`) is the single source of truth for which groups declare which flags — no panel re-derives this |
| `X.3` | A job with zero group options declarations anywhere in its group chain behaves identically to today — no panel changes are visible |
| `X.4` | The `[group]` prefix convention (`[deploy] --env`) is consistent across the config table, diff view, and any drill-down views |
| `X.5` | No panel introduces a "Group Options" ring, tab, or separate section — all group fields are inline with job fields |

---

## Verification checklist for the implementing agent

Before writing any code, audit each assertion against the current codebase:

- `SBR.1–4`: `src/functualize/_cli/tui/sync.py` (render path), `src/functualize/_cli/tui/app.py` (`_sync_smartbar_from_pending`)
- `SBP.1–4`: `src/functualize/_cli/tui/cli_arg_parser.py`
- `SBO.1–3`: `src/functualize/_cli/tui/sync.py`, `src/functualize/_cli/tui/app.py`
- `CTD.1–3`: `src/functualize/_cli/tui/panels/config_table.py` (`FieldDef`), `src/functualize/_cli/tui/chain_resolution.py` (`build_command_panels`)
- `CTA.1–4`: `src/functualize/_cli/tui/panels/config_table.py` (`_format_field_cells`)
- `CTE.1–4`: `src/functualize/_cli/tui/panels/config_table.py`, `src/functualize/_cli/tui/app.py` (event handlers)
- `CF.1–3`: `src/functualize/_cli/tui/panels/config_files.py` (`discover_config_files`)
- `DFD.1–3`: `src/functualize/_cli/data/pending_execution.py`, `src/functualize/_cli/data/config_snapshot_store.py`, `src/functualize/_cli/tui/config_diff.py`
- `DFA.1–3`: `src/functualize/_cli/tui/diff_view_widget.py`, `src/functualize/_cli/tui/config_diff.py`
- `PF.1–4`: `src/functualize/_cli/tui/preflight_summary.py`
- `JB.1–4`: `src/functualize/_cli/tui/panels/job_browser.py`

**Report format**: For each assertion, state `PASS` (code already satisfies, no change) or `GAP` (code does not satisfy, with exact file:line and proposed change). Group GAPs by file. Wait for approval before editing.
