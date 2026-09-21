# FUN-25 — Contracts

**Status:** pre-loaded scaffold.

## What this ticket changes at a boundary

Fill in: public signatures, payloads, and declared surfaces that change. An interface
that changes without appearing here is the defect this file exists to prevent.

## Public API surface

`tests/test_public_api_surface.py` enforces the exported surface. Any addition or removal
is a deliberate decision, not a side effect — record it here with its reasoning.

Relevant today: `FreshStore`, `ScopeStore`, `RunStore` and `ShellHistoryStore` are public
in `functualize.app.utils.__all__`, while `StoreSubstrate` is public **nowhere** — and
`docs/guides/workflows.md:386` tells plugin authors to import it from a private path. The
design recommends deprecating `ScopeStore` and `RunStore` for one minor version and
exporting `StoreSubstrate` and `Stored` from `functualize.plugin`.

## Import-linter contracts

Seven contracts in `pyproject.toml` decide whether an AFTER shape is even legal. Run:

```bash
uv run lint-imports
```

The engine-owned design adds **no layer**, so these should pass unchanged. If your change
needs a contract edited, that is a finding worth raising before you edit it.

## Backward compatibility

State explicitly what breaks and for whom. "Nothing breaks" is a claim that needs the
command that would falsify it.
