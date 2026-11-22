-- migration: foreign-keys-off
-- Rebuild runs to admit a binding refusal. Preserve its children while the
-- parent table is replaced; the runner checks references before restoring FKs.
DROP TRIGGER run_tags_fixed_on_delete;

CREATE TABLE runs_rebuild (
    namespace_id  TEXT    NOT NULL REFERENCES namespaces (id),
    id            TEXT    NOT NULL,
    scope_id      TEXT,
    parent_run_id TEXT,
    job           TEXT    NOT NULL,
    surface       TEXT,
    status        TEXT    NOT NULL CHECK (status IN (
        'blocked', 'cancelled', 'failure', 'invalid', 'refused', 'running',
        'skipped', 'success', 'timeout', 'unknown')),
    args_hash     TEXT,
    invoke_depth  INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,
    PRIMARY KEY (namespace_id, id)
);
INSERT INTO runs_rebuild (
    namespace_id, id, scope_id, parent_run_id, job, surface, status,
    args_hash, invoke_depth, started_at, ended_at
) SELECT
    namespace_id, id, scope_id, parent_run_id, job, surface, status,
    args_hash, invoke_depth, started_at, ended_at
FROM runs;
DROP TABLE runs;
ALTER TABLE runs_rebuild RENAME TO runs;

CREATE INDEX runs_recent ON runs (namespace_id, started_at DESC);
CREATE INDEX runs_job    ON runs (job);
CREATE INDEX runs_scope  ON runs (scope_id);
CREATE INDEX runs_parent ON runs (parent_run_id);

CREATE TRIGGER run_tags_fixed_on_delete BEFORE DELETE ON run_tags
WHEN EXISTS (
    SELECT 1 FROM runs WHERE namespace_id = OLD.namespace_id AND id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'run tags are fixed when the run opens');
END;
