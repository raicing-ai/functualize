# guide/ — the proposed functualize guide

`subjects.md` is the draft of functualize's **Subjects** guide — the Layer-1
deliverable of [`../17-subject-modeling.md`](../17-subject-modeling.md). It is
still a **proposal** — this corpus now lives in functualize's repository under
`.spec/shape-intents/`, but `docs/` is untouched, and the guide lands there only
when the pattern and the upstream asks it rides with ship.

## Landing, when the asks ship

| Edit | Destination |
|---|---|
| copy `subjects.md` | `docs/guides/subjects.md` |
| add one bullet to the Topics list | `docs/guides/index.md`, directly after the "Jobs and Auto-Discovery" bullet: `- [Subjects](subjects.md) — When a job module should be a class: the subject test, the three axes (substrate / actions / target), and how subject classes bind via a plugin` |
| add one nav line | `mkdocs.yml`, Guides section, directly after "Jobs and Auto-Discovery": `- Subjects: guides/subjects.md` |

## Notes

- **Links are written against the destination.** `composition.md`,
  `jobs-discovery.md`, `plugins.md`, `task-runner.md`, `workflows.md` resolve
  only after landing in `docs/guides/`. A link check run over `.spec/` will
  report them as broken until then; that is expected.
- **The example code is smoke-verified** against functualize 0.2.3
  (the repository's own editable install): one class binds as one group
  (`pg.start` / `pg.stop` / `pg.backup`), presence is excluded, the `--to`
  flag runs, and `builtin info schema pg.backup` publishes `['to']`. The
  example's one hard-won caveat: a bare `Path` parameter fails
  `DIValidationError` at boot — take `str` and convert (or put `Path` in a
  config model).
- **The `StaticProvider` import caveat stays** until upstream ask 9
  (`../17` §3 — re-export from `functualize.plugin`) lands; the guide's
  warning admonition should be deleted at the same time.
- **`docs/guides/jobs-discovery.md` is stale** against the source
  (`JOB_NAME` vs the implementation's `JOB_GROUP` — `../17` §5). If that
  docs pass happens before this guide lands, re-check the cross-references
  into it (the Subjects guide already uses `JOB_GROUP`).
