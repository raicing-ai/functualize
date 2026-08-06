# functualize-inline Examples

Inline Textual widgets for prompts, selections, and progress — rendered under your shell prompt during job runs.

| Directory | Demonstrates |
|-----------|--------------|
| [`prompted_deploy/`](prompted_deploy/) | A job that pauses for a confirmation and a selection, rendered as inline terminal widgets |

## Manual verification (interactive widgets aren't headless-testable)

```bash
cd plugins/functualize-inline/examples/prompted_deploy
func deploy.py run
```

Expected behavior:

1. A destructive-styled confirmation widget appears inline ("Deploy to production?") — y / n.
2. On confirm, a selection list of regions appears — pick with arrows + Enter.
3. The job continues, logging the chosen region; the widgets collapse back into the scrollback.

In a headless run (CI, pipe), the same prompts resolve from their defaults instead of blocking. To drive that path in a test, substitute `AutoPrompt` from `functualize.testing`.
