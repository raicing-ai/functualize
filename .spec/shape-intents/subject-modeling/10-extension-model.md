# 10 — Extension Model

Extending the vocabulary is subclassing. The intent's three-file schema pattern
(base / extensions / effective) evaporates, and this file pays the bill for
what that costs.

## 1. What extends what

| Layer | Extensible by | Mechanism |
|---|---|---|
| Substrates | project | subclass `Substrate`, list the module under `[risekit] module_packages` |
| Actions | project | a new `Protocol`, mixed into a class |
| Substrates / actions | maintainer | a risekit release |
| Variants | anyone | a subclass of a tool base, shipped via `risekit.modules` |
| New job surfaces | anyone | ordinary functualize plugins |

## 2. A project-local substrate

```python
class Container(Substrate):
    """Presence = an image exists and a container is addressable."""
    supports = (Controllable, Loggable)

    @abstractmethod
    def presence(self) -> Presence: ...

class Api(Container, Controllable, Loggable):
    group = "apps.api"
    image = "ghcr.io/acme/api:1.4"
    def start(self, sh: Shell) -> None: ...
```

Everything the old `[[kinds]]` TOML block declared — name, required
actions, allowed interfaces — is the class body, enforced by the same
binding path as a built-in. There is no second validation route, which is the
property criterion 59 was reaching for.

Two things a project-local substrate does not get, both correctly:

- It is not in `risekit.core`, so it is not shared vocabulary and no other
  project's tooling is expected to understand it.
- Its actions are unlisted in any built-in `supports` tuple, so binding
  check 5 reports "unknown action, not scoped" as a `validate` finding
  rather than refusing the binding — a project cannot edit risekit's tables, so
  refusing would make project-local Protocols unusable.

## 3. A project-local action

```python
@runtime_checkable
class Health(Protocol):
    health_url: ClassVar[str]
    def healthcheck(self) -> HealthStatus: ...

class Api(Container, Controllable, Health):
    health_url = "http://localhost:8080/health"
    def healthcheck(self) -> HealthStatus: ...
```

Handled exactly like a built-in — no registration, no allowed-list edit.
`runtime_checkable` verifies presence only, so mypy remains the layer that
checks the signature and the `ClassVar` (`02` §6).

It must pass the §`01` 4 test: a verb against the subject. `Health` does —
you health-check *the service*. A `Reportable` would not.

## 4. What is deleted, and what it costs

| Deleted | Replaced by | Criterion |
|---|---|---|
| the extensions file | Python modules under `[risekit] module_packages` | 57 |
| `effective_contracts()` merge | nothing — normal import | 59 |
| the effective-schema rebuild | nothing — no artifact to rebuild | 55, 59 |

Criterion 57 survives on substance: project vocabulary lives in project-owned
files an upgrade never rewrites. The guarantee is filesystem ownership rather
than merge logic — strictly stronger.

Criterion 60 improves: a malformed extension is a `SyntaxError`/`TypeError` at
import, earlier and louder than meta-model validation, and it names a line.

**Criterion 59 does not survive as written.** "The effective schema is the
single validation authority" presupposes a merged artifact, and there is none.
What replaces it is defensible — *one binding path validates every module,
built-in and project-local alike, with no second authority to disagree with* —
but it is a **reduction**, and `12` scores it as one.

## 5. Commands

```console
$ rise new substrate container         # scaffolds the Substrate subclass
$ rise new action health                # scaffolds the Protocol
$ rise schema substrates | actions
$ rise schema export --out contracts/
```

Idempotent; name validation is Python identifier rules plus
`normalize_segment` reachability — stricter than the intent's lowercase rule
and enforced by the language. Both scales use one code path.

## 6. Version pinning — the honest account

The intent (criterion 61): *a pinned version means validation uses the pinned
schema, immune to upgrades.* Under this model the vocabulary **is** the
installed classes, so a pin cannot select a contract. A warning is not
immunity.

**Option 1 — accept the reduction (recommended).**

```toml
[risekit]
framework_version = "1.4.0"
```

Boot compares it to `importlib.metadata.version("risekit")` and warns. Immunity
is delivered by the packaging layer instead: pin `risekit` in the project's own
`pyproject.toml` and the environment cannot move under you. That is how every
Python project achieves version immunity, and it is more honest than a
framework-internal simulation.

**Option 2 — export and replay.** `rise schema export` (`05` §5) writes the
per-substrate JSON Schemas as of the installed version. Commit `contracts/`,
and `rise validate --contracts contracts/` re-checks records against the
**pinned documents**. This restores immunity for **step 2** (record shape). It
cannot restore step 1 (structural conformance), which is a property of code.

Option 2 is cheap — a flag on a mechanism `05` builds anyway — and is what a
compliance-minded user actually wants. Offered, not default. `12` scores
criterion 61 **unmet for step 1, met for step 2 under option 2**.

## 7. Variants for new actions

A new action supports concrete variants with zero schema work: a variant
class implements the Protocol in its own class under the tool's base. The
intent's `{task}:{variant}` templating (criterion 62) was a substrate
constraint of the Taskfile era; the class model removes the need entirely.
