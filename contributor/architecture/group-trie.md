# GroupTrie — Single Namespace Authority

**Audience:** contributors working on CLI dispatch, TUI navigation, MCP metadata,
or plugin command registration.
**Status:** shipped. See [ADR-004](../adr/004-cli-shell-convergence.md).

## 1. What It Is

`GroupTrie` (in `_types/naming.py`) is the single source of truth for the job namespace
shape — the tree of groups, jobs, and plugin commands. It replaces:

- A flat set of dotted prefix strings
- A greedy string-matching loop in dispatch
- A re-implemented ancestor walk in the TUI
- Duplicated `_is_valid_job_group()` in registry and sync

The trie sits at the top of the layer order (in `_types/`, not `_discovery/`), making it
importable by all five consumers without peer-layer violations: CLI dispatch (`_cli/`),
TUI (`_cli/tui/`), engine (`_engine/`), MCP metadata (`plugins/functualize-mcp/`), and
the CLI **adapter** (`app/adapters/cli.py`), which mirrors the trie into a click command
tree and hangs each declaring group's options on the matching node (ADR-009 decision 11).

That fifth consumer is easy to forget — it was, for the whole of S6a/S6b — because it
does not *walk* the trie at request time the way the other four do: it walks it once at
registration and lets click own the parse. A change to how a group's flags are declared
therefore has two landing sites, and `tests/group_options/test_adapter_entry_point_parity.py`
is what keeps them agreeing.

## 2. Two Populations

### Pre-boot trie

Built from discovery cache rows + the `builtin` subtree. **Import-free** — same invariant
as the discovery cache (no job modules imported). Used for warm `--help`, dispatch,
and TUI navigation before APP_READY.

### Post-boot trie

Augmented with plugin command namespaces from `app.get_plugin_commands()`. Built after
APP_READY when plugins have registered. Full tree with all four surfaces' entries.

## 3. Construction

```python
trie = GroupTrie.from_cache(cache_rows, *, groups=builtin_groups)
```

- `cache_rows`: rows from the discovery cache, each with `name`, `group`, and `kind`
- `groups`: additional entries (e.g. `builtin` commands)
- **Leaf derivation:** strip group prefix — NOT `rsplit` (the group is the full dotted
  path; the leaf is the segment after it)
- Dotted-token all-or-nothing split: when resolving `db.migrate` and the trie has a
  direct node for `db.migrate`, resolve as one token — don't split into `db` group
  + `migrate` leaf just because `migrate` exists elsewhere

## 4. Resolution

```python
resolution = trie.resolve(["infra", "aws", "provision"])
```

Returns a `TrieResolution`:

| Attribute | Meaning |
|-----------|---------|
| `kind` | `"group"`, `"job"`, `"dual"`, or `"missing"` |
| `node` | The trie node (for `group`/`job`/`dual`) |
| `remaining` | Unconsumed segments (for group dispatch) |
| `children` | Child nodes (for group listing) |

**Duality nodes:** a name that is both a job and a group (e.g. `deploy` can be a standalone
job AND contain `deploy.staging`). First-class — `kind="dual"`, and the node carries both
the job handle and the group's children.

## 5. Naming Normalization

- `normalize_segment(name)` — lowercase, strip non-alphanumeric

## 6. Reserved Names

Reserved at boot and enforced in `_types/naming.py` and `_app/boot.py`:

- `builtin` — the builtin command subtree (cannot be a user job group)
- `!` — shell mode sigil
- `?` — reserved for future `InputMode`

User jobs or groups with these names are rejected at boot.

## 7. Public Access

```python
# For plugins or functional testing:
from functualize._types.naming import GroupTrie

# App-level access:
app.utils.build_group_trie(cache_rows)
app.group_trie  # post-boot property — full trie with plugin commands
```

## 8. Warm-Boot Invariant

The pre-boot trie is built without importing any job modules. It reads only the discovery
cache, which carries group metadata in a normalized form. This matches the existing
invariant for `--help` and warm dispatch.
