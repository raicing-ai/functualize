# Plan: optional job parameters on the CLI

## Alignment

WorkflowMode: `REPOSITORY_NATIVE`. WorkflowAuthority: `AGENTS.md`,
`.claude/agents/spec-driven-developer.md` Phase 3,
`.claude/rules/spec-workflow.md`, and SD/17137691 v4, **Shape Intent — Optional
Parameters Earn a CLI Flag (X | None and the tri-state boolean)** (`Status =
Approved`, `Authority = Approved`). CurrentPhase: Plan. ArtifactLocations:
`.spec/features/optional-parameter-cli-flag/{spec.md,contracts.md,plan.md,tasks.md}`.
ApprovalState: shape approved; `spec.md` and `contracts.md` confirmed at
`4d4871f`; task plan awaits review. ContextPolicy: the confirmed spec and
contracts are frozen; a disproved clause requires renewed confirmation before
either changes.

The shape's included surfaces are implicit optional CLI values for every
already eligible `X`, both `X | None` and `Optional[X]`, and the `bool | None`
tri-state. Excluded surfaces are general unions, altered non-optional bool
behavior, config-file and environment sources for signature parameters,
discovery findings for still-dropped parameters, and flags for injected
capabilities. Delivery remains before the 0.5.0 tag.

## Architecture gate: BEFORE

```text
job signature
  -> _cli/annotation_utils.py::parse_annotation       [CLI delivery]
       -> app/utils.py::is_cli_value_type              [public bridge]
            -> _primitives/parameter_types.py          [foundation]
       X | None is rejected at compatibility check :254
  -> app/adapters/click_params.py::build_click_params   [delivery adapter]
       -> parse_annotation; rejected parameter is dropped :781
       -> _click_type_for :159 -> _config/job_config.py::_unwrap_optional
                                  [config peer; only reached after filter]
       -> _types/flag_grammar.py::negative_flag_for :195 [foundation]
  -> _engine execution                            [internal peer]
       receives only parameters that survived the delivery adapter
```

Arrows are import/call direction. The `_cli` to `app/utils.py` arrow crosses
from CLI delivery to the public API; the public bridge to `_primitives` is
downward. The adapter's call to the `_config` helper crosses from delivery to
an internal peer, already present. No internal peer imports a delivery layer.
The `func` and embedded `FunctualizeApp` doors converge on this builder through
`create_job_click_command` / `create_job_command`.

**Existing smells.** *Divergent Change* at
`_cli/annotation_utils.py::parse_annotation` and
`app/adapters/click_params.py::_click_type_for`: the classifier and renderer
answer the optional question at different points, so one can reject a type
that the other already knows how to convert. *Long Method* at
`app/adapters/click_params.py::build_click_params` (about 200 lines, filter plus
argument/option emission); the bool collision is one branch within it. The
separate optional unwrappers in `_config/job_config.py`,
`_discovery/providers.py`, and `_discovery/schema_extractor.py` are *Duplicate
Code*, but their current consumers and semantics have different scopes; this
feature does not consolidate them.

## Architecture gate: AFTER

```text
job signature
  -> _cli/annotation_utils.py::parse_annotation          [CLI delivery]
       -> app/utils.py::{is_cli_value_type,
                        unwrap_optional_type}          [public bridge]
            -> _primitives/parameter_types.py            [foundation]
            -> _config/job_config.py::_unwrap_optional   [config peer]
       checks DI/config/CLI eligibility on inner X, keeps original
       AnnotationInfo.base_type for downstream rendering
  -> app/adapters/click_params.py::build_click_params     [delivery adapter]
       -> parse_annotation; eligible optional values survive filter
       -> _click_type_for -> same _unwrap_optional       [existing path]
       -> negative_flag_for                              [foundation]
       -> optional bool branch preserves None and sets is_flag=True
          even when the negative spelling is owned by no_<name>
  -> _engine execution                             [internal peer]
       receives Click-converted value or declared default; unchanged
```

The new `_cli` import is through public `app/utils.py`, not an internal
package. `app/utils.py` re-exports the *existing* `_unwrap_optional` helper
under a descriptive public name; it owns no new optional parsing rule. The
renderer continues to use that same helper. The classifier probes the inner
type for DI, config, and CLI eligibility but retains `AnnotationInfo.base_type`
as the unmodified annotation. That preserves marker handling and the current
renderer contract. `negative_flag_for` retains sole ownership of spelling
collisions; the builder adjusts Click's interpretation only for an optional
boolean with an absent `None` state. No config resolution, schema type, engine
binding, or CLI dependency enters a kernel layer.

`python-design-patterns` (checked-in skill: KISS, single responsibility,
separation of concerns) and `design-patterns-refactoring` (Divergent Change,
Long Method, Duplicate Code) were consulted. The chosen bridge has one rule
and keeps Click construction in the delivery adapter. A broader refactor of
the builder or the other optional unwrappers would add unrelated changes.
`uv run lint-imports` on rebased `38b54460` plus confirmed spec passed: 7
contracts kept, 0 broken. The same command is an Execute gate after edits.

## Rebased evidence and blast radius

The branch was rebased onto `origin/master` `38b54460` before Plan. On this
head, `parse_annotation` still rejects both optional string spellings,
`bool | None`, and optional injected types as CLI-compatible;
`build_click_params` publishes only `name` for the `greet` fixture. The filter
is still `click_params.py:781` and `_click_type_for` still unwraps at `:159`.
`negative_flag_for` moved from `:190` to `:195`, but still returns `None`
when `no_<name>` is a sibling. A direct Click probe showed a paired boolean
option with `default=None` yields absent `None`, positive `True`, negative
`False`; a lone positive option with `default=None` requires a value unless
`is_flag=True` is set. E7 therefore requires explicit flag construction.

Serena references for `parse_annotation` point to the builder's filter and
variadic check and to `tests/cli/test_cli_compatible_type.py` and
`test_annotation_utils_properties.py`. References for `build_click_params`
point to the job, embedded-app, and raw-callback command constructors, plus
adapter and CLI parity tests. References for `_unwrap_optional` point to
config coercion/validation and `_click_type_for`; its implementation should
remain untouched. Graphify confirms `build_click_params` feeds both job
constructors and that `negative_flag_for` is shared by config, group-option,
TUI, and signature rendering. Thus the change stays in classification, the
public bridge, and the plain-signature bool construction; the shared negative
grammar and config callers remain read-only regression targets.

The documented optional injected examples found by `rg -n` are
`README.md:57` (`RunContext | None`) and
`docs/guides/interactivity.md:133` (`TTY | None`). The source scan for those
spellings is a task gate, so new examples are checked rather than assumed
absent. `contributor/adr/016-remote-source-activation.md:268-272` confirms
ordinary function parameters are invocation inputs, not config targets.

## Files to change and dependencies

- `src/functualize/app/utils.py`: public re-export of the existing optional
  helper; required before the classifier imports it.
- `src/functualize/_cli/annotation_utils.py`: classify on the inner type while
  retaining the original base annotation and Provide/marker precedence.
- `src/functualize/app/adapters/click_params.py`: optional bool's explicit
  `is_flag`/`None` behavior, including the sibling collision. Keep the existing
  plain bool branch's observable behavior.
- `tests/cli/test_cli_compatible_type.py`,
  `tests/cli/test_annotation_utils_properties.py`: eligibility and DI/CLI
  exclusivity. `tests/adapters/test_boolean_negation.py`: Click option shape
  and collision. A new `tests/cli/test_optional_parameter_cli.py` covers the
  public command and absence/supply behavior.
- `CHANGELOG.md`: one Unreleased → Fixed entry for the user-visible result.
- `.spec/STATUS.md`: durable decision and verification record during merge
  preparation. The feature directory is then removed in a final deletion-only
  commit, after its graph and validation have been reviewed.

The test paths above come from Serena's reference hit set and existing adapter
tests. The new integration test is required by the external contract; no
other implementation file is in the scoped change set. Existing
`tests/adapters/test_click_params_parity.py`,
`tests/cli/test_arg_marker_unit.py`,
`tests/types/test_flag_grammar_roundtrip.py`,
`tests/discovery/test_parameter_extraction.py`, and the documented example
sources are read-only regression targets from the reference graph.

## Verification and risks

Execute must prove E1-E7 from `spec.md` through the public `func` path where
applicable, and pin E6 against ancestor `e00d870` before accepting the test.
Run the focused tests, `uv run lint-imports`, the repository's Ruff, mypy, and
pytest gates. Remove the production call path temporarily *after committing*
the implementation and verify the new end-to-end test fails, then restore it;
this is the repository's reachability check. Compare existing flag snapshots
and config field behavior without rewriting their contracts. A release check
must confirm the branch is merged before the 0.5.0 tag.

Risk: the sibling `no_loud` consumes `--no-loud`, so an optional `loud`
cannot express `False` on that command; this is the approved degradation and
must be visible in E7. Risk: `app/utils.py` is a broad public bridge; adding
the helper there exposes a reusable function, so its name and export must be
reviewed as API. Risk: the lazy descriptor path and group config options use
the same Click builder's adjacent functions; parity tests must show their
flags did not move. If any gate reveals a confirmed spec clause is false,
stop before editing `spec.md` or `contracts.md` and seek reconfirmation.

## Surviving smells

- *Long Method* — `app/adapters/click_params.py::build_click_params`. It
  already combines filtering and emission; one conditional addition is
  bounded here to avoid changing unrelated command paths. **Maintainer review:
  no** for this feature; the focused E1-E7 tests and parity gates protect the
  touched branch.
- *Duplicate Code* — optional unwrappers in `_discovery/providers.py` and
  `_discovery/schema_extractor.py` remain separate from the shared classifier
  and renderer helper. They serve discovery and config schema concerns outside
  the approved CLI surface. **Maintainer review: no** for this feature; no new
  copy of the optional rule is introduced.
