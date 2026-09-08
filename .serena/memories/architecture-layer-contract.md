# Layer dependency contract

Imports travel in one direction only. This is enforced mechanically by
import-linter (`.import_linter_cache/` in the toolchain), not by convention.

| Layer | May import | Must NOT import |
|---|---|---|
| `_types/` | stdlib only | any `_`-prefixed package |
| `_primitives/` | `_types/` | `_events` … `_cli` |
| `_events/` | `_types/`, `_primitives/` | `_discovery` … `_cli` |
| `_discovery/`, `_config/`, `_engine/`, `_plugins/` | `_types/`, `_primitives/`, `_events/` | **each other**, `_app`, `_cli` |
| `_app/` | all internal layers | `_cli`, any public folder |
| `_cli/` | public folders only | any `_`-prefixed package |

The peer rule is the one most easily broken by accident: `_discovery`,
`_config`, `_engine` and `_plugins` are siblings. If you need them to
cooperate, wire it in `_app/` (the composition root) — that is what it is for.

Drawn as a diagram: `docs/diagrams/layer-dependencies.html`
(spec: `contributor/architecture/diagrams/layer-dependencies.architecture.json`)
