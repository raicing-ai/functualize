# Layer dependency contract

**Source of truth: `[tool.importlinter]` in `pyproject.toml`.** Read it there
rather than trusting any summary, including this one. Check with:

```bash
uv run lint-imports          # 317 files, 815 dependencies, 5 contracts
```

`root_package = "functualize"`, and `exclude_type_checking_imports = true` — so
imports inside `if TYPE_CHECKING:` blocks are invisible to every contract below.

## The five enforced contracts

| Contract | Type | Effect |
|---|---|---|
| `Peer layers are independent` | independence | `_discovery`, `_config`, `_engine`, `_plugins`, **`_gate`** may not import one another |
| `Primitives import nothing internal` | forbidden | `_primitives` may reach `_types` and stdlib only |
| `Types import nothing internal` | forbidden | `_types` may reach stdlib only — not even `_primitives` |
| `Internal never imports public` | forbidden | no `_`-prefixed package may import `app`, `job`, `plugin`, `types`, `testing` or `workflow` |
| `_cli uses public API only` | forbidden | `_cli` may not import any `_`-prefixed package |

There are **five** peer layers, not four. `_gate` (6 files:
`_context`, `_registry`, `_resolver`, `_strategy`) is in the independence
contract and is the one most often forgotten.

The public surface is **six** packages: `app`, `job`, `plugin`, `types`,
`testing`, `workflow`.

## What is NOT enforced

`contributor/`-level prose (and `docs/guides/architecture.md`'s "Layer rules
summarized" table) claims `_events` must not import `_discovery` through
`_cli`. **No contract enforces that** — `_events` never appears as a
`source_module` in a contract forbidding a peer layer.

And it is violated in practice: `src/functualize/_events/adapter.py:88` does a
real runtime `from functualize._config._emit import set_event_sink`, with a
second at line 102. `lint-imports` reports 5 kept / 0 broken, so this is
permitted, not a latent failure.

Treat "`_events` is downstream of the peer layers" as a design intention that
is documented but unpoliced. Do not assume the linter will catch a regression
there.

## Diagram

`docs/diagrams/layer-dependencies.html`
(spec: `contributor/architecture/diagrams/layer-dependencies.architecture.json`)

The diagram draws the enforced contracts. Where it and `pyproject.toml`
disagree, `pyproject.toml` wins and the diagram is the bug.
