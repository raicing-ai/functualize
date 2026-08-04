# Hierarchy (Internal)

The child project hierarchy system now lives in the internal `functualize._discovery/hierarchy.py` module.

## Overview

The hierarchy system allows a parent functualize application to compose child projects, aggregating their jobs into a unified CLI. This is useful for monorepos or multi-team organizations where each team maintains independent job directories.

## Public API

Child project composition is configured through the `JobSources` dataclass:

```python
from functualize.app import FunctualizeApp, JobSources

app = FunctualizeApp(
    name="parent-app",
    job_sources=JobSources(
        directories=["jobs"],
        children=["../child-project-a", "../child-project-b"],
    ),
)
```

## Internal Location

- `_discovery/hierarchy.py` — Child project definitions (`ChildProject` dataclass)
- `_discovery/transforms.py` — Composition logic (`NamespaceTransform` for child job prefixing)

!!! warning "Internal API"
    The hierarchy implementation is in `functualize._discovery`. Configure via `JobSources` from `functualize.app`.

See the [Hierarchy & Validation guide](../guides/hierarchy-validation.md) for detailed usage.
