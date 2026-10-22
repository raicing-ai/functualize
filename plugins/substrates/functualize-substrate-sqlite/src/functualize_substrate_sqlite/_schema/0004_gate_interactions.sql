-- Revision 0003 — gate interaction provenance, decisions, evidence, outbox claims.
--
-- Additive only: every existing row stays, every new column is NULL on it and
-- reads back as the defaulted field. The shapes are the gate-interactions
-- feature's contracts §5; the JSON boundary is the data model's §3 — anything
-- a reader would filter or join on is a column.

-- 2.4 Interactions: the causal identity of a request ----------------------

ALTER TABLE input_requests ADD COLUMN run_id TEXT;
ALTER TABLE input_requests ADD COLUMN position TEXT;

-- 2.4 Interactions: who answered, through what, against which schema -------

ALTER TABLE input_candidates ADD COLUMN resolver_class TEXT;
ALTER TABLE input_candidates ADD COLUMN channel TEXT;
ALTER TABLE input_candidates ADD COLUMN schema_id TEXT;
ALTER TABLE input_candidates ADD COLUMN schema_version TEXT;
ALTER TABLE input_candidates ADD COLUMN payload_hash TEXT;
ALTER TABLE input_candidates ADD COLUMN supersedes_candidate_id TEXT;

-- 2.4 Interactions: the decision and exactly what it observed --------------

CREATE TABLE input_decisions (
    request_id     TEXT PRIMARY KEY REFERENCES input_requests (id) ON DELETE CASCADE,
    accepted_id    TEXT NOT NULL REFERENCES input_candidates (id) ON DELETE CASCADE,
    policy_id      TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    decided_at     TEXT NOT NULL
);
CREATE TRIGGER input_decisions_append_only BEFORE UPDATE ON input_decisions
BEGIN
    SELECT RAISE(ABORT, 'input_decisions is append-only');
END;

CREATE TABLE input_decision_observations (
    request_id   TEXT    NOT NULL REFERENCES input_decisions (request_id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    candidate_id TEXT    NOT NULL REFERENCES input_candidates (id) ON DELETE CASCADE,
    PRIMARY KEY (request_id, position)
);
CREATE INDEX input_decision_observations_candidate
    ON input_decision_observations (candidate_id);
CREATE TRIGGER input_decision_observations_append_only
    BEFORE UPDATE ON input_decision_observations
BEGIN
    SELECT RAISE(ABORT, 'input_decision_observations is append-only');
END;

-- 2.4 Evidence: a reference and a digest, linked to its candidate ----------

ALTER TABLE artifact_refs ADD COLUMN candidate_id TEXT
    REFERENCES input_candidates (id) ON DELETE CASCADE;
CREATE INDEX artifact_refs_candidate ON artifact_refs (candidate_id);

-- 2.4 Effects: the claim a dispatcher holds ---------------------------------

ALTER TABLE outbox ADD COLUMN claim_token TEXT;
