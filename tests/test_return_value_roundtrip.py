"""Return values through the *whole* cache path (S8/T32a, resolved Q19+19a).

`tests/test_fingerprint.py` covers the classifier's contract. This file covers
the trip a value actually takes:

    value -> make_record -> json.dumps -> state.json -> json.loads
          -> reusable_return_value(expected_type) -> injected parameter

The `json.dumps`/`json.loads` hop is the point. Asserting on `make_record`'s
output alone would pass for anything that holds together in memory, and the
state store persists — a tuple that survives in a dict and comes back a list
is exactly the kind of shape change that only appears after a process
restart, which is the class of bug this codebase keeps finding on its warm
path.

Three questions are asked of every type:

1. does it survive the trip,
2. does it come back as the *same type* rather than its JSON shadow, and
3. if it cannot survive, does the classifier say so *before* the write —
   never "reusable" followed by a crash while persisting.
"""

from __future__ import annotations

import dataclasses
import decimal
import enum
import io
import json
import math
import socket
import threading
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import NamedTuple, Optional, Union

import pytest
from pydantic import BaseModel

from functualize._primitives.fingerprint import (
    classify_return_value,
    make_record,
    reusable_return_value,
)

# ─── Subjects ────────────────────────────────────────────────────────────


@dataclasses.dataclass
class Point:
    x: int
    y: int


@dataclasses.dataclass
class Nested:
    p: Point
    tag: str


@dataclasses.dataclass(frozen=True)
class Frozen:
    v: int


@dataclasses.dataclass
class WithDefault:
    a: int
    b: str = "d"


class Color(enum.Enum):
    RED = "red"


class Level(enum.IntEnum):
    HIGH = 3


class Model(BaseModel):
    n: int
    label: str = "d"


class OuterModel(BaseModel):
    inner: Model


class Pair(NamedTuple):
    a: int
    b: str


def _roundtrip(value: object, expected_type: object) -> object:
    """The real path, persistence hop included."""
    record = make_record({}, return_value=value)
    persisted = json.loads(json.dumps(record))
    return reusable_return_value(
        persisted, job_name="subject", expected_type=expected_type
    )


# (label, value, the type the *consumer* declares)
ROUNDTRIP_CASES: list[tuple[str, object, object]] = [
    # scalars
    ("str", "x", str),
    ("empty str", "", str),
    ("unicode", "héllo→", str),
    ("int", 3, int),
    ("big int", 2**70, int),
    ("float", 1.5, float),
    ("negative zero", -0.0, float),
    ("bool", True, bool),
    ("none", None, type(None)),
    ("bytes", b"ab", bytes),
    # containers
    ("list[int]", [1, 2], list[int]),
    ("empty list", [], list[int]),
    ("dict[str,int]", {"a": 1}, dict[str, int]),
    ("empty dict", {}, dict[str, int]),
    ("dict[int,str]", {1: "a"}, dict[int, str]),
    ("tuple", (1, "a"), tuple[int, str]),
    ("set[int]", {1, 2}, set[int]),
    ("frozenset[int]", frozenset({1}), frozenset[int]),
    # stdlib value types
    # A path that genuinely exists: the existence check refuses a dead one,
    # and it runs before the annotation is consulted (pinned below).
    ("Path", Path(__file__), Path),
    ("datetime", datetime(2026, 7, 21, 3, 4, 5), datetime),
    ("date", date(2026, 7, 21), date),
    ("time", time(3, 4), time),
    ("timedelta", timedelta(seconds=90), timedelta),
    ("UUID", uuid.UUID(int=7), uuid.UUID),
    ("Decimal", decimal.Decimal("1.25"), decimal.Decimal),
    ("Enum", Color.RED, Color),
    ("IntEnum", Level.HIGH, Level),
    # user shapes
    ("dataclass", Point(1, 2), Point),
    ("nested dataclass", Nested(Point(1, 2), "t"), Nested),
    ("frozen dataclass", Frozen(1), Frozen),
    ("dataclass w/ default", WithDefault(1), WithDefault),
    ("BaseModel", Model(n=1), Model),
    ("nested BaseModel", OuterModel(inner=Model(n=2)), OuterModel),
    ("NamedTuple", Pair(1, "b"), Pair),
    # generics over user shapes — the item schema the writer cannot know
    ("list[dataclass]", [Point(1, 2), Point(3, 4)], list[Point]),
    ("dict[str,dataclass]", {"a": Point(1, 2)}, dict[str, Point]),
    ("list[BaseModel]", [Model(n=1)], list[Model]),
    # Typing forms. Both spellings are tested on purpose: `Optional[X]` and
    # `X | None` are different runtime objects, job authors write both, and a
    # reconstruction that handled only one would fail on real code. The noqa
    # marks that the legacy spelling is the subject here, not an oversight.
    ("Optional[X] (None)", None, Optional[set[int]]),  # noqa: UP045
    ("Optional[X] (value)", {1}, Optional[set[int]]),  # noqa: UP045
    ("X | None (None)", None, set[int] | None),
    ("X | None (value)", {1}, set[int] | None),
    ("Union[A, B]", 5, Union[int, str]),  # noqa: UP007
    ("A | B", 5, int | str),
    # nesting
    (
        "deeply nested",
        {"a": [{"b": (1, 2)}]},
        dict[str, list[dict[str, tuple[int, int]]]],
    ),
]

# Values nothing can derive a schema for. Each must be refused *before* the
# write, never accepted and then blown up while persisting.
UNSERIALIZABLE_CASES: list[tuple[str, object]] = [
    ("plain object", object()),
    ("open file", io.StringIO("x")),
    ("socket", socket.socket()),
    ("lock", threading.Lock()),
    ("generator", (i for i in range(2))),
    ("lambda", lambda: 1),
    ("module", json),
]


class TestRoundTrip:
    """Survives persistence, and comes back as itself."""

    @pytest.mark.parametrize(
        ("label", "value", "expected_type"),
        ROUNDTRIP_CASES,
        ids=[c[0] for c in ROUNDTRIP_CASES],
    )
    def test_value_survives(
        self, label: str, value: object, expected_type: object
    ) -> None:
        assert _roundtrip(value, expected_type) == value

    @pytest.mark.parametrize(
        ("label", "value", "expected_type"),
        ROUNDTRIP_CASES,
        ids=[c[0] for c in ROUNDTRIP_CASES],
    )
    def test_type_survives(
        self, label: str, value: object, expected_type: object
    ) -> None:
        """A tuple must not come back a list.

        Equality alone would not catch it: `(1, "a") != [1, "a"]` happens to
        hold, but `{1, 2} == {1, 2}` would pass for a list under a laxer
        comparison, and a dependent annotated `set[int]` that receives a list
        fails somewhere far from here.
        """
        assert type(_roundtrip(value, expected_type)) is type(value)


class TestTheWriteIsNeverAPromiseItCannotKeep:
    """`reusable=True` must imply the record is writable. No exceptions."""

    @pytest.mark.parametrize(
        ("label", "value", "expected_type"),
        ROUNDTRIP_CASES,
        ids=[c[0] for c in ROUNDTRIP_CASES],
    )
    def test_reusable_values_produce_a_writable_record(
        self, label: str, value: object, expected_type: object
    ) -> None:
        record = make_record({}, return_value=value)
        assert record["return_value_reusable"] is True
        json.dumps(record)  # the original defect raised here, post-success

    @pytest.mark.parametrize(
        ("label", "value"),
        UNSERIALIZABLE_CASES,
        ids=[c[0] for c in UNSERIALIZABLE_CASES],
    )
    def test_unserializable_values_are_refused_before_the_write(
        self, label: str, value: object
    ) -> None:
        reusable, kind, _type_name, stored = classify_return_value(value)
        assert reusable is False
        assert kind == "unserializable"
        assert stored is None
        json.dumps(make_record({}, return_value=value))  # still writable

    def test_a_self_referential_value_is_refused(self) -> None:
        """Recursion is the failure that would hang rather than raise."""
        loop: dict[str, object] = {}
        loop["self"] = loop
        assert classify_return_value(loop)[0] is False


class TestWithoutAnAnnotation:
    """No declared type means the stored shape comes back, unreconstructed.

    Documented rather than fixed: the writer cannot know the type, so with
    nothing declared there is nothing to rebuild from. These are the shapes a
    consumer sees if it annotates loosely, and each one is a plausible
    surprise worth having written down.
    """

    @pytest.mark.parametrize(
        ("value", "raw"),
        [
            ((1, "a"), [1, "a"]),
            ({1, 2}, [1, 2]),
            (datetime(2026, 7, 21), "2026-07-21T00:00:00"),
            (Point(1, 2), {"x": 1, "y": 2}),
            (Path(__file__), __file__),
            (decimal.Decimal("1.25"), "1.25"),
        ],
        ids=["tuple", "set", "datetime", "dataclass", "path", "decimal"],
    )
    def test_the_json_shape_is_what_comes_back(
        self, value: object, raw: object
    ) -> None:
        assert _roundtrip(value, None) == raw


class TestWrongAnnotation:
    """A drifted declaration is refused, never coerced."""

    @pytest.mark.parametrize(
        ("value", "wanted"),
        [
            (Point(1, 2), Frozen),
            ("abc", int),
            (5, str),
            ({"a": 1}, list[int]),
            (Model(n=1), Point),
        ],
        ids=[
            "dataclass-mismatch",
            "str-as-int",
            "int-as-str",
            "dict-as-list",
            "model-as-dc",
        ],
    )
    def test_a_mismatch_yields_nothing(self, value: object, wanted: object) -> None:
        """None means "re-run", which is right: the recorded value no longer
        answers the question the consumer is asking."""
        assert _roundtrip(value, wanted) is None


class TestNonFiniteFloats:
    """`nan`/`inf` round-trip in Python but are not standard JSON.

    `json.dumps` emits bare `NaN`/`Infinity`, which `json.loads` accepts and
    a strict reader would reject. Only functualize reads `state.json`, so this
    is recorded as known behavior rather than treated as a defect — but a job
    returning `inf` does put a non-conformant token in that file.
    """

    @pytest.mark.parametrize("value", [float("inf"), float("-inf")])
    def test_infinities_survive(self, value: float) -> None:
        assert _roundtrip(value, float) == value

    def test_nan_survives_as_nan(self) -> None:
        assert math.isnan(_roundtrip(float("nan"), float))  # type: ignore[arg-type]

    def test_the_persisted_form_is_non_standard(self) -> None:
        blob = json.dumps(make_record({}, return_value=float("inf")))
        assert "Infinity" in blob


class TestPathFreshness:
    """Existence is a freshness question; pydantic cannot answer it."""

    def test_existence_is_checked_before_the_annotation(self, tmp_path: Path) -> None:
        """A dead path is refused even with no declared type.

        The check sits ahead of the reconstruction branch, so annotating
        loosely does not buy you a stale path back.
        """
        target = tmp_path / "gone.whl"
        target.write_text("x")
        record = json.loads(json.dumps(make_record({}, return_value=target)))
        target.unlink()
        assert reusable_return_value(record, job_name="p", expected_type=None) is None

    def test_a_live_path_survives(self, tmp_path: Path) -> None:
        target = tmp_path / "out.whl"
        target.write_text("built")
        assert _roundtrip(target, Path) == target

    def test_a_deleted_path_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "out.whl"
        target.write_text("built")
        record = json.loads(json.dumps(make_record({}, return_value=target)))
        target.unlink()
        assert reusable_return_value(record, job_name="p", expected_type=Path) is None

    def test_a_path_inside_a_container_is_not_existence_checked(
        self, tmp_path: Path
    ) -> None:
        """Only a bare `Path` return is checked — the record carries one kind
        for the whole value, so a list of paths is `json`, not `path`. Worth
        pinning so the limit is known rather than assumed.
        """
        target = tmp_path / "gone.whl"
        target.write_text("x")
        record = json.loads(json.dumps(make_record({}, return_value=[target])))
        target.unlink()
        assert reusable_return_value(
            record, job_name="p", expected_type=list[Path]
        ) == [target]


class TestEmptyAndFalsyValues:
    """Falsy is not missing — a job returning 0 recorded something."""

    @pytest.mark.parametrize(
        ("value", "wanted"),
        [(0, int), ("", str), (False, bool), ([], list[int]), ({}, dict[str, int])],
        ids=["zero", "empty-str", "false", "empty-list", "empty-dict"],
    )
    def test_a_falsy_value_round_trips(self, value: object, wanted: object) -> None:
        assert _roundtrip(value, wanted) == value

    def test_none_is_recorded_as_reusable(self) -> None:
        """`None` is a legitimate return, distinct from "nothing recorded"."""
        record = make_record({}, return_value=None)
        assert record["return_value_reusable"] is True
        assert record["return_value_kind"] == "none"
