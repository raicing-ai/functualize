"""D1 — display discovery order, and who wins the display_id dedupe.

`vision-implementation/10-display-provider.md` §3 offers a project's own
`displays.py` as "the override point (a project can subclass and add panes)",
and its criterion 6 asserts "the override wins by registration order/priority".

This probe establishes the opposite: entry points are registered FIRST and the
dedupe is first-wins, so a project `displays.py` reusing an installed
`display_id` is silently dropped.

No Textual app is started: `register_display_providers` only needs an object
with `.log.warning` and `._display_slot`, so a recording stub is enough to
observe real ordering and real dedupe.
"""

import tempfile
from pathlib import Path

from functualize._cli.tui.display_provider_discovery import (
    is_display_provider,
    register_display_providers,
)
from functualize.plugin.protocols import DisplayProvider
from functualize.ui.display import Display


# --- 1. a rise-shaped provider satisfies the protocol by duck-type and isinstance


class RiseProjectDisplay(Display):
    display_id = "rise-project"
    display_title = "rise"
    display_priority = 30
    refresh_interval = 5.0
    refresh_timeout = 8.0
    linked_groups = ["rise"]

    def should_show(self, cwd, app) -> bool:
        return (cwd / ".risekit").is_dir()

    def compose_display(self):
        return iter(())


print("is_display_provider(class):   ", is_display_provider(RiseProjectDisplay))
print("isinstance(inst, Protocol):   ", isinstance(RiseProjectDisplay(), DisplayProvider))
print("Display.refresh_timeout default:", Display.refresh_timeout)
print("Display.display_priority default:", Display.display_priority)

# --- 2. should_show is a single is_dir() and never imports the project

root = Path(tempfile.mkdtemp())
proj = root / "proj"
(proj / ".risekit").mkdir(parents=True)
plain = root / "plain"
plain.mkdir()

d = RiseProjectDisplay()
print("should_show(rise project):    ", d.should_show(proj, None))
print("should_show(plain dir):       ", d.should_show(plain, None))

# --- 3. discovery order and dedupe, against a recording stub


class _Ring:
    def __init__(self) -> None:
        self._displays: list[Display] = []


class _Slot:
    def __init__(self) -> None:
        self._ring = _Ring()
        self.order: list[str] = []

    def register_display(self, inst: Display) -> None:
        self._ring._displays.append(inst)
        self.order.append(f"{type(inst).__name__}({inst.display_id})")


class _Log:
    def warning(self, msg: str) -> None:
        print("   [warn]", str(msg)[:100])


class _App:
    def __init__(self) -> None:
        self._display_slot = _Slot()
        self.log = _Log()


# A project displays.py that reuses the installed display_id — the documented
# "override point".
(proj / "displays.py").write_text(
    "from functualize.ui.display import Display\n"
    "class ProjectOverride(Display):\n"
    '    display_id = "rise-project"\n'
    '    display_title = "rise (project override)"\n'
    "    display_priority = 10\n"
    "    def should_show(self, cwd, app): return True\n"
    "    def compose_display(self): return iter(())\n"
    "\n"
    "class ProjectExtra(Display):\n"
    '    display_id = "rise-risks"\n'
    '    display_title = "rise risks"\n'
    "    def should_show(self, cwd, app): return True\n"
    "    def compose_display(self): return iter(())\n"
)

import os

os.chdir(proj)

# Pre-seed the slot the way an installed `functualize.displays` entry point
# would: registered before the CWD scan runs.
app = _App()
app._display_slot.register_display(RiseProjectDisplay())
print("\npre-seeded (as an entry point would):", app._display_slot.order)

register_display_providers(app)
print("after full discovery:               ", app._display_slot.order)

ids = [x.display_id for x in app._display_slot._ring._displays]
print("\nregistered display_ids:", ids)
print("project override applied:", "ProjectOverride" in " ".join(app._display_slot.order))
print("project's NEW display applied:", "rise-risks" in ids)
