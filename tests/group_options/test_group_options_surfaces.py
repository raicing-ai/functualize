"""One param builder, two entry points (S6a T-GO-5 / scrutiny C-D1).

A group's declared options and a job's cached config fields are the *same*
record type, ``FieldDescriptor``, reached from two cache sections. Rendering
them with two copies of the same loop is how a group flag ends up spelled
differently from an identical job flag — the kind of divergence nobody notices
until a user reports that ``--dry-run`` works in one place and ``--dry_run`` in
another. ``build_click_params_from_fields`` is the shared implementation;
these tests hold the two entry points against each other.
"""

from __future__ import annotations

from types import SimpleNamespace

from functualize._types.descriptors import FieldDescriptor
from functualize.app.adapters.click_params import (
    build_click_params_from_descriptor,
    build_click_params_from_fields,
)


def _fields() -> list[FieldDescriptor]:
    """One of each rendering branch the shared loop has to cover."""
    return [
        FieldDescriptor(
            name="env",
            type_annotation="str",
            default="staging",
            required=False,
            description="Target environment",
            short_flag="-e",
        ),
        FieldDescriptor(
            name="dry_run",
            type_annotation="bool",
            default=False,
            required=False,
            description="Preview only",
        ),
        FieldDescriptor(
            name="replicas",
            type_annotation="int",
            default=1,
            required=False,
            description="",
        ),
    ]


def _shape(params: list) -> list[tuple]:
    """The observable rendering of a param list."""
    return [
        (p.name, tuple(p.opts), tuple(p.secondary_opts), p.required, p.default)
        for p in params
    ]


def test_the_descriptor_builder_delegates_to_the_shared_helper() -> None:
    """Identical input, identical output — the property that makes a second
    copy of the loop unnecessary, and its absence detectable."""
    fields = _fields()
    descriptor = SimpleNamespace(config_fields=fields)

    via_descriptor = build_click_params_from_descriptor(descriptor)
    via_fields = build_click_params_from_fields(fields)

    assert _shape(via_descriptor) == _shape(via_fields)


def test_the_shared_helper_renders_the_documented_spellings() -> None:
    """Pins what both entry points produce, so a change to the shared loop is
    a change someone had to mean."""
    params = {p.name: p for p in build_click_params_from_fields(_fields())}

    assert params["env"].opts == ["--env", "-e"]
    assert params["env"].default == "staging"
    assert params["dry_run"].opts == ["--dry-run"]
    assert params["dry_run"].secondary_opts == ["--no-dry-run"]
    assert params["replicas"].opts == ["--replicas"]


def test_an_empty_field_list_renders_nothing() -> None:
    """A group may declare a class with no fields; the listing must not
    invent a param or divide by zero laying out its column."""
    assert build_click_params_from_fields([]) == []
