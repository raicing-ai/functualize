# App Module

::: functualize.app
    options:
      show_root_heading: true
      members_order: source

---

## Overview

The `functualize.app` module is the primary entry point for constructing and configuring a Functualize application.

**Module location:** `src/functualize/app/`

### Public API

```python
from functualize.app import (
    FunctualizeApp,
    JobSources,
    ConfigSources,
    PluginSources,
    ExecutionConfig,
    classic,
    twelve_factor,
    env_only,
    remote_first,
)
```

See the [Architecture Guide](../guides/architecture.md) for how this module relates to other public packages.
