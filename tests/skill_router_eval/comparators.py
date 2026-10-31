"""The four comparators, and the one that reads a real agent.

``KeywordTable`` is this instrument's deterministic baseline: a table of regular
expressions written from the five catalog meanings **before** a single scenario
existed, first match wins, one hot distribution when it matches and an honest
"no idea" when it does not. Its honesty is the point — a no-match proposes
`none` at 0.20, below the gate's 0.70, so the walk escalates rather than
claiming an answer it does not have.

``NativeRouter`` is not a provider: it drives the real router provider
(`evals/providers/claude_router.py`) against a real agent, which is what the
native arm measures. It is a plain adapter because nothing about that run is a
probability distribution — the agent either loaded a skill or it did not — and
giving it a fake one would put it through a threshold it cannot honour.

The hermetic and frontier comparators are Phase 3's, re-exported rather than
re-implemented: the two phases must measure with the same instrument, and a
second copy of a comparator is a second instrument.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

from functualize.plugin import (
    ChoiceRequest,
    DecisionProvenance,
    DecisionResult,
)
from tests.hermetic_eval.comparators import (
    FrontierCall,
    FrontierRouter,
    hermetic,
    hermetic_identity,
    identity_sha256,
)
from tests.skill_router_eval.catalog import NONE, SKILLS
from tests.skill_router_eval.selection import ESCALATED

__all__ = [
    "KEYWORDS",
    "MAX_TURNS_SUBTYPE",
    "NATIVE_CONFIG",
    "FrontierCall",
    "FrontierRouter",
    "KeywordTable",
    "NativeCell",
    "NativeOverrideError",
    "NativeRouter",
    "hermetic",
    "hermetic_identity",
    "identity_sha256",
]

#: Repository root, from ``tests/skill_router_eval/comparators.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The native arm's provider, loaded by path so the instrument measures the
#: same file the suite does.
_PROVIDER = "evals/providers/claude_router.py"

#: The module the provider is registered under, so it is imported exactly once.
_PROVIDER_MODULE = "skill_router_native_reference"

#: The model a keyword answer is attributed to: there is no model.
_KEYWORDS_MODEL = "keywords-v1"

#: The table's rules, ``(option, pattern)``, first match wins. Written from the
#: five meanings in ``catalog.py`` and from nothing else — no scenario, no
#: report, no failure seen in a run. The first two entries exist because the CLI
#: meaning is the only one about the tool's own installation and location, and
#: "not found" is what a missing tool says about itself.
KEYWORDS: tuple[tuple[str, str], ...] = (
    (
        "functualize-cli",
        r"\b(func|functualize)[\w-]*\b[^.]{0,60}"
        r"\b(command not found|(command )?not found|not installed|installed|installing|install"
        r"|uninstall|upgrade|downgrade|version|completion|PATH|which|where)\b",
    ),
    (
        "functualize-cli",
        r"\b(install|uninstall|reinstall|upgrade|downgrade|version of)\b"
        r"[^.]{0,40}\b(func|functualize)\b",
    ),
    (
        "functualize-cli",
        r"\b(shell completion|tab completion|autocomplete|config(uration)?"
        r" (dir|directory|path)|data (dir|directory)|cache (dir|directory)"
        r"|state (dir|directory))\b",
    ),
    (
        "functualize-skill",
        r"\b(agent )?skill\b[^.]{0,60}\b(SKILL\.md|frontmatter|author|write"
        r"|create|bundl(e|ed|es|ing) (a )?(script|file)|instructions)\b",
    ),
    (
        "functualize-skill",
        r"\b(write|create|author|add|make)\b[^.]{0,40}\b(agent )?skill\b",
    ),
    ("functualize-skill", r"\bSKILL\.md\b"),
    (
        "functualize-app",
        r"\b(scaffold|project (layout|structure)|whole (cli|tui|app|program)"
        r"|new (cli|tui) (app|program)|build a (cli|tui)|production ready"
        r"|pyproject|entry point|package (it|the (app|program)))\b",
    ),
    (
        "functualize-app",
        r"\b(tests?|test suite|pytest)\b[^.]{0,40}\b(app|program|project)\b",
    ),
    (
        "functualize",
        r"\b(jobs?\.py|job function|RunContext|rc\.(log|invoke|prompt|state"
        r"|stdout|shell|live)|@job|func run|func builtin|builtin info"
        r"|discover(y|ed)|job config|credentials?|capabilit(y|ies))\b",
    ),
)

#: The native arm's pinned run configuration: the values ``triggering.yaml``
#: has always used for the router probe, so the two measurements are comparable.
NATIVE_CONFIG: Mapping[str, object] = MappingProxyType(
    {"model": "claude-sonnet-5", "max_turns": 3, "timeout_s": 180, "sandbox": "host"}
)

#: The `result` event's subtype when the turn budget stopped the agent. Read
#: from a live run (T2 step 0), not guessed: a turn-budget stop still reports
#: what it loaded, so it is a cell with a cost — not a failed one.
MAX_TURNS_SUBTYPE = "error_max_turns"

#: The tools the native arm is allowed; the provider's own list, for identity.
_DEFAULT_TOOLS = ("Skill", "Read", "Glob", "Grep")

class NativeOverrideError(RuntimeError):
    """An environment override asked for a run the pin does not describe."""

class KeywordTable:
    """The deterministic comparator: one regex pass over the state, no model."""

    name: str = "deterministic"

    def choose(self, request: ChoiceRequest) -> DecisionResult[str]:
        started = time.monotonic()
        options = list(request.options)
        chosen: str | None = None
        for option, pattern in KEYWORDS:
            if option in options and re.search(pattern, request.state, re.IGNORECASE):
                chosen = option
                break
        if chosen is None:
            chosen = NONE if NONE in options else options[-1]
            share = 1.0 / len(options)
            distribution = dict.fromkeys(options, share)
        else:
            distribution = {
                option: (1.0 if option == chosen else 0.0) for option in options
            }
        elapsed = time.monotonic() - started
        return DecisionResult(
            value=chosen,
            provider=self.name,
            model=_KEYWORDS_MODEL,
            provenance=DecisionProvenance(_KEYWORDS_MODEL, latency_seconds=elapsed),
            distribution=distribution,
            confidence=None,
        )

    def identity(self) -> dict[str, object]:
        table = json.dumps([list(rule) for rule in KEYWORDS]).encode("utf-8")
        return {
            "comparator": self.name,
            "keywords_sha256": sha256(table).hexdigest(),
        }

def _load_provider() -> ModuleType:
    """Import ``evals/providers/claude_router.py`` by path, once per process."""
    loaded = sys.modules.get(_PROVIDER_MODULE)
    if loaded is not None:
        return loaded
    path = _REPO_ROOT / _PROVIDER
    spec = importlib.util.spec_from_file_location(_PROVIDER_MODULE, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the router provider from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_PROVIDER_MODULE] = module
    spec.loader.exec_module(module)
    return module

@dataclass(frozen=True)
class NativeCell:
    """One native run, as the provider reported it.

    ``route`` is an ``OPTIONS`` value, or :data:`ESCALATED` for a failed cell.
    ``failed`` is ``None`` for a cell that produced an answer. Everything else
    is verbatim from the provider, so a report never has to reconstruct what a
    run did.
    """

    route: str
    failed: Mapping[str, str] | None
    selected: str | None
    error: str | None
    model: str | None
    cost_usd: float | None
    latency_seconds: float

class NativeRouter:
    """The native comparator: the real router provider, one round trip per call.

    Not a ``DecisionProvider``: the agent selects a skill or nothing, and there
    is no distribution to threshold. Constructing one spawns nothing — only
    :meth:`select` calls the provider.
    """

    name: str = "native"

    def __init__(
        self,
        *,
        call_api: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]
        | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        environment = os.environ if environ is None else environ
        self._refuse_overrides(environment)
        self._call_api = call_api if call_api is not None else _load_provider().call_api

    @staticmethod
    def _refuse_overrides(environment: Mapping[str, str]) -> None:
        pinned = {
            "FZ_EVAL_MODEL": NATIVE_CONFIG["model"],
            "FZ_EVAL_SANDBOX": NATIVE_CONFIG["sandbox"],
        }
        for name, value in pinned.items():
            given = environment.get(name)
            if given is not None and given != value:
                raise NativeOverrideError(
                    f"override refused: {name}={given!r} is not the pinned "
                    f"{value!r}; the native arm measures one configuration"
                )

    def select(self, state: str) -> NativeCell:
        """Run the provider once, reading its response in the contract's order."""
        started = time.monotonic()
        response = self._call_api(state, {"config": dict(NATIVE_CONFIG)}, {})
        elapsed = time.monotonic() - started

        top_error = response.get("error")
        if "output" not in response:
            return NativeCell(
                route=ESCALATED,
                failed={
                    "kind": "setup_error",
                    "message": str(top_error) if top_error is not None else "no output",
                },
                selected=None,
                error=str(top_error) if top_error is not None else None,
                model=None,
                cost_usd=None,
                latency_seconds=elapsed,
            )

        out = response["output"] or {}
        cost = float(response["cost"])
        selected = out.get("selected")
        error = out.get("error")
        model = out.get("model")

        failed: dict[str, str] | None = None
        if error is not None and error != MAX_TURNS_SUBTYPE:
            failed = {"kind": "run_error", "message": str(error)}
        elif selected is not None and selected not in SKILLS:
            failed = {"kind": "unknown_skill", "message": str(selected)}
        route = ESCALATED
        if failed is None:
            route = NONE if selected is None else selected
        return NativeCell(
            route=route,
            failed=failed,
            selected=selected,
            error=str(error) if error is not None else None,
            model=model,
            cost_usd=cost,
            latency_seconds=elapsed,
        )

    def identity(self) -> dict[str, object]:
        """C-3's native identity: the pinned config, the tools, and the bytes."""
        provider = _REPO_ROOT / _PROVIDER
        module = _load_provider()
        tools = list(getattr(module, "ROUTER_TOOLS", _DEFAULT_TOOLS))
        return {
            "comparator": self.name,
            "provider": _PROVIDER,
            "config": dict(NATIVE_CONFIG),
            "tools": tools,
            "env_overrides": "refused",
            "provider_sha256": sha256(provider.read_bytes()).hexdigest(),
        }
