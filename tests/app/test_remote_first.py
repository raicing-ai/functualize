"""remote_first() resolves remotely, or refuses. It never quietly becomes classic().

The defect this closes: the preset returned `config_resolution_chain=None` and
no boot path built a remote source, so `None` fell through to the classic
chain builder. Someone selecting it for AWS Secrets Manager got local files and
environment variables, silently, for the whole life of the shipped preset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from functualize._app.boot import build_resolution_chain, build_vault_source
from functualize._config.registry import ProviderRegistry
from functualize._config.vault import KEY_BYTES, SecretsVault
from functualize._config.vault_source import VaultSource
from functualize.app.presets import classic, env_only, remote_first, twelve_factor

_KEY = b"\x07" * KEY_BYTES


class _FakeRemoteProvider:
    def identifier(self) -> str:
        return "fake-sm"

    def is_ready(self) -> bool:
        return True

    def fetch(self, reference: str) -> str:
        return f"fetched:{reference}"


class _FakeApp:
    """The minimum `build_vault_source` reads. Avoids a full boot."""

    def __init__(self, *, remote: bool, providers: bool) -> None:
        self._config_sources = remote_first() if remote else classic()
        self.config_registry = ProviderRegistry()
        if providers:
            self.config_registry.register_remote_provider(_FakeRemoteProvider())


class TestThePresetCarriesItsIntent:
    def test_remote_first_sets_the_marker(self) -> None:
        """A bare None cannot say 'build the remote chain' — hence the flag."""
        assert remote_first().remote is True

    @pytest.mark.parametrize(
        "preset", [classic, twelve_factor, env_only], ids=["classic", "12f", "env"]
    )
    def test_every_other_preset_leaves_it_off(self, preset: Any) -> None:
        assert preset().remote is False

    def test_remote_first_still_leaves_the_chain_for_boot_to_build(self) -> None:
        assert remote_first().config_resolution_chain is None


class TestRefusalWhenNothingCouldResolve:
    def test_it_raises_rather_than_degrading_to_classic(self) -> None:
        """The headline behaviour. Falling back here is the original bug."""
        app = _FakeApp(remote=True, providers=False)
        with pytest.raises(RuntimeError) as exc:
            build_vault_source(app)
        assert "remote_first()" in str(exc.value)

    def test_the_error_names_the_entry_point_group(self) -> None:
        """An operator needs to know what to install, not just that it failed."""
        app = _FakeApp(remote=True, providers=False)
        with pytest.raises(RuntimeError, match="functualize.remote_providers"):
            build_vault_source(app)

    def test_the_error_explains_why_it_refuses(self) -> None:
        app = _FakeApp(remote=True, providers=False)
        with pytest.raises(RuntimeError, match="Refusing"):
            build_vault_source(app)


class TestOtherPresetsAreUntouched:
    def test_a_non_remote_app_builds_no_remote_source(self) -> None:
        assert build_vault_source(_FakeApp(remote=False, providers=False)) is None

    def test_a_non_remote_app_does_not_require_providers(self) -> None:
        """classic() must not start demanding a provider plugin."""
        assert build_vault_source(_FakeApp(remote=False, providers=True)) is None


class TestChainComposition:
    def _chain(self, remote_source: Any, tmp_path: Path) -> list[str]:
        chain = build_resolution_chain(
            str(tmp_path),
            "app",
            ProviderRegistry(),
            remote_source=remote_source,
        )
        return [s.source_type for s in chain.sources]

    def test_classic_composition_is_unchanged(self, tmp_path: Path) -> None:
        """One builder serves both presets; classic() must not have moved."""
        assert self._chain(None, tmp_path) == ["cli", "env", "file", "default"]

    def test_the_vault_slots_between_cli_and_env(self, tmp_path: Path) -> None:
        """A synced secret outranks env and file; an explicit CLI arg wins."""
        source = VaultSource(tmp_path / "v.db", encryption_key=_KEY)
        assert self._chain(source, tmp_path) == [
            "cli",
            "remote",
            "env",
            "file",
            "default",
        ]


class TestTheVaultSource:
    def _vault(self, tmp_path: Path) -> Path:
        path = tmp_path / "vault.db"
        vault = SecretsVault(path)
        vault.put(
            "database.password",
            "s3cret",
            annotation="fake-sm://prod/db",
            provider="fake-sm",
            encryption_key=_KEY,
        )
        return path

    def test_a_synced_value_resolves(self, tmp_path: Path) -> None:
        source = VaultSource(self._vault(tmp_path), encryption_key=_KEY)
        assert source.get("password", "database") == "s3cret"

    def test_a_miss_returns_none_and_is_recorded(self, tmp_path: Path) -> None:
        """Recorded so task 3.2 can warn; returning None defers to the chain."""
        source = VaultSource(self._vault(tmp_path), encryption_key=_KEY)
        assert source.get("absent", "database") is None
        assert "database.absent" in source.misses

    def test_no_key_leaves_the_source_inert_for_everything_but_a_stored_key(
        self, tmp_path: Path
    ) -> None:
        """Still safe from `func --help`; no longer silent about a stored value.

        **Updated for ADR-023 §1.** The inertness that mattered is intact:
        `usable`, `has` and `keys` answer without opening anything, so the
        paths reachable from `--help` and completion stay quiet.

        What changed is `get` for a key the store actually holds. It used to
        return None, which let the chain hand the job whatever the environment
        happened to carry — a different secret than the one provisioned, with
        the run reporting success.
        """
        from functualize._config.vault import VaultEntryUnreadableError

        source = VaultSource(self._vault(tmp_path), encryption_key=None)
        assert source.usable is False
        assert source.has("password", "database") is False
        assert source.keys("database") == set()
        assert source.get("absent", "database") is None

        with pytest.raises(VaultEntryUnreadableError):
            source.get("password", "database")

    def test_a_missing_vault_file_is_inert(self, tmp_path: Path) -> None:
        """Nobody has run `vault sync` yet."""
        source = VaultSource(tmp_path / "never-synced.db", encryption_key=_KEY)
        assert source.usable is False
        assert source.get("password", "database") is None

    def test_has_and_get_agree(self, tmp_path: Path) -> None:
        """A source claiming a key it cannot deliver breaks the chain."""
        source = VaultSource(self._vault(tmp_path), encryption_key=_KEY)
        for key in ("password", "absent"):
            assert source.has(key, "database") is (
                source.get(key, "database") is not None
            )

    def test_keys_lists_a_section_without_decrypting(self, tmp_path: Path) -> None:
        source = VaultSource(self._vault(tmp_path), encryption_key=_KEY)
        assert source.keys("database") == {"password"}
        assert source.keys("other") == set()

    def test_a_wrong_key_propagates_rather_than_becoming_a_miss(
        self, tmp_path: Path
    ) -> None:
        """A vault that cannot be READ differs from one that lacks the key.

        Collapsing them would hide a wrong-key configuration behind a silent
        fall-through — the shape of the defect this feature removes.
        """
        from functualize._config.vault import (
            VaultEntryUnreadableError,
            VaultError,
        )

        source = VaultSource(self._vault(tmp_path), encryption_key=b"\x09" * KEY_BYTES)
        with pytest.raises(VaultError) as exc:
            source.get("password", "database")

        # **Updated for ADR-023 §2.** This used to be VaultDecryptionError,
        # raised after trying to decrypt the stored value and failing. The key
        # check value now catches it first, so the refusal happens without any
        # secret's ciphertext being touched at all — a stricter guarantee than
        # the one this test was written for, reached by a cheaper route.
        assert isinstance(exc.value, VaultEntryUnreadableError)

    def test_it_satisfies_the_source_protocol(self, tmp_path: Path) -> None:
        from functualize._types.protocols import Source

        assert isinstance(VaultSource(tmp_path / "v.db", encryption_key=_KEY), Source)


class TestOneChainBuilder:
    """Boot and `refresh()` build the chain through one call site.

    Two sites kept equal by a comment drifted twice: `environment` was omitted
    from the rebuild and leaked a prod config file into a dev run, and
    `remote_source` was wired into boot alone so `refresh()` silently dropped
    the vault. The first was fixed with a regression test, which did not
    prevent the second — a test cannot be written for an argument nobody has
    added yet. One call site cannot be forgotten.
    """

    def test_there_is_exactly_one_call_site(self) -> None:
        """Structural, because the defect is structural.

        A behavioural test here would only prove the arguments that exist
        today are passed; what keeps drifting is the *next* one.
        """
        import re
        from pathlib import Path

        src = Path(__file__).resolve().parents[2] / "src" / "functualize"
        pattern = re.compile(r"(?<![_\w])build_resolution_chain\(")
        sites = [
            f"{path.relative_to(src)}:{n}"
            for path in src.rglob("*.py")
            for n, line in enumerate(path.read_text().splitlines(), 1)
            if pattern.search(line) and not line.lstrip().startswith("def ")
        ]

        assert sites == ["_app/impl.py:1346"] or len(sites) == 1, sites

    def test_the_file_pattern_default_is_compared_in_one_place(self) -> None:
        """The other half of what drifted: both sites computed `custom_regex`,
        by two different mechanisms, for a layer reason that no longer holds."""
        from pathlib import Path

        src = Path(__file__).resolve().parents[2] / "src" / "functualize"
        hits = [
            f"{path.relative_to(src)}:{n}"
            for path in src.rglob("*.py")
            for n, line in enumerate(path.read_text().splitlines(), 1)
            if "type(app._config_sources).file_pattern" in line
            or "!= ConfigSources.file_pattern" in line
        ]

        assert len(hits) == 1, hits

    def test_refresh_keeps_the_vault_in_the_chain(self, tmp_path: Path) -> None:
        """The bug this collapse removes, asserted behaviourally too.

        `FunctualizeApp.refresh()` is public and is what the TUI and MCP server
        call when a file changes. It used to return a chain with no vault
        source at all.
        """
        from functualize._config.vault_keys import ENV_VAR, generate_key
        from functualize.app import ConfigSources, FunctualizeApp, JobSources

        (tmp_path / ".functualize").mkdir()
        jobs = tmp_path / "jobs"
        jobs.mkdir()

        import os

        os.environ[ENV_VAR] = generate_key()
        try:
            app = FunctualizeApp(
                "refreshlab",
                job_sources=JobSources(directories=[str(jobs)], lazy=False),
                config_sources=ConfigSources(dotenv=False),
            )
            app._config_path = str(tmp_path)

            before = [s.source_id for s in app.resolution_chain().sources]
            app.refresh()
            after = [s.source_id for s in app.resolution_chain().sources]

            assert before == after
        finally:
            os.environ.pop(ENV_VAR, None)


class TestTheDormantSource:
    """An ordinary app reads a vault it has, and pays a `stat` when it hasn't."""

    def _project(self, tmp_path: Path) -> Path:
        (tmp_path / ".functualize").mkdir()
        (tmp_path / "jobs").mkdir()
        return tmp_path

    def test_a_project_with_no_vault_gets_no_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`classic()` builds exactly the chain it always did."""
        monkeypatch.chdir(self._project(tmp_path))

        assert build_vault_source(_FakeApp(remote=False, providers=False)) is None

    def test_a_project_with_a_vault_gets_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without this, `vault put` would store a value that every ordinary
        run then ignored."""
        from functualize._config.vault import SecretsVault
        from functualize._config.vault_paths import vault_path_for_project

        project = self._project(tmp_path)
        monkeypatch.chdir(project)
        SecretsVault(vault_path_for_project(project)).put(
            "deploy.api_token", "v", encryption_key=_KEY, provider="p", annotation="a"
        )

        source = build_vault_source(_FakeApp(remote=False, providers=False))

        assert source is not None
        assert source.source_id == "vault"

    def test_remote_first_is_unchanged(self, tmp_path: Path) -> None:
        """The existing preset must not have acquired new behaviour."""
        with pytest.raises(RuntimeError, match="no remote configuration"):
            build_vault_source(_FakeApp(remote=True, providers=False))


class TestTheColdBootGate:
    """`cryptography` must not reach a boot that never opens a vault.

    `app/config.py` records that `_config.vault` is deliberately kept off the
    cold boot path. Making the vault source universal would undo that for every
    app in the package unless the existence check comes first — so the check is
    a `stat` through a module that imports only `_primitives`.

    Asserted in a subprocess because it is a statement about `sys.modules`
    after an import, which the test session has already polluted.
    """

    def _probe(self, cwd: Path) -> set[str]:
        import json
        import subprocess
        import sys

        script = (
            "import json, sys\n"
            "from functualize._app.boot import build_vault_source\n"
            "class A:\n"
            "    class _config_sources:\n"
            "        remote = False\n"
            "    _config_sources = _config_sources()\n"
            "assert build_vault_source(A()) is None\n"
            "print(json.dumps([m for m in sys.modules "
            "if m.startswith('cryptography') "
            "or m == 'functualize._config.vault']))\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", script],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return set(json.loads(out.stdout))

    def test_no_vault_means_no_cipher_import(self, tmp_path: Path) -> None:
        (tmp_path / ".functualize").mkdir()

        loaded = self._probe(tmp_path)

        assert loaded == set(), (
            f"a project with no vault imported {sorted(loaded)} while deciding "
            f"it had no vault"
        )

    def test_the_existence_check_itself_imports_no_cipher(self) -> None:
        """The gate module is the thing that must stay cheap.

        Scoped to `functualize.*` imports: stdlib is free, and the claim is
        about which *internal* layers this module may reach — `_primitives`
        only, because anything in `_config` risks pulling the cipher back in
        through a sibling.
        """
        import ast

        src = (
            Path(__file__).resolve().parents[2]
            / "src/functualize/_config/vault_paths.py"
        )
        tree = ast.parse(src.read_text())
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        internal = {m for m in imported if m.startswith("functualize")}

        assert not any(m.startswith("cryptography") for m in imported)
        assert internal, "expected at least one internal import"
        assert all(m.startswith("functualize._primitives") for m in internal), internal
