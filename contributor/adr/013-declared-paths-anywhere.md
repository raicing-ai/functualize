# ADR-013: Declared paths may live anywhere, and are recorded as written

**Status**: accepted
**Date**: 2026-08-30
**Deciders**: Hakim (decision D-2), agent

## Context

`Fingerprint.sources` entries were globbed and then filtered:

```python
for match in base.glob(pattern):
    if not match.is_file():
        continue
    try:
        relative = match.resolve().relative_to(base)
    except ValueError:
        continue  # outside the project root
    found.add(relative.as_posix())
```

The glob found the file; the containment check threw it away. Three declared
forms were therefore impossible:

| Form | What happened |
|---|---|
| `"/srv/checkouts/**/*.tf"` | dropped by the containment check |
| `"../repos/**/*.tf"` | `Path.glob` does not match `..` segments at all |
| a pattern reaching through a symlinked directory | globbed, then discarded — `resolve()` follows the symlink to a real location outside `base` |

**The restriction was never a design decision.** It was in `expand_sources`
from the `v0.1.0` commit, justified by one docstring line — *"records must stay
project-relative"* — which is a statement about the storage format, not about
safety. It is not a boundary of any kind: a job body can already read any file
on the machine, and `Fingerprint` only stats and hashes. And it was applied
**inconsistently**: absolute `generates` paths worked all along, because
`Path(base) / "/abs"` yields `/abs`.

The domain this framework is modelled on does nothing else. Every unit in the
reference pipeline reaches its checkouts through `${REPO_<ID>}` paths that point
outside the unit, so the single most important input declaration in the target
domain was undeclarable.

It surfaced through the D5 refusal — a job pointing `sources` through a symlink
answered `Refused: declared sources resolved to no files`, exit 3. That is the
refusal working exactly as designed, on a case nobody wrote it for.

## Decision

**Remove the containment rule entirely, from `sources` and `generates` alike.
Record each path as the declaration wrote it.**

| Declared | Recorded key |
|---|---|
| relative (`src/**/*.py`) | the match relative to the root, computed **without `resolve()`** |
| relative with `..` (`../repos/**/*.tf`) | the relative path including its `..` segments |
| absolute (`/srv/**/*.tf`) | the absolute path of the match |

Dropping `resolve()` is what fixes the symlink case on its own: a file reached
through a symlinked subtree keeps the name the declaration used.

## Consequences

### Positive

- The declaration a unit actually needs is expressible. Absolute, `../` and
  symlinked inputs are all fingerprinted and all make the job fresh on a second
  run.
- The `sources`/`generates` asymmetry is gone — absolute `generates` worked,
  absolute `sources` did not, for no stated reason.
- **No existing record key changes.** Every key in the wild came from an
  in-project relative declaration whose match resolved inside the root, and that
  is byte-identical under the new rule. This is asserted, not assumed:
  `tests/pipeline/test_declared_paths_anywhere.py::test_an_in_project_key_is_byte_identical_to_before`.

### Negative

- **A record keyed by an absolute path does not match on another machine.**
  That machine re-runs the job once and writes its own key. Nothing breaks; the
  work is simply not shared. This is the accepted trade, and it is stated in
  `Fingerprint`'s docstring rather than left for someone to discover.
- A file matched by both an absolute and a relative pattern is recorded twice,
  under two keys. Benign — it is hashed twice and both entries agree — but it is
  now possible.
- Three walkers instead of one: `Path.glob` cannot match `..`, and
  `Path.relative_to` cannot produce it, so the `..` and absolute forms route
  through `glob.iglob` and `os.path.relpath`.

### Neutral

- The D5 refusal is untouched. A job whose declared sources genuinely resolve to
  nothing still refuses with exit 3. This makes the refusal **rarer and more
  honest** — several patterns that triggered it were legal declarations being
  silently discarded — without weakening it.
- `build_source_map` needed no change: `root / key` is correct for all three
  forms.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| `Fingerprint(sources=..., allow_external=True)` | keeps the old default; makes the escape explicit | an opt-in for something that was never a hazard; a second thing to know; still owes an answer for what the record key is | Ruled out by D-2. There is nothing to opt out of — the restriction protected nothing |
| Rewrite external paths into machine-independent labels (`${REPO_A}/main.tf`) | records stay portable across machines | requires a label registry, a resolution order, and a new failure mode when a label is undefined; invents a small path language | Ruled out by D-2. The cross-machine miss is one extra run, which is cheaper than the mechanism that avoids it |
| Compare the *unresolved* match against `base` and keep containment | a smaller change; fixes the symlink case only | leaves absolute and `../` undeclarable, which is the case the domain actually needs | Fixes the symptom the audit found first, not the capability gap behind it |

## References

- `examples/standalone/composition_lab/` — the pipeline this was found in;
  `demo.sh` walks it and `tests/test_composition_lab_e2e.py` asserts it on
  both surfaces
- `src/functualize/_primitives/fingerprint.py` — `_iter_matches`, `expand_sources`
- `tests/pipeline/test_declared_paths_anywhere.py`
