# Plan — Seams for a third-party host package

## 1. Current state, measured

Commands run against `a2f453d` at authoring time.

| Seam | Command | Result |
|---|---|---|
| S1 | `grep -c "pre_filter" src/functualize/app/config.py` | **0** — `DiscoveryConfig` has nine fields, none a hook |
| S2 | `grep -rn "package_ops\|InstallMode\|Detection" src/functualize/app/ src/functualize/types/ src/functualize/plugin/` | **0** — nothing public |
| S2 | `wc -l src/functualize/_cli/{package_ops,runtime,manifest}.py` | **1,683** lines |
| S3 | `grep -rn "resolve_skills_dir" src/` | **3** call sites + definition + `__all__` + a docstring reference |
| S4 | `job_detail` key count | **12**; `descriptor.declaration` present but dropped |
| S5 | `sed -n 53p src/functualize/_cli/pep723.py` | `_KNOWN_TOOL_KEYS = frozenset({"job"})` |

Probe for S4, run at authoring time:

```
jobs: ['demo.backup']
declaration present: True
  tags: ('scrill:pgops',)
  extra_description: see the pgops skill
job_detail exposes tags? False
```

## 2. The constitutional constraint that shapes S2

> `_cli/` importing internals (any `_`-prefixed package) — reason: `_cli/`
> dogfoods the public API to prove completeness. If `_cli/` can't do something
> via public API, the capability must be added to a public folder first.

`_cli/package_ops.py` and `_cli/runtime.py` are *inside* `_cli`, so they do
not violate this today — but they also cannot be reached by anyone else, and
`app/` may not import `_cli` (the layer table forbids `_app`→`_cli`, and `app/`
is public). So S2 is not a re-export from `_cli`: the code **moves down** to a
public module, and `_cli` imports it from there.

Proposed placement: `functualize/app/packaging.py`. Rationale — it is
application-construction-adjacent (which environment am I in, what would
change it), it is the folder `_cli` is already allowed to import, and it keeps
`types/` free of behaviour.

The move must not drag CLI dependencies down with it. `package_ops.py`'s
`announce` / `plan_or_exit` / `refuse` touch the terminal and stay in `_cli` —
which is also why `contracts.md` §S2 does not promote them.

**Verified at authoring time.** `runtime.py` imports only `os`, `tomllib`,
`dataclasses`, `enum`, `pathlib`, `typing` — stdlib throughout, so all of it
moves. In `package_ops.py`, every `click` reference is at line 723 or later,
inside `refuse` and `plan_or_exit` — exactly the functions `contracts.md`
keeps in `_cli`. The split line holds as drawn; no CLI dependency travels
down with the moved code.

## 3. Approach per seam

**S1.** `_primitives/pre_filter.py` already defines the shape and three
implementations (`ASTModulePreFilter:100`, `DisplayClassPreFilter:126`,
`GroupOptionsPreFilter:163`). Promote the Protocol to `functualize/plugin`,
have `_primitives` implement the public Protocol structurally (it is
`@runtime_checkable`, so no import from `_primitives` upward is needed), and
add the field. `DirectoryScanProvider.__init__` already accepts a `pre_filter`
argument — the wiring is from `DiscoveryConfig` to that existing parameter,
combined with the `require_*`-derived filter rather than replacing it.

**S2.** Move, do not copy. A copy is two detectors that will disagree, which
is the failure this seam exists to prevent. Order: create
`app/packaging.py` with the moved code, repoint `_cli`'s imports, delete the
old definitions, then `lint-imports`.

**S3.** Three call sites migrate to `resolve_skills_locations()`. The
per-source version stamp is the part with real design content: a third-party
skill stamped with functualize's version would break the exact guarantee
`_cli/skills.py:16` exists to provide. Read the distribution and version from
the entry point's own distribution metadata.

Failure isolation matters more than completeness here — `resolve_skills_dir`
is reachable from `func --help`, so a broken entry point must warn and be
skipped.

**S4.** Four keys in one dict literal at `_cli/info.py:137`. Read from
`descriptor.declaration`, guarding `None` for convention-discovered jobs.
Smallest item in either feature and the highest value per line.

**S5.** One frozenset, one dataclass field, one parse line.

## 4. Deferred, with reasons

| Deferred | Why | Revisit when |
|---|---|---|
| The manifest API (`_cli/manifest.py`, 515 lines) | it records what functualize installed *into its own environment*. Letting a host write into that same manifest is a decision about ownership of `install.json`, not an export | a host needs to record installs and `Detection` + command lists prove insufficient |
| Reading `[tool.functualize] skill` | S5 accepts the key; what consumes it depends on the skill-hosting design settling | after S3 ships and a real consumer exists |
| Asserting S4's fields over MCP | needs a live MCP client; `job_detail` is shared so the fields arrive for free, but "arrives for free" is read, not run | the MCP surface gets its first end-to-end test |

## 5. Risks

| Risk | Mitigation |
|---|---|
| S2's move breaks `builtin self *` | those commands are the only consumers; move under test, and run the existing `self doctor` test before and after. Do **not** run `self update` / `self install` during development — they mutate the developer's environment |
| S1's hook lets a caller import arbitrary modules during discovery | the hook *filters*, it never imports; the predicate receives already-read source text. Document that it must be pure and fast — it runs per candidate file |
| S3's entry-point scan slows `func --help` | entry points are already scanned for plugins at boot; skills resolution is lazy (only on `builtin skills *`), so the cost lands where the user asked for it |
| S3's per-source version stamping collides on disk | the destination is `<distribution>-<version>`; two distributions cannot share a name |
| S4 leaks `visibility` or `config_section` unintentionally | the contract names exactly four fields. A test asserts the key set, so a fifth cannot appear silently |

## 6. Files to change

```
src/functualize/plugin/__init__.py            S1 (ModulePreFilter Protocol)
src/functualize/app/config.py                 S1 (DiscoveryConfig.pre_filter)
src/functualize/_app/boot.py                  S1 (wire to DirectoryScanProvider)
src/functualize/app/packaging.py              S2 (new — moved code)
src/functualize/_cli/runtime.py               S2 (repoint / shrink)
src/functualize/_cli/package_ops.py           S2 (repoint / shrink)
src/functualize/_cli/skills.py                S3
src/functualize/_cli/builtins.py              S3 (2 call sites)
src/functualize/_cli/info.py                  S3 (1 call site), S4
src/functualize/_cli/pep723.py                S5
docs/guides/{jobs-discovery,mcp}.md, docs/cli/…  all
tests/…                                       one per seam, plus a fixture
                                              distribution for S3
```

`src/functualize/**` is spec-gated; `tasks.md` with a parseable dependency
graph exists, so these writes are permitted.
