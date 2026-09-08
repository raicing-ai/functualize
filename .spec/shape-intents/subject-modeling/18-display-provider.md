# 18 — Ambient Awareness: rise's Display Provider

rise ships **one `DisplayProvider`** so the inline TUI shows rise's ambient
facts whenever the CWD is a rise project. No new UI mechanism, no TUI fork:
one class on functualize's existing protocol, published through the discovery
path functualize already ships.

Folded in from an earlier vision-implementation brief, which was written
against functualize **0.2.0** and against a package graph v3 rejected. Re-verified against **0.2.3**, corrected in four places, and extended
with the question that file could not ask — *what happens in the second
delivery?* (`04`).

**Verification basis.** Every fact in §1 cites `path:line` into functualize
0.2.3. **[probed]** marks claims executed by
[`evidence/probe_19_display_discovery.py`](evidence/probe_19_display_discovery.py).

## 1. The functualize surface — pinned

| Fact | Cite |
|---|---|
| `DisplayProvider` is a `@runtime_checkable` Protocol: `display_id`, `display_title`, `display_priority` (lower = earlier in the ring), `refresh_interval: float \| None` (min 0.5s), `linked_jobs`, `linked_groups`, `should_show(cwd, app)`, `compose_display()`, `refresh()`, `get_available_actions(focused)` | `plugin/protocols.py:83-117` |
| `Display` base class supplies a default for every member; **subclassing is optional** — discovery duck-types on `display_id` | `ui/display.py:5,54` |
| Defaults: `display_priority = 100`, `refresh_timeout = 10.0`, `refresh_interval = None` | `ui/display.py:86,93,90` **[probed]** |
| `should_show` stays on the **loop thread** — it runs on every CWD change, so it is cheap by contract | `_cli/tui/display_slot.py:18` |
| `refresh()` runs on a **thread worker**, one in-flight per display; the UI update that follows must marshal back to the loop thread | `_cli/tui/display_slot.py:12-16,579-622` |
| A provider may override the bound with a `refresh_timeout` attribute; the minimum interval is enforced at `max(interval, 0.5)` | `_cli/tui/display_slot.py:63-66,553-554` |
| Three discovery paths: cache-flagged job modules, a CWD `displays.py`, and the `functualize.displays` entry-point group | `_cli/tui/display_provider_discovery.py:3-14,48` |
| Affinity: `linked_jobs` (exact) / `linked_groups` (group **or any ancestor**) select related displays; `display_auto_switch="auto"` switches to the lowest-priority related one | `_cli/tui/display_affinity.py:40-71,115-133` |
| `FunctualizeInlineTUI(func_app: FunctualizeApp)` takes **any** booted app — the TUI is not specific to the `func` binary | `_cli/tui/app.py:225` |

## 2. What rise ships: one provider, four panes

One `display_id`, one ring slot — not one per pane. Ctrl+U/Ctrl+O cycling is
for *alternative* views, and rise's facts are one canonical view.

```
┌ rise · bifrost ──────────────────────────────────────┐
│ modules    4 ✓ (api, pipeline, root, jsonschema)     │
│ processes  api ● running    isolation  host ⚠        │
│ validate   ✓ 4/4 green   diagnose  4 records         │
│ lockfile   jsonschema:pip (auto)                     │
│ [v]validate [d]diagnose [s]status                    │
└──────────────────────────────────────────────────────┘
```

| Pane | Source | Thread |
|---|---|---|
| module count + validate badge | the discovery snapshot, cached at boot | cheap, loop-safe |
| per-process state | `Controllable.status()` on `Process`-substrate modules (`01` §2) | worker |
| host-isolation warning | `isolation` `ClassVar`s (`02`) | cheap |
| lockfile summary | latest under `.risekit/lock/` (`06`) | cheap |

**The design rule: the display shows rise's *ambient* facts — identity, health,
risk — never job progress.** In-run progress is `live: Live`'s job, which
functualize already owns. No overlap.

Note the vocabulary correction against the source file: the pane is
**processes**, not "services". There is no `Service` kind in v3 — a service is
the `Process` substrate plus `Controllable` + `Loggable` (`01` §7). The pane
renders whatever satisfies `Controllable`, which is strictly more than the old
`Service` kind could name.

## 3. The provider, shaped

```python
# risekit/tui/displays.py
from pathlib import Path

from functualize.ui.display import Display
from textual.app import ComposeResult
from textual.containers import Vertical


class RiseProjectDisplay(Display):
    display_id = "rise-project"
    display_title = "rise"
    display_priority = 30            # ambient; above the 100 default
    refresh_interval = 5.0
    refresh_timeout = 8.0            # tighter than the 10.0 default
    linked_groups = ["rise", "tools", "repos"]
    linked_jobs = ["rise.validate", "rise.diagnose"]

    def should_show(self, cwd: Path, app) -> bool:
        return (cwd / ".risekit").is_dir()        # loop thread — one is_dir()

    def compose_display(self) -> ComposeResult:
        yield Vertical(
            ModuleSummary(), ProcessStatus(), IsolationWarnings(), LockfileSummary()
        )

    def refresh(self) -> None:
        snapshot = collect_snapshot(self._cwd)    # worker thread; may diagnose
        self.call_from_thread(self._apply, snapshot)

    def get_available_actions(self, focused: bool) -> list[tuple[str, str]]:
        return [("v", "validate"), ("d", "diagnose"), ("s", "status")]
```

```toml
# risekit's pyproject.toml
[project.entry-points."functualize.displays"]
rise-project = "risekit.tui.displays:RiseProjectDisplay"
```

**[probed]** the class satisfies the protocol both ways — `is_display_provider`
duck-type and `isinstance(inst, DisplayProvider)` — and `should_show` returns
`True` in a directory with `.risekit/`, `False` without.

### The architectural consequence: a fourth allowed importer

`11` §1's import-linter contract reads *"only `risekit.binding`,
`risekit.plugin` and `risekit._cli` import functualize, and only its public
surfaces (`functualize.app`, `functualize.job`, `functualize.plugin`)."*

This file adds **`risekit.tui`** as a fourth allowed importer and
**`functualize.ui`** as a fourth allowed surface. That is the whole cost, and
it is worth naming rather than absorbing silently:

- `risekit.core` is untouched — the vocabulary stays pydantic + stdlib, so the
  "checkable without the runtime" property (`12` row 16) survives.
- `risekit.tui` additionally imports **textual**, which nothing else in risekit
  does. It is therefore an **optional extra** (`risekit[tui]`), and the textual
  import must live *inside* `risekit.tui.displays` — never at
  `risekit/__init__.py` level, or a headless install breaks on import.

  Given that, **functualize already contains the failure**: the entry-point
  loop wraps `entry_point.load()` in `try/except Exception`, logs a warning and
  continues, because "loading a third-party entry point executes arbitrary
  code; one broken package must not cost the others their displays"
  (`display_provider_discovery.py:89-106`). A textual-less install therefore
  degrades to *no display* on its own — rise engineers nothing for this beyond
  import placement. The entry point may also resolve to a zero-arg callable
  rather than the class, "so a package can decide lazily" (`:73-74`), which is
  available if the eager instantiation at `:91` ever becomes a cost.

## 4. Both deliveries, one entry point

The source file predates the dual delivery (`04`) and assumed one CLI. It costs
nothing to serve both:

| Delivery | How the display arrives | `should_show` |
|---|---|---|
| **A — guest** (`func rise …`) | the `functualize.displays` entry point, discovered by the host's inline TUI | `.risekit/` at CWD |
| **B — standalone** (`rise`) | the same entry point. Entry points are environment-global and `FunctualizeInlineTUI` accepts any `FunctualizeApp` (`app.py:225`), so rise's own CLI discovers it with no extra wiring | `.risekit/` at CWD |

**One class, one entry point, two deliveries** — the same property `04` claims
for the plugin, and for the same reason: nothing about the display is bound to
which app hosts it.

The predicate stays `.risekit/`-exists in *both*, deliberately. It is tempting
to make the display always-on in delivery B, since `rise` is a rise-only CLI —
but then the same class behaves two ways, and the honest signal ("this
directory is not a rise project") is the one the user needs most when `rise`
reports nothing.

## 5. The override point does not work — and what to do about it

That earlier brief (§3) offers a project's own
`displays.py` as *"the override point (a project can subclass and add panes)"*,
and its criterion 6 asserts *"the override wins by registration order/priority"*.

**Both claims are false against 0.2.3.** Discovery runs entry points **first**,
then cache-flagged modules, then the CWD scan
(`display_provider_discovery.py:51-55`), and every path skips an id already
registered (`:160-161`, `:208`). First registration wins.

**[probed]**, with a project `displays.py` declaring both an override of
`rise-project` (at a *better* priority, 10) and a new `rise-risks` display:

```
pre-seeded (as an entry point would): ['RiseProjectDisplay(rise-project)']
after full discovery:                 ['RiseProjectDisplay(rise-project)',
                                       'ProjectExtra(rise-risks)']
project override applied: False
project's NEW display applied: True
```

So, precisely: **a project can add a display; it cannot replace one.** The
override is dropped with no warning — the dedupe `continue`s silently, and
`display_priority` never enters the decision.

Three consequences, and rise takes the first two now:

1. **Do not document an override point that does not exist.** The scaffold's
   `displays.py` ships an *additional* display (a project-specific pane), never
   a re-declaration of `rise-project`. §8 criterion 6 is rewritten accordingly.
2. **Make replacement explicit instead.** A project that genuinely wants
   different panes sets `display_id = "rise-project-local"` and rise's own
   display stays visible beside it. Two slots in the ring is the honest
   rendering of "two displays exist".
3. **Upstream ask 10** (indexed in `13`, argued here) — *last-wins, or a warning.* Either the CWD scan
   should take precedence over installed packages (the local override is the
   more specific declaration, exactly as `.risekit/`-local config beats global
   config elsewhere in functualize), or the dedupe should log at
   `app.log.warning` the way every other skip in that module already does.
   Silently discarding a user's class is the part that is hard to defend.
   **rise can route around it** — consequence 2 costs a paragraph of docs — so
   this is sequenced with asks 6–8, not before them.

## 6. Behavior contract

1. **Cheap `should_show`** — one `is_dir()`. Nothing imports the project,
   nothing shells out. Loop thread; hard rule.
2. **Worker-safe `refresh`** — all I/O in `refresh()`; UI updates marshal back.
   A hung refresh is bounded by `refresh_timeout = 8.0` and skips its cycle.
   The TUI never freezes because of rise.
3. **Failure containment** — the slot already logs and skips per-provider
   errors; `collect_snapshot` must additionally never raise, and must emit a
   *degraded* snapshot instead (a pane reading `—`, not a missing display).
4. **Same truth as the CLI** — panes read the same discovery and diagnosis data
   the CLI renders (`05`). The display never derives status of its own.
5. **No overlap with `live: Live`** — ambient state only.
6. **Headless-safe** — no textual, no display, no error (§3).

## 7. Interaction

The composed widget implements `InteractiveContent` (`action_*` +
`get_available_actions`), so Shift+Tab into the DISPLAY zone exposes footer
actions:

- `v` → `rise validate`
- `d` → `rise diagnose` (streams to the job output zone)
- `s` → one immediate refresh cycle

All three are **invocations through the normal job surface** — audited,
exit-coded, never in-place magic. Keys are advisory; the binding discipline is
functualize's.

## 8. Placement and acceptance

**Build order** (`11` §2): a new **step 13**, after dogfooding. It is a thin
consumer of a protocol that already exists and gates nothing — but it is the
first thing in risekit to depend on textual, and step 12 should prove the
package works without it.

| Test | Pins |
|---|---|
| `test_should_show_is_pure` | `should_show` performs one `is_dir()` and imports no project code — fails if it grows I/O |
| `test_display_protocol_satisfied` | `isinstance(RiseProjectDisplay(), DisplayProvider)` — fails if the protocol gains a member |
| `test_refresh_timeout_bounded` | a deliberately hung `refresh` does not block the loop thread |
| `test_headless_import` | importing `risekit` with textual absent succeeds and yields no display |
| `test_display_in_both_deliveries` | the entry point resolves under both apps (`04` §7) |
| `test_local_display_coexists` | a project `displays.py` with a *distinct* id registers alongside rise's — the corrected criterion 6 |

**Acceptance criteria** — corrected from the source file's §8:

- [ ] The inline TUI inside a rise project shows the display above the header;
      in a non-rise directory it is absent.
- [ ] Module/validate values match `rise validate` within one refresh interval.
- [ ] `should_show` is a single directory check, pinned by a test that fails if
      it imports project code.
- [ ] A hung refresh is bounded by `refresh_timeout`; the TUI stays responsive.
- [ ] Shift+Tab into the DISPLAY zone exposes `v`/`d`/`s`; `v` runs validate
      through the job surface, with audit and exit codes.
- [ ] A project `displays.py` declaring a **distinct** `display_id` registers
      alongside rise's. ~~The override wins.~~ **A project cannot override
      `rise-project`** — §5, probe 19.
- [ ] The display appears in **both** deliveries from the one entry point.
- [ ] `pip install risekit` without the `tui` extra yields a working CLI and no
      display.

## 9. Not this file's surface

The fullscreen rise dashboard sketched in that same earlier brief is a
**different** surface and stays out of scope. It is a `TextualApp`,
not a `DisplayProvider`; merging the two would put a dashboard's data appetite
behind a contract that promises a cheap `should_show`. If it is ever built, it
is its own file.
