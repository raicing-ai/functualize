# plugin-taxonomy — contracts

External interfaces only: distribution identities, entry-point groups, exported
symbols, config sections, and user-visible command output. Internal types and
storage schemas are not here.

Anything marked **OPEN** is deliberately unsettled and is a Plan-phase decision
(`spec.md` §I).

---

## 1 · Distribution identities

### 1.1 · Renamed — three, no shims

| Before | After | Import package before | Import package after |
|---|---|---|---|
| `functualize-state-sqlite` | `functualize-substrate-sqlite` | `functualize_state_sqlite` | `functualize_substrate_sqlite` |
| `functualize-aws` | `functualize-secrets-aws` | `functualize_aws` | `functualize_secrets_aws` |
| `functualize-bitwarden` | `functualize-secrets-bitwarden` | `functualize_bitwarden` | `functualize_secrets_bitwarden` |

Old PyPI names are abandoned at 0.2.3. No shim distribution, no
`DeprecationWarning` (`.spec/CONSTITUTION.md` → *Forbidden Patterns*).

### 1.2 · New — one

| Name | Import package | Depends on |
|---|---|---|
| `functualize-substrate-s3` | `functualize_substrate_s3` | `functualize>=0.1.0,<1.0.0`, `boto3>=1.34.0` |

### 1.3 · Unchanged — nine

`functualize-http`, `functualize-lambda`, `functualize-mcp`,
`functualize-flow-viz`, `functualize-inline`, `functualize-tasks`,
`functualize-tasks-local`, `functualize-ai`, `functualize-ai-pydantic`.

Their **directories** move (§2); their distribution and import names do not.

---

## 2 · Repository layout

```
plugins/
  adapters/        functualize-http, functualize-lambda,
                   functualize-mcp, functualize-flow-viz
  substrates/      functualize-substrate-sqlite, functualize-substrate-s3
  secrets/         functualize-secrets-aws, functualize-secrets-bitwarden
  domains/         functualize-tasks, functualize-ai
  providers/       functualize-tasks-local, functualize-ai-pydantic,
                   functualize-inline
  conftest.py      (stays at plugins/ root)
  PUBLISHING.md    (stays at plugins/ root)
```

**OPEN (Q4):** `providers/` is the weak name — its members implement a *domain*,
so `implementations/`, or nesting under the domain served, may read better.

### 2.1 · Path consumers that must change with it

Every one verified present today. A move that misses one of these breaks
silently rather than loudly, which is why they are a contract and not a note.

| File | Site | Current |
|---|---|---|
| `pyproject.toml` | 133 | `members = ["plugins/*"]` |
| `.claude/hooks/spec_gate.py` | 25, 87 | `GATED_GLOB_PARTS`; `rel[1] == "src"` |
| `.claude/hooks/agent_contract.py` | 30 | ``plugins/*/src/**`` in the contract text |
| `.claude/hooks/plan_context.py` | 42 | same sentence |
| `evals/providers/_harness.py` | 172 | `"plugins/*/pyproject.toml"` |
| `tests/conftest.py` | 352-360 | `… / "plugins" / "functualize-state-sqlite" / "src"` — path **and** name |
| `tests/integration/test_substrate_durability.py` | 149, 231, 279 | three literal plugin paths |
| `.github/workflows/ci.yml` | 232, 235 | `plugins/functualize-mcp/tests`, `…/examples` |
| `contributor/guides/plugin-development.md` | 78-89 | *"Already a glob — your plugin is auto-included"* — becomes false |
| `plugins/PUBLISHING.md` | throughout | `plugins/<name>/…` verification commands |

---

## 3 · Entry-point groups

### 3.1 · Renamed — hard cutover

```
functualize.remote_providers   ->   functualize.secrets_providers
```

Sole reader today: `src/functualize/_config/registry.py:193`. Core reads the new
name **only**; the old string must not survive in `src/`. Repo-wide the literal
appears 53 times across 19 files.

Entry-point *names* within the group are unchanged: `aws-sm`, `aws-ssm`, `bws`.
They are what a user writes in config, and D1–D4 did not touch them.

### 3.2 · Retired — declared by nobody afterwards

```
functualize.state_providers           (2 declarants: the sqlite plugin, and the shipped example)
functualize.interactivity_providers   (1 declarant: functualize-inline)
```

### 3.3 · Where the retired declarants go — **OPEN (Q2, Q3)**

Two shapes satisfy `spec.md` AC-1 and AC-3. The Plan phase's architecture gate
chooses; this contract records both so the choice is visible.

**Shape A — reuse the group that already loads.**

```toml
[project.entry-points."functualize.plugins"]
substrate-sqlite = "functualize_substrate_sqlite:SQLiteSubstratePlugin"
```

Loads today with no core change. Cost: `_primitives/plugin_kinds.py:56` maps
`functualize.plugins` → `PluginKind.ADAPTER`, and `_cli/plugin_cmd.py::_KIND_ORDER`
renders that as *"ADAPTERS — add commands or a delivery surface"*. A substrate
does neither, so U3 (`spec.md` §C) is not met.

**Shape B — a group that says the truth.**

```toml
[project.entry-points."functualize.substrates"]
sqlite = "functualize_substrate_sqlite:SQLiteSubstratePlugin"
```

Requires a new reader in core, a `PluginKind.SUBSTRATE` member, and a
`_KIND_ORDER` heading. Note `classify_group` derives kind from the *suffix*, so
`functualize.substrates` currently returns `UNKNOWN` — the enum and the
classifier change together.

`functualize-inline` gets the same question, with a third option:
`functualize.displays`, the group `_cli/tui/display_provider_discovery.py:82`
already reads.

### 3.4 · `functualize.vault_key_providers` — documentation only

Declared at root `pyproject.toml:46`, read by no `entry_points(group=…)` call.
Core imports `EnvKeyProvider` and `KeychainKeyProvider` directly, so nothing is
broken. But `src/functualize/_config/vault_keys.py:6` tells plugin authors they
may *"register through the `functualize.vault_key_providers` entry-point group"*,
which is false. Either give it a reader or correct the docstring — no third
option.

---

## 4 · `functualize-substrate-s3` public surface

Mirrors `SQLiteSubstrate` exactly, so a reader of one can read the other.

```python
__all__ = ["S3Substrate", "S3SubstratePlugin"]

class S3Substrate:
    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        *,
        client: Any | None = None,   # an injected boto3 client, for tests
    ) -> None: ...

    @property
    def bucket(self) -> str: ...
    @property
    def prefix(self) -> str: ...

    # StoreSubstrate — all six members (src/functualize/_types/protocols.py:713)
    def read(self, key: str) -> Stored | None: ...
    def write(self, key: str, payload: dict[str, Any], *,
              expect: int | None = None) -> bool: ...
    def lock(self, *keys: str) -> AbstractContextManager[None]: ...
    def clear(self, key: str) -> str | None: ...
    def delete(self, key: str) -> bool: ...
    def describe(self, key: str) -> str: ...
```

### 4.1 · Behavioural contract, where S3 differs from both existing substrates

| Member | Contract |
|---|---|
| `lock()` | **A no-op**, explicitly. The port permits this (`protocols.py:795`: *"May be a no-op for a backend that offers no mutual exclusion"*). It must be documented at the class, not discovered. |
| `write(expect=)` | **The only safety mechanism here**, therefore a real conditional write, not a read-then-put. Returns `False` on mismatch — an ordinary outcome, not an error. |
| `read()` | A missing object is `None`; an object that exists and will not decode raises `SubstrateUnreadableError`. The `None`-vs-empty distinction stores rely on is preserved. |
| `clear()` | Copy-aside to a sibling key, returning that key as the human-readable account. |
| `describe()` | Prose. A key ending `/` is a namespace and is described in aggregate. |

**`lock()` being a no-op is why `spec.md` AC-5 is a prerequisite, not a
companion.** Any caller doing read-modify-write without `expect=` is
silently lossy here. `functualize-tasks-local` is such a caller today.

### 4.2 · Config section

```toml
[plugin.substrate-s3]
bucket = "..."        # required
prefix = ""           # optional
```

Resolved through `app.configuration.resolve_model`, the pattern
`SQLiteStatePlugin._configured_path` already uses.

---

## 5 · Exported symbols of the renamed packages

Unchanged in name; only the module path moves.

| Package | `__all__` |
|---|---|
| `functualize_substrate_sqlite` | `SQLiteSubstrate`, and the plugin class (`SQLiteStatePlugin` → **renamed**, see below) |
| `functualize_secrets_aws` | `HONOURED_KEYS`, `AccountMismatchError`, `AwsReference`, `InvalidReferenceError`, `ParameterStoreProvider`, `SecretNotFoundError`, `SecretsManagerProvider`, `clear_credential_cache`, `parse_reference` |
| `functualize_secrets_bitwarden` | `ACCESS_TOKEN_VAR`, `HONOURED_KEYS`, `ORGANIZATION_VAR`, `AmbiguousKeyError`, `BitwardenAuthError`, `BitwardenRequestError`, `BwsReference`, `InvalidReferenceError`, `SecretsManagerProvider` |

**One class rename:** `SQLiteStatePlugin` → `SQLiteSubstratePlugin`. The word
*State* names a domain ADR-022 retired; keeping it would reintroduce the
mismatch this feature exists to remove. Its `name` attribute changes with it:
`"sqlite-state"` → `"substrate-sqlite"`, which also moves its config section
from `plugin.sqlite-state` to `plugin.substrate-sqlite`.

---

## 6 · Packaging surface

### 6.1 · Root `pyproject.toml`

```toml
[project.optional-dependencies]
cli = [ … unchanged, no plugins … ]
all = [
    "functualize[cli]",
    # NOT here: functualize-secrets-aws, functualize-secrets-bitwarden
    …
]
```

`functualize-secrets-aws` leaves `[all]`, joining `functualize-bitwarden`'s
existing precedent (`pyproject.toml:105-118`). `[cli]` never contained either.

**Downstream consequence, contractual because it is user-visible:** `[all]` is
what the standalone binary bakes (`PYAPP_PROJECT_FEATURES=all`, ADR-015
§Correction / `release.yml`). The binary therefore ships **without** AWS Secrets
Manager and SSM support. This is a breaking change for standalone users and
requires a CHANGELOG entry saying so.

`[tool.uv.sources]` gains `functualize-substrate-s3` and renames three keys:
12 workspace entries today → 13.

### 6.2 · `src/functualize/_cli/data/plugin_catalog.toml`

`tests/cli/test_plugin_catalog.py::test_recommended_set_matches_the_all_extra`
asserts `set(recommended_distributions()) == the [all] extra`, so the catalog
moves in lockstep:

| Entry | `distribution` | `group` | `recommended` |
|---|---|---|---|
| `sqlite` → `substrate-sqlite` | `functualize-substrate-sqlite` | **OPEN (Q2)** | `true` |
| *new* `substrate-s3` | `functualize-substrate-s3` | **OPEN (Q2)** | `true` |
| `aws-sm` | `functualize-secrets-aws` | `functualize.secrets_providers` | **`false`** ← changed |
| `bws` | `functualize-secrets-bitwarden` | `functualize.secrets_providers` | `false` |

`test_all_three_kinds_are_represented` must still pass; `tasks-local` and
`ai-pydantic` keep `implementation` covered under either shape in §3.3.

### 6.3 · PyPI trusted publishers — manual, by the maintainer

| Project | Action |
|---|---|
| `functualize-substrate-sqlite` | manual one-time token upload, then a trusted publisher |
| `functualize-secrets-aws` | manual one-time token upload, then a trusted publisher |
| `functualize-secrets-bitwarden` | manual one-time token upload, then a trusted publisher |
| `functualize-substrate-s3` | **automatic** — a pending publisher is unique on `(owner, repo, workflow, environment)`, so the workflow claims exactly one new name (`release.yml:119-130`) |
| `functualize-state-sqlite`, `functualize-aws`, `functualize-bitwarden` | left at 0.2.3; publishers may be revoked |

---

## 7 · User-visible command output

### 7.1 · `func builtin plugin available`

Headings come from `_cli/plugin_cmd.py::_KIND_ORDER`. Under §3.3 Shape B a
fourth heading is added; under Shape A the substrates appear under ADAPTERS,
which `spec.md` U3 rejects. **OPEN (Q2).**

### 7.2 · `func builtin plugin available --remote` — **OPEN (Q1)**

`_fetch_remote_distributions` (`plugin_cmd.py:395`) enumerates the PyPI Simple
index for every project named `functualize-*`. The three abandoned names remain
on PyPI, so they would render as:

```
UNCURATED — found on PyPI, not vetted by this project
  state-sqlite    functualize-state-sqlite
  aws             functualize-aws
  bitwarden       functualize-bitwarden
```

Two candidate contracts:

- **Suppress** — `plugin_catalog.toml` gains a `retired = [...]` list that
  `available_rows` subtracts from `remote`. *Recommended:* the heading claims
  these were never vetted by this project, and all three were.
- **Accept** — document the listing in the CHANGELOG and leave the code alone.

### 7.3 · `func builtin data show`

`spec.md` AC-7: with `functualize-tasks-local` installed, task documents render
as readable fields. Today `_serialize_task` `json.dumps`es each task into a
*string* that is then stored inside the dict the substrate JSON-encodes again,
so the command prints escaped JSON. Flattening that changes the on-disk shape of
the `tasks` document — an internal schema, so it is specified in `schema.md`,
not here. What is contractual is only the rendered output.

---

## 8 · What does **not** change

- The `StoreSubstrate` protocol itself (`_types/protocols.py:713`). Six members,
  unchanged. This feature adds an implementation; it does not widen the port.
- `TaskProvider`, `TaskItem`, `TaskLink`, `TaskStatus` from `functualize_tasks`.
  F3 changes how `functualize-tasks-local` stores tasks, not what the domain
  publishes.
- Entry-point *names* inside `functualize.secrets_providers`: `aws-sm`,
  `aws-ssm`, `bws`. Users have these in config files.
- `functualize.jobs`, `functualize.skills`, `functualize.domains`,
  `functualize.format_providers`, `functualize.displays`,
  `functualize.ai_providers`, `functualize.tasks_providers`.
- `boto3` stays out of core: `rg -n boto3 src/functualize/` → 0, today and
  after (ADR-016; `spec.md` AC-15).
