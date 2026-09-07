# Plan

## Approach

One export, one docs correction, one guide.

1. `functualize/plugin/__init__.py`: import `StaticProvider` from
   `_discovery/providers.py`, add it to `__all__`.
2. A test that builds a provider using **only public imports**, registers it
   through `add_job_provider`, and asserts the jobs carry their parameters —
   the property that made the private import load-bearing rather than
   cosmetic.
3. `docs/api/discovery.md`: move `StaticProvider` out of the internal list.
4. Land `subjects.md` from the design corpus, adjusted: delete the
   private-import warning, and re-verify the example against the current code
   rather than against 0.2.3.

## Files

| File | Change |
|---|---|
| `src/functualize/plugin/__init__.py` | the export |
| `docs/api/discovery.md` | correct the internal-location note |
| `docs/guides/subjects.md` | new |
| `docs/guides/index.md`, `mkdocs.yml` | one bullet, one nav line |
| `tests/plugins/test_public_provider_seam.py` | new |

## Risks

**A public name is permanent.** Settled in the spec: promote the existing
shape, as ADR-017 did.

**The guide was written against 0.2.3 and two PRs have landed since.** Its
example is re-run against the current build rather than trusted — the same
corpus already carried one stale claim (a docs page it said was wrong had been
fixed by PR #28). Anything that does not reproduce is corrected in the guide,
not asserted.

**`mkdocs --strict` fails on a dangling link**, which is the gate that catches
a guide whose cross-references were written against a different directory.
