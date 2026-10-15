# Contracts

No public API, result type, cache format, or job declaration changes. `LazyJobFunction.materialize()` still returns `(callable, config_class)` and wraps import failures in `JobMaterializationError`. The source-file path region remains guarded by `_IMPORT_LOCK`. A synthetic-source proxy also uses that mutex for its first state publication, although its helper branch does not edit `sys.path`; direct synthetic helper calls remain outside the mutex.
