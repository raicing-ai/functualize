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

## C2 — the collision record is carried on the app, read by attribute

`register_descriptors` records collisions it detects. `_cli/info.py` reads them
the way it already reads provider failures and group options: by attribute
access, never by import, because `_cli` may not import `_discovery` or `_app`.

```python
# _app/boot.py — set during registration
app._job_name_collisions: list[DiscoveryFailure]

# _cli/info.py — read defensively, same shape as the existing provider read
for failure in getattr(app, "_job_name_collisions", ()) or ():
    failures.append(failure.as_dict())
```

An app field is current for this finding, unlike for scan failures: collisions
are detected while registering an already-materialized descriptor list, so
boot has the answer by the time the field is read. That difference is why the
existing provider read exists and why this one may be a field — the comment in
`discovery_failures()` says a boot-time field would be stale for *scan*
failures, which remains true and unchanged.

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
