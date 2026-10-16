# Contracts — did-you-mean-spaced-invocation

## User-visible output (the only external surface that changes)

`func <unknown>` on stderr: for each hit that names a job, the line is

```
  func <segment> <segment> … <leaf>
```

The segments are the job's group, split on `.`. The leaf is the job's name with
`<group>.` removed from the front. A job with no group prints `  func <name>`
unchanged. Group and plugin-command hits print `  func <hit>` unchanged.

All other output is byte-identical: the headline, the explanation, the blank
lines, and `Run 'func' to see all available commands.`

## Internal signatures (new or made public)

```python
# functualize/_types/naming.py — renamed from `_job_segments`, added to __all__
def job_segments(group: str | None, name: str) -> list[str]:
    """Trie segments for a job row: group segments + leaf (group prefix stripped)."""
    # unchanged body; raises ValueError on an empty segment, as today

# functualize/app/commands.py — new object-taking wrapper, added to __all__
def job_invocation(job: Any) -> str:
    """A job's command path as a person types it: segments joined by one space."""
    return " ".join(job_segments(getattr(job, "group", None), str(job.name)))
```

`job_segments` is the derivation `GroupTrie` already uses to place a job
(`_types/naming.py:385`). Printing the same segments that dispatch walks is
what makes B5 (a printed line runs) hold by construction.

## Unchanged

`suggest_similar_commands`, the candidate set, `job_trie_path`, `job_path`,
`normalize_name`, the click adapter, and the TUI.
