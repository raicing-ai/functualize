-- Revision 0001: the relational runtime schema.
--
-- Implements contributor/reference/runtime-persistence-data-model.md
-- section 2 (tables, constraints, indexes), section 5 (lease_generation, the
-- fence every scope write predicates on) and section 7 (this ledger), plus
-- runtime_cutover, the legacy-import marker.
--
-- FROZEN once shipped: the migration runner checksums this text, and a
-- database whose ledger records a different checksum refuses to boot. A
-- change is a new revision, never an edit here.
--
-- Every status CHECK list equals its machine's state set in
-- functualize/_types/lifecycle.py; a test holds the two together.
-- Children carry namespace_id so their foreign keys can reference the
-- composite (namespace_id, id) keys and cascade on delete, which is what
-- retention relies on. Append-only tables refuse UPDATE by trigger.

CREATE TABLE schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    checksum   TEXT    NOT NULL,
    applied_at TEXT    NOT NULL
);

CREATE TABLE namespaces (
    id          TEXT PRIMARY KEY,
    project_key TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX namespaces_project_key ON namespaces (project_key);

-- 2.2 Runs and attempts --------------------------------------------------

CREATE TABLE runs (
    namespace_id  TEXT    NOT NULL REFERENCES namespaces (id),
    id            TEXT    NOT NULL,
    scope_id      TEXT,
    parent_run_id TEXT,
    job           TEXT    NOT NULL,
    surface       TEXT,
    status        TEXT    NOT NULL CHECK (status IN (
        'blocked', 'cancelled', 'failure', 'refused', 'running',
        'skipped', 'success', 'timeout', 'unknown')),
    args_hash     TEXT,
    invoke_depth  INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,
    PRIMARY KEY (namespace_id, id)
);
CREATE INDEX runs_recent ON runs (namespace_id, started_at DESC);
CREATE INDEX runs_job    ON runs (job);
CREATE INDEX runs_scope  ON runs (scope_id);
CREATE INDEX runs_parent ON runs (parent_run_id);

CREATE TABLE run_attempts (
    id             TEXT    PRIMARY KEY,
    namespace_id   TEXT    NOT NULL,
    run_id         TEXT    NOT NULL,
    attempt_no     INTEGER NOT NULL CHECK (attempt_no >= 1),
    status         TEXT    NOT NULL CHECK (status IN (
        'cancelled', 'failed', 'running', 'skipped', 'succeeded')),
    started_at     TEXT    NOT NULL,
    ended_at       TEXT,
    failure_code   TEXT,
    failure_detail TEXT,
    FOREIGN KEY (namespace_id, run_id) REFERENCES runs (namespace_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX run_attempts_run_attempt_no ON run_attempts (namespace_id, run_id, attempt_no);

CREATE TABLE run_events (
    namespace_id TEXT    NOT NULL,
    run_id       TEXT    NOT NULL,
    seq          INTEGER NOT NULL,
    type         TEXT    NOT NULL,
    payload      TEXT,
    occurred_at  TEXT    NOT NULL,
    FOREIGN KEY (namespace_id, run_id) REFERENCES runs (namespace_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX run_events_run_seq ON run_events (namespace_id, run_id, seq);
CREATE TRIGGER run_events_append_only BEFORE UPDATE ON run_events
BEGIN
    SELECT RAISE(ABORT, 'run_events is append-only');
END;

-- 2.3 The workflow aggregate ----------------------------------------------

CREATE TABLE workflow_scopes (
    namespace_id     TEXT    NOT NULL REFERENCES namespaces (id),
    id               TEXT    NOT NULL,
    workflow         TEXT    NOT NULL,
    graph_digest     TEXT,
    status           TEXT    NOT NULL CHECK (status IN (
        'blocked', 'cancelled', 'completed', 'failed', 'running')),
    position         TEXT,
    lease_owner      TEXT,
    lease_expires_at TEXT,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    terminal_at      TEXT,
    PRIMARY KEY (namespace_id, id)
);
CREATE INDEX workflow_scopes_status        ON workflow_scopes (status);
CREATE INDEX workflow_scopes_lease_expires ON workflow_scopes (lease_expires_at);

CREATE TABLE workflow_steps (
    namespace_id TEXT    NOT NULL,
    scope_id     TEXT    NOT NULL,
    step_key     TEXT    NOT NULL,
    iteration    INTEGER NOT NULL DEFAULT 0,
    status       TEXT    NOT NULL,
    inputs       TEXT,
    result       TEXT,
    reusable     INTEGER NOT NULL DEFAULT 0 CHECK (reusable IN (0, 1)),
    started_at   TEXT,
    completed_at TEXT,
    FOREIGN KEY (namespace_id, scope_id) REFERENCES workflow_scopes (namespace_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX workflow_steps_scope_step_iteration
    ON workflow_steps (namespace_id, scope_id, step_key, iteration);

CREATE TABLE workflow_branches (
    namespace_id  TEXT NOT NULL,
    scope_id      TEXT NOT NULL,
    decision_key  TEXT NOT NULL,
    chosen_target TEXT NOT NULL,
    chosen_at     TEXT NOT NULL,
    FOREIGN KEY (namespace_id, scope_id) REFERENCES workflow_scopes (namespace_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX workflow_branches_scope_decision
    ON workflow_branches (namespace_id, scope_id, decision_key);
CREATE TRIGGER workflow_branches_immutable BEFORE UPDATE ON workflow_branches
BEGIN
    SELECT RAISE(ABORT, 'workflow_branches is immutable once written');
END;

CREATE TABLE scope_state (
    namespace_id TEXT    NOT NULL,
    scope_id     TEXT    NOT NULL,
    key          TEXT    NOT NULL,
    value        TEXT,
    version      INTEGER NOT NULL DEFAULT 1,
    updated_at   TEXT    NOT NULL,
    FOREIGN KEY (namespace_id, scope_id) REFERENCES workflow_scopes (namespace_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX scope_state_scope_key ON scope_state (namespace_id, scope_id, key);

CREATE TABLE scope_events (
    namespace_id TEXT    NOT NULL,
    scope_id     TEXT    NOT NULL,
    seq          INTEGER NOT NULL,
    type         TEXT    NOT NULL,
    payload      TEXT,
    occurred_at  TEXT    NOT NULL,
    run_id       TEXT,
    FOREIGN KEY (namespace_id, scope_id) REFERENCES workflow_scopes (namespace_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX scope_events_scope_seq ON scope_events (namespace_id, scope_id, seq);
CREATE TRIGGER scope_events_append_only BEFORE UPDATE ON scope_events
BEGIN
    SELECT RAISE(ABORT, 'scope_events is append-only');
END;

-- 2.4 Interactions and effects --------------------------------------------

CREATE TABLE input_requests (
    id           TEXT    PRIMARY KEY,
    namespace_id TEXT    NOT NULL,
    scope_id     TEXT    NOT NULL,
    gate_key     TEXT    NOT NULL,
    generation   INTEGER NOT NULL,
    status       TEXT    NOT NULL CHECK (status IN (
        'accepted', 'cancelled', 'consumed', 'expired', 'open')),
    schema       TEXT,
    prompt       TEXT,
    created_at   TEXT    NOT NULL,
    resolved_at  TEXT,
    FOREIGN KEY (namespace_id, scope_id) REFERENCES workflow_scopes (namespace_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX input_requests_one_open_per_gate
    ON input_requests (namespace_id, scope_id, gate_key, generation) WHERE status = 'open';

CREATE TABLE input_candidates (
    id         TEXT    PRIMARY KEY,
    request_id TEXT    NOT NULL REFERENCES input_requests (id) ON DELETE CASCADE,
    ordinal    INTEGER NOT NULL,
    source     TEXT,
    outcome    TEXT    NOT NULL,
    detail     TEXT,
    errors     TEXT,
    payload    TEXT,
    evidence   TEXT,
    created_at TEXT    NOT NULL
);
CREATE UNIQUE INDEX input_candidates_request_ordinal ON input_candidates (request_id, ordinal);
CREATE TRIGGER input_candidates_append_only BEFORE UPDATE ON input_candidates
BEGIN
    SELECT RAISE(ABORT, 'input_candidates is append-only');
END;

CREATE TABLE outbox (
    id              TEXT    PRIMARY KEY,
    namespace_id    TEXT    NOT NULL REFERENCES namespaces (id),
    aggregate_type  TEXT    NOT NULL,
    aggregate_id    TEXT    NOT NULL,
    topic           TEXT    NOT NULL,
    payload         TEXT,
    idempotency_key TEXT,
    status          TEXT    NOT NULL,
    available_at    TEXT    NOT NULL,
    claimed_at      TEXT,
    published_at    TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT
);
CREATE UNIQUE INDEX outbox_idempotency_key ON outbox (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX outbox_status_available ON outbox (status, available_at);

CREATE TABLE artifact_refs (
    id           TEXT    PRIMARY KEY,
    namespace_id TEXT    NOT NULL REFERENCES namespaces (id),
    run_id       TEXT,
    scope_id     TEXT,
    step_key     TEXT,
    kind         TEXT    NOT NULL,
    uri          TEXT    NOT NULL,
    digest       TEXT,
    size         INTEGER,
    media_type   TEXT,
    created_at   TEXT    NOT NULL,
    FOREIGN KEY (namespace_id, run_id) REFERENCES runs (namespace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (namespace_id, scope_id) REFERENCES workflow_scopes (namespace_id, id) ON DELETE CASCADE
);

-- The legacy-import marker (contracts section 6) ---------------------------

CREATE TABLE runtime_cutover (
    source        TEXT PRIMARY KEY,
    imported_at   TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    backup_path   TEXT
);
