"""Surface Showcase — every rendering surface in one project.

Demonstrates the surface-architecture capabilities end to end:

  greet    — a normal job (renders in the TUI panel / plain stdout).
  sync     — a `live: Live` job (a live-updating table in a rich stdout zone).
             Also exercises **scrollback output** (rc.log per file + rc.emit
             structured events) alongside the live zone.
  fetch    — scrollback-only job: demonstrates every way to post text into the
             StdoutSurface scrollback region (rc.log, log(), rc.emit).
  edit     — a `tty: TTY` job (owns the terminal; runs a full-screen Textual app).
  report   — an ADAPTIVE job: `tty: TTY | None` + `live: Live`. One unmodified job
             renders as a full-screen app when it can own the terminal, and as a
             live table otherwise — resolved from the signature.

See README.md for exactly what to run and what to look for.

Requires: pip install functualize[cli]   (rich + textual)

Note: this module intentionally does NOT `from __future__ import annotations`.
Pydantic config-class detection needs the real annotation object (a string
annotation hides that a parameter is a BaseModel), and the TTY/Live markers
resolve fine either way.
"""

import time

from pydantic import BaseModel, Field

from functualize.job import TTY, Live, Log, RunContext

# ─────────────────────────────────────────────────────────────────────────────
# 1. A normal job — no surface capabilities. Renders wherever it is run.
# ─────────────────────────────────────────────────────────────────────────────


class GreetConfig(BaseModel):
    name: str = Field(default="world", description="Who to greet")


def greet(config: GreetConfig, rc: RunContext) -> str:
    """A plain job: logs a line. Panel in the TUI, plain text on direct run."""
    rc.log(f"Hello, {config.name}!")
    return f"greeted {config.name}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. A live: Live job — a live-updating construct in the rich stdout zone.
# ─────────────────────────────────────────────────────────────────────────────


class SyncConfig(BaseModel):
    files: int = Field(default=8, ge=1, le=50, description="How many files to sync")


class _SyncTable:
    """A LiveConstruct: owns state + a Rich renderable (__rich__).

    The surface owns the cursor and repaint — this just returns a table. The
    raw fallback is Rich's own degradation (plain table off a TTY).
    """

    def __init__(self, total: int) -> None:
        self.total = total
        self.done = 0
        self.current = ""

    def __rich__(self):  # noqa: ANN204 - Rich renderable
        from rich.table import Table

        table = Table(title=f"Syncing ({self.done}/{self.total})")
        table.add_column("done")
        table.add_column("current file")
        bar = "█" * self.done + "░" * (self.total - self.done)
        table.add_row(bar, self.current or "…")
        return table


def sync(config: SyncConfig, rc: RunContext, log: Log, live: Live) -> str:
    """Sync files with a live-updating table AND per-file scrollback output.

    This demonstrates the two **parallel output channels** of StdoutSurface:

    1. **Live zone** (bottom of terminal) — the progress table redraws in place.
    2. **Scrollback** (above the live zone) — log lines and structured events
       scroll upward, preserved in terminal history (scrollback buffer).

    Ways to post to scrollback from within a job:
      • ``log("msg")`` or ``rc.log("msg")`` — standard logging, appears as a
        plain text line in scrollback (routed via Python logging → StreamHandler).
      • ``rc.emit("event.name", resource="ctx", key=val)`` — emits a structured
        event; StdoutSurface renders a dim one-liner in scrollback:
        ``⚡ event.name (ctx)``

    Direct run: `func sync --files 12` → live table + per-file log lines above.
    """
    table = _SyncTable(config.files)
    handle = live.add(table)

    log.info(f"Starting sync of {config.files} files...")

    for i in range(config.files):
        filename = f"asset_{i:02d}.bin"
        table.done = i + 1
        table.current = filename
        handle.update()

        # Post to scrollback via log (appears above the live zone)
        log(f"  ✓ synced {filename} ({(i + 1) * 128} KB)")

        # Post a structured event — StdoutSurface renders it as a dim line
        # in scrollback: "⚡ file.synced (asset_XX.bin)"
        rc.emit("file.synced", resource=filename, index=i, size_kb=(i + 1) * 128)

        time.sleep(0.3)

    log.info(f"Sync complete: {config.files} files transferred")
    return f"synced {config.files}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. A scrollback-only job — exercises every output channel to scrollback.
# ─────────────────────────────────────────────────────────────────────────────


class FetchConfig(BaseModel):
    endpoints: int = Field(
        default=5, ge=1, le=20, description="Number of endpoints to fetch"
    )
    delay: float = Field(
        default=0.4, ge=0.0, le=5.0, description="Seconds between fetches"
    )


def fetch(config: FetchConfig, rc: RunContext, log: Log) -> str:
    """Fetch dummy endpoints — demonstrates scrollback output alternatives.

    This job has **no** `live: Live` parameter, so there's no live zone at all.
    All output goes to scrollback only. It showcases the three ways a job can
    post lines into the StdoutSurface scrollback region:

    1. **log("msg")** — the injected ``Log`` capability.  Emits through the
       ``functualize.job.<name>`` Python logger → a StreamHandler prints it to
       stdout. This is the standard, recommended way to log from jobs.

    2. **rc.log("msg")** — the RunContext's log method. Functionally the same
       as ``log()`` (both route to the same Python logger), but available when
       a job already holds ``rc`` and doesn't want a separate ``log`` param.

    3. **rc.emit("event", resource=..., **payload)** — emits a *structured event*.
       StdoutSurface's ``handle_event`` renders it as a dim event line:
       ``⚡ event.name (resource)``
       This is meant for machine-readable telemetry that also has a human trace.
       Other surfaces (TUI panel, MCP) may render it differently or aggregate it.

    Run: `func fetch --endpoints 8`
    """
    log.info("─── Fetch job: scrollback output demo ───")
    log.info(f"Fetching {config.endpoints} endpoints...\n")

    for i in range(config.endpoints):
        endpoint = f"/api/resource/{i}"
        status = 200 if i % 4 != 3 else 503

        # Method 1: log() capability — clean per-line output
        if status == 200:
            log(f"  ✓ GET {endpoint} → {status} OK  ({(i + 1) * 42}ms)")
        else:
            log(f"  ✗ GET {endpoint} → {status} Service Unavailable", level="warning")

        # Method 2: rc.log() — same effect, different call site
        rc.log(f"    ↳ response body: {{'id': {i}, 'status': 'ok'}}", level="debug")

        # Method 3: rc.emit() — structured event for telemetry / surface rendering
        rc.emit(
            "http.response",
            resource=endpoint,
            status=status,
            latency_ms=(i + 1) * 42,
        )

        time.sleep(config.delay)

    log.info(f"\n─── Done: {config.endpoints} endpoints fetched ───")
    return f"fetched {config.endpoints}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. A tty: TTY job — owns the terminal, runs a full-screen Textual app.
# ─────────────────────────────────────────────────────────────────────────────


def edit(rc: RunContext, tty: TTY) -> str:
    """Open a full-screen editor (a job-owned Textual app).

    From the TUI: selecting `edit` hands the terminal off (the shell steps
    aside), the app owns the screen, and the shell relaunches when you quit
    (Ctrl+Q).
    Direct run `func edit` runs it immediately. Piped/CI: refused with a clear
    message (a job that owns the terminal can't run without one).
    """
    from functualize.ui import TextualApp  # lazy: only needed at run time

    class _EditorApp(TextualApp[None]):
        # Ctrl+Q, not plain "q": the TextArea has focus and consumes
        # printable keys, so a bare "q" would just type the letter.
        BINDINGS = [("ctrl+q", "quit", "Quit")]

        def compose(self):  # noqa: ANN201
            from textual.widgets import Footer, Header, TextArea

            yield Header()
            yield TextArea("A job-owned full-screen app.\n\nPress Ctrl+Q to quit.")
            yield Footer()

    tty.run(_EditorApp())
    return "edit session ended"


# ─────────────────────────────────────────────────────────────────────────────
# 5. An ADAPTIVE job — one job, many surfaces, resolved from the signature.
#    `tty: TTY | None` = prefer exclusive, degrade; `live: Live` = always there.
# ─────────────────────────────────────────────────────────────────────────────


class ReportConfig(BaseModel):
    rows: int = Field(default=5, ge=1, le=20, description="Rows to report")


def report(
    config: ReportConfig,
    rc: RunContext,
    live: Live,
    tty: TTY | None = None,
) -> str:
    """Render a report as a full-screen app when possible, else a live table.

    The SAME job body adapts: if it was granted terminal ownership (`tty` is
    not None) it runs a full-screen app; otherwise it renders a live table via
    `live`. Nothing about the job changes between surfaces.
    """
    if tty is not None:
        from functualize.ui import TextualApp

        class _ReportApp(TextualApp[None]):
            BINDINGS = [("q", "quit", "Quit")]

            def compose(self):  # noqa: ANN201
                from textual.widgets import DataTable, Footer, Header

                yield Header()
                table: DataTable[str] = DataTable()
                table.add_columns("row", "value")
                for i in range(config.rows):
                    table.add_row(str(i), f"value-{i}")
                yield table
                yield Footer()

        tty.run(_ReportApp())
        return "report (exclusive)"

    table = _SyncTable(config.rows)
    handle = live.add(table)
    for i in range(config.rows):
        table.done = i + 1
        table.current = f"row {i}"
        handle.update()
        time.sleep(0.2)
    rc.log(f"Reported {config.rows} rows")
    return "report (live)"
