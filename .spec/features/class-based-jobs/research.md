# Class-based jobs — research

Findings from the Specify retrieval pass on `master` `bb3aac7`
(2026-10-21) that change the shape or that Plan must carry. Each records the
command behind it.

## Premises re-measured

| Claim | Command | Result |
|---|---|---|
| No class discovery in `_discovery`/`_app` | `git grep -n -e isclass -e getmembers HEAD -- src/functualize/_discovery src/functualize/_app` | no match, exit 1 |
| Function-only filters | `git grep -n isfunction -- src/functualize/_discovery` | `sync.py:410`, `registry.py:607` (plus two docstrings) |
| `@job` replaces | `grep -n __functualize_job__ src/functualize/job/decorators.py` | `:105` assigns the declaration wholesale |
| `JobDeclaration.config_section` has no reader | `git grep -n '\.config_section' -- src/functualize` | the only hits read plugin/domain metadata, not the declaration (`_plugins/loader.py`, `_plugins/domain_registry.py`) plus its own `to_dict` |
| No stacked `@job` and no `@job` on a class anywhere in the repo | AST walk over every `*.py` outside `.venv` counting `job` decorators per function/class | 0 — D4's refusal and C1's class rule break no existing caller |
| Normalization | `normalize_segment` on sample names | `LocalPostgres→local-postgres`, `stop_all→stop-all`, `HTTPServer→http-server` |

## Corrections to the shape page's *Current reality*

- The page (measured `3ebf9a97` and `c03dfb7`) says invoking the surviving name
  of a collision prints nothing. `bb3aac7` (*use one command path across job
  surfaces*) added `_warn_collisions` (`src/functualize/_cli/main.py:937`): the
  survivor's invocation now prints the collision line to stderr, then runs. The
  plain-function rule is therefore *reported* on every surface, but still runs a
  survivor — so model E vs F (D3) is still a real choice.
- Scoped vault resolution landed in `91947bb`. A secret `GroupOptions` field
  already resolves under `--group <declaring group> --field <name>`
  (`docs/guides/group-options.md:141`), while a grouped job's own config field
  uses `--group G --job J`. D2's recommendation therefore reuses an existing
  identity form rather than extending the vault grammar.

## Prior art the design must not contradict

- **ADR-018** (*An unsatisfiable job is reported, not fatal to the app*): one bad
  definition must not take down the project or its diagnostic commands. Model E
  follows it — only the colliding name is refused; model G (refuse the project)
  would contradict it, as `collisions.py` also records.
- **`docs/guides/subjects.md` rule 3** — "Constructors are inert. No-argument, no
  side effects, one instance per process." F1's instance-per-run replaces it;
  the guide revision must say so rather than leave both.
- **`EntryPointProvider` (`src/functualize/_discovery/providers.py:700`)** —
  "Enumeration imports nothing", and its docstring records why (zero-import warm
  boot). An entry point naming a **class** must list several jobs whose names
  come from the class body. Plan must choose between importing that one module
  at enumeration (forfeiting zero-import for that entry point only) and reading
  the class from source; the spec only requires that function entry points keep
  zero-import enumeration.
- **`contributor/reference/pitfalls.md` §5, §11, §12, §21, §22** and
  **`contributor/guides/wiring-discipline.md` §5** — warm-cache and lazy-boot
  defects. A cached class-based descriptor must rebuild "class + method" without
  holding a live object in a cache key, and AC-7 must exercise the warm path
  through a composed boot, not by driving a provider directly.
- **`contributor/adr/010-job-schema-in-core.md`** — every job-facing surface
  publishes the same inputs through `job_input_schema`. C6's "fields appear
  where a function job's config-model fields appear" is that rule applied.
- **`AGENTS.md` → public API example coverage** — `JOB_TAGS` and the class form
  of `@job` are public surface and need a caller in `examples/`.

## Readings of the page that Plan inherits

- **Method `@job(group=...)` inside a job class.** F4 lists `group` among the
  values a contributed value never overwrites, while F1 requires one section per
  class. Read together: the class's group is identity (F1), not contributed
  metadata (F4), so a method naming another group is a finding and produces no
  job (contracts C4) rather than splitting the class across sections.
- **`StaticProvider([Job(function=<job class>)])`** is refused: `Job.name` and
  `Job.group` would rename one job, and a job class names N jobs and its own
  group (F1-b).
- **Public method** excludes pydantic `BaseModel`'s own methods
  (`model_dump`, …), properties, `classmethod`s and `staticmethod`s; F1's
  instance-per-run only makes sense for instance methods.
