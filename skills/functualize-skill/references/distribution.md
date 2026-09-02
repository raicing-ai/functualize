# Where a skill lives, and how it ships

## The five destinations

### 1. Personal, one project — `.claude/skills/<name>/`

Uncommitted (or gitignored). Assume anything you like about the machine; it is
yours. No `compatibility`, no portability concerns. Bare `func` is fine if it
works for you.

### 2. Personal, everywhere — `~/.claude/skills/<name>/`

Loads in every project. Personal skills **override project skills** of the same
name, so a personal `deploy` shadows a repo's `deploy` — surprising for anyone
debugging why a team skill is not running.

Also loads from a `.claude/skills/` in any directory passed with `--add-dir`.

### 3. Team, committed — `.claude/skills/<name>/` in the repo

Everyone who clones gets it. Now portability starts to matter: the skill may
only assume what the repo's own setup guarantees. If the repo has `uv.lock`,
`uv run func` is a safe assumption. If contributors use different toolchains,
resolve the prefix at runtime instead.

Project skills load from `.claude/skills/` in the start directory and every
parent up to the repo root. Skills in *nested* directories below the start
point load lazily — the first time the agent touches a file in that
subdirectory — and appear under a directory-qualified name like
`apps/web:deploy`. Useful in a monorepo where one package ships its own skill.

Note: a project skill's `allowed-tools` grant applies even in an untrusted
directory. Review that field in any repo you did not write.

### 4. Public / cross-repo — a dedicated repo, installed with the skills CLI

Layout, following the convention the ecosystem has settled on:

```
my-skills/
├── README.md
└── skills/
    ├── thing-one/SKILL.md
    └── thing-two/SKILL.md
```

Users install with:

```bash
npx skills add <owner>/<repo>
npx skills add <owner>/<repo> --skill thing-one
```

The CLI materializes each skill once and links it into whichever agent
directories it detects, across a large number of supported agents. Project
installs are recorded in `skills-lock.json`, which is worth committing for
team reproducibility.

Assume **nothing** about the host here. Resolve the invocation prefix at
runtime, and state real requirements in `compatibility`:

```yaml
compatibility: Requires uv and Python 3.11+
```

Two caveats worth knowing: the lock file is thinly documented, and restore-
from-lock has been a requested rather than settled feature. Do not build a
workflow that depends on it without checking the current state.

### 5. Full plugin — a marketplace repo

Choose this only when the deliverable is more than skills: agents, hooks, MCP
servers, LSP config, or bundled executables. For skills alone, option 4 is
less machinery. Plugin skills are namespaced `plugin-name:skill-name`, so they
cannot collide with anything else.

---

## Packaging a marketplace whose scripts are functualize jobs

### The constraint that decides the design

When Claude Code installs a plugin it runs `npm ci --ignore-scripts` or
`bun install --frozen-lockfile` for Node dependencies. **There is no Python
dependency installation step. None.** Nothing will `pip install` functualize
for your users.

So a functualize-powered plugin has exactly one self-contained option: **PEP
723 inline metadata plus `uv`**. Every script declares its own dependencies and
`uv` resolves them on first run. Requiring a preinstalled functualize is the
alternative, and it means the plugin silently fails for anyone who does not
have it.

State the real requirement:

```yaml
compatibility: Requires uv (https://docs.astral.sh/uv/); resolves its own Python dependencies on first run
```

### Repository layout

```
my-plugins/
├── .claude-plugin/
│   └── marketplace.json
└── plugins/
    └── my-plugin/
        ├── .claude-plugin/
        │   └── plugin.json
        └── skills/
            └── my-skill/
                ├── SKILL.md
                └── scripts/
                    └── jobs.py
```

`.claude-plugin/marketplace.json` — `name`, `owner` (with a required `name`),
and `plugins` are the required fields; each entry needs `name` and `source`:

```json
{
  "name": "my-plugins",
  "owner": { "name": "Your Name" },
  "description": "Functualize-powered tooling",
  "plugins": [
    {
      "name": "my-plugin",
      "source": "./plugins/my-plugin",
      "description": "What it does",
      "version": "1.0.0",
      "license": "MIT",
      "keywords": ["functualize"]
    }
  ]
}
```

`source` also accepts `{"source": "github", "repo": "owner/repo", "ref": "v1.0.0"}`,
a git URL, `git-subdir` for a monorepo, `npm`, an `archive` with a `sha256`, or
a `command` that prints a path. Pin with `sha` for exact reproducibility. If
`version` is set, users only receive updates when it changes; omit it and a git
source falls back to the commit SHA.

`plugins/my-plugin/.claude-plugin/plugin.json` — only `name` is required:

```json
{
  "name": "my-plugin",
  "description": "What it does",
  "version": "1.0.0",
  "author": { "name": "Your Name" },
  "license": "MIT"
}
```

The default `skills/` directory is always scanned, and a `skills` manifest
field **adds** to it rather than replacing it — unlike `commands` and `agents`,
which replace their defaults. For a single-skill plugin you can skip `skills/`
entirely and put `SKILL.md` at the plugin root; the frontmatter `name` then
sets the invocation name.

Users install with:

```bash
/plugin marketplace add <owner>/<repo>
/plugin install my-plugin@my-plugins
```

Marketplace names impersonating official ones are blocked, as is a reserved
list including `agent-skills`, `anthropic-plugins`, and
`claude-code-marketplace`. Pick something clearly yours.

### Referencing bundled scripts

Use `${CLAUDE_PLUGIN_ROOT}` for anything shipped with the plugin:

```markdown
Run `uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/my-skill/scripts/jobs.py --help`
```

**`${CLAUDE_PLUGIN_ROOT}` changes on every update** — it includes the version
in its path. Never write anything you want to keep there. `${CLAUDE_PLUGIN_DATA}`
persists across updates and is the right home for a uv cache or generated
files:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uv",
      "args": ["run", "--script", "${CLAUDE_PLUGIN_ROOT}/servers/serve.py"],
      "env": { "UV_CACHE_DIR": "${CLAUDE_PLUGIN_DATA}/uv-cache" }
    }
  }
}
```

### Credentials: the end-to-end flow

A plugin declares `userConfig`, prompted when the plugin is enabled:

```json
{
  "userConfig": {
    "api_token": {
      "type": "string",
      "title": "API token",
      "description": "Token for the upstream service",
      "sensitive": true
    }
  }
}
```

What Claude Code then does with it:

- **`sensitive: true` values go to secure storage** — the macOS Keychain, or
  `~/.claude/.credentials.json` where no keychain is available. Not
  `settings.json`. Keychain storage is capped around 2 KB total, so keep them
  small. Non-sensitive values land in `pluginConfigs[<plugin-id>].options` in
  `settings.json`.
- Values are exported to **hook processes** as `CLAUDE_PLUGIN_OPTION_<KEY>`,
  with `<KEY>` uppercased.
- `${user_config.<key>}` substitutes in MCP and LSP `command` / `args` / `env`,
  in hook and monitor commands, and in skill and agent content.
- **Shell-form commands reject `${user_config.*}`** — substituting a configured
  value into a shell string would let the shell execute its contents, so the
  component fails instead. Use exec form with `args`.

**The names do not line up, and nothing bridges them for you.** Claude Code
produces `CLAUDE_PLUGIN_OPTION_API_TOKEN`; functualize looks for a name derived
from the job and field. Do the rename explicitly in an `mcpServers` `env` map,
which is the one path verified end to end:

```json
{
  "mcpServers": {
    "acme": {
      "command": "uv",
      "args": ["run", "--script", "${CLAUDE_PLUGIN_ROOT}/scripts/jobs.py"],
      "env": { "ACME_SYNC__API_TOKEN": "${user_config.api_token}" }
    }
  }
}
```

The secret moves from secure storage into the child process's environment
without ever entering the conversation.

**Two hazards.**

*Never put `${user_config.<sensitive-key>}` in SKILL.md body text.* Substitution
works in skill content, so the value would be rendered into context and
preserved in the transcript. Reference the variable *name*, never the value.

*Do not assume `CLAUDE_PLUGIN_OPTION_*` reaches a Bash tool invocation.* The
documented export is to hook processes; a skill instructing the agent to run
`uv run --script ...` is not one. If your skill runs scripts through Bash rather
than MCP, have the **user** set the variable (shell profile, `.env`, or
`settings.local.json`), document its exact name in SKILL.md, and fail loudly
with that name when it is missing.

**Confirm the name functualize actually wants** rather than deriving it. Two
conventions exist in the codebase — `SECTION_KEY` and `JOB__FIELD` with a bare
`FIELD` fallback — and only the first is documented:

```bash
func builtin env <job>
```

That prints the resolved variable names with secrets masked. Treat its output as
the authority.

Pair all of this with a `Secret[str]` field so the value is masked in logs,
tracebacks, and emitted output. Never write credentials into a config file the
plugin ships, and never into the shared XDG directory.

### Exposing jobs over MCP instead

If the goal is for the agent to call the jobs as tools rather than run
commands, functualize already has an MCP adapter that turns discovered jobs
into `discover_jobs` / `get_job_schema` / `run_job` tools. A plugin can declare
that server in `mcpServers` and skip bundling scripts entirely. Worth
considering when there are many jobs, or when the agent needs schemas rather
than a command line.

---

## Choosing

Start at the top and stop at the first row that fits:

| If… | Then |
| --- | --- |
| Only you will ever use it | `.claude/skills/` or `~/.claude/skills/` |
| Your team, one repo | commit it to `.claude/skills/` |
| Strangers, skills only | dedicated repo + skills CLI |
| Skills **plus** agents, hooks, or MCP | marketplace |

Do not start at the bottom. A marketplace for a single personal skill is
machinery you will maintain forever for no benefit.
