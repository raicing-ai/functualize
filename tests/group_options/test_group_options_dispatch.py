"""T-GO-3 acceptance: mid-path parsing of group-declared flags.

Covers the plan's [A] criteria for T-GO-3:
- `func deploy --env prod web run` walks to `deploy.web.run`, consuming the
  flag the `deploy` group declares;
- an unknown mid-path flag still errors (model A preserved);
- positional disambiguation (D-d): a flag before the leaf is the group's, a
  flag after it is the job's.

The walk is tested directly (`walk_group_path`) *and* through the real CLI,
because the unit level cannot see the pre-filter — the defect that made the
first implementation silently do nothing lived there, not in the walk.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from functualize._cli.dispatch import walk_group_path
from functualize._primitives.pre_filter import GroupOptionsPreFilter
from functualize._types.descriptors import FieldDescriptor, GroupOptionsSpec
from functualize.app.utils import build_group_trie


def _spec(group: str, *fields: FieldDescriptor) -> GroupOptionsSpec:
    return GroupOptionsSpec(group=group, class_name="X", fields=list(fields))


def _field(
    name: str, type_annotation: str = "str", short: str | None = None
) -> FieldDescriptor:
    return FieldDescriptor(
        name=name,
        type_annotation=type_annotation,
        default=None,
        description="",
        required=False,
        short_flag=short,
    )


def _trie(**specs: GroupOptionsSpec):
    return build_group_trie(
        [("deploy.web", "deploy.web.run", "job")],
        groups=["deploy", "deploy.web"],
        builtin=False,
        group_options=dict(specs),
    )


# --- the walk -------------------------------------------------------------


def test_group_flag_is_consumed_and_the_walk_continues() -> None:
    trie = _trie(deploy=_spec("deploy", _field("env", short="-e")))

    walk = walk_group_path(trie, ["deploy", "--env", "prod", "web", "run"])

    assert walk.node.payload == "deploy.web.run"
    assert walk.options == {"env": "prod"}
    assert walk.remaining == ()
    assert walk.bad_flag is None


@pytest.mark.parametrize(
    "argv",
    [
        ["deploy", "--env", "prod", "web", "run"],
        ["deploy", "--env=prod", "web", "run"],
        ["deploy", "-e", "prod", "web", "run"],
    ],
)
def test_every_flag_spelling_reaches_the_same_place(argv: list[str]) -> None:
    trie = _trie(deploy=_spec("deploy", _field("env", short="-e")))

    walk = walk_group_path(trie, argv)

    assert walk.node.payload == "deploy.web.run"
    assert walk.options == {"env": "prod"}


def test_bool_flag_does_not_swallow_the_next_path_segment() -> None:
    """A presence flag must not eat `web`, or the walk never reaches the job."""
    trie = _trie(deploy=_spec("deploy", _field("dry_run", "bool")))

    walk = walk_group_path(trie, ["deploy", "--dry-run", "web", "run"])

    assert walk.node.payload == "deploy.web.run"
    assert walk.options == {"dry_run": True}


def test_underscored_field_accepts_both_spellings() -> None:
    trie = _trie(deploy=_spec("deploy", _field("dry_run", "bool")))

    assert walk_group_path(trie, ["deploy", "--dry-run", "web"]).options == {
        "dry_run": True
    }
    assert walk_group_path(trie, ["deploy", "--dry_run", "web"]).options == {
        "dry_run": True
    }


def test_unknown_mid_path_flag_stops_the_walk_and_is_reported() -> None:
    """Model A preserved: only *declared* flags are legal mid-path."""
    trie = _trie(deploy=_spec("deploy", _field("env")))

    walk = walk_group_path(trie, ["deploy", "--nope", "web", "run"])

    assert walk.bad_flag == "--nope"
    assert walk.node.payload is None, "the walk stopped at the `deploy` group"


def test_flag_declared_by_an_ancestor_is_inherited() -> None:
    trie = _trie(deploy=_spec("deploy", _field("env")))

    walk = walk_group_path(trie, ["deploy", "web", "--env", "prod", "run"])

    assert walk.options == {"env": "prod"}
    assert walk.node.payload == "deploy.web.run"


def test_a_flag_not_yet_in_scope_is_not_accepted() -> None:
    """`deploy.web`'s flag is not legal before the walk has reached it."""
    trie = _trie(web=_spec("deploy.web", _field("replicas")))

    walk = walk_group_path(trie, ["deploy", "--replicas", "3", "web", "run"])

    assert walk.bad_flag == "--replicas", "only consumed ancestors may declare"


def test_nearest_declaration_shadows_an_ancestor() -> None:
    trie = _trie(
        deploy=_spec("deploy", _field("env")),
        web=_spec("deploy.web", _field("env")),
    )

    walk = walk_group_path(trie, ["deploy", "web", "--env", "prod", "run"])

    assert walk.options == {"env": "prod"}


def test_flag_after_the_leaf_is_left_for_click() -> None:
    """D-d positional disambiguation: position is the scope delimiter."""
    trie = _trie(deploy=_spec("deploy", _field("env")))

    walk = walk_group_path(
        trie, ["deploy", "--env", "prod", "web", "run", "--env", "dev"]
    )

    assert walk.node.payload == "deploy.web.run"
    assert walk.options == {"env": "prod"}, "the group took only the first"
    assert walk.remaining == ("--env", "dev"), "the leaf's own flag is untouched"


def test_missing_value_is_reported_not_silently_dropped() -> None:
    trie = _trie(deploy=_spec("deploy", _field("env")))

    walk = walk_group_path(trie, ["deploy", "--env"])

    assert walk.bad_flag == "--env"


def test_walk_without_any_declarations_matches_model_a() -> None:
    trie = _trie()

    assert walk_group_path(trie, ["deploy", "--env", "prod"]).bad_flag == "--env"
    assert walk_group_path(trie, ["deploy", "web", "run"]).node.payload == (
        "deploy.web.run"
    )


# --- the pre-filter (the defect the unit level could not see) --------------


class TestGroupOptionsPreFilter:
    """The declaration module must survive the pre-filter stack.

    `DefaultModulePreFilter` skips `_`-prefixed files and `ASTModulePreFilter`
    requires a public function — a declaration-only `_group.py` fails both.
    Without the exemption the whole feature silently does nothing, which is
    exactly how the first implementation failed.
    """

    def _write(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "_group.py"
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        return path

    def test_detects_a_group_options_declaration(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
            from functualize.job import GroupOptions

            class DeployOptions(GroupOptions, group="deploy"):
                env: str = "staging"
            """,
        )
        assert GroupOptionsPreFilter().should_import(path) is True

    def test_detects_a_dotted_base(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
            from functualize import job

            class DeployOptions(job.GroupOptions, group="deploy"):
                env: str = "staging"
            """,
        )
        assert GroupOptionsPreFilter().should_import(path) is True

    def test_ignores_an_unrelated_module(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
            class Helper:
                pass

            def _private():
                return 1
            """,
        )
        assert GroupOptionsPreFilter().should_import(path) is False

    def test_unparseable_file_is_not_imported(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, "class Broken(:\n")
        assert GroupOptionsPreFilter().should_import(path) is False

    def test_stack_admits_a_declaration_only_underscore_module(
        self, tmp_path: Path
    ) -> None:
        """The composed stack — not just the leaf filter — must let it through."""
        from functualize._discovery.filter_factory import build_pre_filter_from_config
        from functualize.app.config import DiscoveryConfig

        path = self._write(
            tmp_path,
            """
            from functualize.job import GroupOptions

            class DeployOptions(GroupOptions, group="deploy"):
                env: str = "staging"
            """,
        )
        pre_filter = build_pre_filter_from_config(DiscoveryConfig(), tmp_path)

        assert pre_filter.should_import(path) is True

    def test_stack_still_skips_an_ordinary_private_module(self, tmp_path: Path) -> None:
        """The exemption must not reopen `_helpers.py` to the job scan."""
        from functualize._discovery.filter_factory import build_pre_filter_from_config
        from functualize.app.config import DiscoveryConfig

        path = self._write(
            tmp_path,
            """
            def helper():
                return 1
            """,
        )
        pre_filter = build_pre_filter_from_config(DiscoveryConfig(), tmp_path)

        assert pre_filter.should_import(path) is False
