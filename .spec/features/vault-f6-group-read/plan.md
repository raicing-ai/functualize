# F6 group secret read — Plan

## Gate and authority

- WorkflowMode: `REPOSITORY_NATIVE`; WorkflowAuthority: `AGENTS.md`, `.claude/rules/spec-workflow.md`, `/agentic-plan`, and `.spec/CONSTITUTION.md`.
- CurrentPhase: Plan; ApprovalState: Specify confirmed by the member on 2026-11-03, Plan awaiting member approval. ContextPolicy: this feature's confirmed `spec.md` and `contracts.md`, live SD/12779576 v7, current checkout and retrieval evidence. No Execute work is authorized here.
- ArtifactLocations: `.spec/features/vault-f6-group-read/{spec,contracts,plan,tasks}.md` on `spec/vault-f6-group-read`, based on `master` `38b544609191ccabd99ea7e80f66a8f7de3c1548`.

## Alignment

SD/12779576 v7, *F6 amendment*, says **“Authority for this amendment: Approved.”** Its in-scope surface is **“one public programmatic call which accepts a group path or Rise subject address and a field name”** and returns a **“Secret”**. The call **“uses the existing local vault group lookup under Functualize's active environment”**: requested group then nearest ancestors in that environment, then the requested group and ancestors in the shared/base slot. **“The first existing entry wins.”** A stored unreadable entry fails closed. The section rules out a new invocation input, a second vault environment, job-scope or cross-environment fallback, provider contact during a job, plaintext diagnostics, and value-bearing `inspect`/`list`. These are the boundaries this plan preserves, using the confirmed C1–C3 in `contracts.md`.

## Architecture gate

The repository codemaps (`overview.md`, `modules.md`, `dependencies.md`, `data-flow.md`, `entry-points.md`) and seven import-linter contracts establish two axes: public `job/`, `app/`, `types/` versus internal `_` packages; and internal `_types/`/`_primitives/` foundation, `_events/`, independent `_config/` and `_engine/` peers, then `_app/` composition. `_cli/` uses only public API. The dependency arrows below point **from importer to imported component**; a runtime call travels in the reverse direction only where a typed port is handed in.

### BEFORE

```text
PUBLIC audience
  job/__init__.py -> job/capabilities.py -> _engine/capabilities/*
  app/vault.py -> _config/vault.py, _primitives/vault_identity.py
  types/__init__.py -> _types/redaction.py (Secret)

INTERNAL layers
  _primitives/vault_identity.py (foundation: candidate identity/order)
  _config/vault_source.py (peer: stored-presence selection, local read)
      -> _primitives/vault_identity.py, _config/vault.py
  _engine/capabilities/registry.py (peer: injected capability registry)
      -> _engine/capabilities/*, _primitives/capability_names.py
  _engine/executor.py (peer: job execution) -> registry
  _app/boot.py (composition) -> _config/vault_source.py,
      _config/chain.py, _engine/executor.py
  _app/impl.py (composition) -> _app/boot.py (rebuilds config chain)

  Job configuration -> ResolutionChain -> VaultSource.get(group/job)
  Job body -> injected capability registry; no explicit group Vault read
```

### AFTER

```text
PUBLIC audience
  job/__init__.py -> job/capabilities.py -> _types/protocols.py (Vault)
  app/vault.py -> _config/vault.py (public error reexports)
  types/__init__.py -> _types/redaction.py (Secret)

INTERNAL layers
  _types/protocols.py (foundation: Vault, VaultReaderFactory Protocol ports)
      -> _types/redaction.py (Secret)
  _primitives/vault_identity.py (foundation: unchanged candidate sequence)
  _config/vault_source.py (peer: unchanged local selection and read)
      -> _primitives/vault_identity.py, _config/vault.py
  _engine/capabilities/vault.py (peer: CapabilitySpec for Vault)
      -> _types/protocols.py; factory -> injected reader factory port
  _engine/capabilities/registry.py -> _engine/capabilities/vault.py
      -> _primitives/capability_names.py (matched name invariant)
  _engine/executor.py -> _types/protocols.py (typed factory reference only)
  _app/boot.py (composition) -> _app/vault_reader.py,
      _config/vault_source.py, _engine/executor.py
  _app/vault_reader.py (composition adapter) -> _config/vault_source.py,
      _config/vault.py, _types/protocols.py, _types/redaction.py
  _app/impl.py -> _app/boot.py (unchanged chain rebuild)

  Job body -> Vault.read(group, field) -> _app reader -> VaultSource.get
      -> first stored group candidate -> Secret[str] or typed vault failure
  Existing job config -> ResolutionChain -> VaultSource.get (unchanged miss)
```

No `_engine` to `_config` runtime import is added. The composition root provides a typed reader factory to the engine at its one construction site. The adapter reads from the current `ResolutionChain`'s `VaultSource` when present, so an app chain refresh is observed; if a custom/static chain has none, it constructs the same project `VaultSource` via `build_vault_source(app)`. That fallback import must be local to the read path so `_app/boot.py` and `_app/vault_reader.py` do not form a module import cycle. No chain `resolve()` call is used: that could substitute environment, file or default values. The adapter does not duplicate `VaultIdentity.lookup_candidates` or inspect storage rows. It calls `VaultSource.get(field, group, scope="group")` once; `None` becomes `VaultEntryMissingError`, an existing unreadable/decryption exception propagates, and a successful string is wrapped in `Secret[str]` before returning. A missing vault file is a miss. The selected environment is still `app._environment` through existing boot construction.

The public `Vault` and internal factory port are `Protocol`s, not ABCs or untyped callable conventions. `Vault` is the only new job call surface. A `CapabilitySpec` registers it with no `RunContext` accessor, matching confirmed C1; the existing import-time name-set invariant keeps discovery from treating `vault: Vault` as an invocation argument. The engine carries only the injected port, with no vault policy or source import. The adapter is per-invocation, while the app and its resolver remain the source of current state.

### Alternatives examined and smells

- Direct `_engine` to `_config` import would violate the peer independence contract; rejected.
- A second candidate walker in `job/` or `_engine/` would duplicate the first-present policy, introduce **shotgun surgery**, and contradict C3; rejected.
- Adding the read and vault resolution to `JobExecutionEngine` would increase an existing large class's **divergent change**; rejected.
- A parallel `RunContext.vault` API would broaden C1 and add **middle man** forwarding; rejected.

Consulted repository `.agents/skills/python-design-patterns/SKILL.md` and available `design-patterns-refactoring/SKILL.md` (including Divergent Change, Shotgun Surgery, Feature Envy and Middle Man catalogue entries). Their composition, protocol and single-responsibility guidance supports the narrow port/adapter boundary. No premise or confirmed contract was disproved in the architecture pass, so Specify remains unchanged.

## Retrieval and blast radius

`zg status` bound to this checkout with 954 indexed files; prose queries found ADR-014 (capability registry), ADR-016 (explicit sync), ADR-021 (capability access), ADR-023 (first-present group vault read). Serena overviews and references established `VaultSource.get`, `build_vault_source`, `CapabilitySpec`, `EngineHost`, `VaultError` and `JobExecutionEngine`'s construction seam. `graphify get_neighbors` showed the vault source/config and capability/engine dependency directions; its graph is stale relative to this checkout, so all file and symbol assertions below were checked against source and `rg`. `uv run lint-imports` baseline: 7 kept, 0 broken. Focused baseline pytest invocation: 95 passed.

The observed hit sets drive the task scopes: `VaultSource.get` is covered by `tests/config/test_vault_miss.py`, `tests/config/test_vault_source_lazy.py`, and `tests/app/test_remote_first.py`; `build_vault_source` is used by `_app/impl.py` and `tests/app/test_remote_first.py`; the capability registry/name set is covered by `tests/engine/test_capability_registry.py` and `tests/discovery/test_capability_parity.py`; real job wiring is covered in `tests/integration/test_capability_duality.py`, `tests/integration/test_local_vault_e2e.py`, and `tests/engine/test_engine_is_sealed.py`. The new adapter and public exports require new direct and end-to-end tests. Existing group identity tests in `tests/config/test_vault_identity.py` remain a regression gate, not a policy rewrite.

## Implementation boundaries and checks

1. Add only the typed port and explicit missing error, then the composition adapter. Keep `VaultSource` and `VaultIdentity` behavior intact.
2. Register the capability through the existing `CapabilitySpec` and primitive name-set agreement. Wire it through `build_engine` for static and standard boots. Public reexports make the confirmed imports work.
3. Test group precedence and first-present fail closed for direct and provider origins; missing file/entry; job and other-environment exclusion; static/standard entry paths; no remote provider call; redaction of output, logs and exceptions. Retain ordinary config-chain miss fall-through. Add a real job example and explain the API and typed errors in the configuration guide.
4. Record the durable design in the next ADR (`contributor/adr/044-...md`) before merge. The feature artifacts are branch-only and follow the repository's two-push cleanup after Execute/Verify.

Execute acceptance gates: `uv run lint-imports`; `uv run ruff check src/ tests/`; `uv run ruff format --check src/ tests/`; `uv run mypy src/`; focused `uv run pytest -q` over the vault, capability, discovery and integration hit set; full `uv run pytest` at Verify. A real public-entry job test must fail if the boot-to-factory connection is deliberately removed after the implementation is committed, then pass after restoration (the repository's reachability rule). Inspect the runtime secret marker across captured stdout, stderr, logs, error text and diagnostics. The `contract-diff-carries-task-graph` and write-time checks must parse `tasks.md` before source work starts.

## Risks

- A static custom chain may have no `VaultSource`. The adapter's fallback uses existing boot construction and must be tested with and without a vault file; it must never ask the custom chain for lower-priority values.
- A chain refresh can replace the source. Open the reader from the current app state per invocation rather than capture an old source at boot.
- `VaultSource.get` returns plaintext internally. Wrap at the adapter's public boundary and test every visible error/diagnostic path; deliberate `Secret.get_secret_value()` at a trusted job sink remains the caller's responsibility.
- The name-set/registry split is required by the peer-layer rule; the import-time agreement check and discovery parity test are mandatory to prevent a new CLI input.

## Surviving smells

- **Shotgun Surgery** at `_engine/capabilities/registry.py`, `_primitives/capability_names.py`, and public `job/` exports: adding an injected type requires synchronized declarations. The existing import-time equality check prevents the dangerous discovery drift; the peer-layer boundary prevents deriving the name set from the engine registry. Accepted for this feature; no maintainer review is needed beyond the normal Plan approval and the explicit parity gate.
- **Divergent Change** already exists in `JobExecutionEngine` and `app/vault.py`, which serve several features. This plan adds only a typed factory reference to the engine and a public error reexport to `app/vault.py`; vault behavior lives in the new `_app` adapter. It does not add another responsibility to either class. Accepted existing condition; no separate maintainer review needed.

## Next gate

Ask the member to approve the task waves and the two disclosed surviving smells. Only then may a heavy implementer start Execute from this branch; this Plan turn does not dispatch implementation.
