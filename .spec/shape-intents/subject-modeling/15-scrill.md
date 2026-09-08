# 15 — Scrill: a script that ships its skill, a skill that ships its scripts

The goal, in the owner's words: *a job that, when run, achieves what a generic
skill achieves — but deterministically and hermetically; and a scrill that
allows all modes of operation, forcing interoperability on nobody.*

This page establishes what functualize 0.2.3 already provides for that
(§1, all probed), the three gaps (§2), four alternative shapes with human and
agent lifecycles for each (§3), and the recommendation (§5). The
non-forcing rule is §4 and is the constraint every alternative is judged
against.

---

## 1. What already works — the four mechanisms [probed]

A skill delivers judgment to an agent at decision time. A job delivers
behaviour to a machine. The claim that a job can do the *first* job rests on
four mechanisms that exist today.

| # | Mechanism | What it buys | Evidence |
|---|---|---|---|
| 1 | `JobDescriptor.source_file` is populated for directory-scanned jobs | a job can locate its own `SKILL.md` **by layout** — no manifest, no registry | `evidence/probe_14_scrill_layout.py` |
| 2 | `@job(tags=…, examples=…, extra_description=…)` survives discovery *and the cache* as `descriptor.declaration` | a declaration site for the skill link that costs no import | `evidence/probe_13_declaration_survival.py` |
| 3 | `job_detail(...)["inputSchema"]` — the **inbound** surface, shared by CLI `builtin info` and MCP | the agent reads the interface as JSON Schema instead of trusting prose | probe 13; `_cli/info.py:149` |
| 4 | `Precondition(check, msg)` → `RunStatus.REFUSED`, message verbatim in `metadata.preflight.reason` — the **outbound** surface | the job hands the agent a targeted instruction *at the moment it refuses* | `evidence/probe_15_refusal_guidance.py` |

Mechanism 4 is the interesting one, and it is worth being explicit about why:

```python
@job(guards=Guards(preconditions=[Precondition(
    "test -f /var/lib/postgresql/PG_VERSION",
    "Postgres is not initialised. Read the pgops skill, section 'first run', "
    "then run `func pg init`.")]))
def backup() -> None:
    """Back up the database."""
```

```
status: RunStatus.REFUSED        # exit 3
metadata.preflight.reason: "Postgres is not initialised. Read the pgops
    skill, section 'first run', then run `func pg init`."
```

A skill's description is loaded on a *guess* — the agent matches trigger
tokens and hopes. A precondition message is delivered on a *fact* — the
check ran, it failed, and the guidance is the consequence. That is the
"deterministic and hermetic" claim made concrete: **a skill fires on
similarity, a job fires on state.**

Delivery is also already solved and does not need inventing.
`func builtin skills install` shells out to `npx skills add <dir>`
(`_cli/builtins.py:1565`) — the skills CLI accepts *any* directory. Scrill's
problem is producing and locating the directory, not shipping it.

And functualize already ships the prose version of this idea: the
`functualize-skill` skill (0.2.3, `skills/functualize-skill/SKILL.md`) is
titled *"Author an agent skill whose bundled scripts are functualize jobs."*
It prescribes the layout, PEP 723 self-containment, `Stdout.emit`,
`Secret[str]` masking, and the rule **"do not document the interface twice —
tell the agent to ask the script."** Scrill is the mechanism for a convention
functualize has already written down.

---

## 2. The three gaps

| Gap | Where | Consequence |
|---|---|---|
| `resolve_skills_dir()` is hardcoded to `<functualize package>/_skills`, then `<repo>/skills` | `_cli/skills.py:88` | **no third-party skill hosting.** `builtin skills list` will never show risekit's, or anyone's. Every package reinvents locate/list/materialize — v3 `09` §5 already commits risekit to doing exactly that |
| `job_detail` returns 12 keys; `declaration` is not among them | `_cli/info.py:137`, probe 13 | the skill link exists on the descriptor but **never reaches the agent**. The one surface that could say "this job has a skill" doesn't |
| `_KNOWN_TOOL_KEYS = frozenset({"job"})` — anything else warns | `_cli/pep723.py:53` | a single-file script **cannot declare its skill** without a warning on every run |

These become upstream asks 6, 7, 8 (§6). None is a blocker; all three are
small, and each removes a workaround that would otherwise be permanent.

---

## 3. Four alternatives

Each is given the same two walkthroughs: a human authoring and living with
it, and an agent meeting it cold.

---

### A — Sidecar scrill: *the directory is the scrill*

The skill directory grows a `scripts/` that is an ordinary functualize job
file. Nothing is declared; the relationship is the layout.

```
pgops/
├── SKILL.md              # name: pgops
├── scripts/
│   └── jobs.py           # JOB_GROUP = "pg";  @job def backup(...)
└── references/
    └── recovery.md
```

Works today, unmodified. The job finds its skill with
`Path(source_file).parent.parent / "SKILL.md"` [probed].

#### Human lifecycle

```console
$ rise new scrill pgops             # scaffolds the tree above
$ $EDITOR pgops/SKILL.md            # the judgment: when to back up, what to
                                    # check first, what "healthy" looks like
$ $EDITOR pgops/scripts/jobs.py     # the mechanics
$ func pgops/scripts/jobs.py backup --to /tmp     # run it directly, no install
$ npx skills add ./pgops                          # ship it to the agent
```

Six months later a flag is renamed. The human edits `jobs.py` only —
`SKILL.md` never named the flag, because the skill says *"run
`func builtin info schema` in `scripts/` for the interface."* Nothing drifts
because nothing was duplicated.

#### Agent lifecycle

```
1. discover  a request mentions "restore the staging database"
             → description trigger matches → SKILL.md loads
2. orient    SKILL.md: "This is a functualize job file. Ask it:
                func builtin info schema"
3. read      {"pg.backup": {"to": {"type":"string","default":"/tmp"}},
              "pg.restore": {"from": {"type":"string"}}}
             ← the real signature, not a transcription
4. act       func pg restore --from /backups/2026-09-04.dump
5. refuse    exit 3, reason: "Refusing: staging has open connections.
             Run `func pg drain` first, or pass --force (data loss)."
6. correct   the agent runs `func pg drain`, retries, succeeds
```

Step 5 is the payoff. The agent did not need to have *read* the danger in
the skill — the job asserted it. Had the skill never loaded at all, step 5
still happens.

#### Cost

Two authoring surfaces in one directory, and nothing enforces that the prose
matches the code. Distribution is "a directory", which is fine for a repo
and weak for cross-team sharing.

---

### B — Package scrill: *a distribution ships skills next to jobs*

The unit is a wheel. Skills live in `_skills/`, force-included; jobs are
ordinary modules; both are found through entry points.

```toml
# pyproject.toml
[project.entry-points."functualize.plugins"]
pgops = "pgops.plugin:PLUGIN"

[project.entry-points."functualize.skills"]      # ← upstream ask 6
pgops = "pgops._skills"

[tool.hatch.build.targets.wheel.force-include]
"skills" = "pgops/_skills"
```

```python
@job(group="pg", tags=("scrill:pgops",))
def backup(to: str = "/tmp") -> None:
    """Back up the database."""
```

#### Human lifecycle

```console
$ uv add pgops-scrill
$ func builtin skills list
  functualize        …
  pgops              Operate a local postgres…      ← now listed (ask 6)
$ func builtin skills install                        # npx skills add, all of them
$ func pg backup --to /tmp                           # jobs came with the same wheel
$ uv lock --upgrade-package pgops-scrill
$ func builtin skills install                        # skill and job upgrade together
```

The version-stamping property functualize already relies on
(`_cli/skills.py:16`) now holds for third parties: the skill on disk cannot
describe a release other than the one installed, because it came out of the
same wheel.

#### Agent lifecycle

```
1. discover  skills already materialized at install time — no trigger-match
             gamble for the ones the project has deliberately installed
2. orient    the skill's frontmatter carries metadata.version = the wheel's
3. read      func builtin info --output json
             → every job, with "tags": ["scrill:pgops"]     ← upstream ask 7
             the agent can now go from a job it found to the skill that
             explains it, which is the direction that actually matters
4. act       func pg backup --to /tmp
```

Step 3 inverts the usual flow. Everywhere else, the skill points at the
scripts. Here the *job* points at the skill — so an agent that arrived via
`func builtin info` (or MCP tool discovery) can find the judgment it is
missing, instead of only the reverse.

#### Cost

Needs asks 6 and 7. Wrong shape for a one-off, and the ceremony (a wheel, a
version, an entry point) is real. This is the *distribution* answer, not the
*authoring* answer.

---

### C — Single-file scrill: *the file is the scrill*

One `.py` file, PEP 723 metadata, hermetic through `uv`. The skill is
generated from the file rather than sitting beside it.

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["functualize[cli]"]
#
# [tool.functualize]
# job = "backup"
# skill = "pgops"          # ← upstream ask 8
# ///
"""Back up a local postgres.

Use when asked to back up, dump, or snapshot a postgres database, or when
the user mentions pg_dump. Requires an initialised cluster; refuses with
instructions if there is not one.
"""
```

The module docstring *is* the skill description; `func <file> skills emit`
writes a conformant `SKILL.md` around it.

#### Human lifecycle

```console
$ curl -O https://example.com/pgops.py
$ chmod +x pgops.py
$ ./pgops.py --help                     # uv builds the env on first run
$ ./pgops.py --to /tmp
                                        # want it as a skill too?
$ func pgops.py skills emit ./pgops-skill && npx skills add ./pgops-skill
```

Nothing is installed. Nothing is configured. The file is the whole artifact
and it works on a machine that has never heard of functualize — which is
exactly v3's standalone-bootstrapper case (`04` §1B).

#### Agent lifecycle

```
1. discover  the agent is handed a path, or finds pgops.py in the repo
2. orient    it reads the file — the PEP 723 block and the docstring are
             the frontmatter, in plain sight, no separate document
3. read      ./pgops.py --help          (generated from the signature)
4. act       ./pgops.py --to /tmp --output json
5. refuse    exit 3 + reason, same as everywhere
```

The agent needs no skills infrastructure at all. Reading the file *is*
loading the skill.

#### Cost

Ask 8, or a warning on every run. A skill body must stay docstring-sized —
no `references/`, no progressive disclosure. And the emitted `SKILL.md` is a
derived artifact someone will eventually hand-edit.

---

### D — Derived scrill: *the class is the scrill* (rise-native)

v3's module classes already carry everything a skill's *mechanical* half
needs. Generate it.

```python
class Postgres(Process, Controllable, Backupable):
    """A local postgres cluster managed through systemd.

    Back up before every migration. A backup taken while connections are
    open is not consistent — drain first.
    """
    group = "pg"

    def backup(self, to: Path = Path("/tmp")) -> Path:
        """Back up the cluster to a dump file."""
```

`rise skills build` emits:

| Skill section | Derived from |
|---|---|
| frontmatter `name` | `group` |
| frontmatter `description` | class docstring first paragraph + method summaries |
| "What this is" | substrate + protocol names — `Process`, `Controllable`, `Backupable` |
| "Interface" | `job_input_schema` per bound method — never transcribed |
| "When it will refuse" | every `Precondition.msg` on the class, tabulated |
| "State it reports" | the `Diagnosis` model's JSON Schema |

CI asserts the emitted file matches the committed one — a `--check` mode, the
same lever `12-acceptance-mapping.md` uses everywhere else.

#### Human lifecycle

```console
$ $EDITOR modules/postgres.py           # the only file authored
$ rise skills build                     # writes skills/pg/SKILL.md
$ rise validate                         # class conformance + skill freshness
$ git commit                            # CI runs `rise skills build --check`
```

Renaming `backup(to=…)` to `backup(destination=…)` fails CI until the skill
is rebuilt. This is D24's "schemas derived, never declared" applied to prose:
**the machine-readable contract cannot drift, and now neither can the
human-readable one.**

#### Agent lifecycle

```
1. discover  SKILL.md loads on trigger match, as always
2. orient    it reads: substrate Process; actions Controllable,
             Backupable; six operations; four documented refusal states
3. read      the interface section is verbatim JSON Schema — the agent does
             not have to re-derive it or trust it
4. act       func pg backup --to /tmp
5. refuse    the reason it gets is the same string the skill already listed
             in "When it will refuse" — recognition, not surprise
```

Step 5 is the property no hand-written skill has: what the agent was *told*
and what the system *says* are the same bytes, by construction.

#### Cost

Generated prose is worse prose. Judgment — *"back up before every
migration"* — cannot be derived from a class; it has to be written
somewhere. The answer is a slotted template (`SKILL.md.in` with
`{{ interface }}` / `{{ refusals }}` / `{{ diagnosis }}` slots the generator
fills), which is scrill-design's hydration-slots idea (D23, `13` B2) arriving
by a different road. Without the slots this alternative produces skills no
agent benefits from loading.

---

## 4. The non-forcing rule

*"A scrill allows all modes of operation as an alternative and non-forcing
interoperability."* Made testable:

| Mode | Who has what | Must hold |
|---|---|---|
| **skill only** | agent, no functualize, no `uv` | `SKILL.md` reads as a useful document. Any command it names is a suggestion, not a prerequisite |
| **job only** | a machine, a CI runner, no agent | delete every `SKILL.md`; `func pg backup` behaves identically. Refusal messages still print — they are for humans too |
| **both** | the intended case | the agent gets the schema *and* the judgment; refusals it was warned about are recognised |

Three acceptance criteria fall out, and they belong in
`12-acceptance-mapping.md`:

- **N1** — Removing `SKILL.md` from a scrill changes no job's behaviour,
  exit code, or output.
- **N2** — A scrill's `SKILL.md` is a conformant Agent Skill under
  `parse_frontmatter` (`_cli/skills.py:110`, the six portable fields) and
  installs with `npx skills add` with functualize absent.
- **N3** — No job's correctness depends on a skill having been loaded. A job
  that only works when an agent read the prose first is a bug.

N3 is the load-bearing one. It is what stops scrill becoming a system where
the prose is secretly required, which is the failure mode every
"documentation as configuration" scheme reaches eventually.

---

## 5. Recommendation: they are not four options, they are one pipeline

A, B, C and D compete only if you read them as formats. Read as lifecycle
stages, they compose:

```
  C  single file      →  A  directory        →  B  wheel
  "I wrote a script"     "it earned a skill"    "the team uses it"

              D  generation, running underneath A and B
              (the class is the source; the skill is built, then checked)
```

- **A is the format.** A directory with `SKILL.md` + `scripts/`. It needs
  nothing upstream, works in 0.2.3 today [probed], and matches what
  functualize's own `functualize-skill` skill already prescribes.
- **D is the generator, for rise modules only.** Where a rise class exists,
  the mechanical half of its skill is derived and CI-checked; the judgment
  half is a slot a human fills. Where there is no class — a plain job file —
  A stands alone, hand-written.
- **B is the distribution,** and the moment it exists, ask 6 stops risekit
  from reimplementing locate/list/materialize privately (`09` §5).
- **C is the no-project case,** and it is already v3's standalone story.

The consequence for the earlier boundary question: **scrill is not a
package.** It is (i) a directory convention, (ii) a generator that lives in
risekit next to `rise skills build`, and (iii) three small functualize
features. `scrills-rise` scenario D's shared kernel is still the right
package graph — it just turns out the kernel is `risekit.core` and scrill
never needed a distribution of its own.

## 6. Upstream asks 6–8

Sequenced after asks 1–5 (`13`); none blocks the build order in `11` §2.

| # | Ask | Kind | Evidence | Rise can route around? |
|---|---|---|---|---|
| 6 | `functualize.skills` entry-point group; `resolve_skills_dir` returns a list of `SkillsLocation`, `builtin skills list/install` iterate | feature | `_cli/skills.py:88` hardcodes the package dir | yes, badly — every package reimplements it, starting with risekit |
| 7 | `job_detail` exposes `declaration` (`tags`, `examples`, `extra_description`, `category`) | fix | probe 13: present on the descriptor, dropped by the renderer | no — the agent surface is functualize's |
| 8 | `_KNOWN_TOOL_KEYS` gains `skill` | feature | `_cli/pep723.py:53` warns on unknown keys | yes — accept the warning, or use a comment |

Ask 7 is the cheapest and the most valuable: four fields already on the
descriptor, one dict literal, and it is what lets an agent walk from a job it
found to the judgment it is missing.

## 7. What is still unprobed

- The MCP surface (carried over from `14` §3) — now doubly relevant, since
  ask 7 changes what an MCP client sees.
- `npx skills add` against a generated `SKILL.md` — N2 asserts conformance
  through `parse_frontmatter`, which is functualize's own reader, not the
  skills CLI's. The two are believed to agree; that is not the same as
  checked.
