# Contracts

## C1 — one added export

```python
from functualize.plugin import StaticProvider
```

`functualize/plugin/__init__.py` re-exports the class from
`_discovery/providers.py` and adds `"StaticProvider"` to `__all__`, beside the
`Job` it consumes and the `JobProvider` protocol it satisfies.

Additive: no signature changes, nothing removed, nothing renamed. The class's
constructor (`StaticProvider(functions: list[Callable | Job])`) and its two
protocol methods become public surface as they stand.

**`_discovery/providers.py` keeps the definition.** The public module
re-exports rather than moves it, because `_app/boot.py` and the pipeline
construct it internally and the constitution forbids internal layers importing
public folders.

## C2 — the docs stop pointing at a private import

`docs/api/discovery.md` lists `StaticProvider` under "Internal Location" with
an admonition saying modules under `functualize._discovery` are implementation
details. That page is corrected: the class is named as public, at its public
path, with the internal note kept for its genuinely internal siblings.

## C3 — the guide

`docs/guides/subjects.md` is added; `docs/guides/index.md` gains one bullet
after "Jobs and Auto-Discovery"; `mkdocs.yml` gains one nav line in the same
position. Links in the guide resolve relative to `docs/guides/`, which is what
it was drafted against.
