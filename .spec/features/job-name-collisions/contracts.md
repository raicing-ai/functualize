# Contracts

**No public signature changes.** Everything here is internal (`_app/boot.py`,
`_discovery/registry.py`, `_cli/info.py`) or an addition to an existing
published payload. Stated explicitly because a fix with no new API is a
different risk from one that adds a seam: nothing to deprecate, no host to
migrate.

## C1 — `discovery_failures` gains a new `error_type` value

`builtin info --json`'s `discovery_failures` is a list of records with fixed
keys (`module`, `path`, `error_type`, `message`). A collision is reported as
one of those, with:

| Key | Value for a collision |
|---|---|
| `module` | the losing claimant's module stem (`"wheels"`, `"a"`) |
| `path` | absolute path to the losing claimant's file |
| `error_type` | `"JobNameCollision"` — new value, existing key |
| `message` | names both claimants, the canonical name, and which one is unavailable |

Consumers that switch on `error_type` already have to tolerate unknown values:
`"SyntaxError"` is documented as the marker separating a parse failure from an
import failure, and every other value is an arbitrary exception class name. So
this widens a set that was never closed.

**No key is added or removed, and the list stays always-present** — `[]` when
empty, the rule `config` and `skills` follow.

## C2 — the collision record is carried where the reader already looks

**Revised during execution.** The plan expected an app field
(`app._job_name_collisions`). Two of the three detection sites turned out to
have a better home, and the third needs no new surface at all:

| Detection site | Where the record lives | Reaches `builtin info` by |
|---|---|---|
| cached provider's name index | the provider's own `discovery_failures` | the existing per-provider read — **no change to `info.py` needed** |
| resolution pipeline (providers built by hand) | `ResolutionPipeline.collisions` | one new attribute read off the pipeline |
| eager registry scan | nowhere yet — logged only | nothing; disclosed as TRANSITIONAL, resolved by `eager-boot-provider` |

```python
# _cli/info.py — the same attribute-access shape as the existing provider read
for collision in getattr(pipeline, "collisions", ()) or ():
    ...
```

`_cli` may not import `_discovery` or `_app` (constitution), so both reads are
by attribute and neither adds an import edge. `lint-imports` reports 5 kept, 0
broken.

No app field is added. The one the plan proposed would have been a third place
to keep in sync for no gain.

## C3 — the eager path's `ValueError` is withdrawn

`_discovery/registry.py`'s `scan_and_register_headless` raises
`ValueError("Two jobs normalize to the same name ...")` today. After this
change it does not raise; the collision is reported and the claimant skipped.

This is a behavior change for a library-mode host constructing
`FunctualizeApp(..., JobSources(lazy=False))` and relying on the exception. No
such caller exists in `src/`, `tests/`, `plugins/` or `examples/` — the only
consumers are the tests that pin the raise, which this feature rewrites to pin
the reported outcome instead.

`register_dynamic_job`'s own `ValueError` for an already-registered name is
untouched: that is a caller error at an explicit API call, not a scan finding.
