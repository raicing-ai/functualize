"""Job and group identity: normalization and resolution.

The one place that answers "what name does this denote".

Lives in ``_types`` — the lowest layer — because every altitude needs it and
the peer layers may not import each other. The dependency graph (`_engine`)
resolves references over these names; discovery (`_discovery`) builds them; the
coming kernel group trie (CLI/shell convergence plan, phase A3) will resolve
over them for dispatch and completion, from `_cli` via the public facade. That
plan places the trie in ``_discovery/naming.py``, which cannot work once the
engine consumes it: ``_engine -> _discovery`` breaks the peer-layer contract,
as lint-imports demonstrated the moment the graph imported it.

Without a single policy here, each consumer carries its own — which is how this
codebase ended up with three dependency resolvers that disagreed in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    # Annotation-only: the group-options side map is *data* (a frozen,
    # stdlib-only dataclass in this same package), never a live object, so the
    # trie build still imports nothing at runtime.
    from functualize._types.descriptors import GroupOptionsSpec

__all__ = [
    "BUILTIN_SEGMENT",
    "RESERVED_SIGILS",
    "GroupTrie",
    "NodeKind",
    "TrieNode",
    "TrieResolution",
    "normalize_name",
    "normalize_segment",
    "resolve_name",
]


def normalize_segment(segment: str) -> str:
    """Canonical form of one identity segment: lowercase, hyphenated.

    ``my_job_name`` and ``MyJobName`` both become ``my-job-name``. Python
    identifiers cannot contain hyphens and CLI names conventionally do, so
    without a canonical form the same job has two spellings and every consumer
    picks one — the divergence class that already produced three disagreeing
    dependency resolvers here.

    Applied at registration time to all job and group names, ensuring a single
    canonical spelling throughout the CLI, invoke resolution, and MCP surfaces.

    **Acronyms stay whole.** A hyphen goes before an uppercase letter only when
    it *starts* a word: after a lowercase letter or digit (``buildWheel`` ->
    ``build-wheel``), or as the last capital of a run that a lowercase letter
    follows (``HTTPServer`` -> ``http-server``). Splitting on every capital
    would register ``h-t-t-p-server``, and a name nobody would type is a name
    nobody can run.
    """
    out: list[str] = []
    for index, char in enumerate(segment):
        if char in "_ ":
            out.append("-")
            continue
        if char.isupper() and index and segment[index - 1] not in "_- ":
            starts_word = not segment[index - 1].isupper()
            ends_acronym = (
                not starts_word
                and index + 1 < len(segment)
                and segment[index + 1].islower()
            )
            if starts_word or ends_acronym:
                out.append("-")
        out.append(char.lower())
    return "".join(out).strip("-")


def normalize_name(name: str | None) -> str | None:
    """Canonical form of a full dotted name, segment by segment.

    ``data_ops.run_etl`` -> ``data-ops.run-etl``. ``None`` passes through, so
    callers holding an optional group need no branch.

    Groups normalize with jobs deliberately. A group whose ``name`` said
    ``data-ops.run-etl`` while its ``group`` field said ``data_ops`` would be
    one group with two spellings, and the CLI mounts its subcommand from the
    field — so ``func data-ops run-etl`` would miss a job claiming exactly
    that address.
    """
    if name is None:
        return None
    return ".".join(normalize_segment(part) for part in name.split("."))


def resolve_name(candidate: str, known: Iterable[str]) -> str:
    """Resolve a reference to exactly one known name.

    The single naming policy, so every consumer answers alike:

    1. an exact match wins;
    2. otherwise the candidate is *normalized* and matched again, so the
       Python spelling of a job finds it: ``build_wheel`` and ``buildWheel``
       both reach the registered ``build-wheel``;
    3. for a candidate with *no* group, the last segment is matched against
       each known name's last segment, which is how a bare reference finds
       ``build.compile-it``;
    4. anything else raises — unknown and ambiguous are both declaration
       errors, never a name silently passed through to fail later.

    Step 3 deliberately does not apply to a dotted candidate. Writing a group
    is stating one, so ``unknown.provision`` must fail rather than resolve to
    ``infra.provision`` — a caller who names the wrong group wants to hear
    about it, not to silently run a job from somewhere else.

    Step 2 is normalization, not aliasing. An alias is a second *declared*
    name that someone maintains and that a reader of the job cannot see; this
    is a total function from what you typed to the one name that exists. A job
    still has exactly one identity — you simply cannot miss it by writing it
    the way Python spells it.

    Lives here rather than in the dependency graph because it is a question
    about the *namespace*, and the kernel group trie (CLI/shell convergence
    plan, phase A3) will answer it for dispatch and completion too. One
    policy, several consumers; the alternative is a fourth resolver.

    Raises:
        LookupError: unknown or ambiguous. Callers translate to their own
            error type — this module knows names, not job semantics.
    """
    names = list(known)
    if candidate in names:
        return candidate

    def _canonical(name: str) -> str:
        return ".".join(normalize_segment(part) for part in name.split("."))

    wanted = _canonical(candidate)
    matches = [name for name in names if _canonical(name) == wanted]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise LookupError(f"{candidate!r} is ambiguous — matches {sorted(matches)}")

    if "." in candidate:
        raise LookupError(f"{candidate!r} matches no known name")

    matches = [name for name in names if _canonical(name).rsplit(".", 1)[-1] == wanted]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise LookupError(f"{candidate!r} is ambiguous — matches {sorted(matches)}")
    raise LookupError(f"{candidate!r} matches no known name")


# ─── Group trie ──────────────────────────────────────────────────────────
#
# Namespace *shape*: which names exist, and how they nest. Resolution of any
# single segment delegates to `resolve_name` above, so the trie never grows a
# second naming policy — it only decides how far along a path a token walk got.
#
# The trie is DERIVED state, rebuilt from already-cached descriptors on boot.
# The descriptors (and the live plugin-command list) remain the source of
# truth. Build is O(nodes) and imports nothing: payloads are plain name
# strings, never `JobDescriptor`/`PluginCommand` objects. That is load-bearing,
# not stylistic — `_types` may import nothing internal, and `lint-imports`
# flags a `TYPE_CHECKING`-only import just as loudly as a runtime one.

#: The one reserved top-level segment. First-party builtins mount here; a user
#: job/group or a plugin namespace claiming it is a boot error. Extensible only
#: by direct repo code — never by plugins or jobs.
BUILTIN_SEGMENT = "builtin"

#: First characters the shell's input bar dispatches on. A name beginning with
#: one of these is unreachable in the shell — the bar reads the first character
#: to pick an input mode, so `!deploy` selects the shell mode and tries to run
#: `deploy` as an external program rather than resolving the job. Reserved at
#: boot for that reason, not because the characters are awkward.
#:
#: `?` is reserved *before* it does anything (the ask mode is deferred): a sigil
#: that becomes reserved later would break names that were legal when written.
RESERVED_SIGILS = frozenset({"!", "?"})


class NodeKind(Enum):
    """What a node denotes.

    A node carrying both a payload and children keeps the payload's kind
    (``JOB``/``PLUGIN``/``BUILTIN``) and stays navigable as a group — the
    duality case (a ``deploy`` job that also has ``deploy web`` beneath it).
    """

    JOB = "job"
    GROUP = "group"
    PLUGIN = "plugin"
    BUILTIN = "builtin"


@dataclass(frozen=True)
class TrieNode:
    """One segment of the namespace.

    Attributes:
        segment: This level's name (``""`` for the root).
        path: Full path from the root, e.g. ``("infra", "aws")``.
        payload: The runnable thing at this node, as an opaque *key* — the
            canonical dotted job name, or ``"<namespace>.<command>"`` for a
            plugin command. ``None`` for a pure group. The CLI/shell layer
            re-associates the key with its live object; the trie holds no
            callables and imports no job module.
        children: Child segment -> node.
        kind: See :class:`NodeKind`.
    """

    segment: str
    path: tuple[str, ...]
    payload: str | None
    children: Mapping[str, TrieNode]
    kind: NodeKind

    @property
    def is_leaf(self) -> bool:
        """True when nothing nests beneath this node."""
        return not self.children

    @property
    def has_payload(self) -> bool:
        """True when this node is itself runnable. May also have children."""
        return self.payload is not None


@dataclass(frozen=True)
class TrieResolution:
    """How far a token walk got, and what was left over.

    Attributes:
        node: The deepest node the walk reached. The **root** with a non-empty
            ``remaining`` is how an unknown command reports itself — callers
            test ``node is trie.root and remaining`` rather than needing an
            ``UNKNOWN`` sentinel.
        remaining: Unconsumed tokens after the matched path.
        is_group_listing: True only when the walk landed on a node with no
            payload — the sole "list what is here" case. A node *with* a
            payload always runs it (see :meth:`GroupTrie.resolve`).
    """

    node: TrieNode
    remaining: tuple[str, ...]
    is_group_listing: bool


class _Building:
    """Mutable scratch node. Frozen into a `TrieNode` once the build is done."""

    __slots__ = ("children", "kind", "path", "payload", "segment")

    def __init__(self, segment: str, path: tuple[str, ...], kind: NodeKind) -> None:
        self.segment = segment
        self.path = path
        self.kind = kind
        self.payload: str | None = None
        self.children: dict[str, _Building] = {}

    def freeze(self) -> TrieNode:
        return TrieNode(
            segment=self.segment,
            path=self.path,
            payload=self.payload,
            children={key: child.freeze() for key, child in self.children.items()},
            kind=self.kind,
        )


class GroupTrie:
    """The namespace shape, built from cached rows without importing anything.

    Construct via :meth:`from_cache`. Both inputs are *structural rows*, not
    objects: the caller (which lives in a layer that may see both
    ``JobDescriptor`` and ``PluginCommand``) flattens them first, because this
    class lives in ``_types`` and may not reach those types.
    """

    __slots__ = ("_group_options", "_root")

    def __init__(
        self,
        root: TrieNode,
        group_options: Mapping[str, GroupOptionsSpec] | None = None,
    ) -> None:
        self._root = root
        self._group_options: Mapping[str, GroupOptionsSpec] = group_options or {}

    @property
    def root(self) -> TrieNode:
        """The empty-segment node every path descends from."""
        return self._root

    # ── group options ────────────────────────────────────────────────────
    #
    # Carried as a side map keyed by dotted path rather than a slot on
    # `TrieNode`: options are declared on a handful of groups, so a slot would
    # cost every leaf an always-None field, and the freeze step would have to
    # thread it through nodes that never use it. Nodes stay untouched; a walk
    # looks up the paths it consumed.

    def group_options(self, path: Sequence[str]) -> GroupOptionsSpec | None:
        """The options declared *directly* on the group at `path`, if any."""
        return self._group_options.get(".".join(path))

    def group_options_on_path(self, path: Sequence[str]) -> list[GroupOptionsSpec]:
        """Every declaration along `path`, outermost first.

        Inheritance is by containment: a job under ``deploy.web`` accepts the
        flags declared on ``deploy`` *and* on ``deploy.web``. Returned
        outermost-first so callers merging them can let the nearest
        declaration win by overwriting — the ``merge_config_layers`` idiom.
        """
        found: list[GroupOptionsSpec] = []
        for depth in range(1, len(path) + 1):
            spec = self._group_options.get(".".join(path[:depth]))
            if spec is not None:
                found.append(spec)
        return found

    # ── build ────────────────────────────────────────────────────────────

    @classmethod
    def from_cache(
        cls,
        job_groups: Iterable[tuple[str | None, str, str]],
        plugin_namespaces: Iterable[tuple[str | None, str]] = (),
        *,
        groups: Iterable[str] = (),
        builtin: bool = True,
        group_options: Mapping[str, GroupOptionsSpec] | None = None,
    ) -> GroupTrie:
        """Build the trie.

        Args:
            job_groups: ``(dotted_group_or_None, canonical_name, kind)`` rows
                derived from cached ``JobDescriptor``s. ``canonical_name`` is
                the **full dotted name** the descriptor carries
                (``infra.aws.provision-it``), not the leaf — the leaf is
                obtained by stripping the group prefix, which is exact and
                stays correct for a leaf whose own name contains a dot that is
                not a path separator. ``kind`` is a :class:`NodeKind` value.
            plugin_namespaces: ``(namespace_or_None, command_name)`` rows — the
                ``PluginCommand.namespace`` *string*, never the object.
            groups: Dotted group names to materialize as *payload-less* nodes,
                independently of whether any row above lands under them. The
                cold-boot CLI path needs this: its group list comes from an AST
                sweep for ``JOB_GROUP`` while its job list is file stems, so a
                group can be known without any known job beneath it. Groups
                already implied by a row are a no-op.
            builtin: Seed the reserved ``builtin`` subtree. Pass ``False`` for
                a trie that only describes user space (completion over jobs,
                say).
            group_options: ``{dotted_group: GroupOptionsSpec}`` read from the
                cache's ``group_options`` section. Carried as a side map (see
                :meth:`group_options`); the nodes themselves are unchanged, so
                this stays structural data like every other input here.

        Raises:
            ValueError: a user job/group or plugin namespace claims ``builtin``;
                two rows claim the same runnable path; a row has an empty
                segment.
        """
        root = _Building("", (), NodeKind.GROUP)
        if builtin:
            root.children[BUILTIN_SEGMENT] = _Building(
                BUILTIN_SEGMENT, (BUILTIN_SEGMENT,), NodeKind.BUILTIN
            )

        for group in groups:
            segments = _split_group(group)
            if not segments:
                continue
            _check_segments(segments, f"group {group!r}")
            cls._ensure_path(root, segments, origin="group")

        for job_group, name, kind in job_groups:
            segments = _job_segments(job_group, name)
            node_kind = NodeKind(kind) if not isinstance(kind, NodeKind) else kind
            cls._insert(root, segments, payload=name, kind=node_kind, origin="job")

        for namespace, command_name in plugin_namespaces:
            segments = _split_group(namespace) + [command_name]
            _check_segments(segments, f"plugin command {command_name!r}")
            payload = ".".join(segments)
            cls._insert(
                root,
                segments,
                payload=payload,
                kind=NodeKind.PLUGIN,
                origin="plugin command",
            )

        return cls(root.freeze(), group_options)

    @staticmethod
    def _ensure_path(
        root: _Building,
        segments: list[str],
        *,
        origin: str,
        what: str | None = None,
    ) -> _Building:
        """Walk `segments` under `root`, creating missing nodes as pure groups.

        Returns the node at the end of the path. Nodes that already exist are
        left untouched — including their payload and kind — so materializing a
        group over a runnable node never demotes it.
        """
        if segments[0] == BUILTIN_SEGMENT:
            raise ValueError(
                f"{origin} {what or '.'.join(segments)!r} claims the reserved "
                f"top-level name {BUILTIN_SEGMENT!r}. That subtree is "
                "first-party only — rename the job, group, or namespace."
            )

        node = root
        for depth, segment in enumerate(segments, start=1):
            child = node.children.get(segment)
            if child is None:
                child = _Building(segment, tuple(segments[:depth]), NodeKind.GROUP)
                node.children[segment] = child
            node = child
        return node

    @classmethod
    def _insert(
        cls,
        root: _Building,
        segments: list[str],
        *,
        payload: str,
        kind: NodeKind,
        origin: str,
    ) -> None:
        """Walk/create `segments` under `root` and attach `payload` at the leaf."""
        node = cls._ensure_path(root, segments, origin=origin, what=payload)

        if node.payload is not None:
            raise ValueError(
                f"{origin} {payload!r} collides with {node.payload!r}: both "
                f"claim the command path {' '.join(segments)!r}."
            )
        node.payload = payload
        # A node that already existed as an intermediate group becomes a
        # duality node: it keeps its children and takes the payload's kind.
        node.kind = kind

    # ── query ────────────────────────────────────────────────────────────

    def children(self, path: Sequence[str] = ()) -> list[TrieNode]:
        """Direct children of the node at `path`, sorted by segment.

        Returns an empty list when `path` names nothing. Used by TUI
        drill-down and completion.
        """
        node = self._walk_exact(path)
        if node is None:
            return []
        return sorted(node.children.values(), key=lambda child: child.segment)

    def resolve(self, segments: Sequence[str]) -> TrieResolution:
        """Greedily match the longest path; return the node plus leftovers.

        Per-segment matching delegates to :func:`resolve_name` over that node's
        child keys, so ``func data_ops run_etl`` reaches ``data-ops run-etl``
        by the same rule the dependency graph uses.

        A **dotted token addresses a path**, and is matched all-or-nothing:
        ``["infra.aws", "launch"]`` walks the same three nodes as
        ``["infra", "aws", "launch"]``. ``resolve_name`` rejects a dot inside a
        single segment, so without this a caller writing the dotted form would
        get no match at all. All-or-nothing matters because a half-consumed
        token has no sensible leftover — ``remaining`` is counted in tokens, so
        a token either walks completely or is left untouched for the caller
        (typically as a job's own positional argument).

        The walk stops at the first token that is a flag (``-``-prefixed) or
        matches no child. **Phase A keeps flags path-terminating**; stripping
        known global flags before the walk is Phase D's job, and belongs in
        dispatch so the trie stays free of CLI concerns.

        Node duality: because the match is greedy, a child segment is consumed
        *before* the duality decision is reached, so at a payload-bearing node
        ``remaining`` is empty, a flag, or a non-child token — and the payload
        runs in all three (``is_group_listing`` is False). Listing is reached
        only through ``--help``, which the CLI layer intercepts; ``resolve``
        does not special-case it.
        """
        node = self._root
        consumed = 0
        for token in segments:
            if token.startswith("-"):
                break
            walked = self._walk_token(node, token)
            if walked is None:
                # Unknown *or* ambiguous: either way the path ends here and the
                # caller reports it against the node actually reached.
                break
            node = walked
            consumed += 1

        return TrieResolution(
            node=node,
            remaining=tuple(segments[consumed:]),
            is_group_listing=not node.has_payload,
        )

    def step(self, node: TrieNode, token: str) -> TrieNode | None:
        """Descend one (possibly dotted) `token` from `node`, or None.

        The public form of the per-segment policy :meth:`resolve` applies,
        for callers that must interleave their own token handling with the
        walk. Dispatch needs exactly this to consume a group-declared flag
        mid-path (``func deploy --env prod web run``) and then keep walking:
        :meth:`resolve` deliberately stops at the first ``-``-prefixed token,
        because deciding *whether a flag is legal here* is a CLI concern and
        the trie stays free of those.
        """
        return self._walk_token(node, token)

    @staticmethod
    def _walk_token(node: TrieNode, token: str) -> TrieNode | None:
        """Descend `token` (possibly dotted) from `node`, or None if it fails."""
        for segment in token.split("."):
            if not node.children:
                return None
            try:
                key = resolve_name(segment, node.children.keys())
            except LookupError:
                return None
            node = node.children[key]
        return node

    def _walk_exact(self, path: Sequence[str]) -> TrieNode | None:
        """Resolve `path` to a node, or None. Same per-segment policy as resolve."""
        node = self._root
        for segment in path:
            try:
                key = resolve_name(segment, node.children.keys())
            except LookupError:
                return None
            node = node.children[key]
        return node


def _split_group(group: str | None) -> list[str]:
    """Dotted group -> segments. None/empty -> no segments (top level)."""
    if not group:
        return []
    return group.split(".")


def _job_segments(group: str | None, name: str) -> list[str]:
    """Segments for a job row.

    ``name`` is the descriptor's full dotted name, so the leaf is `name` with
    the group prefix stripped rather than ``name.rsplit(".", 1)``. The
    difference matters for any leaf carrying a dot of its own, such as
    ``deploy[version=1.2]``: that dot is part of the name, not a separator.
    """
    segments = _split_group(group)
    prefix = f"{group}." if group else ""
    leaf = name[len(prefix) :] if prefix and name.startswith(prefix) else name
    segments.append(leaf)
    _check_segments(segments, f"job {name!r}")
    return segments


def _check_segments(segments: list[str], what: str) -> None:
    """Reject empty segments — they would make a path unaddressable."""
    if not segments or any(not segment for segment in segments):
        raise ValueError(f"{what} has an empty path segment: {segments!r}")


def is_valid_job_group(group: str) -> bool:
    """Check whether a JOB_GROUP value is valid.

    A valid JOB_GROUP is a non-empty string where each dot-separated
    segment is a valid Python identifier. Empty segments (from leading/
    trailing dots or consecutive dots) are rejected.
    """
    if not group:
        return False
    return all(segment.isidentifier() for segment in group.split("."))


def group_ancestors(group: str, *, inclusive: bool = False) -> list[str]:
    """Return the dotted ancestor paths that a nested group sits beneath.

    A nested group like ``"infra.aws.k8s"`` is reachable through each of its
    parents, so routing/affinity tables must register those parents too. This is
    the single source for that expansion; the trie's own ``from_cache`` walks the
    same segments node-by-node.

    ``"infra.aws.k8s"`` -> ``["infra", "infra.aws"]`` (proper ancestors). With
    ``inclusive=True`` the group itself is appended:
    ``["infra", "infra.aws", "infra.aws.k8s"]``. A top-level group (no dot)
    has no proper ancestors.
    """
    segments = group.split(".")
    stop = len(segments) + 1 if inclusive else len(segments)
    return [".".join(segments[:i]) for i in range(1, stop)]
