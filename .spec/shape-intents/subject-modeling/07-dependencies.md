# 07 — Python Dependencies

*How should a functualize project declare the packages its jobs import, and
where does rise's `Library` belong?*

Short answer: functualize already has four mechanisms and one hole; rise's
`Library` would be a fifth; and the fix is to notice that three questions share
one word.

## 1. What exists, and the hole

| Mechanism | Scope | Installs? | Where |
|---|---|---|---|
| `pyproject.toml [project.dependencies]` | a packaged project | **No** — read only to sha256-hash for cache invalidation | `_primitives/cache_format.py:314` |
| `[project.optional-dependencies]` extras | the framework and plugins | No | `pyproject.toml` |
| **PEP 723 inline** `# /// script` | **one `.py` file** | **Yes** — delegates to `uv run` | `_cli/pep723.py`; called only from `_cli/main.py:1555` |
| `builtin plugin install` / `self install` | the *running installation's* env | **Yes**, recorded in the manifest | `_cli/package_ops.py` (0.2.3) |

**The hole:** a jobs directory has nowhere to declare anything. The
`job-folder` scaffold emits no `pyproject.toml`, and PEP 723 is wired only into
single-file mode.

### The hole has a sharp edge **[probed]**

A job module whose import fails does not error — it **vanishes**:

```
WARNING:functualize._discovery.registry:Failed to import module 'needs_dep' …
  No module named 'nonexistent_package_xyz'
discovered: ['hello']
`fetch` is present: False
```

`rise fetch` then says *"No such command."* The user's model says "my job is
broken"; the CLI says it never existed. **This is the actual pain**, and it is
fixable without answering the declaration question.

## 2. Three questions wearing one word

| | Question | Whose environment | Owner | Status |
|---|---|---|---|---|
| **Q1** | what does *this installation* need? | the `func`/`rise` install | functualize | **solved in 0.2.3** |
| **Q2** | what do *my job modules import*? | the project's env | uv / pip / poetry | solved for packages; **the hole** for job folders |
| **Q3** | what must exist *on a target*, as a managed subject? | someone else's | rise's registry | `06` |

Q2 and Q3 look identical and are not. The difference is **who owns the
environment**:

- **Q2** is `import yaml` at the top of `jobs/audit.py`. The project's own code
  cannot run without it. It belongs in package metadata, resolved and locked by
  a real resolver.
- **Q3** is *"the machine we are provisioning must have `ansible` importable"*.
  It has a lifecycle, an isolation tag, a variant, and a lockfile entry.

Conflating them is how rise ends up reimplementing pip.

## 3. Alternatives considered

| | Approach | New format | Installs | Needs a resolver | Fixes job folders | Fixes vanishing jobs |
|---|---|---|---|---|---|---|
| A | status quo (`pyproject` only) | no | no | no | ✗ | ✗ |
| B | `[tool.functualize] requires = [...]` | **yes** | yes | inherits uv's | ✓ | ✓ |
| C | PEP 723 in every job module | no | yes | on aggregation | ✓ | ✓ |
| D | declare nothing; **diagnose** the failure | no | no | no | ✗ | **✓✓** |
| E | extras mapped to job groups | no | via pip | no | ✗ | ✓ |
| F | rise's `Library` owns everything | no | yes | **would need one** | ✓ | ✓ |

The arguments, briefly:

- **B**'s central objection is two sources of truth for a packaged project, and
  it invites functualize into *resolution*.
- **C** stretches a spec written for **scripts** over a directory; aggregating N
  modules' blocks into one environment *is* resolution, reached by another road.
- **F** only works if you use rise, inverts the layering, and is pip with worse
  resolution. It answers Q3 well and Q2 badly by pretending they are one.

## 4. Recommendation

**Do not add a dependency system. Add a diagnosis, then one narrow declaration
for the one case that has nowhere to put it.**

1. **D first, always.** Promote "module failed to import" from a swallowed
   warning to a first-class diagnostic — `rise doctor` (host) /
   `func rise doctor` (guest), in the shape `builtin self doctor` already uses:

   ```
   !!  jobs/audit.py   not loaded — No module named 'httpx'
       3 jobs in this file are missing from the CLI
       -> install the distribution providing 'httpx' in this environment
   ```

   Highest value per line in this file: it fixes the pain people actually hit,
   needs no format decision, and is additive to every other option.

2. **A + E for packaged projects.** `pyproject.toml` stays the single source of
   truth; extras say which job groups need what; the diagnostic prints
   `pip install .[audit]` as the remedy.

3. **A narrow B, job folders only.** `.functualize.toml` gains
   `requires = [...]`, understood as *a manifest handed to `uv`* and never as
   something functualize resolves — the contract `_cli/pep723.py` already
   honours for scripts. **Refuse the key when a `pyproject.toml` is present**,
   with an error naming it. That single refusal is what stops B's
   two-sources-of-truth problem from arising.

4. **C stays where it is.** PEP 723 is right for single files.

The rule underneath: **functualize declares and diagnoses; it never resolves.**

## 5. What rise adds

`rise doctor` is a rise verb in both deliveries, and it subsumes the
diagnostic above plus rise's own: rejected modules (`03` §4), unresolved
targets, drifted lockfiles, and the mount point (`04` §6).

## 6. Non-Python projects

A functualize project need not be a Python project. A TypeScript app can be
managed by `func` perfectly well — the *jobs* are Python, and they shell out.
That produces **three** distinct layers, and keeping them apart is the whole
answer:

```
my-ts-app/
├── package.json          # the APP's npm dependencies      <- layer 2
├── pyproject.toml        # the JOB CODE's Python imports   <- layer 1
│     or .functualize.toml  requires = ["httpx"]
├── jobs/
│   └── build.py          # def build(sh: Shell): sh("npm run build")
└── src/                  # TypeScript
```

| Layer | What | Declared in | Installed by |
|---|---|---|---|
| 1 | the **job code's** imports — always Python, because jobs are Python | `pyproject.toml`, or `.functualize.toml requires` when there is no package | uv / pip |
| 2 | the **app's** dependencies — whatever language the app is | `package.json`, `Cargo.toml`, `go.mod`, `Gemfile` | `npm ci`, `cargo fetch`, `go mod download` |
| 3 | **tools** the project needs on the machine (`node` itself, `jsonschema`) | rise's registry | rise's variant router |

**So the proposed `.functualize.toml requires` key stays Python-only, and that
is not a limitation.** It exists for one shape — a jobs folder with no
`pyproject.toml` — and the thing it declares is what the *job files* import.
A TypeScript project's npm packages never go there; they are already declared
in `package.json`, which is a better manifest than anything rise would invent.

### Layer 2 in rise's vocabulary

The `Package` substrate is **language-parameterized**, exactly as the intent
always required (`intent/03-type-system.md` makes `language` and
`package_manager` required tags on `library`):

```python
class AppDeps(Package, Installable):
    group    = "app.deps"
    language = "node"
    manager  = "npm"
    manifest = "package.json"        # rise READS it; never duplicates it
    source   = "project"
```

| `language` | Presence proved by | `install` delegates to |
|---|---|---|
| `python` | `importlib.util.find_spec` | `uv sync` / `pip install -e .` |
| `node` | `require.resolve` / `node_modules` consistency | `npm ci` / `pnpm install` |
| `rust` | the crate in `Cargo.lock` + build artifacts | `cargo fetch` |
| `go` | the module in `go.sum` | `go mod download` |
| `ruby` | `Gem::Specification.find_by_name` | `bundle install` |

Presence dispatches on `language`; installation delegates to `manager`. Rise
resolves nothing in any language — it reads the manifest the ecosystem already
has, proves presence, and shells out to install.

That is what makes `func rise diagnose` answer *"is everything this project
needs present?"* for a TypeScript app: `node` present (layer 3), `node_modules`
consistent with `package.json` (layer 2), job imports satisfied (layer 1).

## 7. Where `Library` belongs

Rise's `Package` substrate carries a discriminator:

```python
class Package(Substrate):
    """Presence = importable in a language runtime."""
    source: ClassVar[Literal["project", "managed"]]
```

| `source` | Meaning | Who installs | Declared in |
|---|---|---|---|
| `"project"` | my own code imports it | uv/pip, from `pyproject.toml` | `pyproject.toml` — rise **reads**, never duplicates |
| `"managed"` | I install it into a target environment | rise's variant router (`06` §7) | a rise module |

A `source="project"` module is **derived, not hand-written**: rise reads
`[project.dependencies]`, and its `install` delegates to `uv sync` rather than
pretending to resolve. Its `diagnose` still proves presence by import
(criterion 22), so the record stays uniform across both modes.

**So: not disparate ways. One declaration (`pyproject.toml`), two readers (uv
installs it; rise diagnoses it), and one extra key for the one shape that has
no package.** Rise's contribution is the uniform *record*, not a second place
to write the same list.

**Decided:** `source="project"` exists, and `rise diagnose` covers all three
layers. Rise reads every manifest and resolves none of them.
