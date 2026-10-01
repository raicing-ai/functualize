# Rise / RiseKit foundation — research record

Findings and verification evidence for the set. Never a gate; the record of
what was checked, when, and with what result. Base for every command:
`origin/master` at `ef1939d`, run 2026-10-01 from the worktree unless a
command says otherwise.

## Provenance

`spec.md` and `contracts.md` were written by a design run that hit its
provider session ceiling and died with both files uncommitted. A second run
(this one) judged both files against the tracker premise and
`.spec/CONSTITUTION.md`, corrected two defects (§ *Corrections*), and wrote
`plan.md`, `tasks.md` and this record. The two inherited files were
otherwise kept: every seam claim, count and negative in them was re-verified
(§ *Verification*) rather than trusted.

## Verification (Retrieval Before Assertion evidence)

| Claim in the set | Command | Result |
|---|---|---|
| no `risekit` anywhere on master | `git grep -i -c risekit origin/master \| wc -l` | 0 |
| no `\bRise\b` anywhere on master | `git grep -E -l '\bRise\b' origin/master \| wc -l` | 0 |
| "capability" already means a DI-injectable (592 uses) | `rg -c -i '\bcapabilit' src/functualize` summed | 592 |
| the ext seam exists | `rg -n 'functualize_ext' src/functualize` | hits in `_discovery/providers.py`, `_app/boot.py`, `_types/errors.py` |
| metadata lands at `metadata["plugins"][ns]` | read `_discovery/providers.py:298-315` (`extract_ext_metadata`) | as claimed |
| namespace ownership + orphan warning | read `_app/boot.py:2102-2148` (`validate_plugin_ext_metadata`), `_types/errors.py:123` | as claimed: warn default, raise under `plugins.strict` |
| plugin loading group and protocol | serena overview + read `_plugins/loader.py:193`, `_plugins/metadata.py` | `PluginLoader(group="functualize.plugins")`; `PluginMetadata` = name/version/description + register |
| a precedent plugin registers exactly this way | `rg -n 'functualize.plugins' plugins/domains/functualize-decision-jev/pyproject.toml` | `jev = "functualize_decision_jev:JevPlugin"` |
| jobs publish via entry points | read `_app/boot.py:214-221` (`EntryPointProvider`), `tests/discovery/test_entry_point_jobs.py` exists | as claimed |
| `functualize.rise_contracts` → UNKNOWN | read `_primitives/plugin_kinds.py:56` (`classify_group`) | as claimed; `functualize.plugins`→ADAPTER, `functualize.domains`→DOMAIN (reporting-only, no loadable instance), `*_providers`→IMPLEMENTATION |
| credential names already in use | `rg -n 'CLOUDFLARE_(ACCOUNT_ID\|API_TOKEN)' tests/substrate_probe/d1.py` | lines 74-76, 183-185; conftest skip convention |
| grouped plugin layout exists | `ls plugins/` | `adapters credentials domains substrates` |
| workspace covers the new dirs | `pyproject.toml` `[tool.uv.workspace] members = ["plugins/*/*"]` | glob already matches; `[tool.uv.sources]` lists every workspace plugin, so the root file changes |
| ADR-031 is the next free number | `ls contributor/adr/` | highest is `030-decisions-are-candidates-not-authority.md` — **the dispatch's "adr is at 016" was stale**; the inherited draft's 031 is correct |
| B1 achievable (nothing new needed in core) | all of the above | every seam the set needs ships on master |
| exit-status/NDJSON mechanics | S6/S11, C6/C7 | design, not premise — asserted as behaviour to build |

Prose pass: `zg` (zvec-grep 0.2.2, `/usr/local/bin/zg`) over the worktree
index (100 %, 853/853 files) for the seam and orphan-warning prose; graphify
over the worktree's `graphify-out/graph.json` for the region's dependency
direction; serena over `_plugins/loader.py` for the symbol surface. Codemaps
read in full: `contributor/architecture/codemaps/` (all five).

## Corrections to the inherited draft

1. **spec.md §7 P-2 cited ADR-016 as "puts providers in plugins".** ADR-016
   is *Activating the Remote Config Layer, via an Encrypted Local Vault* —
   unrelated. Replaced with the supports that are actually in the repository:
   the constitution's completed invariant (delivery adapters extracted to
   monorepo plugin packages; core ships only `CliAdapter` and `TuiAdapter`)
   and the network-provider slice's own plugin-scoped criterion. P-2's
   conclusion is unchanged; only its citation was wrong.
2. **contracts.md C4 referenced a "D4 review check" that nothing defines**
   (spec.md's decisions are D-1…D-3). Rewritten to point at the review check
   carried under D-2 in `plan.md` § *Decisions for the member*, where that
   check is now explicitly item 1.

No other defect found: the ADR-031 number, the seam mechanics, the entry
point patterns, the classify-group behaviour, the substrate-probe credential
names and both vocabulary negatives all verified as written above.

## Premise changes against the tracker (P-1…P-3, mirroring spec.md §7)

- **P-1** — Rise is not a delivery-intent pipeline. Needs member
  confirmation: **D-1**.
- **P-2** — "the Cloudflare Worker + D1 capability" resolves to two Rise /
  RiseKit contracts plus generic Functualize plugins for run persistence and
  Worker execution. Repository law wins; citation corrected as above.
- **P-3** — the forcing case is diagnosed and provisioned, not deployed; the
  tracker's dependency criterion is met by stage-5 ordering.

None of the three reopens whether Rise and RiseKit are required.

## Limitations of this pass

- The tracker (Jira) and the Confluence shape-intent space were **not read
  live** by the finishing run: no signed-in Atlassian browser session was
  available on the host at run time, and re-authentication is a member
  action. The premise was judged against the issue's record of the tracker
  premise (body, dispatch constraints, and the inherited §7, which the
  first run wrote minutes after its own live read). The shape-intent
  decision numbers (11, 13, 14, 15) are quoted from that inherited record
  and are not independently falsifiable from this repository —
  `.spec/STATUS.md` § *Shape Intents* confirms the intents live on
  Confluence, not in-repo.
- Sizes in plan.md § *Files to change* are estimates for new trees; every
  measured count in the set is in § *Verification* above.
