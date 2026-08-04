"""Unit tests for the group trie (`_types/naming.py`, convergence A3.1).

The trie supplies namespace *shape*; every single-segment naming decision
delegates to `resolve_name`, which has its own tests in `test_naming.py`. What
is tested here is the shape: nesting, duality, the reserved `builtin` subtree,
collisions, and how far a token walk gets.
"""

from __future__ import annotations

import pytest

from functualize._types.naming import (
    BUILTIN_SEGMENT,
    GroupTrie,
    NodeKind,
)

# (dotted_group_or_None, canonical_name, kind) — `canonical_name` is the full
# dotted name a JobDescriptor carries, which is what the cache holds.
FIXTURE_JOBS: list[tuple[str | None, str, str]] = [
    (None, "top-level", "job"),
    ("deploy", "deploy.web", "job"),
    ("deploy", "deploy.api", "job"),
    ("infra.aws", "infra.aws.provision-it", "job"),
    ("infra.gcp", "infra.gcp.provision-it", "job"),
]


def _trie(jobs=None, plugins=(), *, builtin=True) -> GroupTrie:
    return GroupTrie.from_cache(
        FIXTURE_JOBS if jobs is None else jobs, plugins, builtin=builtin
    )


class TestBuild:
    def test_top_level_job_is_a_root_child(self) -> None:
        node = _trie().root.children["top-level"]
        assert node.payload == "top-level"
        assert node.kind is NodeKind.JOB
        assert node.is_leaf

    def test_group_prefix_is_stripped_to_form_the_leaf(self) -> None:
        """`name` is the full dotted path, so the leaf is name-minus-group.

        Splitting the group and then appending the whole name would build
        `infra/aws/infra.aws.provision-it`.
        """
        aws = _trie().root.children["infra"].children["aws"]
        assert sorted(aws.children) == ["provision-it"]
        assert aws.children["provision-it"].payload == "infra.aws.provision-it"

    def test_nested_groups_nest_per_segment(self) -> None:
        root = _trie().root
        infra = root.children["infra"]
        assert infra.kind is NodeKind.GROUP
        assert infra.payload is None
        assert sorted(infra.children) == ["aws", "gcp"]
        assert infra.children["aws"].path == ("infra", "aws")

    def test_same_leaf_in_two_groups_does_not_collide(self) -> None:
        trie = _trie()
        assert (
            trie.root.children["infra"].children["aws"].children["provision-it"].payload
            == "infra.aws.provision-it"
        )
        assert (
            trie.root.children["infra"].children["gcp"].children["provision-it"].payload
            == "infra.gcp.provision-it"
        )

    def test_builtin_node_is_seeded_and_can_be_suppressed(self) -> None:
        assert _trie().root.children[BUILTIN_SEGMENT].kind is NodeKind.BUILTIN
        assert BUILTIN_SEGMENT not in _trie(builtin=False).root.children

    def test_plugin_namespace_becomes_a_top_level_node(self) -> None:
        trie = _trie(plugins=[("mcp", "serve"), ("mcp", "tools"), (None, "solo")])
        mcp = trie.root.children["mcp"]
        assert sorted(mcp.children) == ["serve", "tools"]
        assert mcp.children["serve"].kind is NodeKind.PLUGIN
        assert mcp.children["serve"].payload == "mcp.serve"
        assert trie.root.children["solo"].payload == "solo"

    def test_matrix_row_is_a_leaf_sibling_of_its_base(self) -> None:
        """Matrix expansion is deferred (S7); the trie ingests the row shape.

        The bracketed suffix is carried verbatim — notably it is NOT split on
        the dot inside `version=1.2`, because the leaf is derived by stripping
        the group prefix rather than by `rsplit(".")`.
        """
        trie = _trie(
            jobs=[
                (None, "deploy", "job"),
                (None, "deploy[env=dev]", "matrix"),
                ("release", "release.ship[version=1.2]", "matrix"),
            ]
        )
        assert trie.root.children["deploy[env=dev]"].kind is NodeKind.MATRIX
        assert "ship[version=1.2]" in trie.root.children["release"].children


class TestReservedAndCollisions:
    @pytest.mark.parametrize(
        ("jobs", "plugins"),
        [
            ([(None, "builtin", "job")], ()),
            ([("builtin", "builtin.thing", "job")], ()),
            ([], [("builtin", "thing")]),
            ([], [(None, "builtin")]),
        ],
        ids=["job", "group", "plugin-namespace", "plugin-command"],
    )
    def test_builtin_is_reserved_against_every_claimant(self, jobs, plugins) -> None:
        with pytest.raises(ValueError, match="reserved top-level name"):
            GroupTrie.from_cache(jobs, plugins)

    def test_job_and_plugin_command_claiming_one_path_raises(self) -> None:
        with pytest.raises(ValueError, match="collides with"):
            GroupTrie.from_cache([(None, "serve", "job")], [(None, "serve")])

    def test_two_jobs_claiming_one_path_raises(self) -> None:
        with pytest.raises(ValueError, match="collides with"):
            GroupTrie.from_cache([(None, "dup", "job"), (None, "dup", "job")], ())

    def test_a_namespace_may_overlap_a_job_node(self) -> None:
        """`mcp` job + `mcp serve` plugin command is duality, not collision.

        Only two *payloads* on one path collide. This mirrors the shipped
        `check_name_conflicts`, which raises only for a top-level (namespace
        is None) plugin command whose name equals a job's.
        """
        trie = GroupTrie.from_cache([(None, "mcp", "job")], [("mcp", "serve")])
        mcp = trie.root.children["mcp"]
        assert mcp.payload == "mcp"
        assert mcp.has_payload and not mcp.is_leaf
        assert mcp.children["serve"].payload == "mcp.serve"

    def test_empty_segment_raises(self) -> None:
        with pytest.raises(ValueError, match="empty path segment"):
            GroupTrie.from_cache([("a..b", "a..b.thing", "job")], ())


class TestResolve:
    def test_exact_path(self) -> None:
        r = _trie().resolve(["infra", "aws", "provision-it"])
        assert r.node.payload == "infra.aws.provision-it"
        assert r.remaining == ()
        assert r.is_group_listing is False

    def test_python_spelling_resolves_through_every_segment(self) -> None:
        """Delegation to `resolve_name` applies per segment, not just the last."""
        r = _trie().resolve(["infra", "aws", "provision_it"])
        assert r.node.payload == "infra.aws.provision-it"

    def test_partial_path_lands_on_the_group(self) -> None:
        r = _trie().resolve(["infra"])
        assert r.node.segment == "infra"
        assert r.remaining == ()
        assert r.is_group_listing is True

    def test_unknown_first_segment_returns_the_root(self) -> None:
        """R2-3: the unknown-command test is `node is root and remaining`."""
        trie = _trie()
        r = trie.resolve(["nope", "further"])
        assert r.node is trie.root
        assert r.remaining == ("nope", "further")

    def test_bare_root(self) -> None:
        trie = _trie()
        r = trie.resolve([])
        assert r.node is trie.root
        assert r.remaining == ()
        assert r.is_group_listing is True

    def test_trailing_unknown_token_stops_the_walk(self) -> None:
        r = _trie().resolve(["infra", "aws", "provision-it", "extra"])
        assert r.node.payload == "infra.aws.provision-it"
        assert r.remaining == ("extra",)

    def test_a_flag_terminates_the_path_in_phase_a(self) -> None:
        r = _trie().resolve(["deploy", "--env", "prod"])
        assert r.node.segment == "deploy"
        assert r.remaining == ("--env", "prod")

    def test_a_flag_before_a_real_child_still_terminates(self) -> None:
        """The trie stays flag-agnostic: it terminates at *any* flag mid-path.

        Global flags belong before the group name; a flag that reaches the walk
        is a placement error the dispatch layer rejects (`_dispatch_group`), not
        something the trie skips. (An earlier D1 draft stripped known globals
        before the walk via `split_midpath_globals`; that was removed in favor
        of this simpler, idiomatic rule.)
        """
        r = _trie().resolve(["deploy", "--verbose", "web"])
        assert r.node.segment == "deploy"
        assert r.remaining == ("--verbose", "web")


class TestNodeDuality:
    """A `deploy` job that also has `deploy web` beneath it (spec §2.A(5))."""

    def _dual(self) -> GroupTrie:
        return GroupTrie.from_cache(
            [(None, "deploy", "job"), ("deploy", "deploy.web", "job")], ()
        )

    def test_the_node_is_both_payload_and_group(self) -> None:
        node = self._dual().root.children["deploy"]
        assert node.has_payload and not node.is_leaf
        assert node.kind is NodeKind.JOB

    @pytest.mark.parametrize(
        ("argv", "expected_remaining"),
        [
            (["deploy"], ()),
            (["deploy", "--env", "prod"], ("--env", "prod")),
            (["deploy", "not-a-child"], ("not-a-child",)),
        ],
        ids=["bare", "flag", "non-flag-non-child"],
    )
    def test_the_payload_runs_in_all_three_cases(
        self, argv, expected_remaining
    ) -> None:
        r = self._dual().resolve(argv)
        assert r.node.payload == "deploy"
        assert r.remaining == expected_remaining
        assert r.is_group_listing is False

    def test_a_child_is_consumed_before_the_duality_decision(self) -> None:
        r = self._dual().resolve(["deploy", "web"])
        assert r.node.payload == "deploy.web"
        assert r.is_group_listing is False


class TestChildren:
    def test_root_children_sorted(self) -> None:
        assert [n.segment for n in _trie().children()] == [
            BUILTIN_SEGMENT,
            "deploy",
            "infra",
            "top-level",
        ]

    def test_children_of_a_nested_path(self) -> None:
        assert [n.segment for n in _trie().children(["infra", "aws"])] == [
            "provision-it"
        ]

    def test_children_normalizes_the_path(self) -> None:
        assert [n.segment for n in _trie().children(["infra", "AWS"])] == [
            "provision-it"
        ]

    def test_unknown_path_yields_no_children(self) -> None:
        assert _trie().children(["nope"]) == []

    def test_leaf_has_no_children(self) -> None:
        assert _trie().children(["top-level"]) == []


class TestDottedTokens:
    """A dotted token addresses a path, and matches all-or-nothing.

    `func infra.aws launch` was a supported spelling before the trie (dispatch
    joined segments with dots and matched the joined string), so the walk has
    to accept it. All-or-nothing is what keeps `remaining` meaningful: it is
    counted in tokens, and a half-consumed token has no sensible leftover.
    """

    def test_dotted_token_walks_the_same_path_as_separate_tokens(self) -> None:
        dotted = _trie().resolve(["infra.aws", "provision-it"])
        split = _trie().resolve(["infra", "aws", "provision-it"])
        assert dotted.node.payload == split.node.payload == "infra.aws.provision-it"
        assert dotted.remaining == split.remaining == ()

    def test_fully_dotted_token_reaches_a_group(self) -> None:
        r = _trie().resolve(["infra.aws"])
        assert r.node.path == ("infra", "aws")
        assert r.remaining == ()
        assert r.is_group_listing is True

    def test_partially_matching_dotted_token_is_not_consumed(self) -> None:
        """`infra.nope` must not leave the walk sitting on `infra`.

        Consuming the resolvable prefix would report the token as matched and
        drop the part that was wrong — the caller could no longer say which
        name it failed on.
        """
        trie = _trie()
        r = trie.resolve(["infra.nope"])
        assert r.node is trie.root
        assert r.remaining == ("infra.nope",)

    def test_a_dotted_token_past_a_leaf_stays_in_remaining(self) -> None:
        """Arguments to a job are left alone: `... top-level a.b` keeps `a.b`."""
        r = _trie().resolve(["top-level", "a.b"])
        assert r.node.payload == "top-level"
        assert r.remaining == ("a.b",)


class TestBareGroups:
    """`groups=` materializes a group nobody has a cached job under.

    The cold-boot CLI path needs it: `enumerate_group_names` AST-sweeps for
    `JOB_GROUP` while `enumerate_job_names` yields file stems, so a group can
    be known without any known job beneath it.
    """

    def test_bare_group_becomes_a_navigable_node(self) -> None:
        trie = GroupTrie.from_cache((), groups=["reports.weekly"], builtin=False)
        r = trie.resolve(["reports", "weekly"])
        assert r.node.path == ("reports", "weekly")
        assert r.node.payload is None
        assert r.node.kind is NodeKind.GROUP
        assert r.is_group_listing is True

    def test_bare_group_does_not_demote_a_job_at_the_same_path(self) -> None:
        """Order must not matter: the group is shape, the row is the payload."""
        trie = GroupTrie.from_cache(
            [("deploy", "deploy.web", "job")], groups=["deploy"], builtin=False
        )
        assert trie.root.children["deploy"].payload is None
        assert trie.root.children["deploy"].children["web"].payload == "deploy.web"

    def test_bare_group_over_a_runnable_node_keeps_the_payload(self) -> None:
        trie = GroupTrie.from_cache(
            [(None, "deploy", "job")], groups=["deploy"], builtin=False
        )
        assert trie.root.children["deploy"].payload == "deploy"
        assert trie.root.children["deploy"].kind is NodeKind.JOB

    def test_bare_group_cannot_claim_the_reserved_segment(self) -> None:
        with pytest.raises(ValueError, match=BUILTIN_SEGMENT):
            GroupTrie.from_cache((), groups=[BUILTIN_SEGMENT], builtin=True)

    def test_empty_segment_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty path segment"):
            GroupTrie.from_cache((), groups=["a..b"], builtin=False)
