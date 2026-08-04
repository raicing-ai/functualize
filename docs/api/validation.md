# Validation (Internal)

Job configuration validation now lives in the internal `functualize._config/job_config.py` module. End users interact with validation through:

- **`functualize.job.JobConfigView`** — the public resolved configuration view
- **JobConfig Pydantic models** — standard Pydantic `BaseModel` subclasses that are validated automatically

## Public API

```python
from functualize.job import JobConfigView
```

## How Validation Works

When a job function declares a Pydantic `BaseModel` parameter, functualize:

1. Extracts field definitions from the model
2. Resolves values from the config resolution chain (CLI → Env → File → Default)
3. Validates the resolved values against the Pydantic model
4. Raises `ValidationError` if required fields are missing or types don't match

## Internal Location

- `_config/job_config.py` — JobConfigView implementation + validation logic

!!! warning "Internal API"
    The validation implementation is in `functualize._config`. Import from `functualize.job` for the public `JobConfigView` type.

See the [JobConfig with Pydantic](../guides/job-config.md) guide for usage details.
