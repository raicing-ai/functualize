# Architecture plan

## Alignment

Confluence SD/19595276, *Shape Intent — One Job Namespace: Identity, Command Path and Collisions on Every Surface*, version 2, updated 2026-10-19 04:37:16 UTC, was read live. Its field table says `Authority = Approved`; the member approved B, S2, N1-a, N2 include and N3 include. MCH-194 is the one carrier. This plan uses the page's own boundary words: **In scope** every shell surface that prints or accepts a job, the TUI group trie always built from the job list, collision surfacing including the TUI, and FOSS-24 / FOSS-59 root `--help`. **Out of scope** `normalize_segment` and the naming rule, the `GroupOptions` flag grammar, collision as a discovery refusal, flag-name defects, `@job(name=)` override, and standalone `Usage: -c`. Program surfaces keep dotted identity. The older root-help decision in `.spec/STATUS.md:3860` is superseded by N3.

## Architecture gate: current shape

The CLI and application door use one descriptor identity but independently construct shell text. The TUI trie is conditional on `GroupOptions`, so its fallback bypasses path navigation. A collision finding is collected in discovery but narrow listings and TUI rows never project it. Existing smells: **primitive obsession** (`JobDescriptor.name` stands for both identity and command path), **shotgun surgery** (`_cli/main.py`, `app/adapters/cli.py`, `app/adapters/click_params.py`, TUI renderers each derive another spelling), and **divergent change** (`build_group_option_trie` makes job navigation depend on flag declarations).

```text
BEFORE  (arrows mean runtime import or data/call direction)
Internal vocabulary _types:
  src/functualize/_types/descriptors.py --name:str--> src/functualize/_types/naming.py::_job_segments
  src/functualize/_types/naming.py::GroupTrie --name/group--> own _job_segments
Public boundary:
  src/functualize/app/utils.py --build_group_trie--> _types/naming.py
  src/functualize/types/__init__.py --re-export--> _types/descriptors.py
Shell delivery, through public app/types API:
  src/functualize/_cli/main.py --raw name, Click prog_name--> app/adapters/click_params.py
  src/functualize/app/adapters/cli.py --leaf-only name--> src/functualize/app/commands.py
  src/functualize/_cli/dispatch.py --dot-splitting token--> GroupTrie.step
  src/functualize/_cli/tui/cli_arg_parser.py --only if GroupOptions--> app/utils.py::build_group_trie
  src/functualize/_cli/tui/smart_bar_autocomplete.py --optional trie--> flat identity fallback
  src/functualize/_cli/tui/app.py, src/functualize/_cli/tui/sync.py,
  src/functualize/_cli/tui/panels/job_browser.py, src/functualize/_cli/inline_tui.py,
  src/functualize/_cli/data/invocation_preset.py --independent string conversion--> person
  src/functualize/app/_workflow_resume.py, src/functualize/app/adapters/click_params.py
      --independent string conversion--> person
Discovery and report:
  src/functualize/_discovery/collisions.py, src/functualize/_discovery/pipeline.py,
  src/functualize/_discovery/registry.py --finding--> src/functualize/_types/discovery_report.py
  _app composition root --> src/functualize/_cli/info.py --> src/functualize/_cli/builtins.py
  src/functualize/_cli/tui/panels/job_browser.py --descriptors only--> person
```

## Chosen shape

One `CommandPath` value is built from the existing trie's segment rule in `_types/naming.py`. `JobDescriptor.command_path` derives it from `group` and `name`; it is not persisted, so cache JSON and program identity stay unchanged. The trie inserts those same segments. Shell renderers receive the descriptor or a trie node, never reverse-engineer a path from the identity. `TrieNode.path` decides whether one input token traversed more than one group edge: a dotted group traversal is rejected, while a one-segment literal-dot leaf remains legal. This preserves E6 without a blanket dot ban. The app's Click door reports the same spaces hint from its command tree. Root help obtains discovered jobs and the same trie in its diagnostic help path; the global options page remains readable when a project has a discovery problem.

The collision collector keeps the existing `DiscoveryFailure.as_dict()` shape. An optional typed collision detail on the in-memory finding carries claimant names and source paths. A delivery-side projection joins findings by canonical identity to the final surviving descriptor, so a chain of three claimants reports each displaced claimant against the final winner. One text renderer feeds invocation, group help, info, and TUI. Its JSON sibling emits the additive `collisions` array while keeping `name` dotted. No new `_cli` to internal import edge is allowed; existing public app/types facades and the established diagnostic read in `_cli/info.py` remain the boundary.

```text
AFTER  (arrows show dependency direction; bracketed labels are layer/audience)
[_types/internal] src/functualize/_types/naming.py::CommandPath.of + GroupTrie.from_cache
       ^ same path segments                         ^ no CLI dependency
       |                                            |
[_types/internal] src/functualize/_types/descriptors.py::JobDescriptor.command_path
       ^                                               |
       | public re-export                              | app construction
[types/public] src/functualize/types/__init__.py       |
       ^                                               |
       +---- [_cli/delivery] src/functualize/_cli/main.py, src/functualize/_cli/dispatch.py
       +---- [app/public] src/functualize/app/adapters/cli.py,
                         src/functualize/app/commands.py,
                         src/functualize/app/adapters/click_params.py,
                         src/functualize/app/_workflow_resume.py
       +---- [_cli/delivery] src/functualize/_cli/tui/cli_arg_parser.py
                         -> src/functualize/app/utils.py::build_group_trie
       +---- [_cli/delivery] src/functualize/_cli/tui/smart_bar_autocomplete.py,
                         src/functualize/_cli/tui/app.py,
                         src/functualize/_cli/tui/sync.py,
                         src/functualize/_cli/tui/panels/job_browser.py,
                         src/functualize/_cli/inline_tui.py,
                         src/functualize/_cli/data/invocation_preset.py,
                         src/functualize/_cli/completions/provenance.py

[_discovery/peer] src/functualize/_discovery/collisions.py,
                  src/functualize/_discovery/pipeline.py,
                  src/functualize/_discovery/registry.py
       -> [_types/internal] src/functualize/_types/discovery_report.py::typed detail
       -> [_app/composition] existing provider/pipeline inventory
       -> [_cli/delivery] src/functualize/_cli/info.py::one projection + renderers
       -> [_cli/delivery] src/functualize/_cli/builtins.py, src/functualize/_cli/main.py,
                          src/functualize/_cli/tui/app.py,
                          src/functualize/_cli/tui/panels/job_browser.py
```

`app/_workflow_resume.py` receives a descriptor/path at its human-facing hint boundary; state and workflow storage keep identity. `app/adapters/click_params.py` receives the path for its resume line. `invocation_preset.py` is handed a descriptor lookup when building display text; history keys remain identity. `provenance.py` uses group/path data rather than splitting identity. The TUI's bar writer continues to own quoting and mid-path flag placement. Source files that split dots for *programmatic* vault, config, module or version identifiers are outside E8; the ratchet identifies job-name-to-shell conversions and job-name splits explicitly, rather than banning every `split(".")` in the repository.

## Candidate check and constraints

- Option A (a helper returning `str`) leaves **primitive obsession** and raw `descriptor.name` renderers; the ratchet cannot catch the latter. Rejected by approved B.
- Option C (live trie as every renderer's oracle) would add temporal coupling to the app door and cold hints. Rejected by approved B.
- Chosen B puts only value construction and the trie's existing segment rule in `_types/naming.py`. This is an established local exception to the codemap's shorthand “_types zero logic”: `_job_segments`, `GroupTrie`, normalization and resolution already live there. The member explicitly approved this exact location. No peer-layer import or delivery dependency is added. The internal collision detail is data, not a second resolver.
- Root help's old pinned test contradicts N3 and must be rewritten with cold/warm parity. Help must not make a broken project unable to read diagnostic commands. No new global mutable cache, singleton, or second execution path is introduced.

## Blast radius and file scopes

Serena references establish the `_job_segments` caller (`GroupTrie.from_cache`), `build_group_option_trie` consumers (inline TUI, full TUI, SmartBar, example), `walk_group_path` callers (`_cli/main.py`, TUI resolver and group-option tests), `job_catalog` consumers (`_cli/builtins.py`, full report and exact-key tests), and `job_name_collision` producers (collisions, pipeline, registry). Graphify confirms the direction of those edges; its committed graph's `built_at_commit` is unavailable in this checkout, so source and Serena are the line-level authority. The site list from `rg -n` in `research.md` is the task-scope census. No source file moved between `d1c7e40a` and this base in this region.

## Surviving smells

- **Feature envy**: `src/functualize/_cli/info.py::discovery_failures` reads provider and pipeline attributes for diagnostics. It predates this feature and remains the read seam for the projection; changing it to a new public application API would widen the approved Python surface. No new private attribute is introduced, and the existing read is covered cold and warm. Maintainer review: **no**; this is an unchanged seam, disclosed so later public diagnostic API work can remove it without leaving a behavior gap.
- **Long method**: `_cli/main.py::_dispatch_group` is already a large router; this plan keeps path refusal and collision formatting in small helpers rather than adding another branch of formatting inside it. No growth beyond the call/wire is accepted. Maintainer review: **no**, conditional on the implementation keeping the helper split and the task gate measuring it.

No forbidden pattern is accepted: `_cli` continues to import only public facades, internal peer layers remain independent, and no kernel layer imports a runtime TUI library. The task review must state these surviving smells explicitly before Execute.

## Verification and delivery

Tests are written red against `91947bb` for E1–E8, then each wave proves its production wire from both `func` and the app/TUI surfaces. Follow `contributor/guides/wiring-discipline.md`: commit before temporarily removing a wire and show a test fails. Run `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, targeted pytest then the CI tip tier through the PR. Use `dead_code_delta.py` before handoff. A final source scan and exact baseline repro are required, including cold and warm caches and mid-path group flags. The public type/property has a caller under `examples/` and its example tests run. Migrate the durable rule to `.spec/STATUS.md` or an ADR, then make the deletion-only artifact commit after the feature validation push.
