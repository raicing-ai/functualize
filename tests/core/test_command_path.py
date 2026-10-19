"""One shared value separates job identity from shell command path."""

from __future__ import annotations

from functualize.types import CommandPath, JobDescriptor


def test_path_segments_and_spelling_cover_group_depth_and_literal_dot():
    cases = [
        ("suite", "suite.inventory", ("suite", "inventory")),
        ("deploy.web", "deploy.web.run", ("deploy", "web", "run")),
        (None, "tools.lint", ("tools.lint",)),
        ("ci", "pack", ("ci", "pack")),
    ]
    for group, name, segments in cases:
        path = CommandPath.of(group, name)
        assert path.segments == segments
        assert str(path) == " ".join(segments)
        assert JobDescriptor(name=name, group=group).command_path == path


def test_command_path_does_not_change_descriptor_cache_shape():
    descriptor = JobDescriptor(name="suite.inventory", group="suite")
    payload = descriptor.to_dict()
    assert payload["name"] == "suite.inventory"
    assert payload["group"] == "suite"
    assert "command_path" not in payload
    restored = JobDescriptor.from_dict(payload)
    assert restored.command_path == CommandPath(("suite", "inventory"))
