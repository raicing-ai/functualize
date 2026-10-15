# Safe nested lazy materialization

Two concurrent lazy imports must complete when the first module materializes a second job during its import. The source-file insert, import, and remove operation remains serialized over the process-wide `sys.path` list. Successful and failing imports leave `sys.path` as found.

Acceptance: a deterministic two-thread nested-import regression fails against the previous guard and passes with the correction; the existing warm-cache parallel and import-failure tests pass; cold and synthetic-source behavior remains unchanged.
