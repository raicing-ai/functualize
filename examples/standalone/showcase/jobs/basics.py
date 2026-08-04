"""SmartBar flow basics: jobs graded by how many required args they have.

Each job exercises a different execution path in the inline TUI:

- ``status``  → green bar immediately (no args), Ctrl+R executes
- ``ping``    → green bar (all optional), Ctrl+R executes with defaults
- ``send``    → grey bar (1 required), Ctrl+R → quick-fill (1 field)
- ``migrate`` → grey bar (3 required), Ctrl+R → quick-fill (3 fields)

(The 5-required full-modal case is ``deploy`` in deploys.py.)
Ctrl+S on any green-bar command opens the shortcut save dialog.

Run: func (from the showcase directory)
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from functualize.job import RunContext

# --- No args (immediate execution) ---


def status(rc: RunContext) -> str:
    """Show system status (no args needed)."""
    rc.log("Checking system status...")
    rc.log("Database: connected")
    rc.log("Cache: warm")
    rc.log("Queue: 3 pending")
    return "all systems go"


# --- Optional args only (immediate execution with defaults) ---


class PingConfig(BaseModel):
    """Ping config — all optional."""

    host: str = Field(default="localhost", description="Host to ping")
    count: int = Field(default=3, ge=1, le=10, description="Ping count")
    timeout: int = Field(default=5, ge=1, le=30, description="Timeout in seconds")


def ping(config: PingConfig, rc: RunContext) -> str:
    """Ping a host (all optional args — executes with defaults)."""
    rc.log(f"Pinging {config.host} x{config.count} (timeout={config.timeout}s)")
    for i in range(config.count):
        rc.log(f"  Reply {i + 1}: 12ms")
    return f"{config.host}: {config.count}/{config.count} packets received"


# --- 1 required arg (quick-fill with 1 field) ---


class SendConfig(BaseModel):
    """Send config — 1 required field."""

    message: str = Field(description="Message to send")
    channel: str = Field(default="#general", description="Target channel")


def send(config: SendConfig, rc: RunContext) -> str:
    """Send a message (1 required arg: message)."""
    rc.log(f"Sending to {config.channel}: {config.message}")
    return f"Sent: {config.message}"


# --- 3 required args (quick-fill with 3 fields) ---


class Direction(StrEnum):
    """Migration direction."""

    up = "up"
    down = "down"


class MigrateConfig(BaseModel):
    """Migrate config — 3 required fields."""

    database: str = Field(description="Database connection URL")
    target: str = Field(description="Target migration version")
    direction: Direction = Field(description="Migration direction")
    dry_run: bool = Field(default=False, description="Preview without applying")


def migrate(config: MigrateConfig, rc: RunContext) -> str:
    """Run database migration (3 required args → quick-fill)."""
    mode = "DRY RUN" if config.dry_run else "APPLY"
    rc.log(f"[{mode}] Migrating {config.database}")
    rc.log(f"  Direction: {config.direction}, Target: {config.target}")
    return f"Migrated to {config.target} ({config.direction})"
