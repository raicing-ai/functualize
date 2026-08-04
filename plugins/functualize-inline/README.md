# functualize-inline

> **Status: Published** — Independently installable from PyPI.

Textual-based inline interactivity provider for the functualize framework. This plugin renders rich terminal widgets (confirmations, selections, text inputs, progress bars) inline within the terminal using [Textual's](https://textual.textualize.io/) inline mode — without taking over the full screen. When Textual is unavailable (non-TTY, CI environments), it gracefully falls back to plain CLI `input()` prompts.

## Installation

```bash
pip install functualize-inline
```

## Quick Start

```python
from functualize_interactivity import PromptIntent, PromptRequest
from functualize_inline import InlinePlugin

plugin = InlinePlugin()

request = PromptRequest(
    intent=PromptIntent.CONFIRM_NEUTRAL,
    question="Deploy to staging?",
    default=True,
)
response = plugin.collect(request)
print(f"User answered: {response.value} (source: {response.source})")
```

## Features

- **Rich inline widgets** — Confirmation dialogs, single/multi-select lists, text inputs, secret inputs, and acknowledgment prompts rendered with Textual styling
- **Automatic CLI fallback** — Detects non-TTY environments and falls back to plain `input()` prompts so jobs run unattended in CI
- **Structured output rendering** — Implements `OutputRenderer` protocol with `render_log`, `render_phase`, and `render_progress` for formatted terminal output with icons and progress bars
- **Timeout support** — Prompts can auto-dismiss after a configurable timeout, returning the default value
- **Entry-point auto-discovery** — Install the package and it registers itself as an interactivity provider via the `functualize.interactivity_providers` entry point

## API Reference

Public classes and functions exported by this plugin:

### `functualize_inline` (top-level)

- `InlinePlugin` — Main plugin class implementing `InputProvider` and `OutputRenderer` protocols. Entry point for prompt collection and terminal output rendering.

### `functualize_inline.apps`

- `InlinePromptApp` — A short-lived Textual `App` (inline mode) that mounts a prompt widget and returns the user's response as a `(value, source)` tuple.

### `functualize_inline.widgets`

- `PromptResult` — Textual `Message` posted by widgets when the user provides a response. Carries `.value` and `.source` attributes.
- `ConfirmDestructiveWidget` — Red-bordered widget requiring the user to type "yes" to confirm dangerous actions.
- `ConfirmNeutralWidget` — Standard Y/n confirmation widget with keyboard shortcuts.
- `SelectWidget` — Single-select `OptionList` widget (max 12 visible items).
- `MultiSelectWidget` — Checkbox-style multi-select widget with toggle and submit.
- `TextInputWidget` — Free-text input with optional placeholder and default value.
- `SecretInputWidget` — Masked password input widget.
- `AcknowledgeWidget` — Press-any-key dismiss widget for informational prompts.

## Development

Run plugin tests:

```bash
uv run pytest plugins/functualize-inline/tests/ -v
```

Run linting and formatting:

```bash
uv run ruff check plugins/functualize-inline/
uv run ruff format plugins/functualize-inline/
```
