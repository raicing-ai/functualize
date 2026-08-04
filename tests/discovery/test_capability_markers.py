"""Harvest of TTY/Live capability markers from job signatures.

`extract_capability_markers` reads the signature-level capability declarations
into the cached JobDescriptor flags so warm/lazy boot can route a job to the
right rendering surface without importing it. Matched by type *name*, so these
placeholder classes named ``TTY``/``Live`` are representative of the real
capability types.

Also verifies the companion invariant: TTY/Live never leak into the user-facing
CLI parameter list — including the optional ``tty: TTY | None`` form.
"""

from __future__ import annotations

from typing import Optional

import pytest

from functualize._discovery.providers import (
    extract_capability_markers,
    extract_parameters_from_signature,
)


class TTY:
    """Placeholder standing in for the real TTY capability (name-matched)."""


class Live:
    """Placeholder standing in for the real Live capability (name-matched)."""


class Cfg:
    """A plain (non-capability) parameter type."""


# --- Marker harvest ---------------------------------------------------------


def test_bare_tty_is_hard_requirement() -> None:
    def job(cfg: Cfg, tty: TTY) -> None: ...

    markers = extract_capability_markers(job)
    assert markers == {
        "requires_tty": True,
        "optional_tty": False,
        "uses_live": False,
        "suppress_live": (),
        "surface_hint": None,
    }


def test_optional_tty_is_preference() -> None:
    def job(cfg: Cfg, tty: TTY | None = None) -> None: ...

    markers = extract_capability_markers(job)
    assert markers["requires_tty"] is False
    assert markers["optional_tty"] is True
    assert markers["uses_live"] is False


def test_optional_tty_via_typing_optional() -> None:
    def job(cfg: Cfg, tty: Optional[TTY] = None) -> None: ...  # noqa: UP045

    markers = extract_capability_markers(job)
    assert markers["optional_tty"] is True
    assert markers["requires_tty"] is False


def test_live_marks_uses_live() -> None:
    def job(cfg: Cfg, live: Live) -> None: ...

    markers = extract_capability_markers(job)
    assert markers["uses_live"] is True
    assert markers["requires_tty"] is False
    assert markers["optional_tty"] is False


def test_adaptive_job_declares_both() -> None:
    def job(cfg: Cfg, tty: TTY | None = None, live: Live | None = None) -> None: ...

    markers = extract_capability_markers(job)
    assert markers["optional_tty"] is True
    assert markers["uses_live"] is True
    assert markers["requires_tty"] is False


def test_plain_job_has_no_markers() -> None:
    def job(cfg: Cfg, count: int = 3) -> None: ...

    assert extract_capability_markers(job) == {
        "requires_tty": False,
        "optional_tty": False,
        "uses_live": False,
        "suppress_live": (),
        "surface_hint": None,
    }


def test_surface_hint_harvested() -> None:
    from functualize.job.decorators import surface_hint

    @surface_hint("stdout")
    def job(cfg: Cfg) -> None: ...

    assert extract_capability_markers(job)["surface_hint"] == "stdout"


def test_surface_hint_rejects_unknown_surface() -> None:
    from functualize.job.decorators import surface_hint

    with pytest.raises(ValueError):
        surface_hint("hologram")


def test_unresolvable_annotations_fall_back_to_raw_strings() -> None:
    # An undefined annotation makes get_type_hints raise, so the harvest falls
    # back to the raw signature strings — which must still classify TTY/Live.
    def job(cfg: NotARealType, tty: TTY | None = None) -> None: ...  # noqa: F821

    markers = extract_capability_markers(job)
    assert markers["optional_tty"] is True
    assert markers["requires_tty"] is False


# --- CLI-parameter exclusion (the companion invariant) ----------------------


def test_bare_tty_excluded_from_cli_params() -> None:
    def job(cfg: Cfg, tty: TTY) -> None: ...

    names = {p.name for p in extract_parameters_from_signature(job)}
    assert "tty" not in names
    assert "cfg" in names


def test_optional_tty_excluded_from_cli_params() -> None:
    # The Optional form is a Union, so name-based exclusion must unwrap it —
    # otherwise `tty` would leak in as a CLI field.
    def job(cfg: Cfg, tty: TTY | None = None) -> None: ...

    names = {p.name for p in extract_parameters_from_signature(job)}
    assert "tty" not in names


def test_live_excluded_from_cli_params() -> None:
    def job(cfg: Cfg, live: Live) -> None: ...

    names = {p.name for p in extract_parameters_from_signature(job)}
    assert "live" not in names
