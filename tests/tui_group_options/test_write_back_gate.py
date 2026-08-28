"""The gate that was written down as a manual grep, made mechanical.

ADR-009 lists among its positive consequences that

    the grep gate (`tokens[0]` → exactly 3 sanctioned sites, `tokens[1:]` → 1,
    `panels/` → 0) makes the root-cause class of defect **mechanically
    detectable** rather than a matter of review attention

and `contributor/guides/tui-panels.md` §11 records the two commands to run. But
nothing ran them. A recipe in a guide is detectable by a reader who thinks to
look, which is precisely the "review attention" the sentence claims to have
replaced — and the review that produced this file found a fourth write-back
defect sitting behind a *fourth* unenforced rule.

So the gate is a test. Every rule below is a real invariant of the shell's
command handling, and each one failed at least once on this branch.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_TUI = Path(__file__).parent.parent.parent / "src" / "functualize" / "_cli" / "tui"

#: ``file:line`` for each place allowed to read the bar's first token as a
#: command. Pinned to the line's *content*, not its number, so a reformat does
#: not fail the gate and a genuinely new site cannot hide behind a shifted one.
SANCTIONED_TOKENS_0 = {
    # The one owner of "no trie → flat". Route degradations through it.
    (
        "cli_arg_parser.py",
        "return TuiCommandResolution(tokens[0], list(tokens[1:]), {})",
    ),
    # Can only ever match the reserved builtin node.
    ("job_execution.py", "if _is_non_job_command(app, tokens[0]):"),
    # Resolver-backed: the fallback only runs when the walk found nothing.
    ("app.py", "job_name = _preflight_resolution.job_name or tokens[0]"),
    # The builtin fallback. Reached only when the walk resolved nothing *and*
    # `is_non_job_command` confirmed the head names a builtin — which the trie
    # holds no node for and never will, because the CLI's own walk does not
    # know about builtins either.
    ("bar.py", "head = tokens[0]"),
}

#: The same, for the tail slice: "everything after the command is its
#: arguments" is true only where there is no path to walk.
SANCTIONED_TOKENS_TAIL = {
    (
        "cli_arg_parser.py",
        "return TuiCommandResolution(tokens[0], list(tokens[1:]), {})",
    ),
    # Paired with the sanctioned `tokens[0]` above, and only reachable with it.
    ("bar.py", "args = list(tokens[1:])"),
}


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _hits(needle: str, root: Path) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in _python_files(root):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if needle in stripped and not stripped.startswith("#"):
                found.add((path.name, stripped))
    return found


class TestNoNewSiteReadsTheBarsFirstTokenAsTheJob:
    """One cause, nine defects: `tokens[0]` is the *group* under a group."""

    def test_only_the_sanctioned_sites_index_token_zero(self) -> None:
        hits = _hits("tokens[0]", _TUI)
        unexpected = hits - SANCTIONED_TOKENS_0
        assert not unexpected, (
            "a new site reads the bar's first token as the command. Under a "
            "group that token is the group, which is what produced the nine "
            "defects ADR-009 records. Resolve with `resolve_tui_command` "
            f"instead, or add a justification here:\n  {sorted(unexpected)}"
        )

    def test_the_sanctioned_sites_still_exist(self) -> None:
        """A pin that silently stops matching stops gating."""
        hits = _hits("tokens[0]", _TUI)
        assert hits >= SANCTIONED_TOKENS_0, (
            "a sanctioned site was moved or reworded; re-check whether it is "
            f"still correct, then update the pin:\n  {sorted(SANCTIONED_TOKENS_0 - hits)}"
        )

    def test_only_the_resolver_slices_the_tail(self) -> None:
        """`tokens[1:]` is the job's arguments only when there is no path."""
        hits = _hits("tokens[1:]", _TUI)
        unexpected = hits - SANCTIONED_TOKENS_TAIL
        assert not unexpected, (
            "a new site treats the tail as the job's arguments. Under a group "
            "the tail still holds path segments and mid-path group flags; use "
            f"`resolution.args`:\n  {sorted(unexpected)}"
        )
        assert hits >= SANCTIONED_TOKENS_TAIL, sorted(SANCTIONED_TOKENS_TAIL - hits)

    def test_no_panel_resolves_a_command_for_itself(self) -> None:
        """A panel renders; it does not decide what the bar means."""
        hits = _hits("tokens[0]", _TUI / "panels") | _hits(
            "tokens[1:]", _TUI / "panels"
        )
        assert not hits, sorted(hits)


class TestOneTokenizer:
    """The emitters quote; a reader that splits on whitespace un-quotes wrong.

    `str.split()` on bar text is the inverse of no emitter this package has.
    `tokenize_bar_text` is, and it is the only thing allowed to do the job.
    """

    def test_no_module_splits_bar_text_by_hand(self) -> None:
        offenders: list[tuple[str, str]] = []
        for path in _python_files(_TUI):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if any(
                    frag in stripped
                    for frag in (
                        "text.split()",
                        "value.split()",
                        "bar_text.split()",
                        "_smart_bar.value.split()",
                    )
                ):
                    offenders.append((path.name, stripped))
        assert not offenders, (
            "bar text must be tokenized with `tokenize_bar_text`, which is "
            "shlex-based and therefore the inverse of what the emitters "
            f"write:\n  {offenders}"
        )


class TestEveryFieldDefConstructorCarriesTheWires:
    """`wiring-discipline.md` §8 and `tui-panels.md` §13–§14, checked rather
    than remembered.

    A `FieldDef` built without `secret=` prints a credential in the clear;
    one built without `group_path=` files a group's flag under the job, which
    is what `sync_overrides_to_bar` then emits at the wrong position. Both are
    silent, and both are one dropped keyword.
    """

    @pytest.mark.parametrize("kwarg", ["secret", "group_path"])
    def test_the_group_row_builder_passes_it(self, kwarg: str) -> None:
        source = (_TUI / "chain_resolution.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        builder = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_group_field_defs"
        )
        calls = [
            node
            for node in ast.walk(builder)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "FieldDef"
        ]
        assert calls, "build_group_field_defs no longer constructs a FieldDef"
        for call in calls:
            assert kwarg in {kw.arg for kw in call.keywords}, (
                f"a FieldDef built for a group row without `{kwarg}=`. It "
                f"rides in on the cached descriptor for free; dropping it "
                f"leaks a credential (secret) or misplaces a flag (group_path)."
            )
