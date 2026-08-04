"""Unit tests for the @job declaration value objects (S1/T2).

Each value object validates its own invariants at construction and is
JSON-serializable via to_dict(). These tests cover valid/invalid matrices and
serialization for Deps, Fingerprint, Guards, Precondition, Exec, Retry, and the
call() factory.
"""

from __future__ import annotations

import json

import pytest

from functualize.job import (
    Call,
    Deps,
    Exec,
    Fingerprint,
    Guards,
    Precondition,
    Retry,
    call,
)


def _job_ref() -> None:
    """A stand-in callable dependency target."""


class TestCall:
    def test_call_factory_builds_call(self) -> None:
        c = call("build", target="wheel")
        assert isinstance(c, Call)
        assert c.target == "build"
        assert c.kwargs == {"target": "wheel"}

    def test_call_accepts_callable_target(self) -> None:
        c = call(_job_ref, x=1)
        assert c.target is _job_ref
        assert c.kwargs == {"x": 1}

    def test_call_rejects_non_ref_target(self) -> None:
        with pytest.raises(ValueError, match="job-name string or a callable"):
            Call(123)  # type: ignore[arg-type]

    def test_call_to_dict_string_target(self) -> None:
        assert call("build", target="wheel").to_dict() == {
            "ref": "build",
            "opaque": False,
            "kwargs": {"target": "wheel"},
        }

    def test_call_to_dict_callable_target_is_opaque(self) -> None:
        d = call(_job_ref).to_dict()
        assert d["ref"] == "job-ref"
        assert d["opaque"] is True

    def test_call_to_dict_sorts_kwargs(self) -> None:
        assert call("b", z=1, a=2).to_dict()["kwargs"] == {"a": 2, "z": 1}


class TestDeps:
    def test_positional_refs_normalized_to_tuple(self) -> None:
        d = Deps("lint", "test")
        assert d.refs == ("lint", "test")
        assert d.policy == "fail-fast"

    def test_callable_and_call_refs_accepted(self) -> None:
        d = Deps(_job_ref, call("build", target="wheel"))
        assert d.refs[0] is _job_ref
        assert isinstance(d.refs[1], Call)

    def test_policy_keyword(self) -> None:
        assert Deps("a", policy="keep-going").policy == "keep-going"

    def test_invalid_policy_rejected(self) -> None:
        with pytest.raises(ValueError, match="fail-fast.*keep-going"):
            Deps("a", policy="whenever")  # type: ignore[arg-type]

    def test_invalid_ref_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="job-name strings, callables"):
            Deps(123)  # type: ignore[arg-type]

    def test_empty_deps_valid(self) -> None:
        assert Deps().refs == ()

    def test_to_dict_mixes_string_callable_and_call(self) -> None:
        d = Deps("lint", _job_ref, call("build", target="wheel"), policy="keep-going")
        out = d.to_dict()
        assert out["policy"] == "keep-going"
        assert out["refs"][0] == {"ref": "lint", "opaque": False}
        assert out["refs"][1] == {"ref": "job-ref", "opaque": True}
        assert out["refs"][2]["kwargs"] == {"target": "wheel"}
        json.dumps(out)  # serializable


class TestFingerprint:
    def test_defaults(self) -> None:
        fp = Fingerprint()
        assert fp.sources == ()
        assert fp.generates == ()
        assert fp.method == "checksum"

    def test_lists_coerced_to_tuples(self) -> None:
        fp = Fingerprint(sources=["a/**/*.py"], generates=["dist/x.whl"])
        assert fp.sources == ("a/**/*.py",)
        assert fp.generates == ("dist/x.whl",)

    def test_invalid_method_rejected(self) -> None:
        with pytest.raises(ValueError, match="method"):
            Fingerprint(method="magic")  # type: ignore[arg-type]

    def test_non_string_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="sources items must be strings"):
            Fingerprint(sources=[123])  # type: ignore[list-item]

    def test_timestamp_requires_generates(self) -> None:
        with pytest.raises(ValueError, match="requires 'generates'"):
            Fingerprint(sources=["a"], method="timestamp")

    def test_timestamp_with_generates_valid(self) -> None:
        fp = Fingerprint(generates=["out"], method="timestamp")
        assert fp.method == "timestamp"

    def test_to_dict_serializable(self) -> None:
        out = Fingerprint(sources=["a"], generates=["b"]).to_dict()
        assert out == {"sources": ["a"], "generates": ["b"], "method": "checksum"}
        json.dumps(out)


class TestPrecondition:
    def test_string_check(self) -> None:
        p = Precondition("docker --version", msg="install docker")
        assert p.cmd_or_callable == "docker --version"
        assert p.msg == "install docker"

    def test_callable_check(self) -> None:
        p = Precondition(_job_ref)
        assert p.cmd_or_callable is _job_ref

    def test_invalid_check_rejected(self) -> None:
        with pytest.raises(ValueError, match="shell-command string or a callable"):
            Precondition(123)  # type: ignore[arg-type]

    def test_invalid_msg_rejected(self) -> None:
        with pytest.raises(ValueError, match="msg must be a string"):
            Precondition("ok", msg=5)  # type: ignore[arg-type]

    def test_to_dict_string_and_callable(self) -> None:
        assert Precondition("x", msg="m").to_dict() == {
            "check": "x",
            "opaque": False,
            "msg": "m",
        }
        assert Precondition(_job_ref).to_dict()["opaque"] is True


class TestGuards:
    def test_defaults_empty(self) -> None:
        g = Guards()
        assert g.preconditions == ()
        assert g.status == ()

    def test_mixed_precondition_items(self) -> None:
        g = Guards(
            preconditions=["docker --version", _job_ref, Precondition("x", msg="m")],
            status=["test -f dist/app.whl"],
        )
        assert len(g.preconditions) == 3
        assert g.status == ("test -f dist/app.whl",)

    def test_invalid_precondition_item_rejected(self) -> None:
        with pytest.raises(ValueError, match="preconditions items"):
            Guards(preconditions=[123])  # type: ignore[list-item]

    def test_invalid_status_item_rejected(self) -> None:
        with pytest.raises(ValueError, match="status items"):
            Guards(status=[123])  # type: ignore[list-item]

    def test_to_dict_serializable(self) -> None:
        out = Guards(
            preconditions=["a", Precondition("b", msg="m")], status=["c"]
        ).to_dict()
        assert out["preconditions"][0] == {"check": "a", "opaque": False, "msg": None}
        assert out["preconditions"][1] == {"check": "b", "opaque": False, "msg": "m"}
        assert out["status"] == [{"check": "c", "opaque": False}]
        json.dumps(out)


class TestRetry:
    def test_minimal(self) -> None:
        r = Retry(attempts=3)
        assert r.attempts == 3
        assert r.backoff == "exponential"
        assert r.on == ()
        assert r.on_exit_codes == ()

    def test_attempts_must_be_positive_int(self) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            Retry(attempts=0)

    def test_bool_attempts_rejected(self) -> None:
        with pytest.raises(ValueError, match="attempts must be an int"):
            Retry(attempts=True)  # type: ignore[arg-type]

    def test_invalid_backoff_rejected(self) -> None:
        with pytest.raises(ValueError, match="backoff"):
            Retry(attempts=1, backoff="fast")  # type: ignore[arg-type]

    def test_on_must_be_exception_types(self) -> None:
        r = Retry(attempts=2, on=(ValueError, KeyError))
        assert r.on == (ValueError, KeyError)
        with pytest.raises(ValueError, match="exception types"):
            Retry(attempts=2, on=("ValueError",))  # type: ignore[arg-type]

    def test_on_exit_codes_ints(self) -> None:
        assert Retry(attempts=2, on_exit_codes=(1, 2)).on_exit_codes == (1, 2)
        with pytest.raises(ValueError, match="on_exit_codes"):
            Retry(attempts=2, on_exit_codes=("1",))  # type: ignore[arg-type]

    def test_to_dict_serializes_exception_names(self) -> None:
        out = Retry(attempts=2, on=(ValueError,), on_exit_codes=(1,)).to_dict()
        assert out == {
            "attempts": 2,
            "backoff": "exponential",
            "on": ["ValueError"],
            "on_exit_codes": [1],
        }
        json.dumps(out)


class TestExec:
    def test_defaults(self) -> None:
        e = Exec()
        assert e.retry is None
        assert e.platforms is None
        assert e.run == "always"
        assert e.silent is False

    def test_full(self) -> None:
        e = Exec(
            retry=Retry(attempts=2),
            platforms=["linux"],
            run="once",
            silent=True,
        )
        assert e.platforms == ("linux",)
        assert e.run == "once"

    def test_there_is_no_job_level_timeout(self) -> None:
        """Removed after research, not overlooked (§A.5).

        Python cannot preempt a running function, so the field could only
        report an overrun while the work continued — worse than absent, since
        a caller believing the job stopped may release a lock the live job
        holds. `invoke` has no task-level timeout either and `doit` has none
        at all. Enforce where the OS can: `sh(..., timeout=N)`.
        """
        with pytest.raises(TypeError):
            Exec(timeout=5)  # type: ignore[call-arg]

    def test_invalid_retry_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="retry must be a Retry"):
            Exec(retry="yes")  # type: ignore[arg-type]

    def test_invalid_run_rejected(self) -> None:
        with pytest.raises(ValueError, match="run must be"):
            Exec(run="sometimes")  # type: ignore[arg-type]

    def test_non_string_platform_rejected(self) -> None:
        with pytest.raises(ValueError, match="platforms items"):
            Exec(platforms=[1])  # type: ignore[list-item]

    def test_to_dict_serializable(self) -> None:
        out = Exec(retry=Retry(attempts=1), platforms=["linux"]).to_dict()
        assert "timeout" not in out
        assert out["retry"]["attempts"] == 1
        assert out["platforms"] == ["linux"]
        json.dumps(out)

    def test_to_dict_none_retry_and_platforms(self) -> None:
        out = Exec().to_dict()
        assert out["retry"] is None
        assert out["platforms"] is None


def test_all_objects_are_frozen() -> None:
    """Value objects are immutable (frozen dataclasses)."""
    import dataclasses

    for obj in (
        Deps("a"),
        Fingerprint(),
        Guards(),
        Precondition("x"),
        Retry(attempts=1),
        Exec(),
        call("x"),
    ):
        with pytest.raises(dataclasses.FrozenInstanceError):
            obj.foo = "bar"  # type: ignore[attr-defined]
