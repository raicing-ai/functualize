# Conversion playbook

How to convert an existing Python script, or a skill's scripts, to functualize. This file
is a **route map, not the manual**. The manual is what the installed tool tells you about
itself, plus the skills it ships. Those are part of the product you are testing, so use
them the way a real user would, and record where they fall short.

---

## 1. Your sources, in order of authority

| # | Source | How to reach it | Authority |
|---|---|---|---|
| 1 | The running tool | `<prefix> func --help`, `<prefix> func builtin info schema`, `<prefix> func <job> --help`, `<prefix> func builtin why <job>` | **Highest.** It describes the version actually installed |
| 2 | The shipped agent skills | `<prefix> func builtin skills list`, then `<prefix> func builtin skills path` to find the directory, then read the `SKILL.md` files and their `references/` | High. They ship with the version and are tested against it, but they are prose and can drift |
| 3 | Public docs | `https://raicing-ai.github.io/functualize/`, or `docs/` in a functualize checkout | Medium. They may lag the installed version |
| 4 | Examples | `examples/` in a functualize checkout (`quickstart/step1…step8`, `standalone/*`) | Medium. They are pytest-collected, so they usually run |
| 5 | This playbook | here | **Lowest.** A starting hypothesis. Verify before you rely on it |

The shipped skills are the ones built for your task, so read them before you write code:

| Skill | Read it for |
|---|---|
| `functualize` | Always, and first. It covers invoking `func` (§0), orienting (§1), and the four things that are wrong by default (§2) |
| `functualize-app` | Choosing the shape: a single file, a scaffolded project or a plugin. Also `references/standalone-scripts.md` |
| `functualize-skill` | Converting a **skill**: where it lives, frontmatter, scripts as jobs, permissions, tests |
| `functualize-cli` | Installing, upgrading or configuring `func` itself |

If `func builtin skills path` fails, or the skills are missing, or they contradict each
other, **that is a finding**. Record it, then fall back to the next source.

> **A known contradiction, as an example of what to look for.** `functualize-skill` §3
> shows a skill script with the shebang `#!/usr/bin/env -S uv run --script` and tells the
> agent to run `uv run --script scripts/jobs.py --help`. `functualize-app`
> `references/standalone-scripts.md` says that shebang "runs the module body, which runs
> nothing" and exits 0. On 0.4.0 the second claim holds: `uv run --script jobs.py --help`
> printed nothing and exited 0. If you are converting a skill, run it both ways and
> record what *your* version does. Do not trust either document.

---

## 2. Choose the shape

Decide before you write anything. The `functualize-app` skill §1 is the authority. In
short:

| The original is… | Convert to | Entry point |
|---|---|---|
| One script, one verb, run by people or agents who should not have to install anything | **Standalone script** with a PEP 723 header and `[tool.functualize] job = "…"` | `./script.py` or `func script.py` |
| One script with several subcommands (argparse subparsers, click group) | A standalone job file with several functions, or a workspace job file | `func <file-or-dir> <job>` |
| Several related scripts in a repo that is not itself Python-first | **Workspace jobs** under `.functualize/jobs/` at the repo root | `func <job>` from anywhere in the repo |
| A tool with users, config, a name and a release | **Scaffolded project** (`func builtin scaffold init`) | `<app-name> <job>` |
| A skill's `scripts/` folder | Standalone job file(s) inside the skill (`functualize-skill` §3) | whatever the SKILL.md tells the agent to run |

Record the shape you picked and **why** in the journal. If the right shape was unclear,
or the docs pointed two ways, that is a finding. So is a shape you needed that is not on
the list.

---

## 3. The mechanical mapping

These mappings are **hypotheses from the shipped skills**. Confirm each one on the
installed version before relying on it. `func <job> --help` and
`func builtin info schema <job>` show what a signature actually became.

| In the original script | In a functualize job | Where it is documented |
|---|---|---|
| `argparse` / `click` options | Typed function parameters with defaults. `--help` is generated from the signature and docstring | `functualize` §2.2 |
| Subcommands | One function per subcommand. Groups come from files and directories | `functualize` `references/discovery.md` |
| `if __name__ == "__main__": main()` | Delete it. `func` dispatches. For a standalone file, `[tool.functualize] job = "…"` names the entry job | `functualize-app` `references/standalone-scripts.md` |
| `print(...)` of results | `out: Stdout` then `out.emit(value)`. **A return value is not printed** | `functualize` §2.3 |
| `print(...)` of progress, `logging` | `log: Log` then `log(...)`, `log.warning(...)` | `functualize` §2.1, `references/capabilities.md` |
| `subprocess.run(...)` | `sh: Shell` | `references/capabilities.md` |
| `input()` / confirmation prompts | `Prompt` | `references/capabilities.md` |
| `os.environ["API_TOKEN"]`, config files, `.env` | Layered config (TOML + env + flags), with secrets marked so they are masked | `functualize` `references/config-and-secrets.md`. Read the whole file; the marker vs wrapper distinction is subtle |
| Calling another script | `Invoke`, or a declared dependency | `references/capabilities.md`, `references/workflows.md` |
| "Are you sure?" / human approval / multi-step procedure | A `@workflow` with a gate | `references/workflows.md`, `func builtin workflow --help` |
| Ad-hoc caching / "skip if already done" | Fingerprints / freshness, `State` | `references/capabilities.md`, `func builtin why` |
| No tests | Call the function directly with the doubles from `functualize.testing` | `functualize` `references/testing.md` |

Rules that keep the conversion honest:

- **Preserve behaviour first, improve second.** The converted job should do what the
  script did, with the same inputs and the same outputs, unless the user asked for a
  change. Check it by running both on the same input and comparing the output. If you
  cannot make the outputs match, that is a finding.
- **Keep the original until the new one is proven.** Delete it, or leave a shim, only
  when the user wants that.
- **Do not reach for a feature because it exists.** If a script has no config, do not add
  config for the sake of it. Try the feature in a scratch file and record what you learn
  (see `AGENT_BRIEF.md` §1).
- **Do not fight the tool silently.** If you want X and functualize makes it awkward,
  record what you wanted, what you tried and what you settled for. The awkwardness is the
  finding, not your workaround.

---

## 4. Verify the conversion as a user would

Do these for every converted job. Each one is also an observation point (see
`observation-guide.md`):

```bash
<prefix> func builtin info                   # is the job discovered at all?
<prefix> func builtin why <job>              # if not, does `why` explain it?
<prefix> func <job> --help                   # are flags, types, defaults, docs right?
<prefix> func builtin info schema <job>      # does the schema match the signature?
<prefix> func <job> <args>                   # does it do what the original did?
<prefix> func --emit-format json <job> …     # is machine output clean, with no log noise on stdout?
<prefix> func <job> … < /dev/null | cat      # non-TTY: no prompts hang, no ANSI garbage
```

Then run the tests you wrote (`uv run pytest …`), and, for a skill, invoke the script
exactly the way the SKILL.md tells an agent to.

---

## 5. Converting a skill: the extra checks

A skill's user is another agent, so check the conversion from that side too:

- **The SKILL.md invocation line actually works**, when copied verbatim from a fresh shell
  in a directory other than the skill's.
- **`--help` replaces the prose flag list.** Is the generated help good enough that the
  SKILL.md can stop documenting flags? If not, say what was missing.
- **First run cost.** Time the first `uv`-resolved run and a warm run. Record both. A slow
  first run is a real cost for agent users.
- **Output is parseable.** An agent calling the script with `--emit-format json` gets
  exactly one JSON document, or clean NDJSON, on stdout.
- **Secrets stay masked** in logs, errors and emitted payloads, if the script handles
  any. Test it with a fake value like `sk-FIELDTEST-0000`, never a real one.
- **Frontmatter stays portable** (`functualize-skill` §2), and the skill still works where
  `func` is not on PATH.
