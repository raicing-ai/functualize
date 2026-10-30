# ADR-040: An Unknown Settings Key Is Reported Where Configuration Is Inspected, Never Fatal

**Status**: accepted
**Date**: 2026-10-30
**Deciders**: maintainer, through the approved shape of the unknown-key check
(warn and continue; report on the inspection surfaces; check only declared
places) and the decision to remove the global file's own warning.

## Context

A key in a settings document that no setting declares used to be accepted in
silence. `func builtin config path` reported such a file as *used*, and a typo
such as `roots = true` or `[cli] outptu` looked exactly like a setting with no
effect. Only the global file had a check, and it was a reader of its own: it
printed a warning on every run, covered five sections, and silently dropped
`[plugins]`, `[shell]` and every unknown top-level key.

[ADR-039](039-a-setting-is-declared-once.md) gives the check the one thing it
needs: a single declaration that answers "is this key known, here". What
remained was a set of choices about the check itself:

- does an unknown key fail the run, or only get named;
- where is it named;
- which tables are checked at all;
- when does a near miss earn a suggestion.

## Decision

An unknown key is a finding, never an error, and it is reported where a user
inspects configuration, not on the path that runs jobs.

- **Warn and continue.** The check changes no exit code and never drops a key
  that would otherwise apply.
- **Two surfaces, no startup warning.**
  - `func builtin config path` lists the resolution layers and appends
    ` — unknown key "<dotted-key>"[ (did you mean "<dotted-key>"?)]` to each
    file that has findings, in document order.
  - `func builtin info --json` (and `info all --json`) always carries
    `config.unknown_keys`, a list of `{"file", "key", "suggestion"}`: `[]` when
    there are none, otherwise in layer precedence order (nearest project file
    first, global last), then document order.

  There is no stderr warning on an ordinary run. The global file's separate
  warning is gone, and the global file is reported like every other layer.
- **Off the run path.** A warm `func <job>` does not import the check module,
  and stays inside the startup budget.
- **Checked means declared places.** The files checked are exactly the layers
  resolution uses: the upward walk, stopped by `root = true`, with the global
  file last. In `pyproject.toml` only `[tool.functualize]` is checked. A key is
  known when the active declaration accepts it in that place. The check covers
  non-table entries at the top level and inside declared sections. It skips
  free-form `map` sections such as `[aliases]`, unknown tables (which may be
  job sections) and tables nested in sections.
- **One suggestion, same scope.** A finding suggests the best match among the
  keys known in the same scope, when that match scores at least 0.6
  (`difflib.SequenceMatcher` ratio). Otherwise its suggestion is `null`.
- **Known means the active declaration.** An app that extends the declaration
  gets its own keys treated as known. The check keeps no word list of its own.

The PEP 723 `[tool.functualize]` table in a single-file script is its own small
document kind, with `job` as its only key. It keeps its existing behaviour on
the same principle: an unknown key, including the retired `skill`, warns,
naming the key and the known set, and the script runs.

## Consequences

### Positive

- A typo is visible where users look for configuration, without costing a job
  run anything or breaking a CI job that carries a key a newer release
  understands.
- `info --json` gives tooling a machine-readable field, so an editor or CI step
  can choose to enforce what the core deliberately does not.
- One code path reports every layer, so the global file no longer has its own
  rules.

### Negative

- A user who never runs `config path` or `info` never learns of a typo. That is
  the cost of keeping the run path silent and fast.
- The check is only as right as the declaration. A key the runtime honours but
  the declaration does not place where it is written is reported as unknown.
  This is a declaration bug, and it is visible precisely because of this check.

### Neutral

- Values are not validated (types, enum members). Unknown tables are not
  reported, because they may be job sections. Parameters inside a job section
  are not checked. There is no `--json` flag on `config path` and no strict
  mode. Each of these would be a separate decision.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Fail on an unknown key (strict by default, or behind a strict flag) | A typo cannot be missed | Breaks runs, and CI jobs, over a key that may only be newer than the installed release; turns a harmless leftover into an outage | The penalty is out of proportion to the defect; tooling can enforce on `config.unknown_keys` if a project wants strictness |
| Warn on stderr at startup | Seen without asking | Noise on every run; puts the check on the hot path the startup budget protects; the old global-file warning showed both costs | Rejected in the shape; the global warning was removed for the same reason |
| Also report unknown tables | Catches a misspelled section name | A table that is not a declared section may legitimately be a job's own config section | Would report correct job configuration as an error |
