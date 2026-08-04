# Guide: TUI Development

Developing TUI panels and widgets for the inline Textual experience.

> **Start here for architecture and testing rules**:
> [`steering_textual_tui.md`](steering_textual_tui.md) — key-binding
> pitfalls (terminal key aliasing), worker rules, modality enforcement, the
> testing playbook, and a compliance audit of the current code. Its claims
> are backed by executable proofs in `tests/tui_audit/`.

## Height Requirements for PanelHost Children

The `PanelHost` widget uses a constrained content area with `max-height` and `overflow-y: auto` (values below may drift — the source of truth is `src/functualize/_cli/tui/panel_host.py` `DEFAULT_CSS`):

```css
PanelHost .panel-host-content {
    height: auto;
    min-height: 1;
    max-height: 16;
    overflow-y: auto;
}
```

**HARD RULE: Every widget mounted inside PanelHost MUST declare `min-height` in its `DEFAULT_CSS`.**

Without `min-height`, the parent container's `height: auto` collapses to zero when the overflow container shrinks. The widget renders invisible even though its data is populated and lifecycle events fire correctly.

### Why This Happens

`RichLog` is exempt from this rule because it manages its own `virtual_size` internally — it expands to fit written content without relying on parent height CSS.

`DataTable` inside a custom `Widget` wrapper defaults to `height: auto`, which resolves to 0 when the parent chain uses `overflow-y: auto` + `max-height`. Custom widget wrappers containing `DataTable` must declare both widget and table heights.

### Pattern: Panel Widget with DataTable

```python
class MyPanel(Widget):
    """Custom panel wrapping a DataTable."""

    DEFAULT_CSS = """
    MyPanel {
        height: auto;
        min-height: 3;
        max-height: 10;
    }
    MyPanel DataTable {
        height: auto;
        min-height: 2;
        max-height: 10;
    }
    """

    def compose(self) -> ComposeResult:
        yield DataTable()
```

Reference: `contributor/guides/tui-panels.md` is the enforcement steering document for TUI panel constraints (enforcement for AI agents, this guide is for human developers).

### Height Strategy Reference Table

| Panel | Strategy | Status |
|-------|----------|--------|
| `SettingsPanel` | `DEFAULT_CSS` with `min-height: 4` | ✅ Works |
| `JobBrowserPanel` | Widget `min-height: 3` + DataTable `min-height: 2` | ✅ Works |
| `ConfigTablePanel` | Widget `min-height: 3` + DataTable `min-height: 2` | ✅ Works |
| RichLog-based panels | RichLog manages own height, no explicit min-height needed | ✅ Works |

## Deferred Population Pattern

Panel data is often set BEFORE the panel is mounted. When a panel is constructed in `_build_general_panels()` or `_build_command_panels()`, the call to `set_jobs()`/`set_fields()` happens before `PanelHost` mounts the widget.

The inner `DataTable` (or other container) doesn't exist until `compose()` runs after mounting. This creates a timing gap:

**Timeline:**
1. Panel constructor runs → `set_jobs()` called (table is `None`)
2. Panel mounted → `compose()` runs, table created
3. Panel mounted → `on_mount()` runs

**Solution: Use the `_populated` flag pattern:**

```python
class MyPanel(Widget):
    """Panel with deferred population support."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._table: DataTable | None = None
        self._data: list[JobDescriptor] = []
        self._populated: bool = False

    def compose(self) -> ComposeResult:
        """Mount the inner DataTable."""
        self._table = DataTable(cursor_type="row")
        self._table.add_columns("Column 1", "Column 2")
        self._populated = False  # Reset the flag when table is created
        yield self._table

    def on_mount(self) -> None:
        """Populate the table after mount if data was set pre-mount."""
        self._populate_table()

    def set_jobs(self, jobs: list[JobDescriptor]) -> None:
        """Set data — may be called before or after mount."""
        self._data = list(jobs)
        self._populated = False
        self._populate_table()  # No-op if table is None (pre-mount)

    def _populate_table(self) -> None:
        """Actually add rows to the DataTable if it's ready and not yet populated."""
        if self._populated or not self._data or self._table is None:
            return
        self._table.clear()
        for item in self._data:
            self._table.add_row(item.name, item.description)
        self._populated = True
```

### Pattern Breakdown

**Set-before-mount** — `set_jobs()` called before `compose()` runs:
- `_data` is stored, `_populate_table()` returns early because `_table` is `None`
- Later, `on_mount()` runs → `_populate_table()` succeeds because table now exists

**Set-after-mount** — `set_jobs()` called after `on_mount()` runs:
- `_table` already exists → `_populate_table()` populates immediately

**Re-mount** (ring switch) — old ring hidden, new ring shown:
- `on_mount()` runs again → `_populate_table()` repopulates because `_populated` was reset in `compose()`

### Real-World Example

See `JobBrowserPanel` in `src/functualize/_cli/tui/panels/job_browser.py`:

```python
def set_jobs(self, jobs: list[JobDescriptor]) -> None:
    """Populate the table with job descriptors."""
    self._jobs = list(jobs)
    self._filtered_jobs = list(jobs)
    self._populated = False
    self._populate_table()

def compose(self) -> ComposeResult:
    """Mount the inner DataTable."""
    table: DataTable[str] = DataTable(cursor_type="row")
    table.add_columns("Job Name", "Source", "Description")
    self._table = table
    self._populated = False
    yield table

def on_mount(self) -> None:
    """Populate the table after mount if set_jobs was called pre-mount."""
    self._populate_table()

def _populate_table(self) -> None:
    """Actually add rows if ready and not yet populated."""
    if self._populated or not self._filtered_jobs or self._table is None:
        return
    self._table.clear()
    for job in self._filtered_jobs:
        self._table.add_row(job.name, self._derive_source_label(job), self._derive_description(job))
    self._populated = True
```

## Architecture Links

- See [`steering_textual_tui.md`](steering_textual_tui.md) for architecture-wide rules (keys, workers, modality, testing) and the current compliance audit
- See `tests/tui_audit/` for executable proofs of the steering claims (`uv run pytest tests/tui_audit/ -v`)
- See `contributor/architecture/overview.md` for the overall three-layer model (Discovery/Loading/Execution)
- See `src/functualize/_cli/tui/panel_host.py` for `PanelHost` implementation and lifecycle
- See `contributor/guides/tui-panels.md` for AI-agent-facing enforcement rules (mandatory reference for TUI feature work)
- See `.claude/skills/observe-tui/SKILL.md` to observe/drive the live TUI in a PTY while debugging or manually verifying a change (agent-facing; never for automated tests)
