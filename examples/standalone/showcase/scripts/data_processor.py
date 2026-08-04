#!/usr/bin/env python3
"""Standalone jobs with inline dependency usage.

Run with:
    func scripts/data_processor.py process --input-path ./sample.csv --format json
    func scripts/data_processor.py summarize --input-path ./sample.csv

These jobs use Domain SDK packages directly without a full project setup.
Dependencies: pip install functualize functualize-state functualize-tasks

Note: no `from __future__ import annotations` here — the CLI's config-class
expansion needs the real annotation objects; string annotations would hide
that a parameter is a BaseModel.
"""

from enum import StrEnum

from functualize_state import InMemoryState, StateNamespace
from functualize_tasks import MockTasks, TaskLink, TaskStatus
from pydantic import BaseModel, Field

from functualize.job.context import RunContext
from functualize.job.decorators import job

# ---------------------------------------------------------------------------
# Shared state (inline dependency — no project config needed)
# ---------------------------------------------------------------------------

_state = InMemoryState()
_tasks = MockTasks()


# ---------------------------------------------------------------------------
# Job 1: Process data
# ---------------------------------------------------------------------------


class OutputFormat(StrEnum):
    """Supported output formats."""

    json = "json"
    csv = "csv"
    parquet = "parquet"


class ProcessConfig(BaseModel):
    """Configuration for the data processing job."""

    input_path: str = Field(description="Path to the input data file")
    format: OutputFormat = Field(default=OutputFormat.json, description="Output format")
    batch_size: int = Field(
        default=100, ge=1, le=10000, description="Processing batch size"
    )


@job(
    extra_description="Process a data file and output in the specified format",
    tags=["data", "etl"],
    visibility="external",
)
def process(config: ProcessConfig, rc: RunContext) -> dict:
    """Process a data file with configurable output format and batch size."""
    rc.log(f"Processing {config.input_path} → {config.format.value}")

    # Use inline state to track processing progress
    ns = StateNamespace(_state, prefix="process:")
    ns.set("last_input", config.input_path)
    ns.set("last_format", config.format.value)
    ns.set("runs", (ns.get("runs") or 0) + 1)

    # Track as a task
    task_id = _tasks.add(
        f"Process {config.input_path}",
        linked_to=TaskLink(kind="job", target="process"),
    )
    _tasks.update(task_id, status=TaskStatus.IN_PROGRESS)

    # Simulate processing
    records_processed = config.batch_size * 3  # Simulated
    result = {
        "input": config.input_path,
        "output_format": config.format.value,
        "records_processed": records_processed,
        "batch_size": config.batch_size,
    }

    _tasks.update(task_id, status=TaskStatus.DONE)
    rc.log(f"Processed {records_processed} records")
    return result


# ---------------------------------------------------------------------------
# Job 2: Summarize (uses state from process)
# ---------------------------------------------------------------------------


class SummarizeConfig(BaseModel):
    """Configuration for the summarize job."""

    input_path: str = Field(description="Path to summarize")
    top_n: int = Field(default=5, ge=1, le=50, description="Top N results to show")


@job(
    extra_description="Summarize previously processed data",
    tags=["data", "reporting"],
    visibility="external",
)
def summarize(config: SummarizeConfig, rc: RunContext) -> dict:
    """Summarize processed data using inline state tracking."""
    rc.log(f"Summarizing {config.input_path} (top {config.top_n})")

    # Read state from previous runs
    ns = StateNamespace(_state, prefix="process:")
    total_runs = ns.get("runs") or 0

    summary = {
        "input": config.input_path,
        "top_n": config.top_n,
        "previous_runs": total_runs,
        "last_format": ns.get("last_format", "unknown"),
    }

    rc.log(f"Found {total_runs} previous processing run(s)")
    return summary
