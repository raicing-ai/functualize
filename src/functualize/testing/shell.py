"""FakeShell — a test double for the ``Shell`` capability (proposal §B.7).

Records calls, answers from a pattern→result table, and fails loudly on
unexpected commands, so jobs that shell out can be unit-tested without spawning
processes::

    fake = FakeShell({
        "git rev-parse HEAD": ShellResult(0, "abc123\\n", "", "git rev-parse HEAD", 1.0),
        re.compile(r"docker build .*"): ShellResult(0, "", "", "docker build", 1.0),
    })
    run_job(deploy, shell=fake)
    assert fake.calls[0].argv[:2] == ["docker", "build"]
"""

from __future__ import annotations

import os
import re
import shlex
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

from functualize._types.redaction import reveal
from functualize._types.shell import ShellError, ShellResult


@dataclass(frozen=True)
class FakeShellCall:
    """A recorded ``FakeShell`` invocation.

    Attributes:
        argv: The resolved argument vector (list form, or the split display).
        command: The display string the command resolved to.
        kwargs: The keyword options passed to the call.
    """

    argv: list[str]
    command: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class FakeShell:
    """A scripted, recording stand-in for the ``Shell`` capability.

    Args:
        mapping: Maps an exact command string or a compiled regex to the
            ``ShellResult`` to return. The command's display form is matched
            against string keys by equality and against regex keys by
            ``search``.
    """

    def __init__(self, mapping: dict[Any, ShellResult] | None = None) -> None:
        self._mapping: dict[Any, ShellResult] = dict(mapping or {})
        self.calls: list[FakeShellCall] = []
        self._cd_stack: list[str] = []
        self._prefix_stack: list[list[str]] = []
        self._deferred: list[tuple[list[str] | str, dict[str, Any]]] = []

    def __call__(
        self,
        command: list[str] | str,
        *,
        check: bool = True,
        **kwargs: Any,
    ) -> ShellResult:
        """Resolve, record, and answer a command from the mapping.

        Raises:
            AssertionError: If no mapping entry matches (loud on unexpected).
        """
        argv, display = self._resolve(command)
        argv, display = self._apply_prefix(argv, display)
        # An active `cd` block shows up the way the real shell applies it: as
        # the call's effective working directory. Recorded rather than folded
        # into the display, so mapping keys stay the command a job wrote.
        cwd = self._effective_cwd(kwargs.get("cwd"))
        if cwd is not None:
            kwargs = {**kwargs, "cwd": cwd}
        self.calls.append(FakeShellCall(argv=argv, command=display, kwargs=kwargs))

        result = self._lookup(display)
        if result is None:
            raise AssertionError(
                f"FakeShell received an unexpected command: {display!r}. "
                f"Known commands: {[self._key_repr(k) for k in self._mapping]}"
            )
        if check and result.returncode != 0:
            raise ShellError(result)
        return result

    def sudo(self, command: list[str], **kwargs: Any) -> ShellResult:
        """Record a ``sudo``-prefixed call and answer it from the mapping.

        Mirrors :meth:`WiredShell.sudo` for testability: the recorded command is
        ``sudo <command>`` (no ``-S``/password machinery — a fake never spawns a
        real sudo). ``preserve_env``/``password``/``watchers`` are accepted and
        ignored. Match ``sudo <command>`` in the mapping like any other command.
        """
        if not isinstance(command, (list, tuple)):
            raise ValueError("FakeShell.sudo requires the list command form.")
        for sudo_only in ("preserve_env", "password", "watchers"):
            kwargs.pop(sudo_only, None)
        return self(["sudo", *command], **kwargs)

    # ── The scoping and cleanup surface (§B.3, §B.5) ───────────────────────
    #
    # A test double is only a stand-in for the surface it covers. These four
    # were on `WiredShell` and not here, so a job using the documented
    # `with sh.cd(...)` idiom could not be unit-tested with `FakeShell` at all —
    # and once the `Shell` protocol grew them (it had been missing them too),
    # `isinstance(FakeShell(), Shell)` went False, which is how this was found.

    @contextmanager
    def cd(self, path: str) -> Iterator[None]:
        """Record commands in the block as running in ``path`` (§B.3).

        Nestable, resolving relative to the enclosing one, exactly as
        ``WiredShell.cd`` does. The effective directory lands on each recorded
        call's ``kwargs["cwd"]``, so a test can assert *where* a command ran
        without the fake spawning anything.
        """
        self._cd_stack.append(str(path))
        try:
            yield
        finally:
            self._cd_stack.pop()

    @contextmanager
    def prefix(self, command: list[str] | str) -> Iterator[None]:
        """Prepend ``command`` to every command in the block (§B.3).

        The prefix is applied **before** matching, because the real shell runs
        the prefixed argv — so a mapping keyed on ``poetry run pytest`` is what
        matches inside ``with sh.prefix(["poetry", "run"])``. Folding it in
        afterwards would let a test pass against a command that never ran.
        """
        tokens = (
            list(command)
            if isinstance(command, (list, tuple))
            else shlex.split(command)
        )
        self._prefix_stack.append([str(t) for t in tokens])
        try:
            yield
        finally:
            self._prefix_stack.pop()

    def defer(self, command: list[str] | str, **kwargs: Any) -> None:
        """Queue a cleanup command, as ``WiredShell.defer`` does (§B.5).

        Nothing runs until :meth:`run_deferred`. In a real run the engine calls
        that on the job-exit unwind; in a test, call it yourself — or assert on
        :attr:`deferred` to check *what* a job registered without running it.
        """
        self._deferred.append((command, dict(kwargs)))

    @property
    def deferred(self) -> list[list[str] | str]:
        """The cleanup commands queued so far, in registration order."""
        return [command for command, _kwargs in self._deferred]

    def run_deferred(self) -> None:
        """Run and clear the queued cleanups, LIFO.

        ``check=False`` by default, like the real unwind: a cleanup that fails
        must not mask the job's own outcome. Unlike the real unwind, an
        unexpected command still raises — a fake that silently swallowed an
        unmapped cleanup would be a fake that cannot be asserted on.
        """
        while self._deferred:
            command, kwargs = self._deferred.pop()
            kwargs.setdefault("check", False)
            self(command, **kwargs)

    def _effective_cwd(self, call_cwd: str | None) -> str | None:
        """Per-call ``cwd`` wins, else the `cd` stack joined."""
        if call_cwd is not None:
            return call_cwd
        base: str | None = None
        for segment in self._cd_stack:
            base = os.path.join(base, segment) if base else segment
        return base

    def _apply_prefix(self, argv: list[str], display: str) -> tuple[list[str], str]:
        """Prepend all active prefixes (outer→inner) to argv and display."""
        prefix: list[str] = []
        for entry in self._prefix_stack:
            prefix.extend(entry)
        if not prefix:
            return argv, display
        return [*prefix, *argv], " ".join([*prefix, *shlex.split(display)])

    def _resolve(self, command: list[str] | str) -> tuple[list[str], str]:
        """Resolve a command to ``(argv, display)`` for matching and recording."""
        if isinstance(command, (list, tuple)):
            argv = [reveal(a) for a in command]
            return argv, shlex.join(argv)
        text = str(command)
        try:
            argv = shlex.split(text)
        except ValueError:
            argv = [text]
        return argv, text

    def _lookup(self, display: str) -> ShellResult | None:
        for key, result in self._mapping.items():
            if isinstance(key, re.Pattern):
                if key.search(display):
                    return result
            elif key == display:
                return result
        return None

    @staticmethod
    def _key_repr(key: Any) -> str:
        return key.pattern if isinstance(key, re.Pattern) else str(key)
