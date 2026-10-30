-- Revision 0005 — run tags: one row per key per run.
--
-- Additive only: no existing table or column changes, so revision 4 stays a
-- valid rollback target. A run's tags are written with the run, in the same
-- transaction, and are fixed from then on. The triggers refuse every later
-- change as a programming error: an UPDATE; a DELETE while the run still
-- exists (retention's cascade, which runs after the run is gone, passes); and
-- an INSERT once the run's first attempt exists — `start_attempt` stages the
-- tags before attempt 1, so only the opening transition can write them.

CREATE TABLE run_tags (
    namespace_id TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    key          TEXT NOT NULL,
    value        TEXT NOT NULL,
    PRIMARY KEY (namespace_id, run_id, key),
    FOREIGN KEY (namespace_id, run_id) REFERENCES runs (namespace_id, id)
        ON DELETE CASCADE
);
CREATE INDEX run_tags_lookup ON run_tags (namespace_id, key, value);

CREATE TRIGGER run_tags_fixed_on_update BEFORE UPDATE ON run_tags
BEGIN
    SELECT RAISE(ABORT, 'run tags are fixed when the run opens');
END;

CREATE TRIGGER run_tags_fixed_on_delete BEFORE DELETE ON run_tags
WHEN EXISTS (
    SELECT 1 FROM runs WHERE namespace_id = OLD.namespace_id AND id = OLD.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'run tags are fixed when the run opens');
END;

CREATE TRIGGER run_tags_fixed_on_insert BEFORE INSERT ON run_tags
WHEN EXISTS (
    SELECT 1 FROM run_attempts
    WHERE namespace_id = NEW.namespace_id AND run_id = NEW.run_id
)
BEGIN
    SELECT RAISE(ABORT, 'run tags are fixed when the run opens');
END;
