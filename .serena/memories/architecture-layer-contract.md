# Layer dependency contract

**Source of truth: `[tool.importlinter]` in `pyproject.toml`.** Read it there
rather than trusting any summary, including this one. Check with:

```bash
uv run lint-imports          # 318 files, 816 dependencies, 6 contracts
```

`root_package = "functualize"`, and `exclude_type_checking_imports = true` — so
imports inside `if TYPE_CHECKING:` blocks are invisible to every contract below.

## The six enforced contracts

| Contract | Type | Effect |
|---|---|---|
| `Peer layers are independent` | independence | `_discovery`, `_config`, `_engine`, `_plugins`, **`_gate`** may not import one another |
| `Events depends on foundation only` | forbidden | `_events` may reach `_types` and `_primitives` only |
| `Primitives import nothing internal` | forbidden | `_primitives` may reach `_types` and stdlib only |
| `Types import nothing internal` | forbidden | `_types` may reach stdlib only — not even `_primitives` |
| `Internal never imports public` | forbidden | no `_`-prefixed package may import `app`, `job`, `plugin`, `types`, `testing` or `workflow` |
| `_cli uses public API only` | forbidden | `_cli` may not import any `_`-prefixed package |

There are **five** peer layers, not four. `_gate` (6 files:
`_context`, `_registry`, `_resolver`, `_strategy`) is in the independence
contract and is the one most often forgotten.

The public surface is **six** packages: `app`, `job`, `plugin`, `types`,
`testing`, `workflow`.

## The remaining blind spot

`exclude_type_checking_imports = true` means imports inside
`if TYPE_CHECKING:` are invisible to every contract. `_config/chain.py:22` and
`_config/sources.py:35` import `EventBus` from `_events` that way, so
`_config -> _events` is ungoverned. Flipping the flag has not been measured and
would likely break several contracts at once; treat that direction as
unenforced until someone does the work.

History worth knowing: until the `Events depends on foundation only` contract
was added, `_events/adapter.py` imported `_config._emit` at runtime — a
constitution violation that no contract caught. The wiring now lives in
`_app/event_wiring.py`. See `.spec/features/events-layer-independence/`.

## Diagram

`docs/diagrams/layer-dependencies.html`
(spec: `contributor/architecture/diagrams/layer-dependencies.architecture.json`)

The diagram draws the enforced contracts. Where it and `pyproject.toml`
disagree, `pyproject.toml` wins and the diagram is the bug.
