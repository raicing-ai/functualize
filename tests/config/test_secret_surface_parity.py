"""Cross-surface parity for secret and config-field rendering.

One job, one environment, many surfaces. Every surface that reports what a job's
config *will be* must agree with what the job actually *receives*, and must never
render a secret's value.

This is the enforcement mechanism for two rules that the codebase had no way to
check before (ADR-008):

- **One resolver.** ``info --job``, ``builtin env`` and the TUI each re-derived
  values, knew different subsets of the environment conventions, and disagreed with
  the executor. A surface that re-derives a value eventually lies at the moment it
  matters most.
- **One detector.** ``is_secret_field`` decides masking everywhere. Masking must
  follow the model, never the field's name.

The TUI surfaces are covered by Pilot tests; this module covers the CLI surfaces
plus the resolution ladder they share.
"""

from __future__ import annotations

import pytest

from functualize.app.utils import MASK

# --- The fixture job ------------------------------------------------------
# Four fields, each chosen to trip a specific defect:
#   api_url     — ordinary control
#   credential  — secret, EMPTY default (set/unset must stay distinguishable)
#   sort_key    — matches the old name-based regex; must NOT be masked
#   user        — collides with the ambient $USER shell variable
SECRET_JOB = '''
from enum import Enum

from pydantic import BaseModel, Field

from functualize.job import Stdout
from functualize.job.context import RunContext
from functualize.job.decorators import job


class Mode(str, Enum):
    FAST = "fast"
    THOROUGH = "thorough"


class SyncConfig(BaseModel):
    api_url: str = Field(default="https://api.example.com")
    credential: str = Field(default="", json_schema_extra={"secret": True})
    sort_key: str = Field(default="created_at")
    user: str = Field(default="service-account")
    # Shapes the fixture used to omit. Every field here was `str` or `int`, so
    # a precedence ladder was tested only where nothing needed converting.
    targets: list[str] = Field(default_factory=lambda: ["default-target"])
    dry_run: bool = Field(default=False)
    mode: Mode = Field(default=Mode.FAST)


@job(extra_description="Sync with the remote API")
def sync(config: SyncConfig, rc: RunContext) -> str:
    print(f"api_url={config.api_url}")
    print(f"sort_key={config.sort_key}")
    print(f"user={config.user}")
    print(f"targets={','.join(config.targets)}")
    print(f"dry_run={config.dry_run}")
    print(f"mode={config.mode.value}")
    return "ok"


@job(extra_description="Emit the credential through the Stdout capability")
def emit_secret(config: SyncConfig, out: Stdout) -> None:
    """Push the credential down the framework's own data channel.

    Deliberately NOT `print()`: raw prints bypass every framework channel and
    nothing can redact them, so asserting on one would test the impossible.
    `out.write` is the seam `WiredStdout` redacts, and the only one the
    framework can honestly promise.
    """
    out.write("credential=" + config.credential)


class StrictConfig(BaseModel):
    """A required credential with no default — what an operator must discover."""

    token: str = Field(json_schema_extra={"secret": True})


@job(extra_description="Requires a token with no default")
def strict(config: StrictConfig, rc: RunContext) -> str:
    print(f"token={config.token}")
    return "ok"


class DefaultedConfig(BaseModel):
    """A secret carrying a NON-EMPTY default — renders with nothing typed."""

    api_key: str = Field(default="dev-key-in-the-default", json_schema_extra={"secret": True})


@job(extra_description="Secret with a non-empty default")
def defaulted(config: DefaultedConfig, rc: RunContext) -> str:
    print(f"api_key={config.api_key}")
    return "ok"


@job(extra_description="Emit a secret whose value comes from its own default")
def emit_defaulted(config: DefaultedConfig, out: Stdout) -> None:
    """The default tier's emitter — see `emit_secret` for why `out.write`."""
    out.write("api_key=" + config.api_key)
'''

SECRET_ANNOTATED_JOB = '''
from pydantic import BaseModel

from functualize.job import Stdout
from functualize.job.context import RunContext
from functualize.job.decorators import job
from functualize.types import Secret


class VaultConfig(BaseModel):
    """The documented public way to declare a credential."""

    token: Secret[str]


@job(extra_description="Uses the public Secret type")
def vault(config: VaultConfig, rc: RunContext, out: Stdout) -> str:
    rc.log("f-string: " + f"{config.token}")
    out.write("emitted=" + config.token.get_secret_value())
    return "ok"
'''

PYPROJECT = """\
[project]
name = "secrets-test-project"
version = "0.1.0"
"""

#: A value distinctive enough that finding it anywhere is unambiguous.
REAL_SECRET = "hunter2-real-credential-value"


#: The `file` tier's copy of the credential, in the job's own section.
CONFIG_FILE = f"""\
[emit-secret]
credential = "{REAL_SECRET}"
"""


@pytest.fixture()
def secrets_project(project_tree):
    """A project whose jobs declare secret and collision-prone config fields."""
    return project_tree(
        pyproject=PYPROJECT,
        jobs={"job_sync.py": SECRET_JOB},
        extra_files={"config.base.toml": CONFIG_FILE},
    )


@pytest.fixture()
def secrets_project_no_file(project_tree):
    """The same jobs with no config file — for the tiers that must not read one."""
    return project_tree(pyproject=PYPROJECT, jobs={"job_sync.py": SECRET_JOB})


@pytest.fixture()
def vault_project(project_tree):
    """A project declaring a credential with the public ``Secret[str]`` type."""
    return project_tree(
        pyproject=PYPROJECT, jobs={"job_vault.py": SECRET_ANNOTATED_JOB}
    )


def _field_line(stdout: str, field: str) -> str:
    """The ``field=value`` line a fixture job prints, or '' if absent."""
    for line in stdout.splitlines():
        if line.startswith(f"{field}="):
            return line.split("=", 1)[1].strip()
    return ""


def _export_line(stdout: str, name: str) -> str:
    """The ``export NAME=...`` line for ``name``, or '' if absent."""
    for line in stdout.splitlines():
        if line.strip().startswith(f"export {name}="):
            return line
    return ""


def _table_row(stdout: str, field: str) -> str:
    """The Rich table row whose first cell is ``field``, or '' if absent."""
    for line in stdout.splitlines():
        cells = [c.strip() for c in line.split("\u2502")]
        if len(cells) > 1 and cells[1] == field:
            return line
    return ""


# ===========================================================================
# Detection follows the model, never the name
# ===========================================================================


class TestSecretDetection:
    def test_secret_masked_in_info_job(self, cli_run, secrets_project):
        """A secret field's value never reaches `info --job`."""
        result = cli_run(
            ["builtin", "info", "--job", "sync"],
            cwd=secrets_project,
            env={"SYNC_CREDENTIAL": REAL_SECRET},
        )
        assert REAL_SECRET not in result.stdout
        assert REAL_SECRET not in result.stderr

    def test_plain_field_with_secretish_name_not_masked(self, cli_run, secrets_project):
        """`sort_key` matches the old regex but is not secret — show its value."""
        result = cli_run(
            ["builtin", "info", "--job", "sync"],
            cwd=secrets_project,
            env={"SYNC_SORT_KEY": "updated_at"},
        )
        assert "updated_at" in result.stdout

    def test_secret_with_nonempty_default_masked(self, cli_run, secrets_project):
        """A secret's *default* is still a secret — nothing typed, still masked."""
        result = cli_run(["builtin", "info", "--job", "defaulted"], cwd=secrets_project)
        assert "dev-key-in-the-default" not in result.stdout

    @pytest.mark.parametrize(
        ("tier", "argv", "env"),
        [
            ("cli", ["emit-secret", "--credential", REAL_SECRET], {}),
            ("env", ["emit-secret"], {"EMIT_SECRET_CREDENTIAL": REAL_SECRET}),
            ("file", ["emit-secret"], {}),
        ],
    )
    def test_secret_not_echoed_through_the_stdout_capability(
        self, cli_run, secrets_project, tier, argv, env
    ):
        """Output redaction is armed for job config, from *every* tier.

        `WiredStdout` masks any secret value appearing in what a job emits. Raw
        `print()` is out of scope — no framework channel sees it — so this
        asserts on `out.write`, which is the seam the framework actually owns.

        Parametrized over the precedence tier, not written once against `env=`.
        Redaction used to re-resolve the config from the job name with
        `cli_values={}`, so the CLI tier leaked in full while the env tier
        masked — and a suite that only ever set `env=` reported that as green.
        The tier is a test axis here for that reason.
        """
        result = cli_run(argv, cwd=secrets_project, env=env)

        assert result.exit_code == 0, result.stderr
        assert "credential=" in result.stdout, f"[{tier}] the job did not emit at all"
        assert REAL_SECRET not in result.stdout, (
            f"[{tier}] the credential reached stdout unmasked"
        )

    def test_secret_from_a_model_default_is_not_echoed(self, cli_run, secrets_project):
        """The fourth tier. A default is as real a credential as any other."""
        result = cli_run(["emit-defaulted"], cwd=secrets_project)

        assert result.exit_code == 0, result.stderr
        assert "api_key=" in result.stdout, "the job did not emit at all"
        assert "dev-key-in-the-default" not in result.stdout

    @pytest.mark.parametrize(
        ("tier", "job", "env"),
        [
            ("env", "sync", {"SYNC_CREDENTIAL": REAL_SECRET}),
            ("file", "emit-secret", {}),
        ],
    )
    def test_the_tiers_actually_supply_the_credential(
        self, cli_run, secrets_project, tier, job, env
    ):
        """Guard the guard: a tier that supplies nothing masks trivially.

        Without this, deleting the `[emit-secret]` section from the fixture's
        config file would leave the masking test above green while proving
        nothing about the `file` tier. `--include-secrets` is the only surface
        that will show the real value, which is exactly what makes it the right
        check here.
        """
        result = cli_run(
            ["builtin", "env", job, "--include-secrets"],
            cwd=secrets_project,
            env=env,
        )
        assert REAL_SECRET in result.stdout, (
            f"[{tier}] the fixture does not actually supply `credential`, so "
            "the masking test for this tier masks nothing"
        )


# ===========================================================================
# One environment-variable convention
# ===========================================================================


class TestEnvConvention:
    def test_ambient_variable_does_not_override_a_default(
        self, cli_run, secrets_project
    ):
        """An unrelated shell variable must never win over a declared default."""
        result = cli_run(["sync"], cwd=secrets_project, env={"USER": "root-ambient"})
        assert _field_line(result.stdout, "user") == "service-account"

    def test_documented_convention_resolves(self, cli_run, secrets_project):
        """`JOB_FIELD` is the supported form."""
        result = cli_run(
            ["sync"], cwd=secrets_project, env={"SYNC_USER": "from-sync-user"}
        )
        assert _field_line(result.stdout, "user") == "from-sync-user"

    def test_documented_convention_beats_ambient(self, cli_run, secrets_project):
        """With both set, the job-scoped name wins — it is the only one that resolves."""
        result = cli_run(
            ["sync"],
            cwd=secrets_project,
            env={"USER": "root-ambient", "SYNC_USER": "from-sync-user"},
        )
        assert _field_line(result.stdout, "user") == "from-sync-user"

    def test_double_underscore_form_does_not_resolve(self, cli_run, secrets_project):
        """`JOB__FIELD` is removed — it must resolve nothing, not silently win."""
        result = cli_run(
            ["sync"], cwd=secrets_project, env={"SYNC__USER": "double-underscore"}
        )
        assert _field_line(result.stdout, "user") == "service-account"


# ===========================================================================
# Surfaces agree with the run
# ===========================================================================


class TestSurfaceParity:
    @pytest.mark.parametrize(
        "field", ["api_url", "sort_key", "user", "targets", "dry_run", "mode"]
    )
    def test_info_job_agrees_with_the_run(self, cli_run, secrets_project, field):
        """What `info --job` reports is what the job receives.

        Asserted against the field's own table row. A substring search over the
        whole screen passes on any coincidence — `service-account` appears in
        the config-file panel too — and it cannot tell "this field agrees" from
        "some other field happens to print the same text".

        Parametrized over field *shapes*, not just names: the fixture was all
        `str` and `int`, and a `list[str]` field disagreed in exactly the way
        this test exists to catch (`info` reported the env value; the run
        received `[]`).
        """
        env = {
            "USER": "root-ambient",
            "SYNC_SORT_KEY": "updated_at",
            "SYNC_TARGETS": "alpha,beta",
            "SYNC_DRY_RUN": "true",
            "SYNC_MODE": "thorough",
        }
        run = cli_run(["sync"], cwd=secrets_project, env=env)
        info = cli_run(
            ["builtin", "info", "--job", "sync"], cwd=secrets_project, env=env
        )

        value = _field_line(run.stdout, field)
        assert value, f"{field} not printed by the run"

        row = _table_row(info.stdout, field)
        assert row, f"info --job has no row for {field!r}"
        assert value in row, (
            f"info --job disagrees on {field!r}: the run received {value!r}, "
            f"which is absent from its row: {row!r}"
        )

    def test_builtin_env_names_round_trip(self, cli_run, secrets_project):
        """Every name `builtin env` prints must be a name that actually resolves."""
        result = cli_run(["builtin", "env", "sync"], cwd=secrets_project)
        assert "SYNC_USER" in result.stdout
        assert "SYNC__USER" not in result.stdout

        rerun = cli_run(
            ["sync"], cwd=secrets_project, env={"SYNC_USER": "round-tripped"}
        )
        assert _field_line(rerun.stdout, "user") == "round-tripped"


# ===========================================================================
# Discoverability — the operator's questions
# ===========================================================================


class TestDiscoverability:
    def test_builtin_env_survives_a_missing_required_field(
        self, cli_run, secrets_project
    ):
        """The command exists to say what is missing; it must not traceback."""
        result = cli_run(["builtin", "env", "strict"], cwd=secrets_project)
        assert result.exit_code == 0, (
            f"builtin env crashed on a missing required field:\n{result.stderr}"
        )
        assert "ValidationError" not in result.stderr

    def test_builtin_env_names_the_missing_variable(self, cli_run, secrets_project):
        """An operator learns which variable to set, without reading Python."""
        result = cli_run(["builtin", "env", "strict"], cwd=secrets_project)
        assert "STRICT_TOKEN" in result.stdout

    def test_builtin_env_distinguishes_set_from_unset(self, cli_run, secrets_project):
        """A masked secret must not read identically whether or not it is set."""
        unset = cli_run(["builtin", "env", "sync"], cwd=secrets_project)
        was_set = cli_run(
            ["builtin", "env", "sync"],
            cwd=secrets_project,
            env={"SYNC_CREDENTIAL": REAL_SECRET},
        )
        assert unset.stdout != was_set.stdout, (
            "builtin env renders a set secret identically to an unset one — "
            "an operator cannot tell whether the credential is configured"
        )

    def test_builtin_env_does_not_mask_an_empty_secret(self, cli_run, secrets_project):
        """Masking nothing invents a credential that is not there.

        `credential` defaults to `""`. Rendering that as `•••` tells an operator
        the token is configured — the exact misreading every surface here
        exists to prevent, and the one `# source: default` alone is too quiet
        to correct.
        """
        result = cli_run(["builtin", "env", "sync"], cwd=secrets_project)

        line = _export_line(result.stdout, "SYNC_CREDENTIAL")
        assert MASK not in line, f"an empty secret rendered as a masked value: {line!r}"

    def test_builtin_env_masks_a_secret_that_is_actually_set(
        self, cli_run, secrets_project
    ):
        """The other half — without it the fix above could just delete masking."""
        result = cli_run(
            ["builtin", "env", "sync"],
            cwd=secrets_project,
            env={"SYNC_CREDENTIAL": REAL_SECRET},
        )

        line = _export_line(result.stdout, "SYNC_CREDENTIAL")
        assert MASK in line
        assert REAL_SECRET not in result.stdout

    def test_info_job_does_not_mask_an_empty_secret(self, cli_run, secrets_project):
        """Same rule, same field, the other CLI surface."""
        result = cli_run(["builtin", "info", "--job", "sync"], cwd=secrets_project)

        row = _table_row(result.stdout, "credential")
        assert MASK not in row, (
            f"info --job rendered an empty secret as masked: {row!r}"
        )

    def test_info_job_shows_required_unset_as_unset(self, cli_run, secrets_project):
        """A required field with no default must not read as 'model default'."""
        result = cli_run(["builtin", "info", "--job", "strict"], cwd=secrets_project)
        assert "PydanticUndefined" not in result.stdout
        token_row = [ln for ln in result.stdout.splitlines() if "token" in ln]
        assert token_row, "no row for the `token` field"
        assert "model default" not in token_row[0], (
            f"a required field with no default is reported as a default: {token_row[0]!r}"
        )


# ===========================================================================
# The public `Secret[str]` annotation, end to end
# ===========================================================================


class TestPublicSecretType:
    """`functualize.types.Secret` is public API; using it must simply work.

    It previously did not: `Secret[str]` on a plain `BaseModel` raised
    `PydanticSchemaGenerationError` at class-definition time, so the job
    declaring it vanished from `func` with only a stderr warning — no error, no
    non-zero exit, just an absent command. A second gate in
    `validate_job_config_types` rejected it independently, so fixing only the
    Pydantic schema would still have left it unusable.
    """

    def test_the_job_is_discovered(self, cli_run, vault_project):
        result = cli_run([], cwd=vault_project)
        assert "vault" in result.stdout, (
            "a job declaring Secret[str] is missing from the listing — "
            "the schema hook or the type gate has regressed"
        )

    def test_it_resolves_from_the_environment(self, cli_run, vault_project):
        result = cli_run(["vault"], cwd=vault_project, env={"VAULT_TOKEN": REAL_SECRET})
        assert result.exit_code == 0, result.stderr

    def test_it_masks_in_an_f_string(self, cli_run, vault_project):
        """The wrapper's whole purpose: a secret dropped into a log line."""
        result = cli_run(["vault"], cwd=vault_project, env={"VAULT_TOKEN": REAL_SECRET})
        assert REAL_SECRET not in result.stdout + result.stderr

    def test_it_masks_in_info_job(self, cli_run, vault_project):
        result = cli_run(
            ["builtin", "info", "--job", "vault"],
            cwd=vault_project,
            env={"VAULT_TOKEN": REAL_SECRET},
        )
        assert REAL_SECRET not in result.stdout

    def test_deliberately_revealed_value_is_still_redacted_on_the_way_out(
        self, cli_run, vault_project
    ):
        """`get_secret_value()` unwraps, but `Stdout` still masks the result.

        Unwrapping is legitimate at a trusted call site (building an argv, an
        auth header). Writing it to the user's terminal is not that, so the
        output channel redacts it anyway — belt and braces, because the two
        mistakes look identical in a diff.
        """
        result = cli_run(["vault"], cwd=vault_project, env={"VAULT_TOKEN": REAL_SECRET})
        assert "emitted=" in result.stdout
        assert REAL_SECRET not in result.stdout
