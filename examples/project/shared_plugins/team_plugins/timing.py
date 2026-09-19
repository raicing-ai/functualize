"""A directory that is *declared*, not conventional.

`team_plugins/` is an ordinary directory — no `.functualize/` wrapper, and the
loader would never find it on its own. `billing/.functualize.toml` names it in
`plugins_directories`, which is what brings it in.

`shipping/` declares nothing, so this plugin does not load there. That contrast
is the point of the example.
"""

from __future__ import annotations

from typing import Any


class Timing:
    """Marks the start of each run for the apps that opt in."""

    name = "timing"
    version = "1.0.0"
    description = "Announces that timing is active for this app."

    def __call__(self, app: Any) -> None:
        """Registration hook."""
        print(f"[timing] armed for {app.name}")


plugin = Timing()
